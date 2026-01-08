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
class AlertConfig:
    """
    Alert destinations configuration.

    Supports Slack, Email (SMTP), Webhooks, WebSocket broadcast.
    See ADR-004 for evidence grade → alert severity binding requirements.
    """
    # Slack
    slack_webhook_url: Optional[str] = os.getenv("SLACK_WEBHOOK_URL")
    slack_channel: Optional[str] = os.getenv("SLACK_CHANNEL")
    slack_min_priority: str = os.getenv("SLACK_MIN_PRIORITY", "high")
    slack_critical_mentions: Optional[str] = os.getenv("SLACK_CRITICAL_MENTIONS")  # comma-separated user IDs

    # Email (SMTP)
    smtp_host: Optional[str] = os.getenv("SMTP_HOST")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: Optional[str] = os.getenv("SMTP_USER")
    smtp_password: Optional[str] = os.getenv("SMTP_PASSWORD")
    smtp_from_addr: str = os.getenv("SMTP_FROM_ADDR", "alerts@belief-reaction.local")
    smtp_to_addrs: Optional[str] = os.getenv("SMTP_TO_ADDRS")  # comma-separated
    smtp_min_priority: str = os.getenv("SMTP_MIN_PRIORITY", "high")

    # Generic Webhook
    webhook_url: Optional[str] = os.getenv("ALERT_WEBHOOK_URL")
    webhook_auth_header: Optional[str] = os.getenv("ALERT_WEBHOOK_AUTH")  # "Authorization: Bearer ..."
    webhook_min_priority: str = os.getenv("WEBHOOK_MIN_PRIORITY", "medium")

    # WebSocket broadcast
    websocket_enabled: bool = os.getenv("ALERT_WS_ENABLED", "true").lower() == "true"
    websocket_min_priority: str = os.getenv("ALERT_WS_MIN_PRIORITY", "low")

    # Log destination (for debugging)
    log_enabled: bool = os.getenv("ALERT_LOG_ENABLED", "false").lower() == "true"
    log_min_priority: str = os.getenv("ALERT_LOG_MIN_PRIORITY", "low")

    def to_router_config(self) -> dict:
        """Convert to router configuration dict."""
        config = {}

        # Slack
        if self.slack_webhook_url:
            mention_users = {}
            if self.slack_critical_mentions:
                mention_users["critical"] = [u.strip() for u in self.slack_critical_mentions.split(",")]
            config["slack"] = {
                "webhook_url": self.slack_webhook_url,
                "channel": self.slack_channel,
                "min_priority": self.slack_min_priority,
                "mention_users": mention_users,
            }

        # Email
        if self.smtp_host:
            to_addrs = []
            if self.smtp_to_addrs:
                to_addrs = [a.strip() for a in self.smtp_to_addrs.split(",")]
            config["email"] = {
                "smtp_host": self.smtp_host,
                "smtp_port": self.smtp_port,
                "smtp_user": self.smtp_user,
                "smtp_password": self.smtp_password,
                "from_addr": self.smtp_from_addr,
                "to_addrs": to_addrs,
                "min_priority": self.smtp_min_priority,
            }

        # Webhook
        if self.webhook_url:
            headers = {"Content-Type": "application/json"}
            if self.webhook_auth_header:
                parts = self.webhook_auth_header.split(":", 1)
                if len(parts) == 2:
                    headers[parts[0].strip()] = parts[1].strip()
            config["webhook"] = {
                "url": self.webhook_url,
                "headers": headers,
                "min_priority": self.webhook_min_priority,
            }

        # WebSocket
        config["websocket"] = {
            "enabled": self.websocket_enabled,
            "min_priority": self.websocket_min_priority,
        }

        # Log
        config["log"] = {
            "enabled": self.log_enabled,
            "min_priority": self.log_min_priority,
        }

        return config


@dataclass
class Config:
    """Main configuration object."""
    database: DatabaseConfig
    polymarket: PolymarketConfig
    shock: ShockConfig
    reaction: ReactionConfig
    belief_state: BeliefStateConfig
    collector: CollectorConfig
    alerting: AlertConfig

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
            alerting=AlertConfig(),
        )


# Global config instance
config = Config.load()
