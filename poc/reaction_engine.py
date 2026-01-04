"""
Belief Reaction System - Reaction Engine v2
The core engine that processes WebSocket data and produces belief state changes.

v2 集成:
1. LeadingEventDetector - 领先事件检测
2. BeliefStateMachine - 信念状态机 (从 belief_state_machine.py)
3. AlertSystem - 统一警报系统

Data Flow:
WebSocket → State Store → Shock Detection → Reaction Classification
                       ↘ Leading Events ↗        ↓
                                         Belief State Machine → Alerts

"看存在没意义，看反应才有意义"
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Callable, Tuple
import threading
import time

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
    Tracks all price levels and their behavior.
    """

    def __init__(self, token_id: str):
        self.token_id = token_id
        self.levels: Dict[Tuple[str, Decimal], PriceLevel] = {}  # (side, price) -> PriceLevel
        self.best_bid: Optional[Decimal] = None
        self.best_ask: Optional[Decimal] = None
        self.tick_size: Decimal = Decimal("0.01")
        self.last_update_ts: int = 0
        self.lock = threading.Lock()

    def on_book_snapshot(self, bids: List[dict], asks: List[dict], timestamp: int):
        """Process a full book snapshot."""
        with self.lock:
            # Clear existing levels
            self.levels.clear()

            # Process bids
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

            # Process asks
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

            # Update best bid/ask
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
        """
        Process a price_change event.

        Returns (level, delta) where delta is the size change.
        """
        with self.lock:
            key = (side.lower(), price)

            if key in self.levels:
                level = self.levels[key]
                delta = level.update_size(size, timestamp)

                # Remove level if size is 0
                if size <= 0:
                    del self.levels[key]
            else:
                # New level
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

            # Update best bid/ask from message
            if best_bid:
                self.best_bid = best_bid
            if best_ask:
                self.best_ask = best_ask

            self.last_update_ts = timestamp
            return level, delta

    def get_level(self, side: str, price: Decimal) -> Optional[PriceLevel]:
        """Get a specific price level."""
        with self.lock:
            return self.levels.get((side.lower(), price))

    def get_key_levels(self, side: str, count: int = KEY_LEVELS_COUNT) -> List[Decimal]:
        """
        Get key levels = levels with highest size_peak.
        These are 'belief anchors' where conviction has concentrated.
        """
        with self.lock:
            side_levels = [
                level for (s, _), level in self.levels.items()
                if s == side.lower() and level.size_peak > 0
            ]
            sorted_levels = sorted(side_levels, key=lambda l: l.size_peak, reverse=True)
            return [l.price for l in sorted_levels[:count]]

    def get_total_depth(self, side: str, ticks_range: int = 5) -> float:
        """Get total depth within N ticks of best price."""
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
        """Update best bid/ask from current levels."""
        bids = [p for (s, p), l in self.levels.items() if s == 'bid' and l.size_now > 0]
        asks = [p for (s, p), l in self.levels.items() if s == 'ask' and l.size_now > 0]

        self.best_bid = max(bids) if bids else None
        self.best_ask = min(asks) if asks else None


class ReactionEngine:
    """
    The main engine that processes real-time data and produces reactions.

    v2 Components:
    - OrderBookState: Tracks current state of each token's order book
    - ShockDetector: Detects when price levels are tested
    - ReactionClassifier: Classifies reactions after observation window
    - LeadingEventDetector: Detects leading events (PRE_SHOCK_PULL, DEPTH_COLLAPSE, etc.)
    - BeliefStateMachine: Maintains belief state machine for each market
    - AlertSystem: Unified alert management
    """

    def __init__(
        self,
        on_reaction: Optional[Callable[[ReactionEvent], None]] = None,
        on_state_change: Optional[Callable[[BeliefStateChange], None]] = None,
        on_leading_event: Optional[Callable[[LeadingEvent], None]] = None,
        on_alert: Optional[Callable[[dict], None]] = None,
        use_alert_system: bool = True
    ):
        # Callbacks
        self.on_reaction_callback = on_reaction
        self.on_state_change_callback = on_state_change
        self.on_leading_event_callback = on_leading_event
        self.on_alert_callback = on_alert

        # State stores: token_id -> OrderBookState
        self.order_books: Dict[str, OrderBookState] = {}

        # Core components
        self.shock_detector = ShockDetector()
        self.reaction_classifier = ReactionClassifier()
        self.belief_state_engine = BeliefStateEngine(
            on_state_change=self._handle_state_change
        )

        # v2: Leading event detector
        self.leading_event_detector = LeadingEventDetector()

        # v2: Belief state machine (enhanced version)
        self.belief_state_machines: Dict[str, BeliefStateMachineV2] = {}

        # v2: Alert system
        self.use_alert_system = use_alert_system
        if use_alert_system:
            self.alert_system = AlertSystem(
                on_alert=self._handle_alert_system_callback
            )
        else:
            self.alert_system = None

        # Reaction window sampling
        self.sample_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.lock = threading.Lock()

        # Stats
        self.stats = {
            'trades_processed': 0,
            'price_changes_processed': 0,
            'books_processed': 0,
            'shocks_detected': 0,
            'reactions_classified': 0,
            'leading_events_detected': 0,
            'state_changes': 0
        }

    def start(self):
        """Start the reaction engine."""
        self.is_running = True
        self.sample_thread = threading.Thread(target=self._sample_loop, daemon=True)
        self.sample_thread.start()

    def stop(self):
        """Stop the reaction engine."""
        self.is_running = False
        if self.sample_thread:
            self.sample_thread.join(timeout=2)

    def _get_or_create_book(self, token_id: str) -> OrderBookState:
        """Get or create order book state for a token."""
        if token_id not in self.order_books:
            self.order_books[token_id] = OrderBookState(token_id)
        return self.order_books[token_id]

    def _get_or_create_belief_machine(self, token_id: str) -> BeliefStateMachineV2:
        """Get or create belief state machine for a token."""
        if token_id not in self.belief_state_machines:
            self.belief_state_machines[token_id] = BeliefStateMachineV2()
        return self.belief_state_machines[token_id]

    def on_book(self, data: dict):
        """Handle book snapshot message."""
        token_id = data.get('asset_id', '')
        if not token_id:
            return

        bids = data.get('bids', [])
        asks = data.get('asks', [])
        timestamp = int(data.get('timestamp', 0))

        book = self._get_or_create_book(token_id)
        book.on_book_snapshot(bids, asks, timestamp)

        # Update key levels in belief state engine
        bid_key_levels = book.get_key_levels('bid')
        ask_key_levels = book.get_key_levels('ask')
        all_key_levels = bid_key_levels + ask_key_levels
        self.belief_state_engine.update_key_levels(token_id, all_key_levels)

        # v2: Update anchors in leading event detector
        self.leading_event_detector.update_anchors(token_id, timestamp)

        # v2: Update anchors in belief state machine v2
        belief_machine = self._get_or_create_belief_machine(token_id)
        anchor_levels = self.leading_event_detector.get_anchors(token_id)
        belief_machine.update_anchors(token_id, anchor_levels)

        self.stats['books_processed'] += 1

    def on_price_change(self, data: dict):
        """Handle price_change message."""
        timestamp = int(data.get('timestamp', 0))

        for change in data.get('price_changes', []):
            token_id = change.get('asset_id', '')
            if not token_id:
                continue

            price = Decimal(str(change.get('price', '0')))
            size = float(change.get('size', 0))
            side = change.get('side', 'BUY').lower()

            # Map side: BUY orders are on bid side, SELL orders are on ask side
            book_side = 'bid' if side == 'buy' else 'ask'

            best_bid = Decimal(str(change.get('best_bid', '0'))) if change.get('best_bid') else None
            best_ask = Decimal(str(change.get('best_ask', '0'))) if change.get('best_ask') else None

            book = self._get_or_create_book(token_id)
            level, delta = book.on_price_change(
                price, size, book_side, best_bid, best_ask, timestamp
            )

            # Record sample for active observations
            self.reaction_classifier.record_sample(
                token_id, price, timestamp, size, best_bid, best_ask
            )

            # v2: Update leading event detector
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

                # Process detected leading events
                for leading_event in leading_events:
                    self._handle_leading_event(leading_event)

            # v2: Check for GRADUAL_THINNING
            total_depth = book.get_total_depth(book_side)
            thinning_event = self.leading_event_detector.on_book_depth_update(
                token_id=token_id,
                side=book_side,
                total_depth=total_depth,
                trade_volume=0,  # Will be updated on trade
                timestamp=timestamp
            )
            if thinning_event:
                self._handle_leading_event(thinning_event)

            self.stats['price_changes_processed'] += 1

    def on_trade(self, data: dict):
        """Handle last_trade_price message (trade execution)."""
        token_id = data.get('asset_id', '')
        if not token_id:
            return

        trade = TradeEvent.from_ws_message(data)

        # Get the level being hit
        book = self._get_or_create_book(token_id)
        # Trade side BUY hits asks, SELL hits bids
        level_side = 'ask' if trade.side == 'BUY' else 'bid'
        level = book.get_level(level_side, trade.price)

        # v2: Record trade in leading event detector
        self.leading_event_detector.on_trade(token_id, trade.price, trade.size, trade.timestamp)

        # v2: Update GRADUAL_THINNING trade volume
        self.leading_event_detector.gradual_thinning_detector.record_trade(
            token_id, level_side, trade.size, trade.timestamp
        )

        # Check for shock
        shock = self.shock_detector.on_trade(trade, level)

        if shock:
            self.stats['shocks_detected'] += 1

            # Start observing this level
            self.reaction_classifier.start_observation(shock)

            # v2: Alert via AlertSystem
            if self.alert_system:
                self.alert_system.on_shock(shock)
            elif self.on_alert_callback:
                self._emit_shock_alert(shock)

        self.stats['trades_processed'] += 1

    def _sample_loop(self):
        """Background loop to sample active observations and check for expired shocks."""
        while self.is_running:
            try:
                now = int(time.time() * 1000)

                # Check for expired shocks
                expired = self.shock_detector.get_expired_shocks(now)

                for shock in expired:
                    # Classify the reaction
                    reaction = self.reaction_classifier.classify(shock)

                    if reaction:
                        self.stats['reactions_classified'] += 1

                        # Notify callback
                        if self.on_reaction_callback:
                            self.on_reaction_callback(reaction)

                        # v2: Alert via AlertSystem
                        if self.alert_system:
                            self.alert_system.on_reaction(reaction)
                        elif self.on_alert_callback:
                            self._emit_reaction_alert(reaction)

                        # Update belief state (old engine)
                        state_change = self.belief_state_engine.on_reaction(reaction)

                        # v2: Update belief state machine v2
                        belief_machine = self._get_or_create_belief_machine(reaction.token_id)
                        state_change_v2 = belief_machine.on_reaction(reaction)

                        if state_change_v2:
                            self._handle_state_change_v2(state_change_v2)

                        if state_change:
                            self.stats['state_changes'] += 1

                    # Complete the shock
                    self.shock_detector.complete_shock(shock.token_id, shock.price)

                # Sleep until next sample
                time.sleep(REACTION_SAMPLE_INTERVAL_MS / 1000)

            except Exception as e:
                print(f"Error in sample loop: {e}")
                time.sleep(1)

    def _handle_leading_event(self, event: LeadingEvent):
        """Handle a detected leading event."""
        self.stats['leading_events_detected'] += 1

        # Callback
        if self.on_leading_event_callback:
            self.on_leading_event_callback(event)

        # v2: Alert via AlertSystem
        if self.alert_system:
            self.alert_system.on_leading_event(event)

        # v2: Update belief state machine v2
        belief_machine = self._get_or_create_belief_machine(event.token_id)
        state_change = belief_machine.on_leading_event(event)

        if state_change:
            self._handle_state_change_v2(state_change)

    def _handle_state_change(self, change: BeliefStateChange):
        """Handle state change from belief state engine."""
        if self.on_state_change_callback:
            self.on_state_change_callback(change)

        if self.alert_system:
            self.alert_system.on_state_change(change)
        elif self.on_alert_callback:
            self._emit_state_change_alert(change)

    def _handle_state_change_v2(self, change: BeliefStateChange):
        """Handle state change from belief state machine v2."""
        self.stats['state_changes'] += 1

        if self.on_state_change_callback:
            self.on_state_change_callback(change)

        if self.alert_system:
            self.alert_system.on_state_change(change)

    def _handle_alert_system_callback(self, alert: Alert):
        """Handle alert from AlertSystem, convert to dict for legacy callback."""
        if self.on_alert_callback:
            self.on_alert_callback(alert.to_dict())

    # Legacy alert emission (for when AlertSystem is not used)
    def _emit_shock_alert(self, shock: ShockEvent):
        """Emit alert for shock detection."""
        alert = {
            'type': 'SHOCK',
            'token_id': shock.token_id,
            'price': str(shock.price),
            'side': shock.side,
            'trigger': shock.trigger_type,
            'volume': shock.trade_volume,
            'liquidity_before': shock.liquidity_before,
            'message': f"Shock at {shock.price} ({shock.side}) - {shock.trigger_type}"
        }
        self.on_alert_callback(alert)

    def _emit_reaction_alert(self, reaction: ReactionEvent):
        """Emit alert for reaction classification."""
        alert = {
            'type': 'REACTION',
            'token_id': reaction.token_id,
            'price': str(reaction.price),
            'side': reaction.side,
            'reaction_type': reaction.reaction_type.value,
            'refill_ratio': f"{reaction.refill_ratio:.0%}",
            'message': f"{reaction.reaction_type.value} at {reaction.price}"
        }
        self.on_alert_callback(alert)

    def _emit_state_change_alert(self, change: BeliefStateChange):
        """Emit alert for state change."""
        old_indicator = STATE_INDICATORS.get(change.old_state, "")
        new_indicator = STATE_INDICATORS.get(change.new_state, "")

        alert = {
            'type': 'STATE_CHANGE',
            'token_id': change.token_id,
            'old_state': change.old_state.value,
            'new_state': change.new_state.value,
            'evidence': change.evidence,
            'message': f"{old_indicator} {change.old_state.value} → {new_indicator} {change.new_state.value}"
        }
        self.on_alert_callback(alert)

    def get_stats(self) -> dict:
        """Get engine statistics."""
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
        """Get summary for a specific market."""
        state = self.belief_state_engine.get_state(token_id)
        book = self.order_books.get(token_id)

        if not book:
            return None

        indicator = STATE_INDICATORS.get(state, "⚪")

        # v2: Get belief machine state
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

    def get_all_market_summaries(self) -> Dict[str, dict]:
        """Get summaries for all monitored markets."""
        return {
            token_id: self.get_market_summary(token_id)
            for token_id in self.order_books
        }

    def get_alerts(self, **kwargs) -> List[Alert]:
        """Get alerts from AlertSystem."""
        if self.alert_system:
            return self.alert_system.get_alerts(**kwargs)
        return []

    def get_critical_alerts(self, limit: int = 10) -> List[Alert]:
        """Get critical alerts."""
        if self.alert_system:
            return self.alert_system.get_critical_alerts(limit)
        return []
