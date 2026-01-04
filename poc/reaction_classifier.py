"""
Belief Reaction System - Reaction Classifier v2
Classifies reactions into the 6 atomic types after observing the reaction window.

v2 改进 (基于 Spec 1):
1. 双窗口: FAST (8s) + SLOW (30s)
2. 新分类优先级: VACUUM > SWEEP > CHASE > PULL > HOLD > DELAYED
3. 使用 baseline_size 而非 liquidity_before
4. 添加 drop_ratio, vacuum_duration 等新指标

反应类型 (按优先级):
1. VACUUM: 流动性完全消失 (最强信号)
2. SWEEP: 多档被扫 / 快速重定价
3. CHASE: 迁移但未必深度塌陷
4. PULL: 撤退 - 立即取消
5. HOLD: 防守 - 快速补单
6. DELAYED: 默认 - 犹豫/部分补单
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Tuple
import time

from .models import (
    ShockEvent, ReactionEvent, ReactionMetrics, ReactionType, PriceLevel, WindowType
)
from .config import (
    REACTION_FAST_WINDOW_MS,
    REACTION_SLOW_WINDOW_MS,
    REACTION_SAMPLE_INTERVAL_MS,
    # Thresholds
    VACUUM_DURATION_THRESHOLD_MS,
    VACUUM_MIN_SIZE_RATIO,
    VACUUM_REFILL_RATIO,
    SWEEP_DROP_RATIO,
    SWEEP_SHIFT_TICKS,
    CHASE_SHIFT_TICKS,
    PULL_DROP_RATIO,
    PULL_REFILL_RATIO,
    HOLD_REFILL_THRESHOLD,
    HOLD_TIME_THRESHOLD_MS,
    HOLD_REFILL_ALPHA
)


class ReactionObserver:
    """
    Observes a price level after a shock to collect metrics.
    One observer per active shock.

    v2: 支持双窗口，分别计算 FAST 和 SLOW 指标
    """

    def __init__(self, shock: ShockEvent):
        self.shock = shock
        self.samples: List[Tuple[int, float]] = []  # (timestamp, size)
        self.best_bid_shifts: List[Tuple[int, Decimal]] = []
        self.best_ask_shifts: List[Tuple[int, Decimal]] = []
        self.initial_best_bid: Optional[Decimal] = None
        self.initial_best_ask: Optional[Decimal] = None
        self.size_after_shock: Optional[float] = None

        # 是否已分类过各窗口
        self.fast_classified: bool = False
        self.slow_classified: bool = False

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

        # Track best bid/ask for CHASE/SWEEP detection
        if best_bid is not None:
            if self.initial_best_bid is None:
                self.initial_best_bid = best_bid
            self.best_bid_shifts.append((timestamp, best_bid))

        if best_ask is not None:
            if self.initial_best_ask is None:
                self.initial_best_ask = best_ask
            self.best_ask_shifts.append((timestamp, best_ask))

    def compute_metrics(self, window_type: WindowType) -> ReactionMetrics:
        """
        Compute reaction metrics for a specific window.

        Args:
            window_type: FAST or SLOW window
        """
        # 确定窗口边界
        if window_type == WindowType.FAST:
            window_end = self.shock.fast_window_end
        else:
            window_end = self.shock.slow_window_end

        # 过滤窗口内的样本
        window_samples = [
            (ts, sz) for ts, sz in self.samples
            if self.shock.ts_start <= ts <= window_end
        ]

        if not window_samples:
            return ReactionMetrics(window_type=window_type)

        sizes = [s for _, s in window_samples]
        min_liq = min(sizes)
        max_liq = max(sizes)
        end_size = sizes[-1]

        # 使用 baseline_size (v2)
        baseline = self.shock.baseline_size
        if baseline <= 0:
            baseline = self.shock.liquidity_before  # 退化

        # Drop ratio: (baseline - min) / baseline
        drop_ratio = (baseline - min_liq) / baseline if baseline > 0 else 0.0

        # Refill ratio: (max - min) / (baseline - min)
        denominator = baseline - min_liq
        refill_ratio = (max_liq - min_liq) / denominator if denominator > 0 else 0.0

        # Time to refill: first sample where size >= α * baseline
        time_to_refill = None
        refill_target = HOLD_REFILL_ALPHA * baseline
        for ts, size in window_samples:
            if size >= refill_target:
                time_to_refill = ts - self.shock.ts_start
                break

        # Vacuum duration: 连续低于 2% baseline 的时间
        vacuum_duration = self._calculate_vacuum_duration(window_samples, baseline)

        # Cancel speed (based on initial drop)
        if self.size_after_shock is not None and baseline > 0:
            initial_drop = (baseline - self.size_after_shock) / baseline
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

        # Price shift and ticks (for CHASE/SWEEP detection)
        price_shift, shift_ticks = self._calculate_price_shift(window_end)

        return ReactionMetrics(
            window_type=window_type,
            net_liquidity_change=end_size - (self.size_after_shock or 0),
            min_liquidity=min_liq,
            max_liquidity=max_liq,
            end_size=end_size,
            drop_ratio=drop_ratio,
            refill_ratio=refill_ratio,
            time_to_refill_ms=time_to_refill,
            vacuum_duration_ms=vacuum_duration,
            cancel_speed=cancel_speed,
            price_shift=price_shift,
            shift_ticks=shift_ticks
        )

    def _calculate_vacuum_duration(
        self,
        samples: List[Tuple[int, float]],
        baseline: float
    ) -> int:
        """Calculate the longest duration where size <= 2% of baseline."""
        if not samples or baseline <= 0:
            return 0

        vacuum_threshold = VACUUM_MIN_SIZE_RATIO * baseline
        max_duration = 0
        current_start = None

        for ts, size in samples:
            if size <= vacuum_threshold:
                if current_start is None:
                    current_start = ts
            else:
                if current_start is not None:
                    duration = ts - current_start
                    max_duration = max(max_duration, duration)
                    current_start = None

        # Check if still in vacuum at end
        if current_start is not None:
            duration = samples[-1][0] - current_start
            max_duration = max(max_duration, duration)

        return max_duration

    def _calculate_price_shift(self, window_end: int) -> Tuple[Decimal, int]:
        """Calculate price shift and tick count."""
        price_shift = Decimal("0")
        shift_ticks = 0

        tick_size = self.shock.tick_size or Decimal("0.01")

        if self.shock.side == 'bid':
            # For bids, check best_bid shift
            if self.initial_best_bid and self.best_bid_shifts:
                # Find the best_bid at window_end (or closest before)
                final_bid = self.initial_best_bid
                for ts, bid in self.best_bid_shifts:
                    if ts <= window_end:
                        final_bid = bid
                price_shift = final_bid - self.initial_best_bid
                shift_ticks = int(abs(price_shift) / tick_size)
        else:
            # For asks, check best_ask shift
            if self.initial_best_ask and self.best_ask_shifts:
                final_ask = self.initial_best_ask
                for ts, ask in self.best_ask_shifts:
                    if ts <= window_end:
                        final_ask = ask
                price_shift = final_ask - self.initial_best_ask
                shift_ticks = int(abs(price_shift) / tick_size)

        return price_shift, shift_ticks


class ReactionClassifier:
    """
    Manages reaction observation and classification for all active shocks.

    v2: 支持双窗口分类，每个 shock 可生成两个 reaction (FAST + SLOW)
    """

    def __init__(self):
        # Active observers: (token_id, price_str) -> ReactionObserver
        self.observers: Dict[Tuple[str, str], ReactionObserver] = {}

        # Stats
        self.total_classified = 0
        self.classification_counts: Dict[ReactionType, int] = defaultdict(int)
        self.by_window: Dict[WindowType, int] = defaultdict(int)

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

    def classify_fast(self, shock: ShockEvent) -> Optional[ReactionEvent]:
        """
        Classify FAST window reaction.
        Called when fast_window_end is reached.
        """
        key = (shock.token_id, str(shock.price))
        observer = self.observers.get(key)

        if not observer or observer.fast_classified:
            return None

        observer.fast_classified = True
        metrics = observer.compute_metrics(WindowType.FAST)
        reaction_type = self._classify_reaction(shock, metrics)

        self.total_classified += 1
        self.classification_counts[reaction_type] += 1
        self.by_window[WindowType.FAST] += 1

        return self._create_reaction_event(shock, metrics, reaction_type, WindowType.FAST)

    def classify_slow(self, shock: ShockEvent) -> Optional[ReactionEvent]:
        """
        Classify SLOW window reaction.
        Called when slow_window_end is reached.
        """
        key = (shock.token_id, str(shock.price))
        observer = self.observers.get(key)

        if not observer or observer.slow_classified:
            return None

        observer.slow_classified = True
        metrics = observer.compute_metrics(WindowType.SLOW)
        reaction_type = self._classify_reaction(shock, metrics)

        self.total_classified += 1
        self.classification_counts[reaction_type] += 1
        self.by_window[WindowType.SLOW] += 1

        return self._create_reaction_event(shock, metrics, reaction_type, WindowType.SLOW)

    def classify(self, shock: ShockEvent) -> Optional[ReactionEvent]:
        """
        Classify a reaction after the observation window ends.
        兼容旧接口 - 使用 SLOW 窗口
        """
        return self.classify_slow(shock)

    def remove_observer(self, token_id: str, price: Decimal):
        """Remove observer after classification is complete."""
        key = (token_id, str(price))
        self.observers.pop(key, None)

    def _create_reaction_event(
        self,
        shock: ShockEvent,
        metrics: ReactionMetrics,
        reaction_type: ReactionType,
        window_type: WindowType
    ) -> ReactionEvent:
        """Create a ReactionEvent from metrics."""
        return ReactionEvent(
            shock_id=shock.shock_id,
            timestamp=int(time.time() * 1000),
            token_id=shock.token_id,
            price=shock.price,
            side=shock.side,
            reaction_type=reaction_type,
            window_type=window_type,
            baseline_size=shock.baseline_size,
            refill_ratio=metrics.refill_ratio,
            drop_ratio=metrics.drop_ratio,
            time_to_refill_ms=metrics.time_to_refill_ms,
            min_liquidity=metrics.min_liquidity,
            max_liquidity=metrics.max_liquidity,
            vacuum_duration_ms=metrics.vacuum_duration_ms,
            shift_ticks=metrics.shift_ticks,
            price_shift=metrics.price_shift,
            liquidity_before=shock.liquidity_before
        )

    def _classify_reaction(
        self,
        shock: ShockEvent,
        metrics: ReactionMetrics
    ) -> ReactionType:
        """
        Apply classification rules in priority order (Spec 1 v1).

        Priority: VACUUM > SWEEP > CHASE > PULL > HOLD > DELAYED
        """
        baseline = shock.baseline_size
        if baseline <= 0:
            baseline = shock.liquidity_before

        if baseline <= 0:
            return ReactionType.DELAYED  # Can't classify without baseline

        # 1. Check for VACUUM (highest priority)
        # vacuum_duration >= 3s OR (min_size <= 2% AND refill < 20%)
        is_vacuum = (
            metrics.vacuum_duration_ms >= VACUUM_DURATION_THRESHOLD_MS or
            (metrics.min_liquidity <= VACUUM_MIN_SIZE_RATIO * baseline and
             metrics.refill_ratio < VACUUM_REFILL_RATIO)
        )
        if is_vacuum:
            return ReactionType.VACUUM

        # 2. Check for SWEEP (multi-level sweep / fast repricing)
        # (price_shift AND drop >= 50%) OR shift >= 2 ticks
        has_shift = metrics.shift_ticks >= CHASE_SHIFT_TICKS
        is_sweep = (
            (has_shift and metrics.drop_ratio >= SWEEP_DROP_RATIO) or
            metrics.shift_ticks >= SWEEP_SHIFT_TICKS
        )
        if is_sweep:
            return ReactionType.SWEEP

        # 3. Check for CHASE (price anchor moved but not collapsed)
        # shift >= 1 tick AND not SWEEP
        if metrics.shift_ticks >= CHASE_SHIFT_TICKS:
            return ReactionType.CHASE

        # 4. Check for PULL (retreat)
        # drop >= 60% AND refill < 30%
        is_pull = (
            metrics.drop_ratio >= PULL_DROP_RATIO and
            metrics.refill_ratio < PULL_REFILL_RATIO
        )
        if is_pull:
            return ReactionType.PULL

        # 5. Check for HOLD (strong recovery)
        # refill >= 80% AND time_to_refill <= 5s AND no price shift
        is_hold = (
            metrics.refill_ratio >= HOLD_REFILL_THRESHOLD and
            metrics.time_to_refill_ms is not None and
            metrics.time_to_refill_ms <= HOLD_TIME_THRESHOLD_MS and
            metrics.shift_ticks == 0
        )
        if is_hold:
            return ReactionType.HOLD

        # 6. Default to DELAYED
        return ReactionType.DELAYED

    def has_active_observation(self, token_id: str, price: Decimal) -> bool:
        """Check if we're actively observing a level."""
        key = (token_id, str(price))
        return key in self.observers

    def get_stats(self) -> dict:
        """Get classifier statistics."""
        return {
            "total_classified": self.total_classified,
            "active_observations": len(self.observers),
            "by_type": {t.value: c for t, c in self.classification_counts.items()},
            "by_window": {w.value: c for w, c in self.by_window.items()}
        }
