"""
Belief Reaction System - Alerting Module
Handles alert routing and operational management.

v5.15: Add AlertOpsManager for dedup, auto-resolve, explain log
"""

from .router import (
    AlertRouter,
    AlertPayload,
    AlertPriority,
    AlertCategory,
    AlertDestination,
    SlackDestination,
    WebhookDestination,
    LogDestination,
    WebSocketBroadcastDestination,
    create_router_from_config,
    get_default_router,
    route_alert,
)

from .ops import (
    AlertOpsManager,
    AlertStatus,
    ResolutionRule,
    ManagedAlert,
    ExplainLogEntry,
    generate_dedup_key,
    get_ops_manager,
    ALERT_TTL_MS,
    DEDUP_WINDOW_MS,
    STATE_RECOVERY_GRACE_MS,
)

__all__ = [
    # Router
    "AlertRouter",
    "AlertPayload",
    "AlertPriority",
    "AlertCategory",
    "AlertDestination",
    "SlackDestination",
    "WebhookDestination",
    "LogDestination",
    "WebSocketBroadcastDestination",
    "create_router_from_config",
    "get_default_router",
    "route_alert",
    # Ops (v5.15)
    "AlertOpsManager",
    "AlertStatus",
    "ResolutionRule",
    "ManagedAlert",
    "ExplainLogEntry",
    "generate_dedup_key",
    "get_ops_manager",
    "ALERT_TTL_MS",
    "DEDUP_WINDOW_MS",
    "STATE_RECOVERY_GRACE_MS",
]
