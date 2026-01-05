"""
Belief Reaction System - Alert Router
Routes alerts to multiple destinations: Slack, Webhooks, Email, etc.

"告警闭环 - 让每个信号都能到达该到的地方"
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
import httpx

logger = logging.getLogger(__name__)


class AlertPriority(str, Enum):
    """Alert priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    """Alert categories for routing"""
    BELIEF_STATE = "belief_state"       # State machine transitions
    HASH_MISMATCH = "hash_mismatch"     # Data integrity failures
    DATA_GAP = "data_gap"               # Missing data
    SYSTEM = "system"                   # System health
    DETECTION = "detection"             # Shock/reaction detections


@dataclass
class AlertPayload:
    """Structured alert payload"""
    alert_id: str
    category: AlertCategory
    priority: AlertPriority
    title: str
    message: str
    token_id: Optional[str] = None
    ts: int = field(default_factory=lambda: int(time.time() * 1000))
    data: Dict[str, Any] = field(default_factory=dict)
    evidence_ref: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "category": self.category.value,
            "priority": self.priority.value,
            "title": self.title,
            "message": self.message,
            "token_id": self.token_id,
            "ts": self.ts,
            "data": self.data,
            "evidence_ref": self.evidence_ref,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# =============================================================================
# Alert Destinations (Abstract)
# =============================================================================

class AlertDestination(ABC):
    """Base class for alert destinations"""

    @abstractmethod
    async def send(self, alert: AlertPayload) -> bool:
        """Send alert to destination. Returns True if successful."""
        pass

    @abstractmethod
    def matches(self, alert: AlertPayload) -> bool:
        """Check if this destination should receive the alert."""
        pass


# =============================================================================
# Slack Destination
# =============================================================================

class SlackDestination(AlertDestination):
    """Send alerts to Slack via webhook"""

    # Priority to emoji mapping
    PRIORITY_EMOJI = {
        AlertPriority.LOW: ":information_source:",
        AlertPriority.MEDIUM: ":warning:",
        AlertPriority.HIGH: ":rotating_light:",
        AlertPriority.CRITICAL: ":fire:",
    }

    # Category to color mapping
    CATEGORY_COLOR = {
        AlertCategory.BELIEF_STATE: "#f97316",    # Orange
        AlertCategory.HASH_MISMATCH: "#ef4444",   # Red
        AlertCategory.DATA_GAP: "#eab308",        # Yellow
        AlertCategory.SYSTEM: "#3b82f6",          # Blue
        AlertCategory.DETECTION: "#22c55e",       # Green
    }

    def __init__(
        self,
        webhook_url: str,
        channel: Optional[str] = None,
        min_priority: AlertPriority = AlertPriority.LOW,
        categories: Optional[List[AlertCategory]] = None,
        mention_users: Optional[Dict[AlertPriority, List[str]]] = None,
    ):
        self.webhook_url = webhook_url
        self.channel = channel
        self.min_priority = min_priority
        self.categories = categories  # None = all categories
        self.mention_users = mention_users or {}
        self._client = httpx.AsyncClient(timeout=10.0)

    def matches(self, alert: AlertPayload) -> bool:
        """Check if alert matches this destination's filters"""
        # Check priority
        priority_order = {AlertPriority.LOW: 0, AlertPriority.MEDIUM: 1,
                         AlertPriority.HIGH: 2, AlertPriority.CRITICAL: 3}
        if priority_order[alert.priority] < priority_order[self.min_priority]:
            return False

        # Check category
        if self.categories and alert.category not in self.categories:
            return False

        return True

    async def send(self, alert: AlertPayload) -> bool:
        """Send alert to Slack"""
        try:
            emoji = self.PRIORITY_EMOJI.get(alert.priority, ":bell:")
            color = self.CATEGORY_COLOR.get(alert.category, "#808080")

            # Build mention string
            mentions = ""
            if alert.priority in self.mention_users:
                user_mentions = " ".join(f"<@{u}>" for u in self.mention_users[alert.priority])
                mentions = f"\n{user_mentions}"

            # Build Slack message
            payload = {
                "attachments": [
                    {
                        "color": color,
                        "blocks": [
                            {
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": f"{emoji} {alert.title}",
                                    "emoji": True
                                }
                            },
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": alert.message + mentions
                                }
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {
                                        "type": "mrkdwn",
                                        "text": f"*Category:* {alert.category.value} | *Priority:* {alert.priority.value} | *ID:* {alert.alert_id}"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }

            # Add token info if available
            if alert.token_id:
                payload["attachments"][0]["blocks"].insert(2, {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Token:*\n`{alert.token_id[:16]}...`"},
                        {"type": "mrkdwn", "text": f"*Time:*\n<!date^{alert.ts // 1000}^{{date_short_pretty}} at {{time}}|{datetime.fromtimestamp(alert.ts / 1000).isoformat()}>"}
                    ]
                })

            # Add evidence link if available
            if alert.evidence_ref:
                payload["attachments"][0]["blocks"].append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View Evidence"},
                            "url": f"/market/{alert.evidence_ref.get('token_id', '')}?t0={alert.evidence_ref.get('t0', '')}"
                        }
                    ]
                })

            if self.channel:
                payload["channel"] = self.channel

            response = await self._client.post(self.webhook_url, json=payload)
            success = response.status_code == 200

            if success:
                logger.info(f"[SLACK] Alert {alert.alert_id} sent successfully")
            else:
                logger.warning(f"[SLACK] Failed to send alert {alert.alert_id}: {response.status_code}")

            return success

        except Exception as e:
            logger.error(f"[SLACK] Error sending alert {alert.alert_id}: {e}")
            return False

    async def close(self):
        """Close the HTTP client"""
        await self._client.aclose()


# =============================================================================
# Generic Webhook Destination
# =============================================================================

class WebhookDestination(AlertDestination):
    """Send alerts to generic webhook endpoints"""

    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        min_priority: AlertPriority = AlertPriority.LOW,
        categories: Optional[List[AlertCategory]] = None,
        transform: Optional[Callable[[AlertPayload], Dict]] = None,
    ):
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.min_priority = min_priority
        self.categories = categories
        self.transform = transform  # Optional payload transformer
        self._client = httpx.AsyncClient(timeout=10.0)

    def matches(self, alert: AlertPayload) -> bool:
        priority_order = {AlertPriority.LOW: 0, AlertPriority.MEDIUM: 1,
                         AlertPriority.HIGH: 2, AlertPriority.CRITICAL: 3}
        if priority_order[alert.priority] < priority_order[self.min_priority]:
            return False
        if self.categories and alert.category not in self.categories:
            return False
        return True

    async def send(self, alert: AlertPayload) -> bool:
        try:
            payload = self.transform(alert) if self.transform else alert.to_dict()

            response = await self._client.post(
                self.url,
                json=payload,
                headers=self.headers
            )
            success = 200 <= response.status_code < 300

            if success:
                logger.info(f"[WEBHOOK] Alert {alert.alert_id} sent to {self.url}")
            else:
                logger.warning(f"[WEBHOOK] Failed: {response.status_code} - {response.text[:100]}")

            return success

        except Exception as e:
            logger.error(f"[WEBHOOK] Error sending to {self.url}: {e}")
            return False

    async def close(self):
        await self._client.aclose()


# =============================================================================
# Log Destination (for testing/audit)
# =============================================================================

class LogDestination(AlertDestination):
    """Log alerts to Python logger (useful for testing/audit)"""

    def __init__(
        self,
        logger_name: str = "alert_router",
        min_priority: AlertPriority = AlertPriority.LOW,
    ):
        self.logger = logging.getLogger(logger_name)
        self.min_priority = min_priority

    def matches(self, alert: AlertPayload) -> bool:
        priority_order = {AlertPriority.LOW: 0, AlertPriority.MEDIUM: 1,
                         AlertPriority.HIGH: 2, AlertPriority.CRITICAL: 3}
        return priority_order[alert.priority] >= priority_order[self.min_priority]

    async def send(self, alert: AlertPayload) -> bool:
        level = {
            AlertPriority.LOW: logging.INFO,
            AlertPriority.MEDIUM: logging.WARNING,
            AlertPriority.HIGH: logging.ERROR,
            AlertPriority.CRITICAL: logging.CRITICAL,
        }.get(alert.priority, logging.INFO)

        self.logger.log(
            level,
            f"[ALERT] {alert.priority.value.upper()} - {alert.title}\n"
            f"  Category: {alert.category.value}\n"
            f"  Message: {alert.message}\n"
            f"  Token: {alert.token_id}\n"
            f"  Alert ID: {alert.alert_id}"
        )
        return True


# =============================================================================
# WebSocket Broadcast Destination
# =============================================================================

class WebSocketBroadcastDestination(AlertDestination):
    """Broadcast alerts via WebSocket stream"""

    def __init__(
        self,
        min_priority: AlertPriority = AlertPriority.LOW,
        categories: Optional[List[AlertCategory]] = None,
    ):
        self.min_priority = min_priority
        self.categories = categories

    def matches(self, alert: AlertPayload) -> bool:
        priority_order = {AlertPriority.LOW: 0, AlertPriority.MEDIUM: 1,
                         AlertPriority.HIGH: 2, AlertPriority.CRITICAL: 3}
        if priority_order[alert.priority] < priority_order[self.min_priority]:
            return False
        if self.categories and alert.category not in self.categories:
            return False
        return True

    async def send(self, alert: AlertPayload) -> bool:
        try:
            from backend.api.stream import publish_alert, StreamEventType

            await publish_alert(
                {
                    "alert_id": alert.alert_id,
                    "token_id": alert.token_id,
                    "severity": alert.priority.value.upper(),
                    "category": alert.category.value,
                    "summary": alert.title,
                    "message": alert.message,
                    "ts": alert.ts,
                    "data": alert.data,
                },
                event_type=StreamEventType.ALERT_NEW
            )
            logger.debug(f"[WS] Alert {alert.alert_id} broadcast via WebSocket")
            return True

        except Exception as e:
            logger.error(f"[WS] Error broadcasting alert: {e}")
            return False


# =============================================================================
# Alert Router (Main Class)
# =============================================================================

class AlertRouter:
    """
    Routes alerts to multiple destinations based on priority and category.

    Usage:
        router = AlertRouter()
        router.add_destination(SlackDestination(webhook_url="..."))
        router.add_destination(WebhookDestination(url="..."))

        await router.route(AlertPayload(...))
    """

    def __init__(self):
        self.destinations: List[AlertDestination] = []
        self._stats = {
            "alerts_routed": 0,
            "alerts_delivered": 0,
            "alerts_failed": 0,
            "by_priority": {p.value: 0 for p in AlertPriority},
            "by_category": {c.value: 0 for c in AlertCategory},
        }

    def add_destination(self, destination: AlertDestination):
        """Add a destination to the router"""
        self.destinations.append(destination)
        logger.info(f"[ROUTER] Added destination: {destination.__class__.__name__}")

    async def route(self, alert: AlertPayload) -> Dict[str, bool]:
        """
        Route alert to all matching destinations.
        Returns dict of destination_name -> success.
        """
        results = {}

        self._stats["alerts_routed"] += 1
        self._stats["by_priority"][alert.priority.value] += 1
        self._stats["by_category"][alert.category.value] += 1

        for dest in self.destinations:
            dest_name = dest.__class__.__name__
            if dest.matches(alert):
                try:
                    success = await dest.send(alert)
                    results[dest_name] = success
                    if success:
                        self._stats["alerts_delivered"] += 1
                    else:
                        self._stats["alerts_failed"] += 1
                except Exception as e:
                    logger.error(f"[ROUTER] Error routing to {dest_name}: {e}")
                    results[dest_name] = False
                    self._stats["alerts_failed"] += 1

        return results

    async def route_many(self, alerts: List[AlertPayload]) -> List[Dict[str, bool]]:
        """Route multiple alerts"""
        return [await self.route(alert) for alert in alerts]

    def get_stats(self) -> Dict:
        """Get routing statistics"""
        return self._stats.copy()

    async def close(self):
        """Close all destinations"""
        for dest in self.destinations:
            if hasattr(dest, 'close'):
                await dest.close()


# =============================================================================
# Factory Functions
# =============================================================================

def create_router_from_config(config: Dict) -> AlertRouter:
    """
    Create AlertRouter from configuration dict.

    Example config:
    {
        "slack": {
            "webhook_url": "https://hooks.slack.com/...",
            "channel": "#alerts",
            "min_priority": "high",
            "mention_users": {"critical": ["U123", "U456"]}
        },
        "webhook": {
            "url": "https://api.example.com/alerts",
            "headers": {"Authorization": "Bearer ..."}
        },
        "websocket": {
            "enabled": true
        },
        "log": {
            "enabled": true,
            "min_priority": "low"
        }
    }
    """
    router = AlertRouter()

    # Slack
    if slack_cfg := config.get("slack"):
        if webhook_url := slack_cfg.get("webhook_url"):
            mention_users = {}
            for priority_str, users in slack_cfg.get("mention_users", {}).items():
                try:
                    mention_users[AlertPriority(priority_str)] = users
                except ValueError:
                    pass

            router.add_destination(SlackDestination(
                webhook_url=webhook_url,
                channel=slack_cfg.get("channel"),
                min_priority=AlertPriority(slack_cfg.get("min_priority", "low")),
                mention_users=mention_users,
            ))

    # Generic Webhook
    if webhook_cfg := config.get("webhook"):
        if url := webhook_cfg.get("url"):
            router.add_destination(WebhookDestination(
                url=url,
                headers=webhook_cfg.get("headers"),
                min_priority=AlertPriority(webhook_cfg.get("min_priority", "low")),
            ))

    # WebSocket broadcast
    if ws_cfg := config.get("websocket"):
        if ws_cfg.get("enabled", True):
            router.add_destination(WebSocketBroadcastDestination(
                min_priority=AlertPriority(ws_cfg.get("min_priority", "low")),
            ))

    # Log destination
    if log_cfg := config.get("log"):
        if log_cfg.get("enabled", False):
            router.add_destination(LogDestination(
                min_priority=AlertPriority(log_cfg.get("min_priority", "low")),
            ))

    return router


# =============================================================================
# Global Router Instance
# =============================================================================

# Default router with WebSocket and Log destinations
_default_router: Optional[AlertRouter] = None


def get_default_router() -> AlertRouter:
    """Get or create the default alert router"""
    global _default_router
    if _default_router is None:
        _default_router = AlertRouter()
        _default_router.add_destination(WebSocketBroadcastDestination())
        _default_router.add_destination(LogDestination(min_priority=AlertPriority.MEDIUM))
    return _default_router


async def route_alert(alert: AlertPayload) -> Dict[str, bool]:
    """Convenience function to route alert via default router"""
    return await get_default_router().route(alert)
