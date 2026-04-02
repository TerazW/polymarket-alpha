"""
Risk Management System

Implements:
1. Drawdown controls with dynamic position scaling
2. Per-market and portfolio-level position limits
3. Correlation-aware exposure management
4. Regime-aware risk adjustment (integrates with HMM)
5. Circuit breakers for extreme conditions

References:
- MacLean, Thorp & Ziemba (2011) "The Kelly Capital Growth Investment Criterion"
  - Full Kelly: P(drawdown >= d) ~ d^{-1}
  - Half Kelly: P(drawdown >= d) ~ d^{-2} (much safer)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import deque
from enum import Enum
import time
import logging

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    HALTED = "HALTED"


@dataclass
class RiskConfig:
    """Risk management configuration."""
    # Bankroll
    initial_bankroll: float = 10000.0

    # Drawdown limits
    max_drawdown: float = 0.15          # 15% max drawdown -> halt trading
    elevated_drawdown: float = 0.05     # 5% -> reduce position sizes
    high_drawdown: float = 0.10         # 10% -> significantly reduce

    # Position limits
    max_single_position: float = 0.10   # 10% of bankroll per market
    max_total_exposure: float = 0.50    # 50% of bankroll total
    max_correlated_exposure: float = 0.25  # 25% in correlated markets

    # Per-trade limits
    max_trade_size: float = 0.05        # 5% of bankroll per trade
    min_trade_size: float = 5.0         # Minimum $5 trade

    # Regime-based scaling
    volatile_regime_scale: float = 0.5  # Cut sizes by 50% in volatile regime
    calm_regime_scale: float = 1.0      # Full size in calm regime

    # Circuit breaker
    max_losses_per_hour: int = 5        # Max consecutive losing trades per hour
    halt_duration_seconds: float = 3600.0  # 1 hour halt after circuit breaker

    # Daily limits
    max_daily_loss: float = 0.05        # 5% daily loss limit
    max_daily_trades: int = 100


@dataclass
class Position:
    """Represents an open position."""
    market_id: str
    side: str                  # "YES" or "NO"
    entry_price: float
    size: float               # Dollar amount
    quantity: float            # Number of contracts
    entry_time: float
    correlation_group: Optional[str] = None


class RiskManager:
    """
    Portfolio-level risk management.

    Controls position sizing, monitors drawdown, manages correlation
    exposure, and implements circuit breakers.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.bankroll = self.config.initial_bankroll
        self.peak_bankroll = self.bankroll

        # Open positions
        self.positions: Dict[str, Position] = {}

        # PnL tracking
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._daily_reset_time = time.time()

        # Loss tracking for circuit breaker
        self._recent_losses: deque = deque(maxlen=20)

        # Risk state
        self.risk_level = RiskLevel.NORMAL
        self._halt_until: float = 0.0

        # Current regime (updated externally)
        self._current_regime: str = "CALM"

    def evaluate_trade(
        self,
        market_id: str,
        side: str,
        size_usd: float,
        entry_price: float,
        correlation_group: Optional[str] = None,
    ) -> Dict:
        """
        Evaluate whether a trade should be allowed.

        Returns:
            {
                "approved": bool,
                "adjusted_size": float,
                "reason": str,
                "risk_level": RiskLevel,
            }
        """
        self._check_daily_reset()

        # Circuit breaker check
        if self.risk_level == RiskLevel.HALTED:
            if time.time() < self._halt_until:
                return self._reject("circuit_breaker_active")
            self.risk_level = RiskLevel.NORMAL
            logger.info("Circuit breaker lifted")

        # Daily loss limit
        if self._daily_pnl < -self.config.max_daily_loss * self.bankroll:
            return self._reject("daily_loss_limit")

        # Daily trade count
        if self._daily_trades >= self.config.max_daily_trades:
            return self._reject("daily_trade_limit")

        # Drawdown check
        drawdown = self._current_drawdown()
        if drawdown >= self.config.max_drawdown:
            self.risk_level = RiskLevel.HALTED
            self._halt_until = time.time() + self.config.halt_duration_seconds
            return self._reject("max_drawdown_reached")

        # Position scaling based on drawdown
        scale = self._drawdown_scale(drawdown)

        # Regime-based scaling
        regime_scale = self._regime_scale()
        scale *= regime_scale

        adjusted_size = size_usd * scale

        # Per-trade limit
        adjusted_size = min(adjusted_size, self.config.max_trade_size * self.bankroll)

        # Minimum trade size
        if adjusted_size < self.config.min_trade_size:
            return self._reject("below_minimum_size")

        # Single position limit
        existing = self.positions.get(market_id)
        existing_exposure = existing.size if existing else 0.0
        if existing_exposure + adjusted_size > self.config.max_single_position * self.bankroll:
            adjusted_size = max(
                0, self.config.max_single_position * self.bankroll - existing_exposure
            )
            if adjusted_size < self.config.min_trade_size:
                return self._reject("single_position_limit")

        # Total exposure limit
        total_exposure = sum(p.size for p in self.positions.values())
        if total_exposure + adjusted_size > self.config.max_total_exposure * self.bankroll:
            adjusted_size = max(
                0, self.config.max_total_exposure * self.bankroll - total_exposure
            )
            if adjusted_size < self.config.min_trade_size:
                return self._reject("total_exposure_limit")

        # Correlation group limit
        if correlation_group:
            group_exposure = sum(
                p.size for p in self.positions.values()
                if p.correlation_group == correlation_group
            )
            if group_exposure + adjusted_size > self.config.max_correlated_exposure * self.bankroll:
                adjusted_size = max(
                    0, self.config.max_correlated_exposure * self.bankroll - group_exposure
                )
                if adjusted_size < self.config.min_trade_size:
                    return self._reject("correlated_exposure_limit")

        self._update_risk_level(drawdown)

        return {
            "approved": True,
            "adjusted_size": adjusted_size,
            "reason": "approved",
            "risk_level": self.risk_level,
            "drawdown": drawdown,
            "scale_applied": scale,
        }

    def open_position(
        self,
        market_id: str,
        side: str,
        entry_price: float,
        size: float,
        quantity: float,
        correlation_group: Optional[str] = None,
    ):
        """Record a new open position."""
        self.positions[market_id] = Position(
            market_id=market_id,
            side=side,
            entry_price=entry_price,
            size=size,
            quantity=quantity,
            entry_time=time.time(),
            correlation_group=correlation_group,
        )
        self._daily_trades += 1
        logger.info(
            f"Position opened: {market_id} {side} ${size:.2f} @ {entry_price:.4f}"
        )

    def close_position(self, market_id: str, exit_price: float) -> Optional[float]:
        """
        Close a position and record PnL.

        Returns realized PnL.
        """
        pos = self.positions.pop(market_id, None)
        if pos is None:
            return None

        if pos.side == "YES":
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        self.bankroll += pnl
        self.peak_bankroll = max(self.peak_bankroll, self.bankroll)
        self._daily_pnl += pnl

        # Track for circuit breaker
        self._recent_losses.append((time.time(), pnl))

        if pnl < 0:
            self._check_circuit_breaker()

        logger.info(
            f"Position closed: {market_id} PnL=${pnl:.2f} "
            f"Bankroll=${self.bankroll:.2f}"
        )
        return pnl

    def settle_position(self, market_id: str, outcome: int) -> Optional[float]:
        """
        Settle a position at market resolution.

        Args:
            outcome: 1 = YES wins, 0 = NO wins
        """
        exit_price = 1.0 if outcome == 1 else 0.0
        return self.close_position(market_id, exit_price)

    def update_regime(self, regime: str):
        """Update current market regime (from HMM)."""
        self._current_regime = regime

    def get_portfolio_summary(self) -> Dict:
        """Get current portfolio state."""
        total_exposure = sum(p.size for p in self.positions.values())
        return {
            "bankroll": self.bankroll,
            "peak_bankroll": self.peak_bankroll,
            "drawdown": self._current_drawdown(),
            "risk_level": self.risk_level.value,
            "num_positions": len(self.positions),
            "total_exposure": total_exposure,
            "exposure_pct": total_exposure / self.bankroll if self.bankroll > 0 else 0,
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
            "regime": self._current_regime,
        }

    def _current_drawdown(self) -> float:
        if self.peak_bankroll <= 0:
            return 0.0
        return 1.0 - self.bankroll / self.peak_bankroll

    def _drawdown_scale(self, drawdown: float) -> float:
        """Scale position sizes based on current drawdown."""
        if drawdown < self.config.elevated_drawdown:
            return 1.0
        elif drawdown < self.config.high_drawdown:
            # Linear reduction from 1.0 to 0.5
            frac = (drawdown - self.config.elevated_drawdown) / (
                self.config.high_drawdown - self.config.elevated_drawdown
            )
            return 1.0 - 0.5 * frac
        else:
            # Further reduction
            frac = (drawdown - self.config.high_drawdown) / (
                self.config.max_drawdown - self.config.high_drawdown
            )
            return max(0.1, 0.5 - 0.4 * frac)

    def _regime_scale(self) -> float:
        """Scale based on current market regime."""
        if self._current_regime == "VOLATILE":
            return self.config.volatile_regime_scale
        elif self._current_regime == "CALM":
            return self.config.calm_regime_scale
        else:
            return 0.75  # Moderate for TRENDING

    def _check_circuit_breaker(self):
        """Check if circuit breaker should trigger."""
        now = time.time()
        hour_ago = now - 3600
        recent = [pnl for ts, pnl in self._recent_losses if ts > hour_ago and pnl < 0]
        if len(recent) >= self.config.max_losses_per_hour:
            self.risk_level = RiskLevel.HALTED
            self._halt_until = now + self.config.halt_duration_seconds
            logger.warning(
                f"Circuit breaker triggered: {len(recent)} losses in last hour"
            )

    def _update_risk_level(self, drawdown: float):
        if self.risk_level == RiskLevel.HALTED:
            return
        if drawdown >= self.config.high_drawdown:
            self.risk_level = RiskLevel.HIGH
        elif drawdown >= self.config.elevated_drawdown:
            self.risk_level = RiskLevel.ELEVATED
        else:
            self.risk_level = RiskLevel.NORMAL

    def _check_daily_reset(self):
        """Reset daily counters at midnight."""
        now = time.time()
        if now - self._daily_reset_time > 86400:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._daily_reset_time = now

    def _reject(self, reason: str) -> Dict:
        return {
            "approved": False,
            "adjusted_size": 0.0,
            "reason": reason,
            "risk_level": self.risk_level,
        }
