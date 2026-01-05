"""
Tests for API Middleware Integration (v5.24)

Validates:
1. Audit logging middleware
2. Auth middleware
3. Throttle middleware
4. Middleware integration

"安全 → 限流 → 审计"
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import time

from backend.api.middleware import (
    AuditMiddleware,
    AuthMiddleware,
    ThrottleMiddleware,
    register_security_middleware,
    get_api_key_manager,
    get_acl_manager,
    match_endpoint_pattern,
    is_public_endpoint,
    ENDPOINT_PERMISSIONS,
    PUBLIC_ENDPOINTS,
)
from backend.security.auth import APIKeyManager
from backend.security.audit import get_audit_logger, AuditAction


class TestEndpointPatternMatching:
    """Test endpoint pattern matching"""

    def test_direct_match(self):
        """Should match direct endpoint"""
        result = match_endpoint_pattern("GET", "/v1/radar")

        assert result == "radar:read"

    def test_wildcard_match(self):
        """Should match wildcard endpoint"""
        result = match_endpoint_pattern("PUT", "/v1/alerts/abc123/ack")

        assert result == "alerts:ack"

    def test_no_match(self):
        """Should return None for unknown endpoint"""
        result = match_endpoint_pattern("GET", "/unknown/path")

        assert result is None

    def test_is_public_health(self):
        """Health endpoints should be public"""
        assert is_public_endpoint("GET", "/health") is True
        assert is_public_endpoint("GET", "/v1/health") is True

    def test_is_public_metrics(self):
        """Metrics endpoint should be public"""
        assert is_public_endpoint("GET", "/metrics") is True

    def test_is_not_public_radar(self):
        """Radar endpoint should not be public"""
        assert is_public_endpoint("GET", "/v1/radar") is False


class TestGetManagers:
    """Test manager singletons"""

    def test_api_key_manager_singleton(self):
        """Should return same manager instance"""
        manager1 = get_api_key_manager()
        manager2 = get_api_key_manager()

        assert manager1 is manager2

    def test_acl_manager_singleton(self):
        """Should return same ACL manager instance"""
        acl1 = get_acl_manager()
        acl2 = get_acl_manager()

        assert acl1 is acl2


class TestAuditMiddleware:
    """Test AuditMiddleware"""

    def test_logs_request(self):
        """Should log API request"""
        app = FastAPI()
        app.add_middleware(AuditMiddleware)

        @app.get("/test")
        def test_route():
            return {"status": "ok"}

        # Clear audit logger
        logger = get_audit_logger()
        logger.clear()

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200

        # Check audit log
        entries = logger.get_recent(limit=10)
        assert len(entries) >= 1

        # Find our request
        test_entries = [e for e in entries if "/test" in str(e.details.get("path", ""))]
        assert len(test_entries) >= 1
        assert test_entries[0].action == AuditAction.API_REQUEST

    def test_sets_request_id(self):
        """Should set X-Request-ID header"""
        app = FastAPI()
        app.add_middleware(AuditMiddleware)

        @app.get("/test")
        def test_route():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")

        assert "X-Request-ID" in response.headers
        assert response.headers["X-Request-ID"].startswith("req_")


class TestAuthMiddleware:
    """Test AuthMiddleware"""

    def test_public_endpoint_no_auth(self):
        """Public endpoints should not require auth"""
        app = FastAPI()
        app.add_middleware(AuthMiddleware, require_auth=True)

        @app.get("/health")
        def health():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200

    def test_protected_endpoint_requires_auth(self):
        """Protected endpoints should require auth when enabled"""
        app = FastAPI()
        app.add_middleware(AuthMiddleware, require_auth=True)

        @app.get("/v1/radar")
        def radar():
            return {"markets": []}

        client = TestClient(app)
        response = client.get("/v1/radar")

        assert response.status_code == 401

    def test_valid_api_key_passes(self):
        """Valid API key should pass authentication"""
        app = FastAPI()
        manager = get_api_key_manager()
        raw_key, _ = manager.create_key(name="Test", roles=["viewer"])

        app.add_middleware(AuthMiddleware, require_auth=True)

        @app.get("/v1/radar")
        def radar():
            return {"markets": []}

        client = TestClient(app)
        response = client.get("/v1/radar", headers={"X-API-Key": raw_key})

        assert response.status_code == 200

    def test_invalid_api_key_rejected(self):
        """Invalid API key should be rejected"""
        app = FastAPI()
        app.add_middleware(AuthMiddleware, require_auth=True)

        @app.get("/v1/radar")
        def radar():
            return {"markets": []}

        client = TestClient(app)
        response = client.get("/v1/radar", headers={"X-API-Key": "brm_invalid_key_12345"})

        assert response.status_code == 401


class TestThrottleMiddleware:
    """Test ThrottleMiddleware"""

    def test_allows_within_limit(self):
        """Should allow requests within rate limit"""
        app = FastAPI()
        app.add_middleware(ThrottleMiddleware, enabled=True)

        @app.get("/v1/health")
        def health():
            return {"status": "ok"}

        client = TestClient(app)

        # Health has high rate limit (100/s)
        for _ in range(5):
            response = client.get("/v1/health")
            assert response.status_code == 200

    def test_disabled_middleware(self):
        """Disabled middleware should not throttle"""
        app = FastAPI()
        app.add_middleware(ThrottleMiddleware, enabled=False)

        @app.get("/test")
        def test_route():
            return {"status": "ok"}

        client = TestClient(app)

        # Should always pass
        for _ in range(20):
            response = client.get("/test")
            assert response.status_code == 200


class TestMiddlewareIntegration:
    """Test full middleware stack"""

    def test_register_security_middleware(self):
        """Should register all middleware correctly"""
        app = FastAPI()

        @app.get("/test")
        def test_route():
            return {"status": "ok"}

        register_security_middleware(
            app,
            require_auth=False,
            enable_throttling=True,
            enable_audit=True,
        )

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers

    def test_full_stack_public_endpoint(self):
        """Full stack should work for public endpoints"""
        app = FastAPI()

        @app.get("/health")
        def health():
            return {"status": "ok"}

        register_security_middleware(
            app,
            require_auth=True,
            enable_throttling=True,
            enable_audit=True,
        )

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200

    def test_full_stack_with_auth(self):
        """Full stack should work with valid authentication"""
        app = FastAPI()
        manager = get_api_key_manager()
        raw_key, _ = manager.create_key(name="FullTest", roles=["viewer"])

        @app.get("/v1/radar")
        def radar():
            return {"markets": []}

        register_security_middleware(
            app,
            require_auth=True,
            enable_throttling=True,
            enable_audit=True,
        )

        client = TestClient(app)
        response = client.get("/v1/radar", headers={"X-API-Key": raw_key})

        assert response.status_code == 200


class TestEndpointPermissions:
    """Test ENDPOINT_PERMISSIONS constant"""

    def test_read_endpoints_defined(self):
        """Read endpoints should have permissions"""
        assert "GET /v1/radar" in ENDPOINT_PERMISSIONS
        assert "GET /v1/evidence" in ENDPOINT_PERMISSIONS
        assert "GET /v1/alerts" in ENDPOINT_PERMISSIONS

    def test_write_endpoints_defined(self):
        """Write endpoints should have permissions"""
        assert "PUT /v1/alerts/*/ack" in ENDPOINT_PERMISSIONS
        assert "PUT /v1/alerts/*/resolve" in ENDPOINT_PERMISSIONS

    def test_admin_endpoints_defined(self):
        """Admin endpoints should have permissions"""
        assert "GET /v1/admin/keys" in ENDPOINT_PERMISSIONS


class TestPublicEndpoints:
    """Test PUBLIC_ENDPOINTS constant"""

    def test_health_public(self):
        """Health endpoints should be public"""
        assert "GET /health" in PUBLIC_ENDPOINTS
        assert "GET /v1/health" in PUBLIC_ENDPOINTS
        assert "GET /v1/health/deep" in PUBLIC_ENDPOINTS

    def test_metrics_public(self):
        """Metrics should be public"""
        assert "GET /metrics" in PUBLIC_ENDPOINTS

    def test_radar_not_public(self):
        """Radar should not be public"""
        assert "GET /v1/radar" not in PUBLIC_ENDPOINTS
