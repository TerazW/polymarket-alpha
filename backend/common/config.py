"""
Belief Reaction System - Configuration
Centralized configuration from environment variables.
"""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load .env file
load_dotenv()


@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/belief_reaction")
    pool_size: int = int(os.getenv("DB_POOL_SIZE", "5"))
    max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))


@dataclass
class PolymarketConfig:
    """Polymarket API configuration."""
    # WebSocket
    ws_market_url: str = os.getenv("WS_MARKET_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
    ws_ping_interval: int = int(os.getenv("WS_PING_INTERVAL", "10"))

    # REST APIs
    gamma_base_url: str = os.getenv("GAMMA_BASE_URL", "https://gamma-api.polymarket.com")
    clob_rest_base_url: str = os.getenv("CLOB_REST_BASE_URL", "https://clob.polymarket.com")
    data_api_base_url: str = os.getenv("DATA_API_BASE_URL", "https://data-api.polymarket.com")


@dataclass
class ShockConfig:
    """Shock detection configuration."""
    time_window_ms: int = int(os.getenv("SHOCK_TIME_WINDOW_MS", "2000"))
    volume_threshold: float = float(os.getenv("SHOCK_VOLUME_THRESHOLD", "0.35"))
    consecutive_trades: int = int(os.getenv("SHOCK_CONSECUTIVE_TRADES", "3"))


@dataclass
class ReactionConfig:
    """Reaction classification configuration."""
    window_ms: int = int(os.getenv("REACTION_WINDOW_MS", "20000"))
    sample_interval_ms: int = int(os.getenv("REACTION_SAMPLE_INTERVAL_MS", "500"))
    hold_refill_threshold: float = float(os.getenv("HOLD_REFILL_THRESHOLD", "0.8"))
    hold_time_threshold_ms: int = int(os.getenv("HOLD_TIME_THRESHOLD_MS", "5000"))
    vacuum_threshold: float = float(os.getenv("VACUUM_THRESHOLD", "0.05"))
    pull_threshold: float = float(os.getenv("PULL_THRESHOLD", "0.1"))


@dataclass
class BeliefStateConfig:
    """Belief state machine configuration."""
    key_levels_count: int = int(os.getenv("KEY_LEVELS_COUNT", "5"))
    key_levels_lookback_hours: int = int(os.getenv("KEY_LEVELS_LOOKBACK_HOURS", "24"))
    state_reaction_window: int = int(os.getenv("STATE_REACTION_WINDOW", "10"))


@dataclass
class CollectorConfig:
    """Collector configuration."""
    bin_interval_ms: int = int(os.getenv("BIN_INTERVAL_MS", "250"))
    max_markets: int = int(os.getenv("MAX_MARKETS", "100"))
    reconnect_delay_s: int = int(os.getenv("RECONNECT_DELAY_S", "5"))
    max_reconnect_attempts: int = int(os.getenv("MAX_RECONNECT_ATTEMPTS", "10"))


@dataclass
class Config:
    """Main configuration object."""
    database: DatabaseConfig
    polymarket: PolymarketConfig
    shock: ShockConfig
    reaction: ReactionConfig
    belief_state: BeliefStateConfig
    collector: CollectorConfig

    # Redis (optional)
    redis_url: Optional[str] = os.getenv("REDIS_URL")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment."""
        return cls(
            database=DatabaseConfig(),
            polymarket=PolymarketConfig(),
            shock=ShockConfig(),
            reaction=ReactionConfig(),
            belief_state=BeliefStateConfig(),
            collector=CollectorConfig(),
        )


# Global config instance
config = Config.load()
