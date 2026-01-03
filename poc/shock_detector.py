"""
Belief Reaction System - Shock Detector
Detects when a price level is significantly impacted by trading activity.

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
    REACTION_WINDOW_MS
)


class ShockDetector:
    """
    Detects shock events when price levels are tested.

    A shock triggers when:
    1. Trade volume >= SHOCK_VOLUME_THRESHOLD * size_before within SHOCK_TIME_WINDOW_MS
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

    def on_trade(
        self,
        trade: TradeEvent,
        level: Optional[PriceLevel]
    ) -> Optional[ShockEvent]:
        """
        Process a trade and check if it triggers a shock.

        Args:
            trade: The trade event
            level: The price level being hit (if exists)

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

        # Get liquidity before (if level exists)
        liquidity_before = level.size_now if level else 0.0

        # Check shock conditions
        shock = None

        # Condition 1: Volume threshold
        recent_volume = self._get_recent_volume(key)
        if liquidity_before > 0 and recent_volume >= SHOCK_VOLUME_THRESHOLD * liquidity_before:
            shock = ShockEvent(
                token_id=trade.token_id,
                price=trade.price,
                side='bid' if trade.side == 'SELL' else 'ask',  # Trade side is opposite
                ts_start=now,
                trade_volume=recent_volume,
                liquidity_before=liquidity_before,
                trigger_type='volume',
                reaction_window_end=now + REACTION_WINDOW_MS
            )

        # Condition 2: Consecutive trades
        if not shock:
            consecutive = self._track_consecutive(trade)
            if consecutive >= SHOCK_CONSECUTIVE_TRADES:
                shock = ShockEvent(
                    token_id=trade.token_id,
                    price=trade.price,
                    side='bid' if trade.side == 'SELL' else 'ask',
                    ts_start=now,
                    trade_volume=recent_volume,
                    liquidity_before=liquidity_before,
                    trigger_type='consecutive',
                    reaction_window_end=now + REACTION_WINDOW_MS
                )

        if shock:
            self.active_shocks[key] = shock
            self.total_shocks_detected += 1
            # Reset consecutive counter after shock
            self.consecutive_tracker[trade.token_id] = (str(trade.price), 0)
            return shock

        return None

    def get_active_shock(self, token_id: str, price: Decimal) -> Optional[ShockEvent]:
        """Get active shock for a level if exists."""
        key = (token_id, str(price))
        return self.active_shocks.get(key)

    def complete_shock(self, token_id: str, price: Decimal) -> Optional[ShockEvent]:
        """Mark shock as complete (reaction window ended)."""
        key = (token_id, str(price))
        return self.active_shocks.pop(key, None)

    def get_expired_shocks(self, current_time: int) -> List[ShockEvent]:
        """Get all shocks whose reaction windows have expired."""
        expired = []
        for key, shock in list(self.active_shocks.items()):
            if current_time >= shock.reaction_window_end:
                expired.append(shock)
        return expired

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
            "tracked_levels": len(self.recent_trades)
        }
