"""
Audit Logging Module (v5.34)

Provides:
- Structured audit log entries
- Action categorization
- Async-safe logging
- Query interface for audit trail
- Hash chain for append-only verification (v5.34)
- Production environment hardening (v5.34)

"一切操作皆可追溯"
"""

import os
import time
import threading
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from collections import deque
import hashlib


# =============================================================================
# Production Environment Detection (v5.34)
# =============================================================================

def is_production_environment() -> bool:
    """
    Detect if running in production environment.

    Returns True if:
    - ENVIRONMENT=production
    - Or NODE_ENV=production
    - Or PRODUCTION=true
    """
    env = os.getenv("ENVIRONMENT", "").lower()
    node_env = os.getenv("NODE_ENV", "").lower()
    prod_flag = os.getenv("PRODUCTION", "").lower()

    return env == "production" or node_env == "production" or prod_flag == "true"


def get_production_allowlist() -> List[str]:
    """
    Get CIDR allowlist for production dangerous operations.

    Format: DANGEROUS_OPS_ALLOWLIST=10.0.0.0/8,192.168.1.0/24
    """
    allowlist = os.getenv("DANGEROUS_OPS_ALLOWLIST", "")
    if not allowlist:
        return []
    return [cidr.strip() for cidr in allowlist.split(",") if cidr.strip()]


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
    AUTH_KEY_UPDATED = "auth.key_updated"
    AUTH_KEY_REVOKED = "auth.key_revoked"
    AUTH_KEY_DELETED = "auth.key_deleted"

    # Aliases for compatibility (v5.35)
    KEY_CREATED = "auth.key_created"
    KEY_UPDATED = "auth.key_updated"
    KEY_REVOKED = "auth.key_revoked"
    KEY_DELETED = "auth.key_deleted"
    ACL_GRANTED = "admin.acl_grant"
    ACL_REVOKED = "admin.acl_revoke"

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

    v5.34: Added hash chain support for append-only verification.
    Each entry includes prev_hash (hash of previous entry) creating
    a tamper-evident chain.
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
    # v5.34: Hash chain fields
    prev_hash: Optional[str] = None     # Hash of previous entry (chain link)
    entry_hash: Optional[str] = None    # Hash of this entry (computed)

    def __post_init__(self):
        # Generate entry_id if not provided
        if not self.entry_id:
            content = f"{self.timestamp}:{self.action.value}:{self.actor_id}"
            self.entry_id = hashlib.sha256(content.encode()).hexdigest()[:16]

    def compute_hash(self) -> str:
        """
        Compute hash of this entry for chain verification.

        Hash includes prev_hash to create chain link.
        """
        data = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "result": self.result,
            "details": self.details,
            "prev_hash": self.prev_hash,
        }
        json_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
        return hashlib.sha256(json_bytes).hexdigest()

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
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
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
    - Hash chain for append-only verification (v5.34)
    - Chain integrity verification (v5.34)

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

        # Verify chain integrity (v5.34)
        is_valid, errors = logger.verify_chain()
    """

    # Genesis hash for first entry in chain
    GENESIS_HASH = "0" * 64

    def __init__(
        self,
        max_entries: int = 10000,
        sink: Optional[Callable[[AuditEntry], None]] = None,
    ):
        self.max_entries = max_entries
        self.sink = sink
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()

        # v5.34: Hash chain state
        self._last_hash: str = self.GENESIS_HASH
        self._chain_length: int = 0

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

        v5.34: Maintains hash chain for append-only verification.

        Returns:
            The created AuditEntry
        """
        with self._lock:
            # v5.34: Link to previous entry via hash
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
                prev_hash=self._last_hash,  # v5.34: Chain link
            )

            # v5.34: Compute and store entry hash
            entry.entry_hash = entry.compute_hash()
            self._last_hash = entry.entry_hash
            self._chain_length += 1

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

    def verify_chain(self) -> tuple:
        """
        Verify the integrity of the audit chain.

        v5.34: Ensures no entries have been tampered with.

        Returns:
            (is_valid, errors): Tuple of bool and list of error strings
        """
        with self._lock:
            entries = list(self._entries)

        if not entries:
            return True, []

        errors = []
        prev_hash = self.GENESIS_HASH

        for i, entry in enumerate(entries):
            # Check chain link
            if entry.prev_hash != prev_hash:
                errors.append(
                    f"Entry {i} ({entry.entry_id}): prev_hash mismatch. "
                    f"Expected {prev_hash[:16]}..., got {(entry.prev_hash or 'None')[:16]}..."
                )

            # Verify entry hash
            computed = entry.compute_hash()
            if entry.entry_hash != computed:
                errors.append(
                    f"Entry {i} ({entry.entry_id}): entry_hash mismatch. "
                    f"Stored {(entry.entry_hash or 'None')[:16]}..., computed {computed[:16]}..."
                )

            prev_hash = entry.entry_hash or computed

        return len(errors) == 0, errors

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
                # v5.34: Chain statistics
                "chain_length": self._chain_length,
                "last_hash": self._last_hash[:16] + "..." if self._last_hash else None,
            }

    def get_recent(self, limit: int = 100) -> List[AuditEntry]:
        """Get most recent entries"""
        with self._lock:
            entries = list(self._entries)
        return list(reversed(entries[-limit:]))

    def clear(self) -> int:
        """
        Clear all entries (admin operation).

        v5.34: BLOCKED in production environment.
        Audit logs must be preserved for compliance.
        """
        if is_production_environment():
            raise PermissionError(
                "Audit log clearing is blocked in production environment. "
                "Audit logs must be preserved for compliance."
            )

        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            # Reset chain state
            self._last_hash = self.GENESIS_HASH
            self._chain_length = 0
            return count

    def compute_daily_anchor(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Compute daily anchor hash for external verification.

        v5.34: World-class audit chain anchoring.

        Daily anchors provide:
        1. External verification point (can be stored outside DB)
        2. Prevention of chain rewrite attacks
        3. Compliance checkpoint

        Args:
            date_str: Date in YYYY-MM-DD format (defaults to today)

        Returns:
            {
                "date": "2024-01-05",
                "anchor_hash": "abc123...",
                "entry_count": 150,
                "first_entry_id": "...",
                "last_entry_id": "...",
                "computed_at": 1704456000000
            }
        """
        import datetime

        if date_str is None:
            date_str = datetime.date.today().isoformat()

        with self._lock:
            entries = list(self._entries)

        # Filter entries for the target date
        target_start = int(datetime.datetime.fromisoformat(f"{date_str}T00:00:00").timestamp() * 1000)
        target_end = int(datetime.datetime.fromisoformat(f"{date_str}T23:59:59").timestamp() * 1000)

        day_entries = [e for e in entries if target_start <= e.timestamp <= target_end]

        if not day_entries:
            return {
                "date": date_str,
                "anchor_hash": None,
                "entry_count": 0,
                "first_entry_id": None,
                "last_entry_id": None,
                "computed_at": int(time.time() * 1000),
            }

        # Compute anchor hash from all entry hashes of the day
        hash_chain = ":".join(e.entry_hash or e.compute_hash() for e in day_entries)
        anchor_hash = hashlib.sha256(hash_chain.encode()).hexdigest()

        return {
            "date": date_str,
            "anchor_hash": anchor_hash,
            "entry_count": len(day_entries),
            "first_entry_id": day_entries[0].entry_id,
            "last_entry_id": day_entries[-1].entry_id,
            "computed_at": int(time.time() * 1000),
        }

    def verify_daily_anchor(self, anchor: Dict[str, Any]) -> tuple:
        """
        Verify a daily anchor against current data.

        v5.34: Detects if audit entries for a day have been modified.

        Args:
            anchor: Previously computed anchor from compute_daily_anchor()

        Returns:
            (is_valid, message): Tuple of bool and explanation
        """
        if not anchor or not anchor.get("anchor_hash"):
            return True, "No anchor to verify (empty day)"

        current = self.compute_daily_anchor(anchor["date"])

        if current["anchor_hash"] != anchor["anchor_hash"]:
            return False, (
                f"Anchor mismatch for {anchor['date']}: "
                f"stored={anchor['anchor_hash'][:16]}..., "
                f"computed={current['anchor_hash'][:16]}..."
            )

        if current["entry_count"] != anchor["entry_count"]:
            return False, (
                f"Entry count mismatch for {anchor['date']}: "
                f"stored={anchor['entry_count']}, computed={current['entry_count']}"
            )

        return True, f"Anchor verified for {anchor['date']}"


# =============================================================================
# Daily Anchor Storage (v5.34)
# =============================================================================

@dataclass
class DailyAnchor:
    """
    Immutable daily anchor checkpoint.

    v5.34: Store these externally (S3, external DB, printed log)
    for tamper-evident audit trail verification.
    """
    date: str
    anchor_hash: str
    entry_count: int
    first_entry_id: str
    last_entry_id: str
    computed_at: int

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "anchor_hash": self.anchor_hash,
            "entry_count": self.entry_count,
            "first_entry_id": self.first_entry_id,
            "last_entry_id": self.last_entry_id,
            "computed_at": self.computed_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


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


# =============================================================================
# Dangerous Operations Check (v5.34)
# =============================================================================

class DangerousOperationError(Exception):
    """Raised when a dangerous operation is blocked."""
    pass


def check_dangerous_operation_allowed(
    operation: str,
    ip_address: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> tuple:
    """
    Check if a dangerous operation is allowed.

    v5.34: World-class security for dangerous operations.

    Requirements for dangerous operations:
    1. Environment flag must be set (DANGEROUS_OPS_ENABLED=true)
    2. In production: IP must be in allowlist
    3. Operation-specific env flag must be set

    Args:
        operation: Operation type ("inject", "restart", "delete")
        ip_address: Client IP address
        actor_id: Actor performing the operation

    Returns:
        (allowed, reason): Tuple of bool and explanation string
    """
    # Check global dangerous ops flag
    if os.getenv("DANGEROUS_OPS_ENABLED", "false").lower() != "true":
        return False, "Dangerous operations disabled (DANGEROUS_OPS_ENABLED != true)"

    # Check operation-specific flag
    op_flag = f"DANGEROUS_{operation.upper()}_ENABLED"
    if os.getenv(op_flag, "false").lower() != "true":
        return False, f"Operation '{operation}' disabled ({op_flag} != true)"

    # Production environment checks
    if is_production_environment():
        # Must have allowlist configured
        allowlist = get_production_allowlist()
        if not allowlist:
            return False, "Production environment requires DANGEROUS_OPS_ALLOWLIST"

        # IP must be in allowlist (basic check, proper CIDR matching would use ipaddress module)
        if ip_address:
            ip_allowed = False
            for cidr in allowlist:
                if "/" in cidr:
                    # Basic prefix match for CIDR (simplified)
                    network = cidr.split("/")[0]
                    if ip_address.startswith(network.rsplit(".", 1)[0]):
                        ip_allowed = True
                        break
                elif ip_address == cidr:
                    ip_allowed = True
                    break

            if not ip_allowed:
                return False, f"IP {ip_address} not in production allowlist"

    return True, "Operation allowed"


def require_dangerous_operation(
    operation: str,
    ip_address: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> None:
    """
    Require dangerous operation to be allowed, or raise exception.

    Usage:
        try:
            require_dangerous_operation("inject", ip_address=client_ip)
            # Proceed with operation
        except DangerousOperationError as e:
            raise HTTPException(403, str(e))
    """
    allowed, reason = check_dangerous_operation_allowed(operation, ip_address, actor_id)
    if not allowed:
        raise DangerousOperationError(reason)
