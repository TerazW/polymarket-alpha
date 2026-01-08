"""
Belief Reaction System - Shock Detector v2
Detects when a price level is significantly impacted by trading activity.

v2 改进:
1. 使用 baseline_size (中位数) 而非单点 size
2. 添加绝对阈值 MIN_ABS_VOL
3. 双窗口: FAST (8s) + SLOW (30s)

"Shock" = discrete event where liquidity is TESTED, not just changed.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Tuple
import time

from .models import (
    TradeEvent, ShockEvent, PriceLevel
)
from .config import (
    SHOCK_TIME_WINDOW_MS,
    SHOCK_VOLUME_THRESHOLD,
    SHOCK_CONSECUTIVE_TRADES,
    BASELINE_WINDOW_START_MS,
    BASELINE_WINDOW_END_MS,
    MIN_ABS_VOL,
    REACTION_FAST_WINDOW_MS,
    REACTION_SLOW_WINDOW_MS
)


class ShockDetector:
    """
    Detects shock events when price levels are tested.

    v2 触发条件:
    1. Trade volume >= SHOCK_VOLUME_THRESHOLD * baseline_size within SHOCK_TIME_WINDOW_MS
       AND trade_volume >= MIN_ABS_VOL (绝对阈值)
    OR
    2. SHOCK_CONSECUTIVE_TRADES consecutive trades hit same price
    """

    def __init__(self):
        # Recent trades per (token_id, price)
        # Key: (token_id, price_str) -> List of (timestamp, size)
        self.recent_trades: Dict[Tuple[str, str], List[Tuple[int, float]]] = defaultdict(list)

        # Track consecutive trades at same price
        # Key: token_id -> (last_price, count)
        self.consecutive_tracker: Dict[str, Tuple[str, int]] = {}

        # Active shocks waiting for reaction window
        # Key: (token_id, price_str) -> ShockEvent
        self.active_shocks: Dict[Tuple[str, str], ShockEvent] = {}

        # Stats
        self.total_shocks_detected = 0
        self.shocks_by_trigger: Dict[str, int] = defaultdict(int)

    def on_trade(
        self,
        trade: TradeEvent,
        level: Optional[PriceLevel],
        tick_size: Decimal = Decimal("0.01")
    ) -> Optional[ShockEvent]:
        """
        Process a trade and check if it triggers a shock.

        Args:
            trade: The trade event
            level: The price level being hit (if exists)
            tick_size: Current tick size for the market

        Returns:
            ShockEvent if shock triggered, None otherwise
        """
        key = (trade.token_id, str(trade.price))
        now = trade.timestamp

        # Record this trade
        self.recent_trades[key].append((now, trade.size))

        # Prune old trades outside window
        self._prune_old_trades(key, now)

        # Check if shock already active for this level
        if key in self.active_shocks:
            return None  # Already in reaction window

        # 计算基准深度 (v2: 使用中位数而非单点值)
        if level:
            baseline_size = level.get_baseline_size(
                now,
                BASELINE_WINDOW_START_MS,
                BASELINE_WINDOW_END_MS
            )
            liquidity_before = level.size_now  # 保留单点值用于兼容
        else:
            baseline_size = 0.0
            liquidity_before = 0.0

        # Check shock conditions
        shock = None
        recent_volume = self._get_recent_volume(key)

        # Condition 1: Volume threshold (v2: 使用 baseline_size + 绝对阈值)
        if baseline_size > 0:
            volume_ratio = recent_volume / baseline_size
            meets_relative_threshold = volume_ratio >= SHOCK_VOLUME_THRESHOLD
            meets_absolute_threshold = recent_volume >= MIN_ABS_VOL

            if meets_relative_threshold and meets_absolute_threshold:
                shock = self._create_shock(
                    trade, recent_volume, liquidity_before, baseline_size,
                    'volume', tick_size, now
                )
                self.shocks_by_trigger['volume'] += 1

        # Condition 2: Consecutive trades (不需要绝对阈值)
        if not shock:
            consecutive = self._track_consecutive(trade)
            if consecutive >= SHOCK_CONSECUTIVE_TRADES:
                shock = self._create_shock(
                    trade, recent_volume, liquidity_before, baseline_size,
                    'consecutive', tick_size, now
                )
                self.shocks_by_trigger['consecutive'] += 1

        if shock:
            self.active_shocks[key] = shock
            self.total_shocks_detected += 1
            # Reset consecutive counter after shock
            self.consecutive_tracker[trade.token_id] = (str(trade.price), 0)
            return shock

        return None

    def _create_shock(
        self,
        trade: TradeEvent,
        trade_volume: float,
        liquidity_before: float,
        baseline_size: float,
        trigger_type: str,
        tick_size: Decimal,
        now: int
    ) -> ShockEvent:
        """Create a new ShockEvent with dual windows."""
        return ShockEvent(
            token_id=trade.token_id,
            price=trade.price,
            side='bid' if trade.side == 'SELL' else 'ask',  # Trade side is opposite
            ts_start=now,
            trade_volume=trade_volume,
            liquidity_before=liquidity_before,
            baseline_size=baseline_size,
            trigger_type=trigger_type,
            tick_size=tick_size,
            # 双窗口
            fast_window_end=now + REACTION_FAST_WINDOW_MS,
            slow_window_end=now + REACTION_SLOW_WINDOW_MS,
            reaction_window_end=now + REACTION_SLOW_WINDOW_MS  # 兼容旧字段
        )

    def get_active_shock(self, token_id: str, price: Decimal) -> Optional[ShockEvent]:
        """Get active shock for a level if exists."""
        key = (token_id, str(price))
        return self.active_shocks.get(key)

    def complete_shock(self, token_id: str, price: Decimal) -> Optional[ShockEvent]:
        """Mark shock as complete (reaction window ended)."""
        key = (token_id, str(price))
        return self.active_shocks.pop(key, None)

    def get_fast_window_expired_shocks(self, current_time: int) -> List[ShockEvent]:
        """Get all shocks whose FAST windows have expired but still active."""
        expired = []
        for key, shock in list(self.active_shocks.items()):
            if current_time >= shock.fast_window_end:
                expired.append(shock)
        return expired

    def get_slow_window_expired_shocks(self, current_time: int) -> List[ShockEvent]:
        """Get all shocks whose SLOW windows have expired."""
        expired = []
        for key, shock in list(self.active_shocks.items()):
            if current_time >= shock.slow_window_end:
                expired.append(shock)
        return expired

    def get_expired_shocks(self, current_time: int) -> List[ShockEvent]:
        """Get all shocks whose reaction windows have expired (兼容旧接口)."""
        return self.get_slow_window_expired_shocks(current_time)

    def _prune_old_trades(self, key: Tuple[str, str], now: int):
        """Remove trades outside the shock detection window."""
        cutoff = now - SHOCK_TIME_WINDOW_MS
        self.recent_trades[key] = [
            (ts, size) for ts, size in self.recent_trades[key]
            if ts > cutoff
        ]

    def _get_recent_volume(self, key: Tuple[str, str]) -> float:
        """Get total trade volume in recent window."""
        return sum(size for _, size in self.recent_trades[key])

    def _track_consecutive(self, trade: TradeEvent) -> int:
        """Track consecutive trades at same price, return count."""
        token_id = trade.token_id
        price_str = str(trade.price)

        if token_id not in self.consecutive_tracker:
            self.consecutive_tracker[token_id] = (price_str, 1)
            return 1

        last_price, count = self.consecutive_tracker[token_id]

        if last_price == price_str:
            count += 1
            self.consecutive_tracker[token_id] = (price_str, count)
            return count
        else:
            self.consecutive_tracker[token_id] = (price_str, 1)
            return 1

    def get_stats(self) -> dict:
        """Get detector statistics."""
        return {
            "total_shocks": self.total_shocks_detected,
            "active_shocks": len(self.active_shocks),
            "tracked_levels": len(self.recent_trades),
            "by_trigger": dict(self.shocks_by_trigger)
        }
