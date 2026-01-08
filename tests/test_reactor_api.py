"""
Tests for Reactor API Endpoints (v5.27)

Tests:
1. Stats endpoint
2. Reactions endpoint
3. States endpoints
4. Markets endpoints
5. Event injection (when enabled)
6. Start/stop reactor
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
import time

from backend.api.main import app
from backend.api.routes.reactor import (
    get_reactor_service,
    get_belief_service,
    _reactor_service,
    _belief_service,
)


# Reset singletons between tests
@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton services between tests"""
    import backend.api.routes.reactor as reactor_module
    reactor_module._reactor_service = None
    reactor_module._belief_service = None
    yield
    reactor_module._reactor_service = None
    reactor_module._belief_service = None


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


# =============================================================================
# Stats Endpoint Tests
# =============================================================================

class TestStatsEndpoint:
    """Test /reactor/stats endpoint"""

    def test_get_stats(self, client):
        """Test getting reactor stats"""
        response = client.get("/reactor/stats")
        assert response.status_code == 200

        data = response.json()
        assert "events_processed" in data
        assert "trades_processed" in data
        assert "shocks_detected" in data
        assert "reactions_classified" in data

    def test_stats_default_values(self, client):
        """Test stats have correct default values"""
        response = client.get("/reactor/stats")
        data = response.json()

        # Initially all should be 0
        assert data["events_processed"] == 0
        assert data["trades_processed"] == 0
        assert data["shocks_detected"] == 0


# =============================================================================
# Reactions Endpoint Tests
# =============================================================================

class TestReactionsEndpoint:
    """Test /reactor/reactions endpoint"""

    def test_get_reactions_empty(self, client):
        """Test getting reactions when empty"""
        response = client.get("/reactor/reactions")
        assert response.status_code == 200

        data = response.json()
        assert "reactions" in data
        assert "count" in data
        assert "limit" in data
        assert data["reactions"] == []
        assert data["count"] == 0

    def test_get_reactions_with_limit(self, client):
        """Test getting reactions with limit parameter"""
        response = client.get("/reactor/reactions?limit=50")
        assert response.status_code == 200

        data = response.json()
        assert data["limit"] == 50

    def test_get_reactions_with_token_filter(self, client):
        """Test getting reactions with token_id filter"""
        response = client.get("/reactor/reactions?token_id=test_token")
        assert response.status_code == 200

        data = response.json()
        assert data["reactions"] == []


# =============================================================================
# States Endpoints Tests
# =============================================================================

class TestStatesEndpoints:
    """Test /reactor/states endpoints"""

    def test_get_all_states(self, client):
        """Test getting all belief states"""
        response = client.get("/reactor/states")
        assert response.status_code == 200

        data = response.json()
        assert "states" in data
        assert "total_markets" in data
        assert "distribution" in data

    def test_get_single_state(self, client):
        """Test getting state for a single market"""
        response = client.get("/reactor/state/test_token_123")
        assert response.status_code == 200

        data = response.json()
        assert data["token_id"] == "test_token_123"
        assert data["state"] in ["STABLE", "FRAGILE", "CRACKING", "BROKEN"]
        assert "indicator" in data
        assert "confidence" in data

    def test_get_state_history(self, client):
        """Test getting state change history"""
        response = client.get("/reactor/state/test_token/history")
        assert response.status_code == 200

        data = response.json()
        assert data["token_id"] == "test_token"
        assert "history" in data
        assert "count" in data

    def test_get_state_history_with_limit(self, client):
        """Test state history with limit"""
        response = client.get("/reactor/state/test_token/history?limit=10")
        assert response.status_code == 200


# =============================================================================
# Markets Endpoints Tests
# =============================================================================

class TestMarketsEndpoints:
    """Test /reactor/markets endpoints"""

    def test_get_all_markets(self, client):
        """Test getting all tracked markets"""
        response = client.get("/reactor/markets")
        assert response.status_code == 200

        data = response.json()
        assert "markets" in data
        assert "count" in data

    def test_get_market_not_found(self, client):
        """Test getting non-existent market returns 404"""
        response = client.get("/reactor/markets/nonexistent_token_xyz")
        assert response.status_code == 404


# =============================================================================
# Leading Events Endpoint Tests
# =============================================================================

class TestLeadingEventsEndpoint:
    """Test /reactor/leading-events endpoint"""

    def test_get_leading_events_empty(self, client):
        """Test getting leading events when empty"""
        response = client.get("/reactor/leading-events")
        assert response.status_code == 200

        data = response.json()
        assert "events" in data
        assert "count" in data
        assert "limit" in data

    def test_get_leading_events_with_filter(self, client):
        """Test getting leading events with token filter"""
        response = client.get("/reactor/leading-events?token_id=test&limit=50")
        assert response.status_code == 200


# =============================================================================
# Event Injection Tests (v5.33: Enhanced security)
# =============================================================================

class TestEventInjection:
    """Test /reactor/events endpoint (event injection)

    Security requirements (v5.33):
    1. REACTOR_ALLOW_INJECTION env var must be "true"
    2. Request must have ADMIN role with dangerous:inject permission
    3. All attempts are logged to audit trail
    """

    def test_injection_disabled_by_default(self, client):
        """Test that event injection is disabled by default (env check)"""
        response = client.post("/reactor/events", json={
            "event_type": "trade",
            "token_id": "test_token",
            "payload": {"price": "0.50", "size": 100, "side": "BUY"},
        })

        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()

    @patch.dict("os.environ", {"REACTOR_ALLOW_INJECTION": "true"})
    def test_injection_requires_permission(self, client):
        """Test that injection requires dangerous:inject permission (v5.33)"""
        # Even with env var enabled, should fail without ADMIN role
        response = client.post("/reactor/events", json={
            "event_type": "trade",
            "token_id": "test_token",
            "payload": {"price": "0.50", "size": 100, "side": "BUY"},
        })

        # Should be denied due to missing permission (403)
        assert response.status_code == 403
        assert "permission" in response.json()["detail"].lower()

    @patch.dict("os.environ", {"REACTOR_ALLOW_INJECTION": "true"})
    def test_injection_with_admin_role(self, client):
        """Test injection succeeds with ADMIN role (v5.33)"""
        # Mock the request state to have ADMIN role
        from unittest.mock import patch

        # Patch check_permission to return True (simulating ADMIN role)
        with patch('backend.api.routes.reactor.check_permission', return_value=True):
            response = client.post("/reactor/events", json={
                "event_type": "book",
                "token_id": "injection_test_admin",
                "payload": {
                    "bids": [{"price": "0.50", "size": 100}],
                    "asks": [{"price": "0.51", "size": 100}],
                },
            })

            # Should succeed with ADMIN permission
            assert response.status_code == 200
            assert response.json()["success"] is True

    def test_injection_audit_logging_on_deny(self, client):
        """Test that denied injection attempts are logged (v5.33)"""
        from backend.security import get_audit_logger, AuditAction

        audit_logger = get_audit_logger()

        # Make request (should be denied due to env var being false)
        response = client.post("/reactor/events", json={
            "event_type": "trade",
            "token_id": "audit_test_token",
            "payload": {"price": "0.50", "size": 100, "side": "BUY"},
        })

        assert response.status_code == 403

        # Query for injection denied entries specifically
        entries = audit_logger.query(
            action=AuditAction.DATA_INJECTION_DENIED,
            limit=10
        )
        assert len(entries) > 0, "No DATA_INJECTION_DENIED audit entries found"

        # Verify the entry details
        latest = entries[0]
        assert latest.resource_id == "audit_test_token"
        assert latest.result == "denied"
        assert "injection_disabled" in latest.details.get("reason", "")

    @patch.dict("os.environ", {"REACTOR_ALLOW_INJECTION": "true"})
    def test_injection_audit_logging_on_success(self, client):
        """Test that successful injection is logged as DANGEROUS operation (v5.33)"""
        from backend.security import get_audit_logger, AuditAction
        from unittest.mock import patch

        audit_logger = get_audit_logger()

        # Mock ADMIN permission
        with patch('backend.api.routes.reactor.check_permission', return_value=True):
            response = client.post("/reactor/events", json={
                "event_type": "book",
                "token_id": "audit_success_test",
                "payload": {
                    "bids": [{"price": "0.50", "size": 100}],
                    "asks": [{"price": "0.51", "size": 100}],
                },
            })

            assert response.status_code == 200

        # Query for dangerous injection entries specifically
        entries = audit_logger.query(
            action=AuditAction.DANGEROUS_EVENT_INJECTION,
            limit=10
        )
        assert len(entries) > 0, "No DANGEROUS_EVENT_INJECTION audit entries found"

        # Verify the entry details
        latest = entries[0]
        assert latest.resource_id == "audit_success_test"
        assert latest.result == "success"
        assert latest.details.get("event_type") == "book"


# =============================================================================
# Start/Stop Reactor Tests
# =============================================================================

class TestReactorControl:
    """Test /reactor/start and /reactor/stop endpoints"""

    def test_start_reactor(self, client):
        """Test starting the reactor"""
        response = client.post("/reactor/start")
        assert response.status_code == 200
        assert response.json()["status"] == "started"

    def test_stop_reactor(self, client):
        """Test stopping the reactor"""
        response = client.post("/reactor/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"

    def test_start_stop_sequence(self, client):
        """Test start -> stop sequence"""
        # Start
        response = client.post("/reactor/start")
        assert response.status_code == 200

        # Stop
        response = client.post("/reactor/stop")
        assert response.status_code == 200

        # Start again
        response = client.post("/reactor/start")
        assert response.status_code == 200


# =============================================================================
# Health Endpoint Tests
# =============================================================================

class TestReactorHealth:
    """Test /reactor/health endpoint"""

    def test_health_check(self, client):
        """Test reactor health check"""
        response = client.get("/reactor/health")
        assert response.status_code == 200

        data = response.json()
        assert "healthy" in data
        assert "running" in data
        assert "events_processed" in data
        assert "tracked_markets" in data


# =============================================================================
# Response Model Validation Tests
# =============================================================================

class TestResponseModels:
    """Test that response models are correctly formatted"""

    def test_stats_response_structure(self, client):
        """Test stats response has all required fields"""
        response = client.get("/reactor/stats")
        data = response.json()

        required_fields = [
            "events_processed",
            "trades_processed",
            "price_changes_processed",
            "books_processed",
            "shocks_detected",
            "reactions_classified",
            "leading_events_detected",
            "state_changes",
            "tracked_books",
        ]

        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_state_response_structure(self, client):
        """Test state response has all required fields"""
        response = client.get("/reactor/state/test_token")
        data = response.json()

        required_fields = ["token_id", "state", "indicator", "since_ts", "confidence"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_state_enum_values(self, client):
        """Test that state values are valid enum values"""
        response = client.get("/reactor/state/test_token")
        data = response.json()

        valid_states = ["STABLE", "FRAGILE", "CRACKING", "BROKEN"]
        assert data["state"] in valid_states


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_invalid_limit_too_large(self, client):
        """Test that limit > 1000 is rejected"""
        response = client.get("/reactor/reactions?limit=2000")
        assert response.status_code == 422  # Validation error

    def test_invalid_limit_negative(self, client):
        """Test that negative limit is rejected"""
        response = client.get("/reactor/reactions?limit=-1")
        assert response.status_code == 422

    def test_special_characters_in_token_id(self, client):
        """Test handling of special characters in token_id"""
        # URL encoding handles special chars
        response = client.get("/reactor/state/token%20with%20spaces")
        assert response.status_code == 200


# =============================================================================
# Integration Tests
# =============================================================================

class TestReactorIntegration:
    """Integration tests for reactor API"""

    def test_full_workflow(self, client):
        """Test complete workflow: start -> check -> stop"""
        # 1. Check initial health
        response = client.get("/reactor/health")
        assert response.status_code == 200
        assert response.json()["healthy"] is True

        # 2. Start reactor
        response = client.post("/reactor/start")
        assert response.status_code == 200

        # 3. Get stats
        response = client.get("/reactor/stats")
        assert response.status_code == 200

        # 4. Get states
        response = client.get("/reactor/states")
        assert response.status_code == 200

        # 5. Get markets
        response = client.get("/reactor/markets")
        assert response.status_code == 200

        # 6. Stop reactor
        response = client.post("/reactor/stop")
        assert response.status_code == 200

    def test_concurrent_requests(self, client):
        """Test handling concurrent requests"""
        import concurrent.futures

        def make_request():
            return client.get("/reactor/stats")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in futures]

        # All should succeed
        assert all(r.status_code == 200 for r in results)
