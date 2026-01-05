"""
API Middleware Integration (v5.24)

Integrates security, throttling, and audit logging into FastAPI.

Middleware order (executed first-to-last on request, last-to-first on response):
1. AuditMiddleware - Log all requests
2. AuthMiddleware - API key authentication
3. ThrottleMiddleware - Rate limiting

"安全 → 限流 → 审计"
"""

import time
from typing import Optional, Callable, Dict, Any
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio

from backend.security.auth import (
    APIKeyManager,
    authenticate_request,
    AuthStatus,
)
from backend.security.acl import (
    check_permission,
    ACLManager,
)
from backend.security.audit import (
    AuditAction,
    audit_log,
    get_audit_logger,
)
from backend.common.throttle import (
    AsyncTokenBucket,
    PerKeyRateLimiter,
    ConcurrencyLimiter,
    ThrottleRegistry,
    get_throttle_registry,
    EndpointThrottleConfig,
    DEFAULT_ENDPOINT_CONFIGS,
)


# =============================================================================
# Global Managers (Singletons)
# =============================================================================

_api_key_manager: Optional[APIKeyManager] = None
_acl_manager: Optional[ACLManager] = None


def get_api_key_manager() -> APIKeyManager:
    """Get the global API key manager"""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager


def get_acl_manager() -> ACLManager:
    """Get the global ACL manager"""
    global _acl_manager
    if _acl_manager is None:
        _acl_manager = ACLManager()
    return _acl_manager


# =============================================================================
# Endpoint Permission Mapping
# =============================================================================

# Map endpoints to required permissions
ENDPOINT_PERMISSIONS: Dict[str, str] = {
    # Read endpoints
    "GET /v1/radar": "radar:read",
    "GET /v1/evidence": "evidence:read",
    "GET /v1/alerts": "alerts:read",
    "GET /v1/replay/catalog": "replay:read",
    "GET /v1/heatmap/tiles": "heatmap:read",
    "GET /v1/metrics": "metrics:read",

    # Write endpoints
    "PUT /v1/alerts/*/ack": "alerts:ack",
    "PUT /v1/alerts/*/resolve": "alerts:resolve",
    "POST /v1/replay/trigger": "replay:trigger",

    # Admin endpoints
    "GET /v1/admin/keys": "admin:keys",
    "POST /v1/admin/keys": "admin:keys",
    "DELETE /v1/admin/keys/*": "admin:keys",
    "GET /v1/admin/audit": "admin:audit",
}

# Endpoints that don't require authentication
PUBLIC_ENDPOINTS = {
    "GET /health",
    "GET /v1/health",
    "GET /v1/health/deep",
    "GET /metrics",
}


def match_endpoint_pattern(method: str, path: str) -> Optional[str]:
    """Match endpoint to permission pattern"""
    key = f"{method} {path}"

    # Direct match
    if key in ENDPOINT_PERMISSIONS:
        return ENDPOINT_PERMISSIONS[key]

    # Wildcard match
    import fnmatch
    for pattern, permission in ENDPOINT_PERMISSIONS.items():
        if "*" in pattern:
            pattern_method, pattern_path = pattern.split(" ", 1)
            if method == pattern_method and fnmatch.fnmatch(path, pattern_path):
                return permission

    return None


def is_public_endpoint(method: str, path: str) -> bool:
    """Check if endpoint is public (no auth required)"""
    key = f"{method} {path}"
    return key in PUBLIC_ENDPOINTS


# =============================================================================
# Audit Middleware
# =============================================================================

class AuditMiddleware(BaseHTTPMiddleware):
    """
    Logs all API requests for audit trail.

    Captures:
    - Request method, path, query params
    - Response status code
    - Request duration
    - Client IP, User-Agent
    - Authenticated key (if any)
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        request_id = f"req_{int(start_time * 1000)}"

        # Store request_id for other middleware
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Get actor info (set by auth middleware if authenticated)
        actor_type = getattr(request.state, "actor_type", "anonymous")
        actor_id = getattr(request.state, "actor_id", "anonymous")

        # Determine result
        result = "success" if response.status_code < 400 else "failure"
        if response.status_code == 401:
            result = "unauthorized"
        elif response.status_code == 403:
            result = "forbidden"
        elif response.status_code == 429:
            result = "rate_limited"

        # Log the request
        audit_log(
            action=AuditAction.API_REQUEST,
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type="endpoint",
            resource_id=f"{request.method} {request.url.path}",
            result=result,
            details={
                "method": request.method,
                "path": str(request.url.path),
                "query": str(request.url.query),
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            request_id=request_id,
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


# =============================================================================
# Auth Middleware
# =============================================================================

class AuthMiddleware(BaseHTTPMiddleware):
    """
    API key authentication middleware.

    Extracts API key from X-API-Key header and validates it.
    Sets request.state.auth with authentication result.
    """

    def __init__(self, app: FastAPI, require_auth: bool = False):
        super().__init__(app)
        self.require_auth = require_auth
        self.key_manager = get_api_key_manager()
        self.acl_manager = get_acl_manager()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        method = request.method
        path = request.url.path

        # Skip auth for public endpoints
        if is_public_endpoint(method, path):
            return await call_next(request)

        # Extract API key
        api_key = request.headers.get("X-API-Key")

        # Authenticate
        auth_result = authenticate_request(api_key, self.key_manager)

        # Store auth info in request state
        if auth_result.is_authenticated:
            request.state.actor_type = "key"
            request.state.actor_id = auth_result.key.key_id
            request.state.auth = auth_result
            request.state.roles = auth_result.key.roles
        else:
            request.state.actor_type = "anonymous"
            request.state.actor_id = "anonymous"
            request.state.auth = None
            request.state.roles = []

        # Check if auth is required
        if self.require_auth and not auth_result.is_authenticated:
            # Log failed auth
            if api_key:
                audit_log(
                    action=AuditAction.AUTH_FAILED,
                    actor_type="anonymous",
                    actor_id="anonymous",
                    details={"reason": auth_result.status.value},
                    ip_address=request.client.host if request.client else None,
                )

            return JSONResponse(
                status_code=401,
                content={
                    "error": auth_result.error_message or "Authentication required",
                    "code": auth_result.status.value,
                },
            )

        # Check permission if authenticated
        if auth_result.is_authenticated:
            required_permission = match_endpoint_pattern(method, path)

            if required_permission:
                has_permission = check_permission(
                    roles=auth_result.key.roles,
                    required_permission=required_permission,
                    acl_manager=self.acl_manager,
                    subject_type="key",
                    subject_id=auth_result.key.key_id,
                )

                if not has_permission:
                    audit_log(
                        action=AuditAction.AUTHZ_DENIED,
                        actor_type="key",
                        actor_id=auth_result.key.key_id,
                        resource_type="permission",
                        resource_id=required_permission,
                        result="denied",
                        ip_address=request.client.host if request.client else None,
                    )

                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": f"Permission denied: {required_permission}",
                            "code": "FORBIDDEN",
                        },
                    )

        return await call_next(request)


# =============================================================================
# Throttle Middleware
# =============================================================================

class ThrottleMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware.

    Applies per-endpoint rate limits based on configuration.
    Supports per-key and per-IP limiting.
    """

    def __init__(self, app: FastAPI, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        self.registry = get_throttle_registry()
        self._limiters: Dict[str, AsyncTokenBucket] = {}
        self._per_key_limiters: Dict[str, PerKeyRateLimiter] = {}

    def _get_limiter(self, endpoint: str, config: EndpointThrottleConfig) -> AsyncTokenBucket:
        """Get or create limiter for endpoint"""
        if endpoint not in self._limiters:
            self._limiters[endpoint] = AsyncTokenBucket(
                rate=config.rate,
                capacity=config.burst,
            )
        return self._limiters[endpoint]

    def _get_per_key_limiter(self, endpoint: str, config: EndpointThrottleConfig) -> PerKeyRateLimiter:
        """Get or create per-key limiter for endpoint"""
        if endpoint not in self._per_key_limiters:
            self._per_key_limiters[endpoint] = PerKeyRateLimiter(
                rate=config.rate,
                capacity=config.burst,
            )
        return self._per_key_limiters[endpoint]

    def _extract_key(self, request: Request, key_extractor: str) -> str:
        """Extract throttle key from request"""
        if key_extractor == "ip":
            return request.client.host if request.client else "unknown"
        elif key_extractor == "token_id":
            return request.query_params.get("token_id", "unknown")
        elif key_extractor == "api_key":
            return getattr(request.state, "actor_id", "anonymous")
        else:
            return "global"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        path = request.url.path

        # Get throttle config for this endpoint
        config = self.registry.get_config(path)

        # Determine the key for rate limiting
        if config.per_key and config.key_extractor:
            key = self._extract_key(request, config.key_extractor)
            limiter = self._get_per_key_limiter(path, config)
            allowed = limiter.acquire(key)
        else:
            limiter = self._get_limiter(path, config)
            allowed = await limiter.acquire()

        if not allowed:
            # Log rate limit hit
            audit_log(
                action=AuditAction.API_RATE_LIMITED,
                actor_type=getattr(request.state, "actor_type", "anonymous"),
                actor_id=getattr(request.state, "actor_id", "anonymous"),
                resource_type="endpoint",
                resource_id=path,
                result="rate_limited",
                ip_address=request.client.host if request.client else None,
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "code": "RATE_LIMITED",
                    "retry_after_seconds": 1.0 / config.rate,
                },
                headers={
                    "Retry-After": str(int(1.0 / config.rate)),
                },
            )

        return await call_next(request)


# =============================================================================
# Middleware Registration
# =============================================================================

def register_security_middleware(
    app: FastAPI,
    require_auth: bool = False,
    enable_throttling: bool = True,
    enable_audit: bool = True,
) -> None:
    """
    Register all security middleware on a FastAPI app.

    Order matters! Middleware is executed in reverse order of registration.
    We want: Request → Audit → Auth → Throttle → Handler
    So we register: Throttle, Auth, Audit (reverse order)

    Args:
        app: FastAPI application
        require_auth: Whether to require authentication for all non-public endpoints
        enable_throttling: Whether to enable rate limiting
        enable_audit: Whether to enable audit logging
    """
    # Register in reverse order of desired execution
    if enable_throttling:
        app.add_middleware(ThrottleMiddleware, enabled=True)

    app.add_middleware(AuthMiddleware, require_auth=require_auth)

    if enable_audit:
        app.add_middleware(AuditMiddleware)


# =============================================================================
# Dependency Injection Helpers (for route-level auth)
# =============================================================================

async def get_current_key(request: Request):
    """
    FastAPI dependency to get the current authenticated API key.

    Usage:
        @router.get("/protected")
        async def protected_route(key: APIKey = Depends(get_current_key)):
            return {"key_id": key.key_id}
    """
    auth = getattr(request.state, "auth", None)
    if auth and auth.is_authenticated:
        return auth.key
    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_role(role: str):
    """
    FastAPI dependency factory to require a specific role.

    Usage:
        @router.post("/admin/action")
        async def admin_action(key: APIKey = Depends(require_role("admin"))):
            ...
    """
    async def dependency(request: Request):
        roles = getattr(request.state, "roles", [])
        if role not in roles and "admin" not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{role}' required")
        return getattr(request.state, "auth", None)
    return dependency
