"""
Tests for Monitoring Module

Tests:
- Prometheus metrics registration and export
- Health check functionality
- Metric types (Counter, Gauge, Histogram)
"""

import pytest
import time
import asyncio
from unittest.mock import Mock, patch, MagicMock


# =============================================================================
# Metrics Tests
# =============================================================================

class TestCounter:
    """Test Counter metric type"""

    def test_counter_increment(self):
        """Test basic counter increment"""
        from backend.monitoring.metrics import Counter

        counter = Counter("test_counter", "Test counter")
        assert counter.get() == 0

        counter.inc()
        assert counter.get() == 1

        counter.inc(5)
        assert counter.get() == 6

    def test_counter_with_labels(self):
        """Test counter with labels"""
        from backend.monitoring.metrics import Counter

        counter = Counter("labeled_counter", "Counter with labels")

        counter.inc(labels={"method": "GET"})
        counter.inc(labels={"method": "POST"})
        counter.inc(2, labels={"method": "GET"})

        assert counter.get(labels={"method": "GET"}) == 3
        assert counter.get(labels={"method": "POST"}) == 1

    def test_counter_collect(self):
        """Test counter collection"""
        from backend.monitoring.metrics import Counter

        counter = Counter("collect_counter", "")
        counter.inc(labels={"status": "200"})
        counter.inc(2, labels={"status": "500"})

        collected = counter.collect()
        assert len(collected) == 2


class TestGauge:
    """Test Gauge metric type"""

    def test_gauge_set(self):
        """Test gauge set"""
        from backend.monitoring.metrics import Gauge

        gauge = Gauge("test_gauge", "Test gauge")

        gauge.set(10)
        assert gauge.get() == 10

        gauge.set(5)
        assert gauge.get() == 5

    def test_gauge_inc_dec(self):
        """Test gauge increment/decrement"""
        from backend.monitoring.metrics import Gauge

        gauge = Gauge("inc_dec_gauge", "")
        gauge.set(10)

        gauge.inc(3)
        assert gauge.get() == 13

        gauge.dec(5)
        assert gauge.get() == 8

    def test_gauge_with_labels(self):
        """Test gauge with labels"""
        from backend.monitoring.metrics import Gauge

        gauge = Gauge("labeled_gauge", "")

        gauge.set(10, labels={"host": "server1"})
        gauge.set(20, labels={"host": "server2"})

        assert gauge.get(labels={"host": "server1"}) == 10
        assert gauge.get(labels={"host": "server2"}) == 20


class TestHistogram:
    """Test Histogram metric type"""

    def test_histogram_observe(self):
        """Test histogram observation"""
        from backend.monitoring.metrics import Histogram

        hist = Histogram("test_histogram", "", buckets=(0.1, 0.5, 1.0, float('inf')))

        hist.observe(0.05)
        hist.observe(0.3)
        hist.observe(0.8)
        hist.observe(2.0)

        collected = hist.collect()
        data = collected[""]

        assert data['count'] == 4
        assert data['sum'] == pytest.approx(0.05 + 0.3 + 0.8 + 2.0)

        # Check bucket counts (cumulative)
        assert data['buckets'][0.1] == 1   # 0.05
        assert data['buckets'][0.5] == 2   # 0.05, 0.3
        assert data['buckets'][1.0] == 3   # 0.05, 0.3, 0.8
        assert data['buckets'][float('inf')] == 4  # all

    def test_histogram_with_labels(self):
        """Test histogram with labels"""
        from backend.monitoring.metrics import Histogram

        hist = Histogram("labeled_histogram", "", buckets=(0.1, 1.0, float('inf')))

        hist.observe(0.05, labels={"endpoint": "/api"})
        hist.observe(0.5, labels={"endpoint": "/health"})

        collected = hist.collect()
        assert 'endpoint="/api"' in collected or len(collected) == 2


class TestMetricsRegistry:
    """Test MetricsRegistry"""

    def test_registry_counter(self):
        """Test counter registration"""
        from backend.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()
        counter = registry.counter("test_requests", "Total requests")

        counter.inc()
        counter.inc()

        # Get same counter by name
        same_counter = registry.counter("test_requests", "")
        assert same_counter.get() == 2

    def test_registry_gauge(self):
        """Test gauge registration"""
        from backend.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()
        gauge = registry.gauge("active_users", "Active users")

        gauge.set(100)
        assert registry.get_metric("active_users").get() == 100

    def test_registry_histogram(self):
        """Test histogram registration"""
        from backend.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()
        hist = registry.histogram("response_time", "Response time")

        hist.observe(0.1)
        hist.observe(0.2)

        assert registry.get_metric("response_time") is not None

    def test_export_prometheus_format(self):
        """Test Prometheus format export"""
        from backend.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        # Add some metrics
        counter = registry.counter("http_requests_total", "Total HTTP requests")
        counter.inc(labels={"method": "GET", "status": "200"})

        gauge = registry.gauge("active_connections", "Active connections")
        gauge.set(42)

        output = registry.export_prometheus()

        # Check format
        assert "# HELP http_requests_total" in output
        assert "# TYPE http_requests_total counter" in output
        assert 'http_requests_total{method="GET",status="200"}' in output

        assert "# HELP active_connections" in output
        assert "# TYPE active_connections gauge" in output
        assert "active_connections 42" in output


class TestGetMetricsRegistry:
    """Test global registry singleton"""

    def test_singleton(self):
        """Test that get_metrics_registry returns same instance"""
        from backend.monitoring.metrics import get_metrics_registry

        r1 = get_metrics_registry()
        r2 = get_metrics_registry()

        assert r1 is r2


# =============================================================================
# Health Check Tests
# =============================================================================

class TestHealthStatus:
    """Test HealthStatus enum"""

    def test_health_statuses(self):
        """Test all health status values"""
        from backend.monitoring.health import HealthStatus

        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"


class TestCheckResult:
    """Test CheckResult dataclass"""

    def test_check_result_to_dict(self):
        """Test CheckResult serialization"""
        from backend.monitoring.health import CheckResult, HealthStatus
        from datetime import datetime

        result = CheckResult(
            name="database",
            status=HealthStatus.HEALTHY,
            message="Connection successful",
            latency_ms=15.5,
            details={"host": "localhost"},
        )

        d = result.to_dict()

        assert d["name"] == "database"
        assert d["status"] == "healthy"
        assert d["message"] == "Connection successful"
        assert d["latency_ms"] == 15.5
        assert d["details"]["host"] == "localhost"
        assert "checked_at" in d


class TestHealthReport:
    """Test HealthReport dataclass"""

    def test_health_report_to_dict(self):
        """Test HealthReport serialization"""
        from backend.monitoring.health import HealthReport, CheckResult, HealthStatus

        checks = [
            CheckResult("db", HealthStatus.HEALTHY, "OK"),
            CheckResult("cache", HealthStatus.DEGRADED, "Slow"),
        ]

        report = HealthReport(
            status=HealthStatus.DEGRADED,
            checks=checks,
            version="1.0.0",
            uptime_seconds=3600.5,
        )

        d = report.to_dict()

        assert d["status"] == "degraded"
        assert d["version"] == "1.0.0"
        assert d["uptime_seconds"] == 3600.5
        assert len(d["checks"]) == 2
        assert d["summary"]["total"] == 2
        assert d["summary"]["healthy"] == 1
        assert d["summary"]["degraded"] == 1


class TestHealthChecker:
    """Test HealthChecker class"""

    @pytest.fixture
    def mock_db_config(self):
        return {
            'host': '127.0.0.1',
            'port': 5433,
            'database': 'test_db',
            'user': 'postgres',
            'password': 'postgres',
        }

    @pytest.fixture
    def mock_psycopg2(self):
        """Create mock psycopg2 module"""
        mock_module = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
        mock_module.connect.return_value = mock_conn
        return mock_module, mock_conn, mock_cursor

    @pytest.mark.asyncio
    async def test_database_check_success(self, mock_db_config, mock_psycopg2):
        """Test successful database check"""
        import sys

        mock_module, mock_conn, mock_cursor = mock_psycopg2

        with patch.dict(sys.modules, {'psycopg2': mock_module}):
            # Need to reload the health module to use mocked psycopg2
            import importlib
            import backend.monitoring.health as health_module
            importlib.reload(health_module)

            checker = health_module.HealthChecker(db_config=mock_db_config)
            result = await checker._check_database()

            # Use string comparison to avoid enum identity issues after reload
            assert result.status.value == "healthy"
            assert "successful" in result.message.lower()

    @pytest.mark.asyncio
    async def test_database_check_failure(self, mock_db_config):
        """Test failed database check"""
        import sys

        mock_module = MagicMock()
        mock_module.connect.side_effect = Exception("Connection refused")

        with patch.dict(sys.modules, {'psycopg2': mock_module}):
            import importlib
            import backend.monitoring.health as health_module
            importlib.reload(health_module)

            checker = health_module.HealthChecker(db_config=mock_db_config)
            result = await checker._check_database()

            # Use string comparison to avoid enum identity issues after reload
            assert result.status.value == "unhealthy"
            assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_websocket_manager_check(self, mock_db_config):
        """Test WebSocket manager check"""
        from backend.monitoring.health import HealthChecker, HealthStatus

        # Mock the stream_manager
        with patch('backend.api.stream.stream_manager') as mock_manager:
            mock_manager.connection_count = 5
            mock_manager._running = True

            checker = HealthChecker(db_config=mock_db_config)
            result = await checker._check_websocket_manager()

            assert result.status == HealthStatus.HEALTHY
            assert result.details['active_connections'] == 5

    @pytest.mark.asyncio
    async def test_run_all_checks(self, mock_db_config, mock_psycopg2):
        """Test running all health checks"""
        import sys
        from backend.monitoring.health import HealthChecker, HealthStatus

        mock_module, mock_conn, mock_cursor = mock_psycopg2

        with patch.dict(sys.modules, {'psycopg2': mock_module}):
            import importlib
            import backend.monitoring.health as health_module
            importlib.reload(health_module)

            # Mock stream manager
            with patch('backend.api.stream.stream_manager') as mock_manager:
                mock_manager.connection_count = 0
                mock_manager._running = True

                checker = health_module.HealthChecker(db_config=mock_db_config)
                report = await checker.run_all_checks(timeout=5.0)

                # Should have multiple checks
                assert len(report.checks) > 0
                assert report.version == "1.0.0"
                assert report.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_check_timeout(self, mock_db_config):
        """Test that checks timeout properly"""
        from backend.monitoring.health import HealthChecker, HealthStatus

        async def slow_check():
            await asyncio.sleep(10)
            return None

        checker = HealthChecker(db_config=mock_db_config)
        checker._checks = [slow_check]

        report = await checker.run_all_checks(timeout=0.1)

        assert report.status == HealthStatus.UNHEALTHY
        assert "timed out" in report.checks[0].message.lower()


class TestDeepHealthCheck:
    """Test deep_health_check factory function"""

    @pytest.mark.asyncio
    async def test_deep_health_check_function(self):
        """Test the factory function"""
        import sys

        db_config = {
            'host': '127.0.0.1',
            'port': 5433,
            'database': 'test_db',
            'user': 'postgres',
            'password': 'postgres',
        }

        mock_module = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0,)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
        mock_module.connect.return_value = mock_conn

        with patch.dict(sys.modules, {'psycopg2': mock_module}):
            import importlib
            import backend.monitoring.health as health_module
            importlib.reload(health_module)

            with patch('backend.api.stream.stream_manager') as mock_manager:
                mock_manager.connection_count = 0
                mock_manager._running = True

                report = await health_module.deep_health_check(db_config, version="2.0.0")

                assert report.version == "2.0.0"
                assert len(report.checks) > 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestMetricsMiddleware:
    """Test metrics middleware integration"""

    def test_middleware_registration(self):
        """Test that middleware can be applied to app"""
        from fastapi import FastAPI
        from backend.monitoring.metrics import metrics_middleware, get_metrics_registry

        app = FastAPI()
        metrics_middleware(app)

        # Check that metrics were registered
        registry = get_metrics_registry()
        assert registry.get_metric("http_requests_total") is not None
        assert registry.get_metric("http_request_duration_seconds") is not None


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_counter_negative_increment(self):
        """Counter should accept positive values only for semantics"""
        from backend.monitoring.metrics import Counter

        counter = Counter("test", "")
        counter.inc(-5)  # Technically allowed but not recommended

        # Counter can go negative if misused
        assert counter.get() == -5

    def test_histogram_negative_observation(self):
        """Histogram should handle negative values"""
        from backend.monitoring.metrics import Histogram

        hist = Histogram("test", "", buckets=(0.0, 1.0, float('inf')))
        hist.observe(-0.5)

        collected = hist.collect()
        assert collected[""]["count"] == 1

    def test_empty_labels(self):
        """Test metrics with empty labels dict"""
        from backend.monitoring.metrics import Counter

        counter = Counter("test", "")
        counter.inc(labels={})
        counter.inc(labels=None)

        # Both should increment the same (no-label) counter
        assert counter.get() == 2
        assert counter.get(labels={}) == 2

    def test_registry_duplicate_registration(self):
        """Test registering duplicate metric names"""
        from backend.monitoring.metrics import MetricsRegistry, Counter

        registry = MetricsRegistry()
        registry.register(Counter("duplicate", "First"))

        with pytest.raises(ValueError):
            registry.register(Counter("duplicate", "Second"))
