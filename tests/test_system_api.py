"""
Tests for System API Endpoints (v5.32)

Tests:
1. Health endpoint
2. Services endpoint
3. Start/stop/restart lifecycle
4. Service restart
5. Configuration endpoint
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from backend.api.main import app
from backend.system.startup import (
    reset_system_manager,
    ServiceStatus,
    ServiceHealth,
    SystemHealth,
)


# Reset singleton between tests
@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset system manager singleton between tests"""
    reset_system_manager()
    yield
    reset_system_manager()


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


# =============================================================================
# Health Endpoint Tests
# =============================================================================

class TestHealthEndpoint:
    """Test /system/health endpoint"""

    def test_health_not_started(self, client):
        """Test health when system not started"""
        response = client.get("/system/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "not_started"
        assert data["healthy"] is True
        assert data["services"] == {}

    def test_health_response_structure(self, client):
        """Test health response has required fields"""
        response = client.get("/system/health")
        data = response.json()

        required_fields = ["healthy", "status", "uptime_seconds", "services"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# =============================================================================
# Services Endpoint Tests
# =============================================================================

class TestServicesEndpoint:
    """Test /system/services endpoint"""

    def test_services_not_started(self, client):
        """Test services when system not started"""
        response = client.get("/system/services")
        assert response.status_code == 200

        data = response.json()
        assert data["services"] == []
        assert data["count"] == 0

    def test_services_after_start(self, client):
        """Test services after starting system"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()
                    mock_stream.stop = AsyncMock()

                    # Start system
                    response = client.post("/system/start", json={
                        "token_ids": ["token1"],
                        "enable_reactor": True,
                        "enable_collector": True,
                        "enable_stream": True,
                    })
                    assert response.status_code == 200

                    # Get services
                    response = client.get("/system/services")
                    assert response.status_code == 200

                    data = response.json()
                    assert data["count"] >= 1


# =============================================================================
# Start Endpoint Tests
# =============================================================================

class TestStartEndpoint:
    """Test /system/start endpoint"""

    def test_start_system(self, client):
        """Test starting the system"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()

                    response = client.post("/system/start", json={
                        "token_ids": ["token1"],
                    })
                    assert response.status_code == 200

                    data = response.json()
                    assert data["status"] == "started"
                    assert data["message"] == "System started successfully"

    def test_start_with_options(self, client):
        """Test starting with specific options"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            response = client.post("/system/start", json={
                "token_ids": ["token1"],
                "enable_reactor": True,
                "enable_collector": False,
                "enable_stream": False,
                "persist_to_db": False,
            })
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "started"

    def test_start_already_running(self, client):
        """Test starting when already running"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()

                    # Start first time
                    response = client.post("/system/start", json={"token_ids": []})
                    assert response.status_code == 200

                    # Start second time
                    response = client.post("/system/start", json={"token_ids": []})
                    assert response.status_code == 200

                    data = response.json()
                    assert data["status"] == "already_running"


# =============================================================================
# Stop Endpoint Tests
# =============================================================================

class TestStopEndpoint:
    """Test /system/stop endpoint"""

    def test_stop_not_started(self, client):
        """Test stopping when not started"""
        response = client.post("/system/stop")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "not_started"

    def test_stop_system(self, client):
        """Test stopping the system"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()
                    mock_stream.stop = AsyncMock()

                    # Start first
                    response = client.post("/system/start", json={"token_ids": []})
                    assert response.status_code == 200

                    # Stop
                    response = client.post("/system/stop")
                    assert response.status_code == 200

                    data = response.json()
                    assert data["status"] == "stopped"


# =============================================================================
# Restart Endpoint Tests
# =============================================================================

class TestRestartEndpoint:
    """Test /system/restart endpoint"""

    def test_restart_not_started(self, client):
        """Test restarting when not started"""
        response = client.post("/system/restart")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "not_started"

    def test_restart_system(self, client):
        """Test restarting the system"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()
                    mock_stream.stop = AsyncMock()

                    # Start first
                    response = client.post("/system/start", json={"token_ids": ["token1"]})
                    assert response.status_code == 200

                    # Restart
                    response = client.post("/system/restart")
                    assert response.status_code == 200

                    data = response.json()
                    assert data["status"] == "restarted"


# =============================================================================
# Service Restart Endpoint Tests
# =============================================================================

class TestServiceRestartEndpoint:
    """Test /system/restart/{service} endpoint"""

    def test_restart_service_not_started(self, client):
        """Test restarting service when system not started"""
        response = client.post("/system/restart/reactor")
        assert response.status_code == 400
        assert "not started" in response.json()["detail"].lower()

    def test_restart_invalid_service(self, client):
        """Test restarting invalid service"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            # Start system first
            response = client.post("/system/start", json={
                "enable_reactor": True,
                "enable_collector": False,
                "enable_stream": False,
            })
            assert response.status_code == 200

            # Try to restart invalid service
            response = client.post("/system/restart/invalid_service")
            assert response.status_code == 400
            assert "invalid service" in response.json()["detail"].lower()

    def test_restart_reactor_service(self, client):
        """Test restarting reactor service"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            # Start system first
            response = client.post("/system/start", json={
                "enable_reactor": True,
                "enable_collector": False,
                "enable_stream": False,
            })
            assert response.status_code == 200

            # Restart reactor
            response = client.post("/system/restart/reactor")
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "restarted"
            assert data["service"] == "reactor"


# =============================================================================
# Config Endpoint Tests
# =============================================================================

class TestConfigEndpoint:
    """Test /system/config endpoint"""

    def test_config_not_started(self, client):
        """Test config when system not started"""
        response = client.get("/system/config")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "not_started"
        assert data["config"] is None

    def test_config_after_start(self, client):
        """Test config after starting system"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            # Start with specific config
            response = client.post("/system/start", json={
                "token_ids": ["token1", "token2"],
                "enable_reactor": True,
                "enable_collector": False,
                "enable_stream": False,
                "persist_to_db": False,
            })
            assert response.status_code == 200

            # Get config
            response = client.get("/system/config")
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "running"
            assert data["config"]["token_ids"] == ["token1", "token2"]
            assert data["config"]["enable_reactor"] is True
            assert data["config"]["enable_collector"] is False


# =============================================================================
# Integration Tests
# =============================================================================

class TestSystemIntegration:
    """Integration tests for system API"""

    def test_full_lifecycle(self, client):
        """Test complete lifecycle: start -> check -> restart -> stop"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()
                    mock_stream.stop = AsyncMock()

                    # 1. Check initial health
                    response = client.get("/system/health")
                    assert response.status_code == 200
                    assert response.json()["status"] == "not_started"

                    # 2. Start system
                    response = client.post("/system/start", json={"token_ids": ["test"]})
                    assert response.status_code == 200
                    assert response.json()["status"] == "started"

                    # 3. Check health after start
                    response = client.get("/system/health")
                    assert response.status_code == 200

                    # 4. Get services
                    response = client.get("/system/services")
                    assert response.status_code == 200

                    # 5. Get config
                    response = client.get("/system/config")
                    assert response.status_code == 200

                    # 6. Restart system
                    response = client.post("/system/restart")
                    assert response.status_code == 200

                    # 7. Stop system
                    response = client.post("/system/stop")
                    assert response.status_code == 200
                    assert response.json()["status"] == "stopped"
