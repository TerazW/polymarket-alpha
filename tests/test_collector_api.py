"""
Tests for Collector API Endpoints (v5.30)

Tests:
1. Health endpoint
2. Status endpoint
3. Stats endpoint
4. Token management endpoints
5. Start/stop lifecycle
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from backend.api.main import app
from backend.api.routes.collector import (
    get_collector_service,
    create_collector_service,
    reset_collector_service,
)


# Reset singleton between tests
@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset collector service singleton between tests"""
    reset_collector_service()
    yield
    reset_collector_service()


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


# =============================================================================
# Health Endpoint Tests
# =============================================================================

class TestHealthEndpoint:
    """Test /collector/health endpoint"""

    def test_health_not_started(self, client):
        """Test health when collector not started"""
        response = client.get("/collector/health")
        assert response.status_code == 200

        data = response.json()
        assert data["healthy"] is True
        assert data["running"] is False
        assert data["connection_state"] == "NOT_STARTED"
        assert data["token_count"] == 0

    def test_health_after_start(self, client):
        """Test health after starting collector"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = True
            mock_service.state.value = "CONNECTED"
            mock_service.token_ids = ["token1", "token2"]
            mock_service._events_forwarded = 100
            mock_service.start = AsyncMock()
            MockService.return_value = mock_service

            # Start collector
            response = client.post("/collector/start", json=["token1", "token2"])
            assert response.status_code == 200

            # Now patch get_collector_service to return our mock
            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.get("/collector/health")
                assert response.status_code == 200

                data = response.json()
                assert data["running"] is True
                assert data["connection_state"] == "CONNECTED"


# =============================================================================
# Status Endpoint Tests
# =============================================================================

class TestStatusEndpoint:
    """Test /collector/status endpoint"""

    def test_status_not_started(self, client):
        """Test status when collector not started"""
        response = client.get("/collector/status")
        assert response.status_code == 200

        data = response.json()
        assert data["running"] is False
        assert data["connection_state"] == "NOT_STARTED"
        assert data["is_connected"] is False
        assert data["token_count"] == 0

    def test_status_structure(self, client):
        """Test status response structure"""
        response = client.get("/collector/status")
        data = response.json()

        required_fields = ["running", "connection_state", "is_connected", "token_count"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# =============================================================================
# Stats Endpoint Tests
# =============================================================================

class TestStatsEndpoint:
    """Test /collector/stats endpoint"""

    def test_stats_not_started(self, client):
        """Test stats when collector not started"""
        response = client.get("/collector/stats")
        assert response.status_code == 200

        data = response.json()
        assert data["messages_received"] == 0
        assert data["events_forwarded_to_reactor"] == 0

    def test_stats_response_structure(self, client):
        """Test stats response has all required fields"""
        response = client.get("/collector/stats")
        data = response.json()

        required_fields = [
            "messages_received",
            "messages_published",
            "events_forwarded_to_reactor",
            "connection_attempts",
            "reconnections",
            "errors",
            "uptime_seconds",
        ]

        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# =============================================================================
# Token Management Tests
# =============================================================================

class TestTokenManagement:
    """Test token management endpoints"""

    def test_get_tokens_empty(self, client):
        """Test getting tokens when collector not started"""
        response = client.get("/collector/tokens")
        assert response.status_code == 200

        data = response.json()
        assert data["tokens"] == []
        assert data["count"] == 0

    def test_add_tokens_without_service(self, client):
        """Test adding tokens when service not initialized"""
        response = client.post("/collector/tokens", json={"token_ids": ["token1"]})
        assert response.status_code == 400
        assert "not initialized" in response.json()["detail"].lower()

    def test_remove_tokens_without_service(self, client):
        """Test removing tokens when service not initialized"""
        response = client.request(
            "DELETE",
            "/collector/tokens",
            json={"token_ids": ["token1"]}
        )
        assert response.status_code == 400

    def test_add_tokens_with_service(self, client):
        """Test adding tokens with running service"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = False
            mock_service.token_ids = ["token1"]
            mock_service.start = AsyncMock()
            mock_service.add_tokens = AsyncMock()
            MockService.return_value = mock_service

            # Start collector first
            response = client.post("/collector/start", json=["token1"])
            assert response.status_code == 200

            # Update mock for add_tokens
            def add_tokens_side_effect(tokens):
                mock_service.token_ids.extend(tokens)

            mock_service.add_tokens.side_effect = add_tokens_side_effect

            # Patch get_collector_service
            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.post("/collector/tokens", json={"token_ids": ["token2", "token3"]})
                assert response.status_code == 200

                data = response.json()
                assert data["status"] == "success"
                assert "token2" in data.get("added", [])

    def test_remove_tokens_with_service(self, client):
        """Test removing tokens with running service"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = False
            mock_service.token_ids = ["token1", "token2", "token3"]
            mock_service.start = AsyncMock()
            mock_service.remove_tokens = AsyncMock()
            MockService.return_value = mock_service

            # Start collector first
            response = client.post("/collector/start", json=["token1"])
            assert response.status_code == 200

            # Update mock for remove_tokens
            def remove_tokens_side_effect(tokens):
                for t in tokens:
                    if t in mock_service.token_ids:
                        mock_service.token_ids.remove(t)

            mock_service.remove_tokens.side_effect = remove_tokens_side_effect

            # Patch get_collector_service
            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.request(
                    "DELETE",
                    "/collector/tokens",
                    json={"token_ids": ["token2"]}
                )
                assert response.status_code == 200

                data = response.json()
                assert data["status"] == "success"


# =============================================================================
# Lifecycle Tests
# =============================================================================

class TestLifecycle:
    """Test start/stop lifecycle endpoints"""

    def test_start_collector(self, client):
        """Test starting collector"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = False
            mock_service.token_ids = ["token1"]
            mock_service.start = AsyncMock()
            MockService.return_value = mock_service

            response = client.post("/collector/start", json=["token1"])
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "started"
            mock_service.start.assert_called_once()

    def test_start_collector_without_tokens(self, client):
        """Test starting collector without initial tokens"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = False
            mock_service.token_ids = []
            mock_service.start = AsyncMock()
            MockService.return_value = mock_service

            response = client.post("/collector/start")
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "started"

    def test_start_already_running(self, client):
        """Test starting when already running"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = True
            mock_service.token_ids = ["token1"]
            mock_service.start = AsyncMock()
            MockService.return_value = mock_service

            # Start first time
            response = client.post("/collector/start", json=["token1"])

            # Patch for second call
            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.post("/collector/start", json=["token1"])
                assert response.status_code == 200

                data = response.json()
                assert data["status"] == "already_running"

    def test_stop_collector(self, client):
        """Test stopping collector"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = True
            mock_service.token_ids = ["token1"]
            mock_service.start = AsyncMock()
            mock_service.stop = AsyncMock()
            MockService.return_value = mock_service

            # Start first
            response = client.post("/collector/start", json=["token1"])
            assert response.status_code == 200

            # Patch for stop
            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.post("/collector/stop")
                assert response.status_code == 200

                data = response.json()
                assert data["status"] == "stopped"
                mock_service.stop.assert_called_once()

    def test_stop_not_initialized(self, client):
        """Test stopping when not initialized"""
        response = client.post("/collector/stop")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "not_initialized"

    def test_stop_already_stopped(self, client):
        """Test stopping when already stopped"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = False
            mock_service.token_ids = []
            mock_service.start = AsyncMock()
            mock_service.stop = AsyncMock()
            MockService.return_value = mock_service

            # Start and then manually mark as stopped
            response = client.post("/collector/start")

            # Patch for stop with _started = False
            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.post("/collector/stop")
                assert response.status_code == 200

                data = response.json()
                assert data["status"] == "already_stopped"


# =============================================================================
# Connection States Endpoint Tests
# =============================================================================

class TestConnectionStatesEndpoint:
    """Test /collector/connection-states endpoint"""

    def test_get_connection_states(self, client):
        """Test getting available connection states"""
        response = client.get("/collector/connection-states")
        assert response.status_code == 200

        data = response.json()
        assert "states" in data

        states = data["states"]
        assert len(states) == 4

        state_values = [s["value"] for s in states]
        assert "DISCONNECTED" in state_values
        assert "CONNECTING" in state_values
        assert "CONNECTED" in state_values
        assert "RECONNECTING" in state_values


# =============================================================================
# Integration Tests
# =============================================================================

class TestCollectorIntegration:
    """Integration tests for collector API"""

    def test_full_lifecycle(self, client):
        """Test complete lifecycle: start -> check status -> stop"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = False
            mock_service.token_ids = []
            mock_service.state.value = "DISCONNECTED"
            mock_service.is_connected = False
            mock_service._events_forwarded = 0
            mock_service.start = AsyncMock()
            mock_service.stop = AsyncMock()
            mock_service.get_stats = AsyncMock(return_value={
                'messages_received': 0,
                'messages_published': 0,
            })
            MockService.return_value = mock_service

            # 1. Check initial health
            response = client.get("/collector/health")
            assert response.status_code == 200
            assert response.json()["running"] is False

            # 2. Start collector
            response = client.post("/collector/start", json=["test_token"])
            assert response.status_code == 200
            assert response.json()["status"] == "started"

            # Update mock state
            mock_service._started = True
            mock_service.state.value = "CONNECTED"
            mock_service.is_connected = True
            mock_service.token_ids = ["test_token"]

            # Patch get_collector_service for subsequent calls
            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                # 3. Check status
                response = client.get("/collector/status")
                assert response.status_code == 200
                data = response.json()
                assert data["running"] is True

                # 4. Check tokens
                response = client.get("/collector/tokens")
                assert response.status_code == 200
                assert "test_token" in response.json()["tokens"]

                # 5. Get stats
                response = client.get("/collector/stats")
                assert response.status_code == 200

                # 6. Stop collector
                response = client.post("/collector/stop")
                assert response.status_code == 200
                assert response.json()["status"] == "stopped"


# =============================================================================
# Validation Tests
# =============================================================================

class TestValidation:
    """Test request validation"""

    def test_add_tokens_empty_list(self, client):
        """Test that empty token list is rejected"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = True
            mock_service.token_ids = []
            MockService.return_value = mock_service

            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.post("/collector/tokens", json={"token_ids": []})
                assert response.status_code == 422  # Validation error

    def test_add_tokens_invalid_body(self, client):
        """Test that invalid body is rejected"""
        with patch('backend.api.routes.collector.CollectorService') as MockService:
            mock_service = MagicMock()
            mock_service._started = True
            MockService.return_value = mock_service

            with patch('backend.api.routes.collector.get_collector_service', return_value=mock_service):
                response = client.post("/collector/tokens", json={"invalid": "data"})
                assert response.status_code == 422
