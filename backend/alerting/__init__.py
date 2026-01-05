"""
Belief Reaction System - Alerting Module
Handles alert routing to multiple destinations.
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

__all__ = [
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
]
