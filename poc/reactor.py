"""
Belief Reaction System - Reactor v1
Consumes events from EventBus and produces reactions/state changes.

Responsibilities:
1. Consume RawEvents from EventBus
2. Maintain order book state
3. Detect shocks and classify reactions
4. Detect leading events
5. Manage belief state machine
6. Generate alerts

Does NOT:
- Handle WebSocket connection (that's the Collector's job)
- Parse raw WebSocket messages

"看存在没意义，看反应才有意义"
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Callable, Tuple
import threading
import time

# v5.13: Determinism infrastructure
from backend.common.determinism import (
    get_event_clock, deterministic_now, ReplayContext, ProcessingMode
)

from .event_bus import EventBus, RawEvent, EventType
from .models import (
    PriceLevel, TradeEvent, ShockEvent, ReactionEvent,
    BeliefState, BeliefStateChange, ReactionType, LeadingEvent,
    STATE_INDICATORS, AnchorLevel
)
from .config import (
    REACTION_WINDOW_MS,
    REACTION_SAMPLE_INTERVAL_MS,
    KEY_LEVELS_COUNT
)
from .shock_detector import ShockDetector
from .reaction_classifier import ReactionClassifier
from .belief_state import BeliefStateEngine
from .leading_events import LeadingEventDetector
from .belief_state_machine import BeliefStateMachine as BeliefStateMachineV2
from .alert_system import AlertSystem, Alert


class OrderBookState:
    """
    In-memory state store for a single token's order book.
    (Same as in reaction_engine.py - extracted for reuse)
    """

    def __init__(self, token_id: str):
        self.token_id = token_id
        self.levels: Dict[Tuple[str, Decimal], PriceLevel] = {}
        self.best_bid: Optional[Decimal] = None
        self.best_ask: Optional[Decimal] = None
        self.tick_size: Decimal = Decimal("0.01")
        self.last_update_ts: int = 0
        self.lock = threading.Lock()

    def on_book_snapshot(self, bids: List[dict], asks: List[dict], timestamp: int):
        """Process a full book snapshot."""
        with self.lock:
            self.levels.clear()

            for bid in bids:
                price = Decimal(str(bid.get('price', '0')))
                size = float(bid.get('size', 0))
                level = PriceLevel(
                    token_id=self.token_id,
                    price=price,
                    side='bid',
                    size_now=size,
                    size_peak=size,
                    first_seen_ts=timestamp,
                    last_update_ts=timestamp
                )
                self.levels[('bid', price)] = level

            for ask in asks:
                price = Decimal(str(ask.get('price', '0')))
                size = float(ask.get('size', 0))
                level = PriceLevel(
                    token_id=self.token_id,
                    price=price,
                    side='ask',
                    size_now=size,
                    size_peak=size,
                    first_seen_ts=timestamp,
                    last_update_ts=timestamp
                )
                self.levels[('ask', price)] = level

            self._update_best_prices()
            self.last_update_ts = timestamp

    def on_price_change(
        self,
        price: Decimal,
        size: float,
        side: str,
        best_bid: Optional[Decimal],
        best_ask: Optional[Decimal],
        timestamp: int
    ) -> Tuple[Optional[PriceLevel], float]:
        """Process a price_change event."""
        with self.lock:
            key = (side.lower(), price)

            if key in self.levels:
                level = self.levels[key]
                delta = level.update_size(size, timestamp)

                if size <= 0:
                    del self.levels[key]
            else:
                level = PriceLevel(
                    token_id=self.token_id,
                    price=price,
                    side=side.lower(),
                    size_now=size,
                    size_peak=size,
                    first_seen_ts=timestamp,
                    last_update_ts=timestamp
                )
                self.levels[key] = level
                delta = size

            if best_bid:
                self.best_bid = best_bid
            if best_ask:
                self.best_ask = best_ask

            self.last_update_ts = timestamp
            return level, delta

    def get_level(self, side: str, price: Decimal) -> Optional[PriceLevel]:
        with self.lock:
            return self.levels.get((side.lower(), price))

    def get_key_levels(self, side: str, count: int = KEY_LEVELS_COUNT) -> List[Decimal]:
        with self.lock:
            side_levels = [
                level for (s, _), level in self.levels.items()
                if s == side.lower() and level.size_peak > 0
            ]
            sorted_levels = sorted(side_levels, key=lambda l: l.size_peak, reverse=True)
            return [l.price for l in sorted_levels[:count]]

    def get_total_depth(self, side: str, ticks_range: int = 5) -> float:
        with self.lock:
            best_price = self.best_bid if side == 'bid' else self.best_ask
            if not best_price:
                return 0.0

            total = 0.0
            price_range = ticks_range * self.tick_size

            for (s, price), level in self.levels.items():
                if s != side:
                    continue
                if abs(price - best_price) <= price_range:
                    total += level.size_now

            return total

    def _update_best_prices(self):
        bids = [p for (s, p), l in self.levels.items() if s == 'bid' and l.size_now > 0]
        asks = [p for (s, p), l in self.levels.items() if s == 'ask' and l.size_now > 0]

        self.best_bid = max(bids) if bids else None
        self.best_ask = min(asks) if asks else None


class Reactor:
    """
    Event reactor - consumes events and produces reactions.

    This is the decoupled version of ReactionEngine that:
    - Consumes events from EventBus (not directly from WebSocket)
    - Can be used for both real-time and replay processing
    """

    def __init__(
        self,
        event_bus: EventBus,
        on_reaction: Optional[Callable[[ReactionEvent], None]] = None,
        on_state_change: Optional[Callable[[BeliefStateChange], None]] = None,
        on_leading_event: Optional[Callable[[LeadingEvent], None]] = None,
        on_alert: Optional[Callable[[dict], None]] = None,
        use_alert_system: bool = True,
        replay_mode: bool = False,
    ):
        self.event_bus = event_bus
        self.replay_mode = replay_mode

        # Callbacks
        self.on_reaction_callback = on_reaction
        self.on_state_change_callback = on_state_change
        self.on_leading_event_callback = on_leading_event
        self.on_alert_callback = on_alert

        # State stores
        self.order_books: Dict[str, OrderBookState] = {}

        # Core components
        self.shock_detector = ShockDetector()
        self.reaction_classifier = ReactionClassifier()
        self.belief_state_engine = BeliefStateEngine(
            on_state_change=self._handle_state_change
        )

        # Leading event detector
        self.leading_event_detector = LeadingEventDetector()

        # Belief state machine v2
        self.belief_state_machines: Dict[str, BeliefStateMachineV2] = {}

        # Alert system
        self.use_alert_system = use_alert_system
        if use_alert_system:
            self.alert_system = AlertSystem(
                on_alert=self._handle_alert_system_callback
            )
        else:
            self.alert_system = None

        # Processing threads
        self.consume_thread: Optional[threading.Thread] = None
        self.sample_thread: Optional[threading.Thread] = None
        self.is_running = False

        # Current time (for replay mode)
        self._current_time = 0

        # Stats
        self.stats = {
            'events_processed': 0,
            'trades_processed': 0,
            'price_changes_processed': 0,
            'books_processed': 0,
            'shocks_detected': 0,
            'reactions_classified': 0,
            'leading_events_detected': 0,
            'state_changes': 0
        }

    def start(self):
        """Start the reactor"""
        self.is_running = True

        # Start consumer thread
        self.consume_thread = threading.Thread(
            target=self._consume_loop,
            daemon=True
        )
        self.consume_thread.start()

        # Start sample thread (for reaction window expiry)
        if not self.replay_mode:
            self.sample_thread = threading.Thread(
                target=self._sample_loop,
                daemon=True
            )
            self.sample_thread.start()

    def stop(self):
        """Stop the reactor"""
        self.is_running = False

        if self.consume_thread:
            self.consume_thread.join(timeout=2)

        if self.sample_thread:
            self.sample_thread.join(timeout=2)

    def _get_current_time(self) -> int:
        """
        Get current time (milliseconds).

        v5.13: Uses deterministic event clock.
        In replay mode, returns the event timestamp set by process_event.
        In live mode, uses wall clock but warns (for audit trail).
        """
        if self.replay_mode:
            return self._current_time
        # v5.13: Use deterministic clock (will warn in LIVE mode)
        return deterministic_now(context="Reactor._get_current_time")

    def _get_or_create_book(self, token_id: str) -> OrderBookState:
        if token_id not in self.order_books:
            self.order_books[token_id] = OrderBookState(token_id)
        return self.order_books[token_id]

    def _get_or_create_belief_machine(self, token_id: str) -> BeliefStateMachineV2:
        if token_id not in self.belief_state_machines:
            self.belief_state_machines[token_id] = BeliefStateMachineV2()
        return self.belief_state_machines[token_id]

    def _consume_loop(self):
        """Main event consumption loop"""
        while self.is_running:
            try:
                event = self.event_bus.poll(timeout_ms=100)

                if event:
                    self._process_event(event)

            except Exception as e:
                print(f"Error in consume loop: {e}")
                time.sleep(0.1)

    def _process_event(self, event: RawEvent):
        """Process a single RawEvent"""
        # Update current time for replay mode
        if self.replay_mode:
            self._current_time = event.server_ts

        self.stats['events_processed'] += 1

        if event.event_type == EventType.BOOK:
            self._handle_book(event)
        elif event.event_type == EventType.TRADE:
            self._handle_trade(event)
        elif event.event_type == EventType.PRICE_CHANGE:
            self._handle_price_change(event)

        # In replay mode, check for expired shocks after each event
        if self.replay_mode:
            self._check_expired_shocks(event.server_ts)

    def _handle_book(self, event: RawEvent):
        """Handle book snapshot event"""
        data = event.payload
        token_id = event.token_id
        timestamp = event.ws_ts or event.server_ts

        bids = data.get('bids', [])
        asks = data.get('asks', [])

        book = self._get_or_create_book(token_id)
        book.on_book_snapshot(bids, asks, timestamp)

        # Update key levels
        bid_key_levels = book.get_key_levels('bid')
        ask_key_levels = book.get_key_levels('ask')
        all_key_levels = bid_key_levels + ask_key_levels
        self.belief_state_engine.update_key_levels(token_id, all_key_levels)

        # Update anchors
        self.leading_event_detector.update_anchors(token_id, timestamp)

        belief_machine = self._get_or_create_belief_machine(token_id)
        anchor_levels = self.leading_event_detector.get_anchors(token_id)
        belief_machine.update_anchors(token_id, anchor_levels)

        self.stats['books_processed'] += 1

    def _handle_trade(self, event: RawEvent):
        """Handle trade event"""
        data = event.payload
        token_id = event.token_id
        timestamp = event.ws_ts or event.server_ts

        trade = TradeEvent(
            token_id=token_id,
            price=Decimal(str(data.get('price', '0'))),
            size=float(data.get('size', 0)),
            side=data.get('side', 'BUY').upper(),
            timestamp=timestamp
        )

        book = self._get_or_create_book(token_id)
        level_side = 'ask' if trade.side == 'BUY' else 'bid'
        level = book.get_level(level_side, trade.price)

        # Record trade in leading event detector
        self.leading_event_detector.on_trade(
            token_id, trade.price, trade.size, timestamp
        )

        # Update GRADUAL_THINNING trade volume
        self.leading_event_detector.gradual_thinning_detector.record_trade(
            token_id, level_side, trade.size, timestamp
        )

        # Check for shock
        shock = self.shock_detector.on_trade(trade, level)

        if shock:
            self.stats['shocks_detected'] += 1
            self.reaction_classifier.start_observation(shock)

            if self.alert_system:
                self.alert_system.on_shock(shock)

        self.stats['trades_processed'] += 1

    def _handle_price_change(self, event: RawEvent):
        """Handle price change event"""
        data = event.payload
        token_id = event.token_id
        timestamp = event.ws_ts or event.server_ts

        price = Decimal(str(data.get('price', '0')))
        size = float(data.get('size', 0))
        side = data.get('side', 'BUY').lower()

        book_side = 'bid' if side == 'buy' else 'ask'

        best_bid = Decimal(str(data.get('best_bid', '0'))) if data.get('best_bid') else None
        best_ask = Decimal(str(data.get('best_ask', '0'))) if data.get('best_ask') else None

        book = self._get_or_create_book(token_id)
        level, delta = book.on_price_change(
            price, size, book_side, best_bid, best_ask, timestamp
        )

        # Record sample for active observations
        self.reaction_classifier.record_sample(
            token_id, price, timestamp, size, best_bid, best_ask
        )

        # Update leading event detector
        if level:
            baseline = level.get_baseline_size(timestamp)
            best_price = best_bid if book_side == 'bid' else best_ask

            leading_events = self.leading_event_detector.on_level_update(
                level=level,
                baseline=baseline,
                timestamp=timestamp,
                best_price=best_price,
                tick_size=book.tick_size
            )

            for leading_event in leading_events:
                self._handle_leading_event(leading_event)

        # Check for GRADUAL_THINNING
        total_depth = book.get_total_depth(book_side)
        thinning_event = self.leading_event_detector.on_book_depth_update(
            token_id=token_id,
            side=book_side,
            total_depth=total_depth,
            trade_volume=0,
            timestamp=timestamp
        )
        if thinning_event:
            self._handle_leading_event(thinning_event)

        self.stats['price_changes_processed'] += 1

    def _sample_loop(self):
        """Background loop to check for expired shocks"""
        while self.is_running:
            try:
                now = self._get_current_time()
                self._check_expired_shocks(now)
                time.sleep(REACTION_SAMPLE_INTERVAL_MS / 1000)

            except Exception as e:
                print(f"Error in sample loop: {e}")
                time.sleep(1)

    def _check_expired_shocks(self, current_time: int):
        """Check and classify expired shocks"""
        expired = self.shock_detector.get_expired_shocks(current_time)

        for shock in expired:
            reaction = self.reaction_classifier.classify(shock)

            if reaction:
                self.stats['reactions_classified'] += 1

                if self.on_reaction_callback:
                    self.on_reaction_callback(reaction)

                if self.alert_system:
                    self.alert_system.on_reaction(reaction)

                # Update belief states
                state_change = self.belief_state_engine.on_reaction(reaction)

                belief_machine = self._get_or_create_belief_machine(reaction.token_id)
                state_change_v2 = belief_machine.on_reaction(reaction)

                if state_change_v2:
                    self._handle_state_change_v2(state_change_v2)

                if state_change:
                    self.stats['state_changes'] += 1

            self.shock_detector.complete_shock(shock.token_id, shock.price)

    def _handle_leading_event(self, event: LeadingEvent):
        """Handle a detected leading event"""
        self.stats['leading_events_detected'] += 1

        if self.on_leading_event_callback:
            self.on_leading_event_callback(event)

        if self.alert_system:
            self.alert_system.on_leading_event(event)

        belief_machine = self._get_or_create_belief_machine(event.token_id)
        state_change = belief_machine.on_leading_event(event)

        if state_change:
            self._handle_state_change_v2(state_change)

    def _handle_state_change(self, change: BeliefStateChange):
        """Handle state change from belief state engine"""
        if self.on_state_change_callback:
            self.on_state_change_callback(change)

        if self.alert_system:
            self.alert_system.on_state_change(change)

    def _handle_state_change_v2(self, change: BeliefStateChange):
        """Handle state change from belief state machine v2"""
        self.stats['state_changes'] += 1

        if self.on_state_change_callback:
            self.on_state_change_callback(change)

        if self.alert_system:
            self.alert_system.on_state_change(change)

    def _handle_alert_system_callback(self, alert: Alert):
        """Handle alert from AlertSystem"""
        if self.on_alert_callback:
            self.on_alert_callback(alert.to_dict())

    def get_stats(self) -> dict:
        """Get reactor statistics"""
        stats = {
            **self.stats,
            'tracked_books': len(self.order_books),
            'shock_detector': self.shock_detector.get_stats(),
            'classifier': self.reaction_classifier.get_stats(),
            'belief_engine': self.belief_state_engine.get_stats(),
            'leading_events': self.leading_event_detector.get_stats(),
        }

        if self.alert_system:
            stats['alert_system'] = self.alert_system.get_stats()

        return stats

    def get_market_summary(self, token_id: str) -> Optional[dict]:
        """Get summary for a specific market"""
        state = self.belief_state_engine.get_state(token_id)
        book = self.order_books.get(token_id)

        if not book:
            return None

        indicator = STATE_INDICATORS.get(state, "⚪")

        belief_machine = self.belief_state_machines.get(token_id)
        if belief_machine:
            v2_state = belief_machine.get_state(token_id)
            v2_indicator = STATE_INDICATORS.get(v2_state, "⚪")
        else:
            v2_state = state
            v2_indicator = indicator

        return {
            'token_id': token_id,
            'state': state.value,
            'indicator': indicator,
            'state_v2': v2_state.value,
            'indicator_v2': v2_indicator,
            'best_bid': str(book.best_bid) if book.best_bid else None,
            'best_ask': str(book.best_ask) if book.best_ask else None,
            'bid_key_levels': [str(p) for p in book.get_key_levels('bid')],
            'ask_key_levels': [str(p) for p in book.get_key_levels('ask')],
            'last_update': book.last_update_ts
        }

    def clear_state(
        self,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        token_ids: Optional[List[str]] = None
    ):
        """
        Clear state for rebuild.

        Used by consistency rebuild mechanism.
        """
        if token_ids:
            for token_id in token_ids:
                if token_id in self.order_books:
                    del self.order_books[token_id]
                if token_id in self.belief_state_machines:
                    del self.belief_state_machines[token_id]
        else:
            self.order_books.clear()
            self.belief_state_machines.clear()

        # Reset stats
        for key in self.stats:
            self.stats[key] = 0

    def get_alerts(self, **kwargs) -> List[Alert]:
        """Get alerts from AlertSystem"""
        if self.alert_system:
            return self.alert_system.get_alerts(**kwargs)
        return []
