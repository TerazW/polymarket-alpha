"""
Trading System Configuration

All trading parameters loaded from environment variables with safe defaults.
"""

import os
from dataclasses import dataclass
from typing import Optional

from backend.strategy.kelly import KellyConfig
from backend.strategy.risk_manager import RiskConfig
from backend.trading.trader import TradingConfig


def load_trading_config() -> TradingConfig:
    """Load trading configuration from environment variables."""
    kelly = KellyConfig(
        max_fraction=float(os.getenv("KELLY_MAX_FRACTION", "0.25")),
        kelly_multiplier=float(os.getenv("KELLY_MULTIPLIER", "0.5")),
        min_edge=float(os.getenv("KELLY_MIN_EDGE", "0.02")),
        min_confidence=float(os.getenv("KELLY_MIN_CONFIDENCE", "0.55")),
    )

    risk = RiskConfig(
        initial_bankroll=float(os.getenv("TRADING_BANKROLL", "10000.0")),
        max_drawdown=float(os.getenv("RISK_MAX_DRAWDOWN", "0.15")),
        elevated_drawdown=float(os.getenv("RISK_ELEVATED_DRAWDOWN", "0.05")),
        high_drawdown=float(os.getenv("RISK_HIGH_DRAWDOWN", "0.10")),
        max_single_position=float(os.getenv("RISK_MAX_SINGLE_POSITION", "0.10")),
        max_total_exposure=float(os.getenv("RISK_MAX_TOTAL_EXPOSURE", "0.50")),
        max_correlated_exposure=float(os.getenv("RISK_MAX_CORRELATED_EXPOSURE", "0.25")),
        max_trade_size=float(os.getenv("RISK_MAX_TRADE_SIZE", "0.05")),
        min_trade_size=float(os.getenv("RISK_MIN_TRADE_SIZE", "5.0")),
        volatile_regime_scale=float(os.getenv("RISK_VOLATILE_SCALE", "0.5")),
        max_losses_per_hour=int(os.getenv("RISK_MAX_LOSSES_HOUR", "5")),
        halt_duration_seconds=float(os.getenv("RISK_HALT_DURATION", "3600")),
        max_daily_loss=float(os.getenv("RISK_MAX_DAILY_LOSS", "0.05")),
        max_daily_trades=int(os.getenv("RISK_MAX_DAILY_TRADES", "100")),
    )

    return TradingConfig(
        signal_interval_seconds=float(os.getenv("TRADING_SIGNAL_INTERVAL", "10.0")),
        feedback_interval_seconds=float(os.getenv("TRADING_FEEDBACK_INTERVAL", "60.0")),
        min_direction_strength=float(os.getenv("TRADING_MIN_DIRECTION", "0.15")),
        min_edge=float(os.getenv("TRADING_MIN_EDGE", "0.02")),
        min_confidence=float(os.getenv("TRADING_MIN_CONFIDENCE", "0.55")),
        paper_mode=os.getenv("TRADING_PAPER_MODE", "true").lower() == "true",
        max_slippage=float(os.getenv("TRADING_MAX_SLIPPAGE", "0.01")),
        kelly_config=kelly,
        risk_config=risk,
    )
