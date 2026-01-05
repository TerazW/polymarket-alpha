"""
Admin API Routes (v5.35)

API key management, ACL configuration, and system administration.

All endpoints require admin role.

"管理员权限，最高级别"
"""

import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

from backend.security import (
    APIKey,
    Permission,
    Role,
    ROLE_PERMISSIONS,
    ACLEntry,
)
from backend.api.middleware import (
    get_api_key_manager,
    get_acl_manager,
    get_current_key,
)
from backend.security.audit import audit_log, AuditAction

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# Request/Response Models
# =============================================================================

class CreateKeyRequest(BaseModel):
    """Request to create a new API key"""
    name: str = Field(..., min_length=1, max_length=100)
    roles: List[str] = Field(default_factory=list)
    expires_in_days: Optional[int] = Field(None, ge=1, le=365)
    metadata: Optional[dict] = None


class CreateKeyResponse(BaseModel):
    """Response with new API key (only time raw key is shown)"""
    key_id: str
    api_key: str  # Raw key - only shown once!
    name: str
    roles: List[str]
    expires_at: Optional[int]
    message: str = "Store this API key securely. It will not be shown again."


class KeyInfo(BaseModel):
    """API key info (without raw key)"""
    key_id: str
    name: str
    created_at: int
    expires_at: Optional[int]
    enabled: bool
    roles: List[str]
    last_used_at: Optional[int]
    is_expired: bool
    is_valid: bool


class UpdateRolesRequest(BaseModel):
    """Request to update key roles"""
    roles: List[str]


class GrantPermissionRequest(BaseModel):
    """Request to grant a permission"""
    subject_type: str = Field(..., pattern="^(key|role|user)$")
    subject_id: str = Field(..., min_length=1)
    permission: str = Field(..., min_length=1)
    resource_pattern: str = Field(default="*")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365)


class ACLEntryResponse(BaseModel):
    """ACL entry info"""
    entry_id: str
    subject_type: str
    subject_id: str
    permission: str
    resource_pattern: str
    granted_at: int
    granted_by: str
    expires_at: Optional[int]


# =============================================================================
# Helper Functions
# =============================================================================

async def require_admin(request: Request):
    """Dependency to require admin role"""
    roles = getattr(request.state, "roles", [])
    if "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Admin role required"
        )
    return getattr(request.state, "auth", None)


# =============================================================================
# API Key Management
# =============================================================================

@router.get("/keys", response_model=List[KeyInfo])
async def list_api_keys(
    request: Request,
    include_disabled: bool = False,
    _: None = Depends(require_admin),
):
    """
    List all API keys.

    Requires: admin role
    """
    manager = get_api_key_manager()
    keys = manager.list_keys(include_disabled=include_disabled)

    return [
        KeyInfo(
            key_id=k.key_id,
            name=k.name,
            created_at=k.created_at,
            expires_at=k.expires_at,
            enabled=k.enabled,
            roles=k.roles,
            last_used_at=k.last_used_at,
            is_expired=k.is_expired(),
            is_valid=k.is_valid(),
        )
        for k in keys
    ]


@router.post("/keys", response_model=CreateKeyResponse)
async def create_api_key(
    request: Request,
    body: CreateKeyRequest,
    _: None = Depends(require_admin),
):
    """
    Create a new API key.

    The raw API key is only returned once in this response.
    Store it securely - it cannot be retrieved later.

    Requires: admin role
    """
    manager = get_api_key_manager()

    # Validate roles
    valid_roles = {r.value for r in Role}
    for role in body.roles:
        if role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role: {role}. Valid roles: {list(valid_roles)}"
            )

    raw_key, key_record = manager.create_key(
        name=body.name,
        roles=body.roles,
        expires_in_days=body.expires_in_days,
        metadata=body.metadata,
    )

    # Audit log
    actor_id = getattr(request.state, "actor_id", "system")
    audit_log(
        action=AuditAction.KEY_CREATED,
        actor_type="key",
        actor_id=actor_id,
        resource_type="api_key",
        resource_id=key_record.key_id,
        result="success",
        details={"name": body.name, "roles": body.roles},
    )

    return CreateKeyResponse(
        key_id=key_record.key_id,
        api_key=raw_key,
        name=key_record.name,
        roles=key_record.roles,
        expires_at=key_record.expires_at,
    )


@router.get("/keys/{key_id}", response_model=KeyInfo)
async def get_api_key(
    request: Request,
    key_id: str,
    _: None = Depends(require_admin),
):
    """
    Get API key details.

    Requires: admin role
    """
    manager = get_api_key_manager()
    key = manager.get_key(key_id)

    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    return KeyInfo(
        key_id=key.key_id,
        name=key.name,
        created_at=key.created_at,
        expires_at=key.expires_at,
        enabled=key.enabled,
        roles=key.roles,
        last_used_at=key.last_used_at,
        is_expired=key.is_expired(),
        is_valid=key.is_valid(),
    )


@router.put("/keys/{key_id}/roles")
async def update_key_roles(
    request: Request,
    key_id: str,
    body: UpdateRolesRequest,
    _: None = Depends(require_admin),
):
    """
    Update roles for an API key.

    Requires: admin role
    """
    manager = get_api_key_manager()

    # Validate roles
    valid_roles = {r.value for r in Role}
    for role in body.roles:
        if role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role: {role}"
            )

    if not manager.update_roles(key_id, body.roles):
        raise HTTPException(status_code=404, detail="Key not found")

    # Audit log
    actor_id = getattr(request.state, "actor_id", "system")
    audit_log(
        action=AuditAction.KEY_UPDATED,
        actor_type="key",
        actor_id=actor_id,
        resource_type="api_key",
        resource_id=key_id,
        result="success",
        details={"new_roles": body.roles},
    )

    return {"status": "updated", "key_id": key_id, "roles": body.roles}


@router.delete("/keys/{key_id}")
async def revoke_api_key(
    request: Request,
    key_id: str,
    permanent: bool = False,
    _: None = Depends(require_admin),
):
    """
    Revoke or delete an API key.

    By default, keys are disabled (can be re-enabled).
    Use permanent=true to delete permanently.

    Requires: admin role
    """
    manager = get_api_key_manager()

    if permanent:
        if not manager.delete_key(key_id):
            raise HTTPException(status_code=404, detail="Key not found")
        action = AuditAction.KEY_DELETED
        message = "deleted permanently"
    else:
        if not manager.revoke_key(key_id):
            raise HTTPException(status_code=404, detail="Key not found")
        action = AuditAction.KEY_REVOKED
        message = "revoked (disabled)"

    # Audit log
    actor_id = getattr(request.state, "actor_id", "system")
    audit_log(
        action=action,
        actor_type="key",
        actor_id=actor_id,
        resource_type="api_key",
        resource_id=key_id,
        result="success",
    )

    return {"status": message, "key_id": key_id}


# =============================================================================
# ACL Management
# =============================================================================

@router.get("/acl", response_model=List[ACLEntryResponse])
async def list_acl_entries(
    request: Request,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    _: None = Depends(require_admin),
):
    """
    List ACL entries.

    Optionally filter by subject.

    Requires: admin role
    """
    manager = get_acl_manager()

    if subject_type and subject_id:
        entries = manager.get_entries_for_subject(subject_type, subject_id)
    else:
        entries = manager.list_entries()

    return [
        ACLEntryResponse(
            entry_id=e.entry_id,
            subject_type=e.subject_type,
            subject_id=e.subject_id,
            permission=e.permission,
            resource_pattern=e.resource_pattern,
            granted_at=e.granted_at,
            granted_by=e.granted_by,
            expires_at=e.expires_at,
        )
        for e in entries
    ]


@router.post("/acl", response_model=ACLEntryResponse)
async def grant_permission(
    request: Request,
    body: GrantPermissionRequest,
    _: None = Depends(require_admin),
):
    """
    Grant a permission to a subject.

    Requires: admin role
    """
    import time

    manager = get_acl_manager()
    actor_id = getattr(request.state, "actor_id", "system")

    expires_at = None
    if body.expires_in_days:
        now = int(time.time() * 1000)
        expires_at = now + (body.expires_in_days * 24 * 60 * 60 * 1000)

    entry = manager.grant(
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        permission=body.permission,
        resource_pattern=body.resource_pattern,
        granted_by=actor_id,
        expires_at=expires_at,
    )

    # Audit log
    audit_log(
        action=AuditAction.ACL_GRANTED,
        actor_type="key",
        actor_id=actor_id,
        resource_type="acl_entry",
        resource_id=entry.entry_id,
        result="success",
        details={
            "subject": f"{body.subject_type}:{body.subject_id}",
            "permission": body.permission,
        },
    )

    return ACLEntryResponse(
        entry_id=entry.entry_id,
        subject_type=entry.subject_type,
        subject_id=entry.subject_id,
        permission=entry.permission,
        resource_pattern=entry.resource_pattern,
        granted_at=entry.granted_at,
        granted_by=entry.granted_by,
        expires_at=entry.expires_at,
    )


@router.delete("/acl/{entry_id}")
async def revoke_permission(
    request: Request,
    entry_id: str,
    _: None = Depends(require_admin),
):
    """
    Revoke an ACL entry.

    Requires: admin role
    """
    manager = get_acl_manager()

    if not manager.revoke(entry_id):
        raise HTTPException(status_code=404, detail="ACL entry not found")

    # Audit log
    actor_id = getattr(request.state, "actor_id", "system")
    audit_log(
        action=AuditAction.ACL_REVOKED,
        actor_type="key",
        actor_id=actor_id,
        resource_type="acl_entry",
        resource_id=entry_id,
        result="success",
    )

    return {"status": "revoked", "entry_id": entry_id}


# =============================================================================
# Role Information
# =============================================================================

@router.get("/roles")
async def list_roles(_: None = Depends(require_admin)):
    """
    List available roles and their permissions.

    Requires: admin role
    """
    return {
        "roles": {
            role.value: {
                "name": role.value,
                "permissions": [p.value for p in permissions],
            }
            for role, permissions in ROLE_PERMISSIONS.items()
        }
    }


@router.get("/permissions")
async def list_permissions(_: None = Depends(require_admin)):
    """
    List all available permissions.

    Requires: admin role
    """
    return {
        "permissions": [
            {
                "name": p.value,
                "category": p.value.split(":")[0] if ":" in p.value else "other",
            }
            for p in Permission
        ]
    }


# =============================================================================
# Bootstrap Endpoint (Special - for initial setup)
# =============================================================================

@router.post("/bootstrap")
async def bootstrap_admin_key(request: Request):
    """
    Bootstrap the first admin API key.

    This endpoint only works if:
    1. No API keys exist yet, OR
    2. ADMIN_BOOTSTRAP_TOKEN env var is provided and matches

    This is a one-time setup operation.

    Returns the admin API key (only shown once).
    """
    manager = get_api_key_manager()

    # Check if bootstrap is allowed
    existing_keys = manager.list_keys(include_disabled=True)
    bootstrap_token = os.getenv("ADMIN_BOOTSTRAP_TOKEN")

    if existing_keys:
        # Keys exist - require bootstrap token
        provided_token = request.headers.get("X-Bootstrap-Token")
        if not bootstrap_token:
            raise HTTPException(
                status_code=403,
                detail="Keys already exist. Set ADMIN_BOOTSTRAP_TOKEN to create additional admin keys."
            )
        if provided_token != bootstrap_token:
            raise HTTPException(
                status_code=403,
                detail="Invalid bootstrap token"
            )

    # Create admin key
    raw_key, key_record = manager.create_key(
        name="Bootstrap Admin Key",
        roles=["admin"],
        expires_in_days=None,  # Never expires
        metadata={"bootstrap": True},
    )

    # Audit log
    audit_log(
        action=AuditAction.KEY_CREATED,
        actor_type="system",
        actor_id="bootstrap",
        resource_type="api_key",
        resource_id=key_record.key_id,
        result="success",
        details={"type": "bootstrap_admin"},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "status": "success",
        "message": "Admin API key created. Store this key securely - it will not be shown again!",
        "key_id": key_record.key_id,
        "api_key": raw_key,
        "roles": key_record.roles,
    }
