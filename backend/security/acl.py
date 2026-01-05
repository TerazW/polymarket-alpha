"""
Access Control List (ACL) Module (v5.23)

Provides:
- Permission definitions
- Role-based access control
- Resource-level permissions
- ACL checking

"最小权限原则"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum
import threading
import fnmatch


# =============================================================================
# Permissions
# =============================================================================

class Permission(str, Enum):
    """
    System permissions.

    Format: resource:action
    """
    # Read operations
    RADAR_READ = "radar:read"
    EVIDENCE_READ = "evidence:read"
    ALERTS_READ = "alerts:read"
    REPLAY_READ = "replay:read"
    HEATMAP_READ = "heatmap:read"
    METRICS_READ = "metrics:read"

    # Write operations
    ALERTS_ACK = "alerts:ack"
    ALERTS_RESOLVE = "alerts:resolve"
    REPLAY_TRIGGER = "replay:trigger"

    # Admin operations
    ADMIN_KEYS = "admin:keys"           # Manage API keys
    ADMIN_CONFIG = "admin:config"       # Modify configuration
    ADMIN_AUDIT = "admin:audit"         # View audit logs

    # Wildcard
    ALL = "*"


# =============================================================================
# Roles
# =============================================================================

class Role(str, Enum):
    """
    Predefined roles.

    Each role has a set of permissions.
    """
    VIEWER = "viewer"           # Read-only access
    OPERATOR = "operator"       # Read + acknowledge alerts
    ANALYST = "analyst"         # Read + replay + evidence
    ADMIN = "admin"             # Full access


# Role to permissions mapping
ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.RADAR_READ,
        Permission.EVIDENCE_READ,
        Permission.ALERTS_READ,
        Permission.HEATMAP_READ,
        Permission.METRICS_READ,
    },

    Role.OPERATOR: {
        Permission.RADAR_READ,
        Permission.EVIDENCE_READ,
        Permission.ALERTS_READ,
        Permission.ALERTS_ACK,
        Permission.ALERTS_RESOLVE,
        Permission.HEATMAP_READ,
        Permission.METRICS_READ,
    },

    Role.ANALYST: {
        Permission.RADAR_READ,
        Permission.EVIDENCE_READ,
        Permission.ALERTS_READ,
        Permission.ALERTS_ACK,
        Permission.REPLAY_READ,
        Permission.REPLAY_TRIGGER,
        Permission.HEATMAP_READ,
        Permission.METRICS_READ,
    },

    Role.ADMIN: {
        Permission.ALL,  # Full access
    },
}


def get_role_permissions(role_name: str) -> Set[Permission]:
    """Get permissions for a role name"""
    try:
        role = Role(role_name)
        return ROLE_PERMISSIONS.get(role, set())
    except ValueError:
        return set()


def get_all_permissions_for_roles(role_names: List[str]) -> Set[Permission]:
    """Get combined permissions for multiple roles"""
    permissions: Set[Permission] = set()
    for role_name in role_names:
        permissions.update(get_role_permissions(role_name))
    return permissions


# =============================================================================
# ACL Entry
# =============================================================================

@dataclass
class ACLEntry:
    """
    Access Control List entry.

    Grants permission to a subject (key, user, role) on a resource.
    """
    entry_id: str
    subject_type: str           # "key", "role", "user"
    subject_id: str             # key_id, role name, or user_id
    permission: str             # Permission or pattern (e.g., "alerts:*")
    resource_pattern: str = "*" # Resource pattern (e.g., "token:abc*")
    granted_at: int = 0
    granted_by: str = "system"
    expires_at: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches_permission(self, required: str) -> bool:
        """Check if this entry grants the required permission"""
        if self.permission == "*":
            return True
        if self.permission == required:
            return True
        # Wildcard matching (e.g., "alerts:*" matches "alerts:read")
        return fnmatch.fnmatch(required, self.permission)

    def matches_resource(self, resource: str) -> bool:
        """Check if this entry covers the resource"""
        if self.resource_pattern == "*":
            return True
        return fnmatch.fnmatch(resource, self.resource_pattern)

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "permission": self.permission,
            "resource_pattern": self.resource_pattern,
            "granted_at": self.granted_at,
            "granted_by": self.granted_by,
            "expires_at": self.expires_at,
        }


# =============================================================================
# ACL Manager
# =============================================================================

class ACLManager:
    """
    Manages Access Control List entries.

    Thread-safe for concurrent access.

    Usage:
        acl = ACLManager()

        # Grant permission
        acl.grant(
            subject_type="key",
            subject_id="key_abc123",
            permission="alerts:ack",
            resource_pattern="token:*",
        )

        # Check permission
        allowed = acl.check(
            subject_type="key",
            subject_id="key_abc123",
            permission="alerts:ack",
            resource="token:test-token",
        )
    """

    def __init__(self):
        self._entries: Dict[str, ACLEntry] = {}
        self._subject_index: Dict[str, List[str]] = {}  # subject_key -> entry_ids
        self._lock = threading.Lock()
        self._entry_counter = 0

    def _subject_key(self, subject_type: str, subject_id: str) -> str:
        """Create index key for subject"""
        return f"{subject_type}:{subject_id}"

    def grant(
        self,
        subject_type: str,
        subject_id: str,
        permission: str,
        resource_pattern: str = "*",
        granted_by: str = "system",
        expires_at: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ACLEntry:
        """
        Grant a permission to a subject.

        Args:
            subject_type: "key", "role", or "user"
            subject_id: ID of the subject
            permission: Permission to grant
            resource_pattern: Resource pattern (default: all)
            granted_by: Who granted this permission
            expires_at: Optional expiration timestamp (ms)
            metadata: Additional metadata

        Returns:
            The created ACLEntry
        """
        import time

        with self._lock:
            self._entry_counter += 1
            entry_id = f"acl_{self._entry_counter:06d}"

            entry = ACLEntry(
                entry_id=entry_id,
                subject_type=subject_type,
                subject_id=subject_id,
                permission=permission,
                resource_pattern=resource_pattern,
                granted_at=int(time.time() * 1000),
                granted_by=granted_by,
                expires_at=expires_at,
                metadata=metadata or {},
            )

            self._entries[entry_id] = entry

            # Update subject index
            subject_key = self._subject_key(subject_type, subject_id)
            if subject_key not in self._subject_index:
                self._subject_index[subject_key] = []
            self._subject_index[subject_key].append(entry_id)

            return entry

    def revoke(self, entry_id: str) -> bool:
        """
        Revoke an ACL entry.

        Args:
            entry_id: Entry ID to revoke

        Returns:
            True if entry was found and revoked
        """
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False

            # Remove from subject index
            subject_key = self._subject_key(entry.subject_type, entry.subject_id)
            if subject_key in self._subject_index:
                self._subject_index[subject_key] = [
                    eid for eid in self._subject_index[subject_key]
                    if eid != entry_id
                ]

            del self._entries[entry_id]
            return True

    def check(
        self,
        subject_type: str,
        subject_id: str,
        permission: str,
        resource: str = "*",
    ) -> bool:
        """
        Check if subject has permission on resource.

        Args:
            subject_type: Type of subject
            subject_id: Subject ID
            permission: Required permission
            resource: Resource being accessed

        Returns:
            True if permission is granted
        """
        import time
        now = int(time.time() * 1000)

        with self._lock:
            subject_key = self._subject_key(subject_type, subject_id)
            entry_ids = self._subject_index.get(subject_key, [])

            for entry_id in entry_ids:
                entry = self._entries.get(entry_id)
                if entry is None:
                    continue

                # Check expiration
                if entry.expires_at is not None and entry.expires_at < now:
                    continue

                # Check permission and resource match
                if entry.matches_permission(permission) and entry.matches_resource(resource):
                    return True

            return False

    def get_entries_for_subject(
        self,
        subject_type: str,
        subject_id: str,
    ) -> List[ACLEntry]:
        """Get all ACL entries for a subject"""
        with self._lock:
            subject_key = self._subject_key(subject_type, subject_id)
            entry_ids = self._subject_index.get(subject_key, [])
            return [self._entries[eid] for eid in entry_ids if eid in self._entries]

    def list_entries(self) -> List[ACLEntry]:
        """List all ACL entries"""
        with self._lock:
            return list(self._entries.values())


# =============================================================================
# Permission Checking Utility
# =============================================================================

def check_permission(
    roles: List[str],
    required_permission: str,
    acl_manager: Optional[ACLManager] = None,
    subject_type: str = "key",
    subject_id: str = "",
    resource: str = "*",
) -> bool:
    """
    Check if roles grant the required permission.

    First checks role-based permissions, then ACL entries.

    Args:
        roles: List of role names
        required_permission: Permission required
        acl_manager: Optional ACL manager for additional checks
        subject_type: Subject type for ACL check
        subject_id: Subject ID for ACL check
        resource: Resource for ACL check

    Returns:
        True if permission is granted
    """
    # Get all permissions from roles
    permissions = get_all_permissions_for_roles(roles)

    # Check for wildcard
    if Permission.ALL in permissions:
        return True

    # Check for exact match
    try:
        required = Permission(required_permission)
        if required in permissions:
            return True
    except ValueError:
        pass

    # Check for pattern match (e.g., "alerts:*")
    for perm in permissions:
        if fnmatch.fnmatch(required_permission, perm.value):
            return True

    # Check ACL if manager provided
    if acl_manager and subject_id:
        if acl_manager.check(subject_type, subject_id, required_permission, resource):
            return True

    return False
