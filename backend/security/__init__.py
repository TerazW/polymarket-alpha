"""
Security Module (v5.23)

API authentication, authorization, and audit logging.

Components:
- APIKey management and validation
- Access Control Lists (ACL)
- Audit logging for all sensitive operations

"安全是底线"
"""

from .auth import (
    # API Key
    APIKey,
    APIKeyManager,
    generate_api_key,
    hash_api_key,
    # Authentication
    AuthResult,
    AuthStatus,
    authenticate_request,
    # Decorators
    require_api_key,
    require_permission,
)

from .acl import (
    # Permissions
    Permission,
    Role,
    ROLE_PERMISSIONS,
    # ACL
    ACLEntry,
    ACLManager,
    check_permission,
)

from .audit import (
    # Audit
    AuditAction,
    AuditEntry,
    AuditLogger,
    get_audit_logger,
    audit_log,
)

__all__ = [
    # Auth
    'APIKey',
    'APIKeyManager',
    'generate_api_key',
    'hash_api_key',
    'AuthResult',
    'AuthStatus',
    'authenticate_request',
    'require_api_key',
    'require_permission',
    # ACL
    'Permission',
    'Role',
    'ROLE_PERMISSIONS',
    'ACLEntry',
    'ACLManager',
    'check_permission',
    # Audit
    'AuditAction',
    'AuditEntry',
    'AuditLogger',
    'get_audit_logger',
    'audit_log',
]
