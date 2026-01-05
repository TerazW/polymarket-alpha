"""
Audit Logging Module (v5.23)

Provides:
- Structured audit log entries
- Action categorization
- Async-safe logging
- Query interface for audit trail

"一切操作皆可追溯"
"""

import time
import threading
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from collections import deque
import hashlib


# =============================================================================
# Audit Actions
# =============================================================================

class AuditAction(str, Enum):
    """
    Categorized audit actions.

    Format: category.action
    """
    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_FAILED = "auth.failed"
    AUTH_KEY_CREATED = "auth.key_created"
    AUTH_KEY_REVOKED = "auth.key_revoked"
    AUTH_KEY_DELETED = "auth.key_deleted"

    # Authorization
    AUTHZ_DENIED = "authz.denied"
    AUTHZ_GRANTED = "authz.granted"

    # API Access
    API_REQUEST = "api.request"
    API_ERROR = "api.error"
    API_RATE_LIMITED = "api.rate_limited"

    # Alert Operations
    ALERT_CREATED = "alert.created"
    ALERT_ACK = "alert.ack"
    ALERT_RESOLVED = "alert.resolved"
    ALERT_SUPPRESSED = "alert.suppressed"

    # Data Operations
    DATA_READ = "data.read"
    DATA_EXPORT = "data.export"
    DATA_REPLAY = "data.replay"
    DATA_INJECTION = "data.injection"         # v5.33: Event injection (dangerous)
    DATA_INJECTION_DENIED = "data.injection_denied"

    # Admin Operations
    ADMIN_CONFIG_CHANGE = "admin.config_change"
    ADMIN_ACL_GRANT = "admin.acl_grant"
    ADMIN_ACL_REVOKE = "admin.acl_revoke"

    # Dangerous Operations (require special authorization)
    DANGEROUS_EVENT_INJECTION = "dangerous.event_injection"
    DANGEROUS_SYSTEM_RESTART = "dangerous.system_restart"
    DANGEROUS_DATA_DELETE = "dangerous.data_delete"

    # System Events
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"


# =============================================================================
# Audit Entry
# =============================================================================

@dataclass
class AuditEntry:
    """
    Structured audit log entry.

    All fields are immutable after creation.
    """
    entry_id: str                       # Unique entry identifier
    timestamp: int                      # Unix timestamp (ms)
    action: AuditAction                 # Action type
    actor_type: str                     # "key", "user", "system"
    actor_id: str                       # Key ID, user ID, or "system"
    resource_type: Optional[str] = None # "alert", "evidence", "token", etc.
    resource_id: Optional[str] = None   # Specific resource ID
    result: str = "success"             # "success", "failure", "denied"
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None

    def __post_init__(self):
        # Generate entry_id if not provided
        if not self.entry_id:
            content = f"{self.timestamp}:{self.action.value}:{self.actor_id}"
            self.entry_id = hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "result": self.result,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# =============================================================================
# Audit Logger
# =============================================================================

class AuditLogger:
    """
    Central audit logging service.

    Features:
    - In-memory buffer with size limit
    - Optional external sink (callback)
    - Query interface for recent entries
    - Thread-safe operations

    Usage:
        logger = AuditLogger(max_entries=10000)

        # Log an action
        logger.log(
            action=AuditAction.ALERT_ACK,
            actor_type="key",
            actor_id="key_abc123",
            resource_type="alert",
            resource_id="alert-456",
            details={"reason": "false positive"},
        )

        # Query recent entries
        entries = logger.query(
            action=AuditAction.ALERT_ACK,
            actor_id="key_abc123",
            limit=100,
        )
    """

    def __init__(
        self,
        max_entries: int = 10000,
        sink: Optional[Callable[[AuditEntry], None]] = None,
    ):
        self.max_entries = max_entries
        self.sink = sink
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()

        # Stats
        self._total_logged = 0
        self._by_action: Dict[str, int] = {}
        self._by_result: Dict[str, int] = {}

    def log(
        self,
        action: AuditAction,
        actor_type: str = "system",
        actor_id: str = "system",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        result: str = "success",
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> AuditEntry:
        """
        Log an audit entry.

        Returns:
            The created AuditEntry
        """
        entry = AuditEntry(
            entry_id="",  # Will be generated
            timestamp=int(time.time() * 1000),
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )

        with self._lock:
            self._entries.append(entry)
            self._total_logged += 1

            # Update stats
            action_key = action.value
            self._by_action[action_key] = self._by_action.get(action_key, 0) + 1
            self._by_result[result] = self._by_result.get(result, 0) + 1

        # Send to external sink if configured
        if self.sink:
            try:
                self.sink(entry)
            except Exception:
                pass  # Don't fail on sink errors

        return entry

    def query(
        self,
        action: Optional[AuditAction] = None,
        actor_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        result: Optional[str] = None,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditEntry]:
        """
        Query audit entries with filters.

        Args:
            action: Filter by action type
            actor_type: Filter by actor type
            actor_id: Filter by actor ID
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            result: Filter by result
            from_ts: Start timestamp (inclusive)
            to_ts: End timestamp (inclusive)
            limit: Maximum entries to return
            offset: Entries to skip

        Returns:
            List of matching AuditEntry objects
        """
        with self._lock:
            entries = list(self._entries)

        # Apply filters
        filtered = []
        for entry in reversed(entries):  # Most recent first
            if action and entry.action != action:
                continue
            if actor_type and entry.actor_type != actor_type:
                continue
            if actor_id and entry.actor_id != actor_id:
                continue
            if resource_type and entry.resource_type != resource_type:
                continue
            if resource_id and entry.resource_id != resource_id:
                continue
            if result and entry.result != result:
                continue
            if from_ts and entry.timestamp < from_ts:
                continue
            if to_ts and entry.timestamp > to_ts:
                continue
            filtered.append(entry)

        # Apply pagination
        return filtered[offset:offset + limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get audit statistics"""
        with self._lock:
            return {
                "total_logged": self._total_logged,
                "current_buffer_size": len(self._entries),
                "max_buffer_size": self.max_entries,
                "by_action": dict(self._by_action),
                "by_result": dict(self._by_result),
            }

    def get_recent(self, limit: int = 100) -> List[AuditEntry]:
        """Get most recent entries"""
        with self._lock:
            entries = list(self._entries)
        return list(reversed(entries[-limit:]))

    def clear(self) -> int:
        """Clear all entries (admin operation)"""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count


# =============================================================================
# Global Audit Logger Singleton
# =============================================================================

_audit_logger: Optional[AuditLogger] = None
_audit_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger singleton"""
    global _audit_logger
    with _audit_lock:
        if _audit_logger is None:
            _audit_logger = AuditLogger()
        return _audit_logger


def audit_log(
    action: AuditAction,
    actor_type: str = "system",
    actor_id: str = "system",
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    result: str = "success",
    details: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> AuditEntry:
    """
    Convenience function to log to global audit logger.

    Usage:
        audit_log(
            AuditAction.ALERT_ACK,
            actor_type="key",
            actor_id=auth.key.key_id,
            resource_type="alert",
            resource_id=alert_id,
        )
    """
    logger = get_audit_logger()
    return logger.log(
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        details=details,
        **kwargs,
    )
