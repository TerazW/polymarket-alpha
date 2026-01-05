"""
Belief Reaction System - Alert Ops Manager v5.15
Operational management: deduplication, auto-resolve, and explain log.

P0-3 Implementation:
- 去重键 (dedup_key): Prevent duplicate alerts within window
- 自动 resolve: Auto-close alerts on state recovery or TTL
- Explain log: Full audit trail of alert lifecycle changes

"每个告警都有生命周期，每次变更都有记录"
"""

import asyncio
import time
import uuid
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Tuple
from collections import defaultdict

from .router import AlertPayload, AlertPriority, AlertCategory

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class AlertStatus(str, Enum):
    """Alert lifecycle status"""
    OPEN = "OPEN"                    # Active alert
    AUTO_RESOLVED = "AUTO_RESOLVED"  # System auto-closed
    MANUAL_RESOLVED = "MANUAL_RESOLVED"  # User closed
    SUPERSEDED = "SUPERSEDED"        # Replaced by newer alert
    EXPIRED = "EXPIRED"              # TTL expired
    DEDUPLICATED = "DEDUPLICATED"    # Merged into existing


class ResolutionRule(str, Enum):
    """Rules that trigger auto-resolution"""
    STATE_RECOVERED = "STATE_RECOVERED"      # Belief state → STABLE
    CONDITION_CLEARED = "CONDITION_CLEARED"  # Alert condition no longer true
    SUPERSEDED_BY_NEW = "SUPERSEDED_BY_NEW"  # Newer alert for same condition
    TTL_EXPIRED = "TTL_EXPIRED"              # Exceeded time limit
    MANUAL = "MANUAL"                        # User action


# TTL by priority (milliseconds)
ALERT_TTL_MS = {
    AlertPriority.LOW: 30 * 60 * 1000,         # 30 min
    AlertPriority.MEDIUM: 2 * 60 * 60 * 1000,  # 2 hours
    AlertPriority.HIGH: 6 * 60 * 60 * 1000,    # 6 hours
    AlertPriority.CRITICAL: 24 * 60 * 60 * 1000,  # 24 hours
}

# Dedup window (milliseconds)
DEDUP_WINDOW_MS = 60 * 1000  # 1 minute

# Grace period before auto-resolve on state recovery
STATE_RECOVERY_GRACE_MS = 5 * 60 * 1000  # 5 minutes


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class ExplainLogEntry:
    """
    Audit log entry for alert lifecycle changes.
    Records who/what changed the alert and why.
    """
    log_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    alert_id: str = ""
    timestamp: int = 0
    old_status: AlertStatus = AlertStatus.OPEN
    new_status: AlertStatus = AlertStatus.OPEN
    rule: ResolutionRule = ResolutionRule.MANUAL
    reason: str = ""
    triggered_by: str = "system"  # "system" or user_id
    evidence: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "alert_id": self.alert_id,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp / 1000).isoformat() if self.timestamp else None,
            "old_status": self.old_status.value,
            "new_status": self.new_status.value,
            "rule": self.rule.value,
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "evidence": self.evidence,
            "context": self.context,
        }


@dataclass
class ManagedAlert:
    """
    Alert with full lifecycle management.
    Wraps AlertPayload with operational state.
    """
    payload: AlertPayload
    status: AlertStatus = AlertStatus.OPEN
    dedup_key: str = ""
    created_at: int = 0
    last_updated_at: int = 0
    resolved_at: Optional[int] = None
    resolution_rule: Optional[ResolutionRule] = None
    resolution_reason: str = ""
    manual_override: bool = False  # User explicitly kept open
    superseded_by: Optional[str] = None
    merged_count: int = 0  # How many dupes were merged
    related_ids: List[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status == AlertStatus.OPEN

    @property
    def alert_id(self) -> str:
        return self.payload.alert_id

    def to_dict(self) -> Dict[str, Any]:
        result = self.payload.to_dict()
        result.update({
            "ops_status": self.status.value,
            "dedup_key": self.dedup_key,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "resolved_at": self.resolved_at,
            "resolution_rule": self.resolution_rule.value if self.resolution_rule else None,
            "resolution_reason": self.resolution_reason,
            "manual_override": self.manual_override,
            "superseded_by": self.superseded_by,
            "merged_count": self.merged_count,
            "related_ids": self.related_ids,
        })
        return result


# =============================================================================
# Dedup Key Generation
# =============================================================================

def generate_dedup_key(
    payload: AlertPayload,
    custom_key: Optional[str] = None
) -> str:
    """
    Generate deduplication key for an alert.

    Default key format: {category}:{token_id}:{data_hash}

    Custom key can be provided in payload.data["dedup_key"]
    """
    if custom_key:
        return custom_key

    # Check if payload has explicit dedup_key
    if "dedup_key" in payload.data:
        return str(payload.data["dedup_key"])

    # Generate from category + token + relevant data
    parts = [payload.category.value]

    if payload.token_id:
        parts.append(payload.token_id)

    # Add distinguishing data fields
    if "price" in payload.data:
        # Bucket price to avoid minor variations
        price = payload.data["price"]
        if isinstance(price, (int, float)):
            parts.append(f"p{int(price * 100)}")

    if "level" in payload.data:
        parts.append(f"l{payload.data['level']}")

    if "subtype" in payload.data:
        parts.append(payload.data["subtype"])

    return ":".join(parts)


# =============================================================================
# Alert Ops Manager
# =============================================================================

class AlertOpsManager:
    """
    Operational management for alerts.

    Features:
    1. Deduplication: Merge similar alerts within window
    2. Auto-resolve: Close alerts on TTL or condition recovery
    3. Supersession: New alerts replace old for same condition
    4. Explain log: Full audit trail
    5. Manual override: User can keep alerts open

    Usage:
        ops = AlertOpsManager()

        # Process incoming alert
        managed, is_new = await ops.process_alert(payload)

        if is_new:
            await router.route(payload)

        # Check for auto-resolution
        resolved = ops.tick()

        # Manual actions
        ops.resolve_manual(alert_id, "Fixed by user", user_id="admin")
        ops.keep_open(alert_id, user_id="admin")

        # Query
        active = ops.get_active_alerts(token_id="abc")
        history = ops.get_explain_log(alert_id="xyz")
    """

    def __init__(
        self,
        on_status_change: Optional[Callable[[ManagedAlert, ExplainLogEntry], None]] = None,
        dedup_window_ms: int = DEDUP_WINDOW_MS,
        enable_auto_resolve: bool = True,
        max_alerts: int = 10000,
        max_explain_log: int = 50000,
    ):
        self.on_status_change = on_status_change
        self.dedup_window_ms = dedup_window_ms
        self.enable_auto_resolve = enable_auto_resolve
        self.max_alerts = max_alerts
        self.max_explain_log = max_explain_log

        # Storage
        self.alerts: Dict[str, ManagedAlert] = {}
        self.alerts_by_token: Dict[str, List[str]] = defaultdict(list)
        self.alerts_by_dedup_key: Dict[str, str] = {}  # dedup_key -> alert_id

        # State tracking for auto-resolve
        self.token_stable_since: Dict[str, int] = {}  # token_id -> timestamp

        # Explain log
        self.explain_log: List[ExplainLogEntry] = []

        # Stats
        self.stats = {
            "total_processed": 0,
            "total_deduplicated": 0,
            "total_superseded": 0,
            "auto_resolved": 0,
            "manual_resolved": 0,
            "expired": 0,
        }

    # =========================================================================
    # Alert Processing
    # =========================================================================

    async def process_alert(
        self,
        payload: AlertPayload,
        custom_dedup_key: Optional[str] = None
    ) -> Tuple[ManagedAlert, bool]:
        """
        Process incoming alert with dedup and supersession.

        Returns:
            (ManagedAlert, is_new) - is_new=False means deduplicated
        """
        now = int(time.time() * 1000)
        self.stats["total_processed"] += 1

        # Generate dedup key
        dedup_key = generate_dedup_key(payload, custom_dedup_key)

        # Check for existing active alert with same dedup key
        existing_id = self.alerts_by_dedup_key.get(dedup_key)
        if existing_id and existing_id in self.alerts:
            existing = self.alerts[existing_id]
            if existing.is_active:
                # Within dedup window?
                if now - existing.last_updated_at < self.dedup_window_ms:
                    # Merge into existing
                    existing.merged_count += 1
                    existing.last_updated_at = now
                    existing.related_ids.append(payload.alert_id)
                    self.stats["total_deduplicated"] += 1

                    logger.debug(
                        f"[OPS] Deduplicated alert {payload.alert_id} into {existing_id} "
                        f"(merged_count={existing.merged_count})"
                    )
                    return existing, False

                # Outside window - supersede
                await self._supersede_alert(existing, payload.alert_id, now)

        # Create new managed alert
        managed = ManagedAlert(
            payload=payload,
            status=AlertStatus.OPEN,
            dedup_key=dedup_key,
            created_at=now,
            last_updated_at=now,
        )

        self.alerts[payload.alert_id] = managed
        self.alerts_by_token[payload.token_id or ""].append(payload.alert_id)
        self.alerts_by_dedup_key[dedup_key] = payload.alert_id

        # Log creation
        self._log_change(
            managed, AlertStatus.OPEN, AlertStatus.OPEN,
            ResolutionRule.MANUAL, "Alert created", "system"
        )

        # Prune old alerts
        self._prune_alerts()

        logger.info(f"[OPS] New alert {payload.alert_id} (dedup_key={dedup_key})")
        return managed, True

    async def _supersede_alert(
        self,
        old: ManagedAlert,
        new_id: str,
        timestamp: int
    ):
        """Mark old alert as superseded by new one"""
        self._resolve_internal(
            old,
            AlertStatus.SUPERSEDED,
            ResolutionRule.SUPERSEDED_BY_NEW,
            f"Superseded by {new_id}",
            "system",
            timestamp
        )
        old.superseded_by = new_id
        self.stats["total_superseded"] += 1

    # =========================================================================
    # Auto-Resolution
    # =========================================================================

    def tick(self, current_time: Optional[int] = None) -> List[ManagedAlert]:
        """
        Periodic check for auto-resolution conditions.
        Returns list of newly resolved alerts.
        """
        if not self.enable_auto_resolve:
            return []

        now = current_time or int(time.time() * 1000)
        resolved = []

        for alert_id, managed in list(self.alerts.items()):
            if not managed.is_active:
                continue
            if managed.manual_override:
                continue

            token_id = managed.payload.token_id or ""

            # Check TTL expiration
            ttl = ALERT_TTL_MS.get(managed.payload.priority, ALERT_TTL_MS[AlertPriority.MEDIUM])
            if now - managed.created_at > ttl:
                self._resolve_internal(
                    managed,
                    AlertStatus.EXPIRED,
                    ResolutionRule.TTL_EXPIRED,
                    f"Expired after {ttl // 60000} minutes",
                    "system",
                    now
                )
                self.stats["expired"] += 1
                resolved.append(managed)
                continue

            # Check state recovery (with grace period)
            if token_id in self.token_stable_since:
                stable_since = self.token_stable_since[token_id]
                if now - stable_since >= STATE_RECOVERY_GRACE_MS:
                    self._resolve_internal(
                        managed,
                        AlertStatus.AUTO_RESOLVED,
                        ResolutionRule.STATE_RECOVERED,
                        f"Token state stable for {STATE_RECOVERY_GRACE_MS // 1000}s",
                        "system",
                        now,
                        evidence=[
                            f"State stabilized at: {datetime.fromtimestamp(stable_since/1000).isoformat()}",
                            f"Grace period: {STATE_RECOVERY_GRACE_MS // 1000}s",
                        ]
                    )
                    self.stats["auto_resolved"] += 1
                    resolved.append(managed)

        return resolved

    def on_state_change(self, token_id: str, is_stable: bool, timestamp: int):
        """
        Notify ops manager of belief state change.
        Called when belief state transitions.
        """
        if is_stable:
            if token_id not in self.token_stable_since:
                self.token_stable_since[token_id] = timestamp
                logger.debug(f"[OPS] Token {token_id} became stable at {timestamp}")
        else:
            self.token_stable_since.pop(token_id, None)

    def clear_condition(
        self,
        dedup_key: str,
        reason: str = "Condition cleared"
    ) -> Optional[ManagedAlert]:
        """
        Auto-resolve alert when its condition is no longer true.
        Returns resolved alert if found.
        """
        alert_id = self.alerts_by_dedup_key.get(dedup_key)
        if not alert_id or alert_id not in self.alerts:
            return None

        managed = self.alerts[alert_id]
        if not managed.is_active:
            return None

        now = int(time.time() * 1000)
        self._resolve_internal(
            managed,
            AlertStatus.AUTO_RESOLVED,
            ResolutionRule.CONDITION_CLEARED,
            reason,
            "system",
            now
        )
        self.stats["auto_resolved"] += 1
        return managed

    # =========================================================================
    # Manual Actions
    # =========================================================================

    def resolve_manual(
        self,
        alert_id: str,
        reason: str = "Manually resolved",
        user_id: str = "user"
    ) -> bool:
        """Manually resolve an alert"""
        managed = self.alerts.get(alert_id)
        if not managed or not managed.is_active:
            return False

        now = int(time.time() * 1000)
        self._resolve_internal(
            managed,
            AlertStatus.MANUAL_RESOLVED,
            ResolutionRule.MANUAL,
            reason,
            user_id,
            now
        )
        self.stats["manual_resolved"] += 1
        return True

    def keep_open(self, alert_id: str, user_id: str = "user") -> bool:
        """
        Override auto-resolution: keep alert open.
        Also reopens auto-resolved or expired alerts.
        """
        managed = self.alerts.get(alert_id)
        if not managed:
            return False

        now = int(time.time() * 1000)
        managed.manual_override = True

        # Reopen if was auto-resolved or expired
        if managed.status in (AlertStatus.AUTO_RESOLVED, AlertStatus.EXPIRED):
            old_status = managed.status
            managed.status = AlertStatus.OPEN
            managed.resolved_at = None
            managed.last_updated_at = now

            self._log_change(
                managed, old_status, AlertStatus.OPEN,
                ResolutionRule.MANUAL,
                "User overrode auto-resolution",
                user_id
            )

        return True

    def acknowledge(self, alert_id: str, user_id: str = "user") -> bool:
        """Acknowledge alert (mark as seen but keep open)"""
        managed = self.alerts.get(alert_id)
        if not managed:
            return False

        now = int(time.time() * 1000)
        managed.last_updated_at = now

        self._log_change(
            managed, managed.status, managed.status,
            ResolutionRule.MANUAL,
            "Acknowledged",
            user_id
        )
        return True

    # =========================================================================
    # Internal Resolution
    # =========================================================================

    def _resolve_internal(
        self,
        managed: ManagedAlert,
        new_status: AlertStatus,
        rule: ResolutionRule,
        reason: str,
        triggered_by: str,
        timestamp: int,
        evidence: Optional[List[str]] = None
    ):
        """Internal: update alert status and log"""
        old_status = managed.status
        managed.status = new_status
        managed.resolved_at = timestamp
        managed.resolution_rule = rule
        managed.resolution_reason = reason
        managed.last_updated_at = timestamp

        self._log_change(
            managed, old_status, new_status,
            rule, reason, triggered_by, evidence
        )

        # Remove from dedup index if resolved
        if managed.dedup_key in self.alerts_by_dedup_key:
            if self.alerts_by_dedup_key[managed.dedup_key] == managed.alert_id:
                del self.alerts_by_dedup_key[managed.dedup_key]

    def _log_change(
        self,
        managed: ManagedAlert,
        old_status: AlertStatus,
        new_status: AlertStatus,
        rule: ResolutionRule,
        reason: str,
        triggered_by: str,
        evidence: Optional[List[str]] = None
    ):
        """Add entry to explain log"""
        entry = ExplainLogEntry(
            alert_id=managed.alert_id,
            timestamp=int(time.time() * 1000),
            old_status=old_status,
            new_status=new_status,
            rule=rule,
            reason=reason,
            triggered_by=triggered_by,
            evidence=evidence or [],
            context={
                "token_id": managed.payload.token_id,
                "category": managed.payload.category.value,
                "priority": managed.payload.priority.value,
            }
        )

        self.explain_log.append(entry)

        # Prune log if too large
        if len(self.explain_log) > self.max_explain_log:
            self.explain_log = self.explain_log[-self.max_explain_log:]

        # Callback
        if self.on_status_change:
            self.on_status_change(managed, entry)

    def _prune_alerts(self):
        """Remove oldest resolved alerts if over limit"""
        if len(self.alerts) <= self.max_alerts:
            return

        # Sort by resolved_at (resolved first) then created_at
        sorted_ids = sorted(
            self.alerts.keys(),
            key=lambda aid: (
                0 if self.alerts[aid].is_active else 1,
                self.alerts[aid].resolved_at or self.alerts[aid].created_at
            )
        )

        # Remove oldest resolved
        to_remove = len(self.alerts) - self.max_alerts
        for alert_id in sorted_ids[:to_remove]:
            managed = self.alerts[alert_id]
            if not managed.is_active:
                del self.alerts[alert_id]
                # Clean up indexes
                token_id = managed.payload.token_id or ""
                if alert_id in self.alerts_by_token.get(token_id, []):
                    self.alerts_by_token[token_id].remove(alert_id)

    # =========================================================================
    # Queries
    # =========================================================================

    def get_active_alerts(
        self,
        token_id: Optional[str] = None,
        category: Optional[AlertCategory] = None,
        min_priority: Optional[AlertPriority] = None,
        limit: int = 100
    ) -> List[ManagedAlert]:
        """Get active alerts with optional filters"""
        if token_id:
            alert_ids = self.alerts_by_token.get(token_id, [])
        else:
            alert_ids = list(self.alerts.keys())

        priority_order = {p: i for i, p in enumerate(AlertPriority)}

        result = []
        for aid in reversed(alert_ids):
            managed = self.alerts.get(aid)
            if not managed or not managed.is_active:
                continue
            if category and managed.payload.category != category:
                continue
            if min_priority:
                if priority_order.get(managed.payload.priority, 0) < priority_order.get(min_priority, 0):
                    continue
            result.append(managed)
            if len(result) >= limit:
                break

        return result

    def get_alert(self, alert_id: str) -> Optional[ManagedAlert]:
        """Get single alert by ID"""
        return self.alerts.get(alert_id)

    def get_explain_log(
        self,
        alert_id: Optional[str] = None,
        limit: int = 100
    ) -> List[ExplainLogEntry]:
        """Get explain log entries"""
        if alert_id:
            return [e for e in reversed(self.explain_log) if e.alert_id == alert_id][:limit]
        return list(reversed(self.explain_log))[:limit]

    def get_alert_history(self, alert_id: str) -> Dict[str, Any]:
        """Get complete history for an alert"""
        managed = self.alerts.get(alert_id)
        if not managed:
            return {"error": "Alert not found", "alert_id": alert_id}

        log_entries = self.get_explain_log(alert_id=alert_id, limit=100)

        return {
            "alert": managed.to_dict(),
            "explain_log": [e.to_dict() for e in log_entries],
            "related_alerts": [
                self.alerts[rid].to_dict()
                for rid in managed.related_ids
                if rid in self.alerts
            ][:10]
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get ops statistics"""
        active_count = sum(1 for a in self.alerts.values() if a.is_active)
        by_status = defaultdict(int)
        for a in self.alerts.values():
            by_status[a.status.value] += 1

        return {
            **self.stats,
            "current_active": active_count,
            "total_tracked": len(self.alerts),
            "by_status": dict(by_status),
            "explain_log_size": len(self.explain_log),
            "dedup_keys_tracked": len(self.alerts_by_dedup_key),
        }

    def export_explain_log(self, limit: int = 10000) -> List[Dict]:
        """Export explain log for audit/compliance"""
        return [e.to_dict() for e in self.explain_log[-limit:]]


# =============================================================================
# Global Instance
# =============================================================================

_default_ops_manager: Optional[AlertOpsManager] = None


def get_ops_manager() -> AlertOpsManager:
    """Get or create default ops manager"""
    global _default_ops_manager
    if _default_ops_manager is None:
        _default_ops_manager = AlertOpsManager()
    return _default_ops_manager
