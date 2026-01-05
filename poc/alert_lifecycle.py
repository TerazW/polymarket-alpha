"""
Belief Reaction System - Alert Lifecycle Manager v1
Handles auto-resolution, deduplication, merging, and audit logging.

Core Principles:
1. 规则驱动: 所有自动解除都基于明确规则
2. 可审计: 所有状态变化都有日志
3. 手动 Override: 用户可覆盖任何自动决策

"看存在没意义，看反应才有意义"
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Callable, Set, Tuple
from collections import defaultdict
import time
import uuid
import json

from .models import BeliefState
from .alert_system import Alert, AlertType, AlertPriority


class AlertStatus(Enum):
    """Alert lifecycle status"""
    OPEN = "OPEN"           # 活跃状态
    AUTO_RESOLVED = "AUTO_RESOLVED"  # 自动解除 (规则触发)
    MANUAL_RESOLVED = "MANUAL_RESOLVED"  # 手动解除
    SUPERSEDED = "SUPERSEDED"  # 被新告警替代
    EXPIRED = "EXPIRED"     # 过期自动关闭
    MANUAL_KEPT = "MANUAL_KEPT"  # 用户手动保持 (override auto-resolve)


class ResolutionRule(Enum):
    """Auto-resolution rules"""
    STATE_RECOVERED = "STATE_RECOVERED"      # 状态恢复到 STABLE
    DEPTH_RECOVERED = "DEPTH_RECOVERED"      # 深度恢复
    SUPERSEDED_BY_NEW = "SUPERSEDED_BY_NEW"  # 被更新的告警替代
    TTL_EXPIRED = "TTL_EXPIRED"              # 超时过期
    MANUAL = "MANUAL"                        # 手动操作


@dataclass
class AlertResolutionLog:
    """Audit log entry for alert status changes"""
    log_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    alert_id: str = ""
    timestamp: int = 0
    old_status: AlertStatus = AlertStatus.OPEN
    new_status: AlertStatus = AlertStatus.OPEN
    rule: ResolutionRule = ResolutionRule.MANUAL
    reason: str = ""
    triggered_by: str = ""  # "system" or user_id
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "log_id": self.log_id,
            "alert_id": self.alert_id,
            "timestamp": self.timestamp,
            "old_status": self.old_status.value,
            "new_status": self.new_status.value,
            "rule": self.rule.value,
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "evidence": self.evidence,
            "created_at": datetime.fromtimestamp(self.timestamp / 1000).isoformat() if self.timestamp else None
        }


@dataclass
class ManagedAlert:
    """Alert with lifecycle management"""
    alert: Alert
    status: AlertStatus = AlertStatus.OPEN
    created_at: int = 0
    resolved_at: Optional[int] = None
    resolution_rule: Optional[ResolutionRule] = None
    resolution_reason: str = ""
    manual_override: bool = False  # True if user explicitly kept it open
    superseded_by: Optional[str] = None  # alert_id of superseding alert
    related_alerts: List[str] = field(default_factory=list)  # merged alerts

    @property
    def is_active(self) -> bool:
        return self.status == AlertStatus.OPEN or self.status == AlertStatus.MANUAL_KEPT

    def to_dict(self) -> dict:
        result = self.alert.to_dict()
        result.update({
            "lifecycle_status": self.status.value,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_rule": self.resolution_rule.value if self.resolution_rule else None,
            "resolution_reason": self.resolution_reason,
            "manual_override": self.manual_override,
            "superseded_by": self.superseded_by,
            "related_alerts": self.related_alerts,
        })
        return result


# =============================================================================
# Resolution Rules Configuration
# =============================================================================

# TTL (Time To Live) by priority - alerts auto-expire after this duration
ALERT_TTL_MS = {
    AlertPriority.LOW: 30 * 60 * 1000,       # 30 minutes
    AlertPriority.MEDIUM: 2 * 60 * 60 * 1000, # 2 hours
    AlertPriority.HIGH: 6 * 60 * 60 * 1000,   # 6 hours
    AlertPriority.CRITICAL: 24 * 60 * 60 * 1000,  # 24 hours
}

# Deduplication window - similar alerts within this window are merged
DEDUP_WINDOW_MS = 60 * 1000  # 1 minute

# State recovery grace period - wait before auto-resolving on state recovery
STATE_RECOVERY_GRACE_MS = 5 * 60 * 1000  # 5 minutes


class AlertLifecycleManager:
    """
    Manages alert lifecycle with auto-resolution and audit logging.

    Features:
    1. Auto-resolution on state recovery
    2. Deduplication of similar alerts
    3. Alert merging for same token
    4. TTL-based expiration
    5. Full audit trail
    6. Manual override support
    """

    def __init__(
        self,
        on_status_change: Optional[Callable[[ManagedAlert, AlertResolutionLog], None]] = None,
    ):
        self.on_status_change = on_status_change

        # Managed alerts: alert_id -> ManagedAlert
        self.alerts: Dict[str, ManagedAlert] = {}

        # Index by token for fast lookup
        self.alerts_by_token: Dict[str, List[str]] = defaultdict(list)

        # Current belief state per token (for auto-resolution)
        self.token_states: Dict[str, BeliefState] = {}
        self.state_since: Dict[str, int] = {}  # When state became STABLE

        # Audit log
        self.audit_log: List[AlertResolutionLog] = []
        self.max_audit_log = 10000

        # Dedup tracking: (token_id, subtype, price_bucket) -> last_alert_id
        self.recent_alerts: Dict[Tuple[str, str, str], Tuple[str, int]] = {}

        # Stats
        self.stats = {
            "total_created": 0,
            "total_resolved": 0,
            "auto_resolved": 0,
            "manual_resolved": 0,
            "deduplicated": 0,
            "merged": 0,
        }

    # =========================================================================
    # Alert Creation
    # =========================================================================

    def add_alert(self, alert: Alert) -> ManagedAlert:
        """
        Add a new alert with lifecycle management.
        Handles deduplication and merging.
        """
        now = int(time.time() * 1000)

        # Check for deduplication
        dedup_key = self._get_dedup_key(alert)
        if dedup_key in self.recent_alerts:
            existing_id, existing_ts = self.recent_alerts[dedup_key]
            if now - existing_ts < DEDUP_WINDOW_MS and existing_id in self.alerts:
                # Merge into existing alert
                existing = self.alerts[existing_id]
                if existing.is_active:
                    existing.related_alerts.append(alert.alert_id)
                    self.stats["deduplicated"] += 1
                    return existing

        # Create managed alert
        managed = ManagedAlert(
            alert=alert,
            status=AlertStatus.OPEN,
            created_at=now,
        )

        self.alerts[alert.alert_id] = managed
        self.alerts_by_token[alert.token_id].append(alert.alert_id)
        self.recent_alerts[dedup_key] = (alert.alert_id, now)
        self.stats["total_created"] += 1

        # Check if this supersedes any existing alerts
        self._check_supersede(managed)

        return managed

    def _get_dedup_key(self, alert: Alert) -> Tuple[str, str, str]:
        """Generate deduplication key for alert"""
        price_bucket = str(alert.price)[:4] if alert.price else "none"
        return (alert.token_id, alert.subtype or "", price_bucket)

    def _check_supersede(self, new_alert: ManagedAlert):
        """Check if new alert supersedes older ones"""
        token_id = new_alert.alert.token_id

        for alert_id in self.alerts_by_token.get(token_id, []):
            if alert_id == new_alert.alert.alert_id:
                continue

            old_alert = self.alerts.get(alert_id)
            if not old_alert or not old_alert.is_active:
                continue

            # Same type and subtype = supersede
            if (old_alert.alert.alert_type == new_alert.alert.alert_type and
                old_alert.alert.subtype == new_alert.alert.subtype):
                self._resolve_alert(
                    old_alert,
                    AlertStatus.SUPERSEDED,
                    ResolutionRule.SUPERSEDED_BY_NEW,
                    f"Superseded by newer alert {new_alert.alert.alert_id}",
                    triggered_by="system"
                )
                old_alert.superseded_by = new_alert.alert.alert_id

    # =========================================================================
    # State Change Handling
    # =========================================================================

    def on_belief_state_change(self, token_id: str, new_state: BeliefState, timestamp: int):
        """
        Handle belief state change - potentially auto-resolve alerts.
        """
        old_state = self.token_states.get(token_id)
        self.token_states[token_id] = new_state

        if new_state == BeliefState.STABLE:
            self.state_since[token_id] = timestamp
        else:
            self.state_since.pop(token_id, None)

        # If state recovered to STABLE, schedule auto-resolution check
        if new_state == BeliefState.STABLE and old_state != BeliefState.STABLE:
            # Don't resolve immediately - wait for grace period
            # This will be checked in tick()
            pass

    def tick(self, current_time: Optional[int] = None):
        """
        Periodic tick to check for auto-resolution conditions.
        Call this regularly (e.g., every second).
        """
        now = current_time or int(time.time() * 1000)

        for alert_id, managed in list(self.alerts.items()):
            if not managed.is_active:
                continue

            # Skip if manually overridden
            if managed.manual_override:
                continue

            token_id = managed.alert.token_id

            # Check TTL expiration
            ttl = ALERT_TTL_MS.get(managed.alert.priority, ALERT_TTL_MS[AlertPriority.MEDIUM])
            if now - managed.created_at > ttl:
                self._resolve_alert(
                    managed,
                    AlertStatus.EXPIRED,
                    ResolutionRule.TTL_EXPIRED,
                    f"Alert expired after {ttl // 60000} minutes",
                    triggered_by="system"
                )
                continue

            # Check state recovery (with grace period)
            if token_id in self.state_since:
                stable_since = self.state_since[token_id]
                if now - stable_since >= STATE_RECOVERY_GRACE_MS:
                    # State has been STABLE for grace period - auto-resolve
                    self._resolve_alert(
                        managed,
                        AlertStatus.AUTO_RESOLVED,
                        ResolutionRule.STATE_RECOVERED,
                        f"Token state recovered to STABLE for {STATE_RECOVERY_GRACE_MS // 1000}s",
                        triggered_by="system",
                        evidence=[
                            f"State recovered at: {datetime.fromtimestamp(stable_since/1000).isoformat()}",
                            f"Grace period: {STATE_RECOVERY_GRACE_MS // 1000}s",
                        ]
                    )

    # =========================================================================
    # Resolution
    # =========================================================================

    def _resolve_alert(
        self,
        managed: ManagedAlert,
        new_status: AlertStatus,
        rule: ResolutionRule,
        reason: str,
        triggered_by: str = "system",
        evidence: Optional[List[str]] = None
    ):
        """Internal: resolve an alert and log the change"""
        now = int(time.time() * 1000)
        old_status = managed.status

        # Update alert
        managed.status = new_status
        managed.resolved_at = now
        managed.resolution_rule = rule
        managed.resolution_reason = reason

        # Create audit log
        log_entry = AlertResolutionLog(
            alert_id=managed.alert.alert_id,
            timestamp=now,
            old_status=old_status,
            new_status=new_status,
            rule=rule,
            reason=reason,
            triggered_by=triggered_by,
            evidence=evidence or []
        )

        self.audit_log.append(log_entry)
        if len(self.audit_log) > self.max_audit_log:
            self.audit_log = self.audit_log[-self.max_audit_log:]

        # Update stats
        self.stats["total_resolved"] += 1
        if triggered_by == "system":
            self.stats["auto_resolved"] += 1
        else:
            self.stats["manual_resolved"] += 1

        # Callback
        if self.on_status_change:
            self.on_status_change(managed, log_entry)

    def resolve_manual(
        self,
        alert_id: str,
        reason: str = "Manually resolved by user",
        user_id: str = "user"
    ) -> bool:
        """Manually resolve an alert"""
        managed = self.alerts.get(alert_id)
        if not managed or not managed.is_active:
            return False

        self._resolve_alert(
            managed,
            AlertStatus.MANUAL_RESOLVED,
            ResolutionRule.MANUAL,
            reason,
            triggered_by=user_id
        )
        return True

    def keep_open(self, alert_id: str, user_id: str = "user") -> bool:
        """
        Manual override: keep alert open even if auto-resolution would apply.
        """
        managed = self.alerts.get(alert_id)
        if not managed:
            return False

        managed.manual_override = True

        # If was auto-resolved, reopen
        if managed.status == AlertStatus.AUTO_RESOLVED:
            now = int(time.time() * 1000)
            log_entry = AlertResolutionLog(
                alert_id=alert_id,
                timestamp=now,
                old_status=managed.status,
                new_status=AlertStatus.MANUAL_KEPT,
                rule=ResolutionRule.MANUAL,
                reason="User overrode auto-resolution",
                triggered_by=user_id
            )

            managed.status = AlertStatus.MANUAL_KEPT
            managed.resolved_at = None

            self.audit_log.append(log_entry)

            if self.on_status_change:
                self.on_status_change(managed, log_entry)

        return True

    # =========================================================================
    # Queries
    # =========================================================================

    def get_active_alerts(
        self,
        token_id: Optional[str] = None,
        min_priority: Optional[AlertPriority] = None,
        limit: int = 50
    ) -> List[ManagedAlert]:
        """Get active (open) alerts"""
        if token_id:
            alert_ids = self.alerts_by_token.get(token_id, [])
        else:
            alert_ids = list(self.alerts.keys())

        result = []
        for aid in reversed(alert_ids):
            managed = self.alerts.get(aid)
            if not managed or not managed.is_active:
                continue
            if min_priority and managed.alert.priority.value < min_priority.value:
                continue
            result.append(managed)
            if len(result) >= limit:
                break

        return result

    def get_audit_log(
        self,
        alert_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AlertResolutionLog]:
        """Get audit log entries"""
        if alert_id:
            return [log for log in reversed(self.audit_log)
                    if log.alert_id == alert_id][:limit]
        return list(reversed(self.audit_log))[:limit]

    def get_alert_history(self, alert_id: str) -> Dict:
        """Get complete history for an alert"""
        managed = self.alerts.get(alert_id)
        if not managed:
            return {"error": "Alert not found"}

        logs = self.get_audit_log(alert_id=alert_id, limit=100)

        return {
            "alert": managed.to_dict(),
            "history": [log.to_dict() for log in logs],
            "related_alerts": [
                self.alerts[aid].to_dict()
                for aid in managed.related_alerts
                if aid in self.alerts
            ]
        }

    def get_stats(self) -> dict:
        """Get lifecycle statistics"""
        active_count = sum(1 for a in self.alerts.values() if a.is_active)
        by_status = defaultdict(int)
        for a in self.alerts.values():
            by_status[a.status.value] += 1

        return {
            **self.stats,
            "current_active": active_count,
            "total_tracked": len(self.alerts),
            "by_status": dict(by_status),
            "audit_log_size": len(self.audit_log),
        }

    def export_audit_log(self, filepath: str):
        """Export full audit log to file (for compliance)"""
        with open(filepath, 'w') as f:
            for log in self.audit_log:
                f.write(json.dumps(log.to_dict()) + '\n')
