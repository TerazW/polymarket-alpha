"""
API Key Authentication (v5.23)

Provides:
- API key generation and hashing
- Key validation and lookup
- Request authentication
- Decorator-based protection

"身份认证是第一道防线"
"""

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable
from enum import Enum
from functools import wraps
import threading


# =============================================================================
# Constants
# =============================================================================

API_KEY_PREFIX = "brm_"  # Belief Reaction Monitor
API_KEY_LENGTH = 32      # Characters after prefix
HASH_ALGORITHM = "sha256"


# =============================================================================
# API Key Generation
# =============================================================================

def generate_api_key() -> str:
    """
    Generate a new API key.

    Format: brm_<32 random hex characters>

    Returns:
        New API key string
    """
    random_part = secrets.token_hex(API_KEY_LENGTH // 2)
    return f"{API_KEY_PREFIX}{random_part}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for storage.

    Args:
        api_key: Raw API key

    Returns:
        SHA-256 hash of the key
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


# =============================================================================
# API Key Data Model
# =============================================================================

@dataclass
class APIKey:
    """
    API Key record.

    The raw key is only available at creation time.
    Storage uses the hashed version.
    """
    key_id: str                         # Unique identifier
    key_hash: str                       # SHA-256 hash of the key
    name: str                           # Human-readable name
    created_at: int                     # Creation timestamp (ms)
    expires_at: Optional[int] = None    # Expiration timestamp (ms), None = never
    enabled: bool = True
    roles: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_used_at: Optional[int] = None

    def is_expired(self) -> bool:
        """Check if key is expired"""
        if self.expires_at is None:
            return False
        return int(time.time() * 1000) > self.expires_at

    def is_valid(self) -> bool:
        """Check if key is valid for use"""
        return self.enabled and not self.is_expired()

    def to_dict(self, include_hash: bool = False) -> dict:
        """Serialize to dict"""
        d = {
            "key_id": self.key_id,
            "name": self.name,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "enabled": self.enabled,
            "roles": self.roles,
            "metadata": self.metadata,
            "last_used_at": self.last_used_at,
            "is_expired": self.is_expired(),
            "is_valid": self.is_valid(),
        }
        if include_hash:
            d["key_hash"] = self.key_hash
        return d


# =============================================================================
# API Key Manager
# =============================================================================

class APIKeyManager:
    """
    Manages API keys: creation, validation, revocation.

    Thread-safe for concurrent access.

    Usage:
        manager = APIKeyManager()

        # Create new key
        raw_key, key_record = manager.create_key(
            name="Production API",
            roles=["reader", "writer"],
            expires_in_days=90,
        )

        # Validate key
        key_record = manager.validate_key(raw_key)
        if key_record and key_record.is_valid():
            # Authorized

        # Revoke key
        manager.revoke_key(key_id)
    """

    def __init__(self):
        self._keys: Dict[str, APIKey] = {}       # key_id -> APIKey
        self._hash_index: Dict[str, str] = {}    # key_hash -> key_id
        self._lock = threading.Lock()

    def create_key(
        self,
        name: str,
        roles: Optional[List[str]] = None,
        expires_in_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        Create a new API key.

        Args:
            name: Human-readable name
            roles: List of role names
            expires_in_days: Days until expiration (None = never)
            metadata: Additional metadata

        Returns:
            Tuple of (raw_key, APIKey record)
        """
        raw_key = generate_api_key()
        key_hash = hash_api_key(raw_key)
        key_id = f"key_{secrets.token_hex(8)}"

        now = int(time.time() * 1000)
        expires_at = None
        if expires_in_days is not None:
            expires_at = now + (expires_in_days * 24 * 60 * 60 * 1000)

        key_record = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            created_at=now,
            expires_at=expires_at,
            enabled=True,
            roles=roles or [],
            metadata=metadata or {},
        )

        with self._lock:
            self._keys[key_id] = key_record
            self._hash_index[key_hash] = key_id

        return raw_key, key_record

    def validate_key(self, raw_key: str) -> Optional[APIKey]:
        """
        Validate an API key and return the record if valid.

        Args:
            raw_key: Raw API key string

        Returns:
            APIKey record if found, None otherwise
        """
        if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
            return None

        key_hash = hash_api_key(raw_key)

        with self._lock:
            key_id = self._hash_index.get(key_hash)
            if key_id is None:
                return None

            key_record = self._keys.get(key_id)
            if key_record is None:
                return None

            # Update last used
            key_record.last_used_at = int(time.time() * 1000)

            return key_record

    def get_key(self, key_id: str) -> Optional[APIKey]:
        """Get key by ID"""
        with self._lock:
            return self._keys.get(key_id)

    def list_keys(self, include_disabled: bool = False) -> List[APIKey]:
        """List all keys"""
        with self._lock:
            keys = list(self._keys.values())
            if not include_disabled:
                keys = [k for k in keys if k.enabled]
            return keys

    def revoke_key(self, key_id: str) -> bool:
        """
        Revoke an API key (disable it).

        Args:
            key_id: Key ID to revoke

        Returns:
            True if key was found and revoked
        """
        with self._lock:
            key_record = self._keys.get(key_id)
            if key_record is None:
                return False

            key_record.enabled = False
            return True

    def delete_key(self, key_id: str) -> bool:
        """
        Permanently delete an API key.

        Args:
            key_id: Key ID to delete

        Returns:
            True if key was found and deleted
        """
        with self._lock:
            key_record = self._keys.get(key_id)
            if key_record is None:
                return False

            # Remove from indexes
            del self._hash_index[key_record.key_hash]
            del self._keys[key_id]
            return True

    def update_roles(self, key_id: str, roles: List[str]) -> bool:
        """Update roles for a key"""
        with self._lock:
            key_record = self._keys.get(key_id)
            if key_record is None:
                return False

            key_record.roles = roles
            return True


# =============================================================================
# Authentication Result
# =============================================================================

class AuthStatus(str, Enum):
    """Authentication status"""
    SUCCESS = "SUCCESS"
    MISSING_KEY = "MISSING_KEY"
    INVALID_KEY = "INVALID_KEY"
    EXPIRED_KEY = "EXPIRED_KEY"
    DISABLED_KEY = "DISABLED_KEY"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"


@dataclass
class AuthResult:
    """Result of authentication attempt"""
    status: AuthStatus
    key: Optional[APIKey] = None
    error_message: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        return self.status == AuthStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "authenticated": self.is_authenticated,
            "error": self.error_message,
            "key_id": self.key.key_id if self.key else None,
            "roles": self.key.roles if self.key else [],
        }


# =============================================================================
# Request Authentication
# =============================================================================

def authenticate_request(
    api_key: Optional[str],
    manager: APIKeyManager,
    required_roles: Optional[List[str]] = None,
) -> AuthResult:
    """
    Authenticate a request using API key.

    Args:
        api_key: API key from request header
        manager: APIKeyManager instance
        required_roles: Required roles (any match = success)

    Returns:
        AuthResult with status and key info
    """
    if not api_key:
        return AuthResult(
            status=AuthStatus.MISSING_KEY,
            error_message="API key required. Use X-API-Key header.",
        )

    key_record = manager.validate_key(api_key)

    if key_record is None:
        return AuthResult(
            status=AuthStatus.INVALID_KEY,
            error_message="Invalid API key.",
        )

    if not key_record.enabled:
        return AuthResult(
            status=AuthStatus.DISABLED_KEY,
            key=key_record,
            error_message="API key has been disabled.",
        )

    if key_record.is_expired():
        return AuthResult(
            status=AuthStatus.EXPIRED_KEY,
            key=key_record,
            error_message="API key has expired.",
        )

    # Check roles if required
    if required_roles:
        has_role = any(role in key_record.roles for role in required_roles)
        if not has_role:
            return AuthResult(
                status=AuthStatus.INSUFFICIENT_PERMISSIONS,
                key=key_record,
                error_message=f"Requires one of roles: {required_roles}",
            )

    return AuthResult(
        status=AuthStatus.SUCCESS,
        key=key_record,
    )


# =============================================================================
# Decorators for Route Protection
# =============================================================================

def require_api_key(manager: APIKeyManager):
    """
    Decorator to require API key authentication.

    Usage:
        @app.get("/protected")
        @require_api_key(key_manager)
        async def protected_route(auth: AuthResult):
            return {"key_id": auth.key.key_id}
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Note: In actual FastAPI usage, you'd extract the key from request
            # This is a simplified version for demonstration
            api_key = kwargs.get("x_api_key")
            auth_result = authenticate_request(api_key, manager)

            if not auth_result.is_authenticated:
                # In FastAPI, you'd raise HTTPException here
                return {"error": auth_result.error_message, "status": auth_result.status.value}

            kwargs["auth"] = auth_result
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_permission(manager: APIKeyManager, permission: str):
    """
    Decorator to require specific permission.

    Usage:
        @app.post("/admin/action")
        @require_permission(key_manager, "admin:write")
        async def admin_action(auth: AuthResult):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            api_key = kwargs.get("x_api_key")
            # Permission check would use ACL module
            auth_result = authenticate_request(api_key, manager)

            if not auth_result.is_authenticated:
                return {"error": auth_result.error_message}

            # TODO: Check permission via ACL
            kwargs["auth"] = auth_result
            return await func(*args, **kwargs)
        return wrapper
    return decorator
