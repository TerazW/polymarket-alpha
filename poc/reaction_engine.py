"""
Belief Reaction System - Reaction Engine
The core engine that processes WebSocket data and produces belief state changes.

Data Flow:
WebSocket → State Store → Shock Detection → Reaction Classification → Belief State
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Callable, Tuple
import threading
import time

from .models import (
    PriceLevel, TradeEvent, ShockEvent, ReactionEvent,
    BeliefState, BeliefStateChange, ReactionType, STATE_INDICATORS
)
from .config import (
    REACTION_WINDOW_MS,
    REACTION_SAMPLE_INTERVAL_MS,
    KEY_LEVELS_COUNT
)
from .shock_detector import ShockDetector
from .reaction_classifier import ReactionClassifier
from .belief_state import BeliefStateEngine


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

    def _update_best_prices(self):
        """Update best bid/ask from current levels."""
        bids = [p for (s, p), l in self.levels.items() if s == 'bid' and l.size_now > 0]
        asks = [p for (s, p), l in self.levels.items() if s == 'ask' and l.size_now > 0]

        self.best_bid = max(bids) if bids else None
        self.best_ask = min(asks) if asks else None


class ReactionEngine:
    """
    The main engine that processes real-time data and produces reactions.

    Components:
    - OrderBookState: Tracks current state of each token's order book
    - ShockDetector: Detects when price levels are tested
    - ReactionClassifier: Classifies reactions after observation window
    - BeliefStateEngine: Maintains belief state machine for each market
    """

    def __init__(
        self,
        on_reaction: Optional[Callable[[ReactionEvent], None]] = None,
        on_state_change: Optional[Callable[[BeliefStateChange], None]] = None,
        on_alert: Optional[Callable[[dict], None]] = None
    ):
        # Callbacks
        self.on_reaction_callback = on_reaction
        self.on_state_change_callback = on_state_change
        self.on_alert_callback = on_alert

        # State stores: token_id -> OrderBookState
        self.order_books: Dict[str, OrderBookState] = {}

        # Core components
        self.shock_detector = ShockDetector()
        self.reaction_classifier = ReactionClassifier()
        self.belief_state_engine = BeliefStateEngine(
            on_state_change=self._handle_state_change
        )

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

        # Check for shock
        shock = self.shock_detector.on_trade(trade, level)

        if shock:
            self.stats['shocks_detected'] += 1

            # Start observing this level
            self.reaction_classifier.start_observation(shock)

            # Alert on shock
            if self.on_alert_callback:
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

                        # Alert on reaction
                        if self.on_alert_callback:
                            self._emit_reaction_alert(reaction)

                        # Update belief state
                        state_change = self.belief_state_engine.on_reaction(reaction)

                        if state_change:
                            self.stats['state_changes'] += 1

                    # Complete the shock
                    self.shock_detector.complete_shock(shock.token_id, shock.price)

                # Sleep until next sample
                time.sleep(REACTION_SAMPLE_INTERVAL_MS / 1000)

            except Exception as e:
                print(f"Error in sample loop: {e}")
                time.sleep(1)

    def _handle_state_change(self, change: BeliefStateChange):
        """Handle state change from belief state engine."""
        if self.on_state_change_callback:
            self.on_state_change_callback(change)

        if self.on_alert_callback:
            self._emit_state_change_alert(change)

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
        return {
            **self.stats,
            'tracked_books': len(self.order_books),
            'shock_detector': self.shock_detector.get_stats(),
            'classifier': self.reaction_classifier.get_stats(),
            'belief_engine': self.belief_state_engine.get_stats()
        }

    def get_market_summary(self, token_id: str) -> Optional[dict]:
        """Get summary for a specific market."""
        state = self.belief_state_engine.get_state(token_id)
        book = self.order_books.get(token_id)

        if not book:
            return None

        indicator = STATE_INDICATORS.get(state, "⚪")

        return {
            'token_id': token_id,
            'state': state.value,
            'indicator': indicator,
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
