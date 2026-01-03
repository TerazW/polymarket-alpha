"""
Belief Reaction System - Reaction Classifier
Classifies reactions into the 6 atomic types after observing the reaction window.

The 6 reaction types are the system's VOCABULARY:
- HOLD: Defend - quickly refills after shock
- DELAY: Hesitate - partial/slow refill
- PULL: Retreat - cancels immediately after shock
- VACUUM: Vacuum - liquidity completely vanishes
- CHASE: Chase - anchor moved, belief repricing
- FAKE: Anchor - adds more after shock (psychological)
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Tuple
import time

from .models import (
    ShockEvent, ReactionEvent, ReactionMetrics, ReactionType, PriceLevel
)
from .config import (
    REACTION_WINDOW_MS,
    REACTION_SAMPLE_INTERVAL_MS,
    HOLD_REFILL_THRESHOLD,
    HOLD_TIME_THRESHOLD_MS,
    VACUUM_THRESHOLD,
    PULL_THRESHOLD
)


class ReactionObserver:
    """
    Observes a price level after a shock to collect metrics.
    One observer per active shock.
    """

    def __init__(self, shock: ShockEvent):
        self.shock = shock
        self.samples: List[Tuple[int, float]] = []  # (timestamp, size)
        self.best_bid_shifts: List[Tuple[int, Decimal]] = []
        self.best_ask_shifts: List[Tuple[int, Decimal]] = []
        self.initial_best_bid: Optional[Decimal] = None
        self.initial_best_ask: Optional[Decimal] = None
        self.size_after_shock: Optional[float] = None

    def record_sample(
        self,
        timestamp: int,
        size: float,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None
    ):
        """Record a sample of the level state."""
        self.samples.append((timestamp, size))

        # Track first sample as "after shock" state
        if self.size_after_shock is None:
            self.size_after_shock = size

        # Track best bid/ask for CHASE detection
        if best_bid is not None:
            if self.initial_best_bid is None:
                self.initial_best_bid = best_bid
            self.best_bid_shifts.append((timestamp, best_bid))

        if best_ask is not None:
            if self.initial_best_ask is None:
                self.initial_best_ask = best_ask
            self.best_ask_shifts.append((timestamp, best_ask))

    def compute_metrics(self) -> ReactionMetrics:
        """Compute reaction metrics from collected samples."""
        if not self.samples:
            return ReactionMetrics()

        sizes = [s for _, s in self.samples]
        min_liq = min(sizes)
        max_liq = max(sizes)
        end_size = sizes[-1]

        liquidity_before = self.shock.liquidity_before

        # Refill ratio: max recovery relative to original
        refill_ratio = max_liq / liquidity_before if liquidity_before > 0 else 0.0

        # Time to refill: first sample where size >= 80% of original
        time_to_refill = None
        refill_target = 0.8 * liquidity_before
        for ts, size in self.samples:
            if size >= refill_target:
                time_to_refill = ts - self.shock.ts_start
                break

        # Cancel speed
        if self.size_after_shock is not None and liquidity_before > 0:
            initial_drop = (liquidity_before - self.size_after_shock) / liquidity_before
            if initial_drop > 0.9:
                cancel_speed = 'instant'
            elif initial_drop > 0.5:
                cancel_speed = 'fast'
            elif initial_drop > 0.2:
                cancel_speed = 'slow'
            else:
                cancel_speed = 'none'
        else:
            cancel_speed = 'none'

        # Price shift (for CHASE detection)
        price_shift = Decimal("0")
        if self.shock.side == 'bid':
            # For bids, check best_bid shift
            if self.initial_best_bid and self.best_bid_shifts:
                final_bid = self.best_bid_shifts[-1][1]
                price_shift = final_bid - self.initial_best_bid
        else:
            # For asks, check best_ask shift
            if self.initial_best_ask and self.best_ask_shifts:
                final_ask = self.best_ask_shifts[-1][1]
                price_shift = final_ask - self.initial_best_ask

        return ReactionMetrics(
            net_liquidity_change=end_size - (self.size_after_shock or 0),
            min_liquidity=min_liq,
            max_liquidity=max_liq,
            refill_ratio=refill_ratio,
            time_to_refill_ms=time_to_refill,
            cancel_speed=cancel_speed,
            price_shift=price_shift
        )


class ReactionClassifier:
    """
    Manages reaction observation and classification for all active shocks.
    """

    def __init__(self):
        # Active observers: (token_id, price_str) -> ReactionObserver
        self.observers: Dict[Tuple[str, str], ReactionObserver] = {}

        # Stats
        self.total_classified = 0
        self.classification_counts: Dict[ReactionType, int] = defaultdict(int)

    def start_observation(self, shock: ShockEvent):
        """Start observing a new shock."""
        key = (shock.token_id, str(shock.price))
        self.observers[key] = ReactionObserver(shock)

    def record_sample(
        self,
        token_id: str,
        price: Decimal,
        timestamp: int,
        size: float,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None
    ):
        """Record a sample for an observed level."""
        key = (token_id, str(price))
        if key in self.observers:
            self.observers[key].record_sample(timestamp, size, best_bid, best_ask)

    def classify(self, shock: ShockEvent) -> Optional[ReactionEvent]:
        """
        Classify a reaction after the observation window ends.

        Classification priority (check most specific first):
        1. VACUUM: Liquidity completely vanished
        2. FAKE: Counter-intuitive increase
        3. CHASE: Anchor moved
        4. PULL: Immediate retreat
        5. HOLD: Strong recovery
        6. DELAY: Default - hesitation
        """
        key = (shock.token_id, str(shock.price))
        observer = self.observers.pop(key, None)

        if not observer:
            return None

        metrics = observer.compute_metrics()
        reaction_type = self._classify_reaction(shock, metrics)

        # Update stats
        self.total_classified += 1
        self.classification_counts[reaction_type] += 1

        return ReactionEvent(
            shock_id=shock.shock_id,
            timestamp=int(time.time() * 1000),
            token_id=shock.token_id,
            price=shock.price,
            side=shock.side,
            reaction_type=reaction_type,
            refill_ratio=metrics.refill_ratio,
            time_to_refill_ms=metrics.time_to_refill_ms,
            min_liquidity=metrics.min_liquidity,
            price_shift=metrics.price_shift,
            liquidity_before=shock.liquidity_before
        )

    def _classify_reaction(
        self,
        shock: ShockEvent,
        metrics: ReactionMetrics
    ) -> ReactionType:
        """Apply classification rules in priority order."""
        liquidity_before = shock.liquidity_before

        if liquidity_before <= 0:
            return ReactionType.DELAY  # Can't classify without baseline

        # 1. Check for VACUUM (strongest signal)
        if metrics.min_liquidity <= VACUUM_THRESHOLD * liquidity_before:
            if metrics.refill_ratio < 0.1:  # No meaningful refill
                return ReactionType.VACUUM

        # 2. Check for FAKE (counter-intuitive increase)
        if metrics.max_liquidity > liquidity_before:
            return ReactionType.FAKE

        # 3. Check for CHASE (price anchor moved)
        if abs(metrics.price_shift) > 0:
            return ReactionType.CHASE

        # 4. Check for PULL
        if metrics.min_liquidity <= PULL_THRESHOLD * liquidity_before:
            if metrics.refill_ratio < 0.3:
                return ReactionType.PULL

        # 5. Check for HOLD (strong recovery)
        if metrics.refill_ratio >= HOLD_REFILL_THRESHOLD:
            if metrics.time_to_refill_ms and metrics.time_to_refill_ms < HOLD_TIME_THRESHOLD_MS:
                return ReactionType.HOLD

        # 6. Default to DELAY
        return ReactionType.DELAY

    def has_active_observation(self, token_id: str, price: Decimal) -> bool:
        """Check if we're actively observing a level."""
        key = (token_id, str(price))
        return key in self.observers

    def get_stats(self) -> dict:
        """Get classifier statistics."""
        return {
            "total_classified": self.total_classified,
            "active_observations": len(self.observers),
            "by_type": {t.value: c for t, c in self.classification_counts.items()}
        }
