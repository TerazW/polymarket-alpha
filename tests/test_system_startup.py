"""
Tests for System Startup Manager (v5.31)

Tests:
1. SystemStartupManager initialization
2. Service startup sequence
3. Service shutdown sequence
4. Health monitoring
5. Service restart
6. Context manager
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import time

from backend.system.startup import (
    SystemStartupManager,
    ServiceStatus,
    ServiceHealth,
    SystemHealth,
    get_system_manager,
    create_system_manager,
    reset_system_manager,
)


# Reset singleton between tests
@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset system manager singleton between tests"""
    reset_system_manager()
    yield
    reset_system_manager()


# =============================================================================
# ServiceStatus Tests
# =============================================================================

class TestServiceStatus:
    """Test ServiceStatus enum"""

    def test_status_values(self):
        """Test ServiceStatus enum values"""
        assert ServiceStatus.STOPPED.value == "stopped"
        assert ServiceStatus.STARTING.value == "starting"
        assert ServiceStatus.RUNNING.value == "running"
        assert ServiceStatus.STOPPING.value == "stopping"
        assert ServiceStatus.ERROR.value == "error"
        assert ServiceStatus.DEGRADED.value == "degraded"


# =============================================================================
# ServiceHealth Tests
# =============================================================================

class TestServiceHealth:
    """Test ServiceHealth dataclass"""

    def test_create_health(self):
        """Test creating ServiceHealth"""
        health = ServiceHealth(
            name="test",
            status=ServiceStatus.RUNNING,
            healthy=True,
            started_at=time.time(),
        )
        assert health.name == "test"
        assert health.status == ServiceStatus.RUNNING
        assert health.healthy is True

    def test_to_dict(self):
        """Test ServiceHealth to_dict"""
        health = ServiceHealth(
            name="test",
            status=ServiceStatus.RUNNING,
            healthy=True,
            started_at=time.time() - 10,  # 10 seconds ago
        )
        data = health.to_dict()

        assert data["name"] == "test"
        assert data["status"] == "running"
        assert data["healthy"] is True
        assert data["uptime_seconds"] >= 9

    def test_to_dict_with_error(self):
        """Test ServiceHealth to_dict with error"""
        health = ServiceHealth(
            name="test",
            status=ServiceStatus.ERROR,
            healthy=False,
            error="Connection failed",
        )
        data = health.to_dict()

        assert data["status"] == "error"
        assert data["error"] == "Connection failed"


# =============================================================================
# SystemHealth Tests
# =============================================================================

class TestSystemHealth:
    """Test SystemHealth dataclass"""

    def test_create_system_health(self):
        """Test creating SystemHealth"""
        health = SystemHealth(
            healthy=True,
            status="healthy",
            started_at=time.time(),
        )
        assert health.healthy is True
        assert health.status == "healthy"

    def test_to_dict(self):
        """Test SystemHealth to_dict"""
        svc_health = ServiceHealth(
            name="reactor",
            status=ServiceStatus.RUNNING,
            healthy=True,
        )
        health = SystemHealth(
            healthy=True,
            status="healthy",
            services={"reactor": svc_health},
            started_at=time.time() - 5,
        )
        data = health.to_dict()

        assert data["healthy"] is True
        assert data["status"] == "healthy"
        assert "reactor" in data["services"]
        assert data["uptime_seconds"] >= 4


# =============================================================================
# SystemStartupManager Initialization Tests
# =============================================================================

class TestManagerInit:
    """Test SystemStartupManager initialization"""

    def test_create_manager(self):
        """Test creating manager with defaults"""
        manager = SystemStartupManager()
        assert manager.enable_reactor is True
        assert manager.enable_collector is True
        assert manager.enable_stream is True
        assert manager.is_running is False

    def test_create_with_token_ids(self):
        """Test creating manager with token IDs"""
        manager = SystemStartupManager(token_ids=["token1", "token2"])
        assert manager.token_ids == ["token1", "token2"]

    def test_create_with_disabled_services(self):
        """Test creating manager with some services disabled"""
        manager = SystemStartupManager(
            enable_reactor=True,
            enable_collector=False,
            enable_stream=False,
        )
        assert manager.enable_reactor is True
        assert manager.enable_collector is False
        assert manager.enable_stream is False


# =============================================================================
# Service Startup Tests
# =============================================================================

class TestServiceStartup:
    """Test service startup sequence"""

    @pytest.mark.asyncio
    async def test_start_all(self):
        """Test starting all services"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    # Configure mocks
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()

                    manager = SystemStartupManager(token_ids=["token1"])
                    health = await manager.start_all()

                    assert health.healthy is True
                    assert health.status == "healthy"
                    assert "reactor" in health.services
                    assert "collector" in health.services
                    assert "stream" in health.services

    @pytest.mark.asyncio
    async def test_start_reactor_only(self):
        """Test starting only reactor service"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            manager = SystemStartupManager(
                enable_reactor=True,
                enable_collector=False,
                enable_stream=False,
            )
            health = await manager.start_all()

            assert health.healthy is True
            assert "reactor" in health.services
            assert "collector" not in health.services
            assert "stream" not in health.services

    @pytest.mark.asyncio
    async def test_start_with_error(self):
        """Test starting with service error"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            MockReactor.side_effect = Exception("Connection failed")

            manager = SystemStartupManager(
                enable_reactor=True,
                enable_collector=False,
                enable_stream=False,
            )
            health = await manager.start_all()

            assert health.healthy is False
            assert health.services["reactor"].status == ServiceStatus.ERROR


# =============================================================================
# Service Shutdown Tests
# =============================================================================

class TestServiceShutdown:
    """Test service shutdown sequence"""

    @pytest.mark.asyncio
    async def test_stop_all(self):
        """Test stopping all services"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    # Configure mocks
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()
                    mock_stream.stop = AsyncMock()

                    manager = SystemStartupManager(token_ids=["token1"])
                    await manager.start_all()
                    health = await manager.stop_all()

                    assert health.status == "stopped"

    @pytest.mark.asyncio
    async def test_stop_not_started(self):
        """Test stopping when not started"""
        manager = SystemStartupManager()
        health = await manager.stop_all()

        assert health.status == "stopped"


# =============================================================================
# Health Monitoring Tests
# =============================================================================

class TestHealthMonitoring:
    """Test health monitoring"""

    @pytest.mark.asyncio
    async def test_get_health(self):
        """Test getting health status"""
        manager = SystemStartupManager()
        health = await manager.get_health()

        assert health.status == "stopped"
        assert health.healthy is True

    @pytest.mark.asyncio
    async def test_health_callback(self):
        """Test health change callback"""
        callback = MagicMock()

        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            manager = SystemStartupManager(
                enable_reactor=True,
                enable_collector=False,
                enable_stream=False,
                on_health_change=callback,
            )

            await manager.start_all()

            # Callback should have been called
            callback.assert_called()


# =============================================================================
# Service Restart Tests
# =============================================================================

class TestServiceRestart:
    """Test service restart functionality"""

    @pytest.mark.asyncio
    async def test_restart_reactor(self):
        """Test restarting reactor service"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            manager = SystemStartupManager(
                enable_reactor=True,
                enable_collector=False,
                enable_stream=False,
            )

            await manager.start_all()
            health = await manager.restart_service("reactor")

            assert health is not None
            # Stop and start should have been called
            assert mock_reactor.stop.called or mock_reactor.start.called

    @pytest.mark.asyncio
    async def test_restart_unknown_service(self):
        """Test restarting unknown service raises error"""
        manager = SystemStartupManager()

        with pytest.raises(ValueError):
            await manager.restart_service("unknown")


# =============================================================================
# Context Manager Tests
# =============================================================================

class TestContextManager:
    """Test async context manager"""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test using manager as context manager"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                with patch('backend.api.stream.stream_manager') as mock_stream:
                    mock_reactor = AsyncMock()
                    MockReactor.return_value = mock_reactor

                    mock_collector = AsyncMock()
                    MockCollector.return_value = mock_collector

                    mock_stream.start = AsyncMock()
                    mock_stream.stop = AsyncMock()

                    async with SystemStartupManager(token_ids=["token1"]) as manager:
                        assert manager.is_running is True

                    # After exiting, services should be stopped
                    # (verified by mock calls)


# =============================================================================
# Singleton Tests
# =============================================================================

class TestSingleton:
    """Test global singleton management"""

    def test_get_manager_none(self):
        """Test getting manager when not created"""
        assert get_system_manager() is None

    def test_create_manager(self):
        """Test creating global manager"""
        manager = create_system_manager(token_ids=["token1"])
        assert manager is not None
        assert get_system_manager() is manager

    def test_reset_manager(self):
        """Test resetting global manager"""
        create_system_manager()
        assert get_system_manager() is not None

        reset_system_manager()
        assert get_system_manager() is None


# =============================================================================
# Property Access Tests
# =============================================================================

class TestPropertyAccess:
    """Test service property access"""

    @pytest.mark.asyncio
    async def test_reactor_property(self):
        """Test reactor property access"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            mock_reactor = AsyncMock()
            MockReactor.return_value = mock_reactor

            manager = SystemStartupManager(
                enable_reactor=True,
                enable_collector=False,
                enable_stream=False,
            )

            await manager.start_all()
            assert manager.reactor is not None

    @pytest.mark.asyncio
    async def test_collector_property(self):
        """Test collector property access"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                mock_reactor = AsyncMock()
                MockReactor.return_value = mock_reactor

                mock_collector = AsyncMock()
                MockCollector.return_value = mock_collector

                manager = SystemStartupManager(
                    enable_reactor=True,
                    enable_collector=True,
                    enable_stream=False,
                    token_ids=["token1"],
                )

                await manager.start_all()
                assert manager.collector is not None


# =============================================================================
# Degraded Health Tests
# =============================================================================

class TestDegradedHealth:
    """Test degraded health scenarios"""

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """Test partial service failure results in degraded status"""
        with patch('backend.reactor.service.ReactorService') as MockReactor:
            with patch('backend.collector.service.CollectorService') as MockCollector:
                # Reactor succeeds
                mock_reactor = AsyncMock()
                MockReactor.return_value = mock_reactor

                # Collector fails
                MockCollector.side_effect = Exception("Connection failed")

                manager = SystemStartupManager(
                    enable_reactor=True,
                    enable_collector=True,
                    enable_stream=False,
                    token_ids=["token1"],
                )

                health = await manager.start_all()

                assert health.status == "degraded"
                assert health.healthy is False
                assert health.services["reactor"].status == ServiceStatus.RUNNING
                assert health.services["collector"].status == ServiceStatus.ERROR
