"""
Tests for Cost Alerting Module (v5.36)
"""

import pytest
import time
from backend.monitoring.cost_alerts import (
    CostMonitor,
    CostMonitorConfig,
    CostMetricsCollector,
    CostThreshold,
    CostCategory,
    CostAlertSeverity,
    CostMetric,
    CostAlert,
    DEFAULT_THRESHOLDS,
    get_cost_collector,
    track_api_request,
    track_tile_request,
    track_reactor_event,
    set_ws_connections,
    set_tracked_markets,
)


class TestCostThreshold:
    """Test CostThreshold configuration"""

    def test_threshold_creation(self):
        threshold = CostThreshold(
            name="test_metric",
            category=CostCategory.BANDWIDTH,
            unit="GB",
            period="daily",
            warning_threshold=50.0,
            critical_threshold=100.0,
        )
        assert threshold.name == "test_metric"
        assert threshold.warning_threshold == 50.0
        assert threshold.critical_threshold == 100.0

    def test_threshold_with_soft_limit(self):
        threshold = CostThreshold(
            name="test_metric",
            category=CostCategory.STORAGE,
            unit="GB",
            period="current",
            warning_threshold=50.0,
            critical_threshold=100.0,
            soft_limit=150.0,
        )
        assert threshold.soft_limit == 150.0

    def test_default_thresholds_exist(self):
        """Verify all expected default thresholds are defined"""
        expected = [
            "tile_egress_daily",
            "tile_egress_monthly",
            "db_size_total",
            "db_growth_daily",
            "api_requests_daily",
            "ws_connections_concurrent",
            "tracked_markets",
        ]
        for name in expected:
            assert name in DEFAULT_THRESHOLDS, f"Missing threshold: {name}"


class TestCostMetricsCollector:
    """Test CostMetricsCollector"""

    def test_increment_counter(self):
        collector = CostMetricsCollector()
        collector.increment("test_counter")
        collector.increment("test_counter")
        collector.increment("test_counter", 5.0)

        assert collector.get_counter("test_counter") == 7.0

    def test_set_gauge(self):
        collector = CostMetricsCollector()
        collector.set_gauge("test_gauge", 100.0)
        assert collector.get_counter("test_gauge") == 100.0

        collector.set_gauge("test_gauge", 50.0)
        assert collector.get_counter("test_gauge") == 50.0

    def test_reset_counter(self):
        collector = CostMetricsCollector()
        collector.increment("test_counter", 10.0)

        value = collector.reset_counter("test_counter")
        assert value == 10.0
        assert collector.get_counter("test_counter") == 0

    def test_collect_all_returns_metrics(self):
        collector = CostMetricsCollector()
        collector.increment("api_requests_daily", 100)
        collector.set_gauge("ws_connections_concurrent", 50)

        metrics = collector.collect_all()

        assert "api_requests_daily" in metrics
        assert metrics["api_requests_daily"].current_value == 100
        assert "ws_connections_concurrent" in metrics
        assert metrics["ws_connections_concurrent"].current_value == 50


class TestCostMonitor:
    """Test CostMonitor"""

    def test_monitor_creation(self):
        monitor = CostMonitor()
        assert monitor.config is not None
        assert monitor.collector is not None

    def test_monitor_with_custom_config(self):
        config = CostMonitorConfig(
            check_interval_seconds=60,
            alert_cooldown_seconds=1800,
        )
        monitor = CostMonitor(config=config)
        assert monitor.config.check_interval_seconds == 60
        assert monitor.config.alert_cooldown_seconds == 1800

    def test_check_thresholds_no_alerts(self):
        """No alerts when under thresholds"""
        collector = CostMetricsCollector()
        collector.increment("api_requests_daily", 100)  # Well under 100K threshold

        monitor = CostMonitor(collector=collector)
        alerts = monitor.check_thresholds()

        # Should not have alerts for api_requests_daily
        api_alerts = [a for a in alerts if a.metric_name == "api_requests_daily"]
        assert len(api_alerts) == 0

    def test_check_thresholds_warning(self):
        """Warning alert when at warning threshold"""
        config = CostMonitorConfig(
            thresholds={
                "test_metric": CostThreshold(
                    name="test_metric",
                    category=CostCategory.COMPUTE,
                    unit="count",
                    period="daily",
                    warning_threshold=100,
                    critical_threshold=200,
                ),
            }
        )
        collector = CostMetricsCollector()
        collector.increment("test_metric", 120)  # Above warning (100), below critical (200)

        monitor = CostMonitor(config=config, collector=collector)
        alerts = monitor.check_thresholds()

        # Should have warning
        test_alerts = [a for a in alerts if a.metric_name == "test_metric"]
        assert len(test_alerts) == 1
        assert test_alerts[0].severity == CostAlertSeverity.WARNING

    def test_check_thresholds_critical(self):
        """Critical alert when at 100%+ of critical threshold"""
        config = CostMonitorConfig(
            thresholds={
                "test_metric": CostThreshold(
                    name="test_metric",
                    category=CostCategory.BANDWIDTH,
                    unit="GB",
                    period="daily",
                    warning_threshold=50,
                    critical_threshold=100,
                ),
            }
        )
        collector = CostMetricsCollector()
        collector.increment("test_metric", 150)  # 150% of critical

        monitor = CostMonitor(config=config, collector=collector)
        alerts = monitor.check_thresholds()

        test_alerts = [a for a in alerts if a.metric_name == "test_metric"]
        assert len(test_alerts) == 1
        assert test_alerts[0].severity == CostAlertSeverity.CRITICAL

    def test_alert_cooldown(self):
        """Alerts should not repeat within cooldown period"""
        config = CostMonitorConfig(
            alert_cooldown_seconds=3600,
            thresholds={
                "test_metric": CostThreshold(
                    name="test_metric",
                    category=CostCategory.COMPUTE,
                    unit="count",
                    period="daily",
                    warning_threshold=100,
                    critical_threshold=200,
                ),
            }
        )
        collector = CostMetricsCollector()
        collector.increment("test_metric", 150)

        monitor = CostMonitor(config=config, collector=collector)

        # First check - should alert
        alerts1 = monitor.check_thresholds()
        assert len(alerts1) == 1

        # Second check immediately - should not alert (cooldown)
        alerts2 = monitor.check_thresholds()
        assert len(alerts2) == 0

    def test_alert_callback(self):
        """Alert callback is invoked"""
        received_alerts = []

        def callback(alert: CostAlert):
            received_alerts.append(alert)

        config = CostMonitorConfig(
            thresholds={
                "test_metric": CostThreshold(
                    name="test_metric",
                    category=CostCategory.STORAGE,
                    unit="GB",
                    period="current",
                    warning_threshold=10,
                    critical_threshold=20,
                ),
            }
        )
        collector = CostMetricsCollector()
        collector.set_gauge("test_metric", 15)

        monitor = CostMonitor(config=config, collector=collector, alert_callback=callback)
        monitor.check_thresholds()

        assert len(received_alerts) == 1
        assert received_alerts[0].metric_name == "test_metric"

    def test_auto_degradation(self):
        """Auto-degradation when soft limit exceeded"""
        config = CostMonitorConfig(
            enable_auto_degradation=True,
            thresholds={
                "test_metric": CostThreshold(
                    name="test_metric",
                    category=CostCategory.BANDWIDTH,
                    unit="GB",
                    period="daily",
                    warning_threshold=50,
                    critical_threshold=100,
                    soft_limit=150,
                ),
            }
        )
        collector = CostMetricsCollector()
        collector.increment("test_metric", 160)  # Above soft limit

        monitor = CostMonitor(config=config, collector=collector)
        monitor.check_thresholds()

        assert monitor.is_degraded("test_metric")

    def test_clear_degraded(self):
        """Can clear degraded status"""
        monitor = CostMonitor()
        monitor._degraded_metrics.add("test_metric")

        assert monitor.is_degraded("test_metric")

        monitor.clear_degraded("test_metric")
        assert not monitor.is_degraded("test_metric")

    def test_get_cost_report(self):
        """Cost report generation"""
        collector = CostMetricsCollector()
        collector.increment("api_requests_daily", 1000)
        collector.set_gauge("ws_connections_concurrent", 100)

        monitor = CostMonitor(collector=collector)
        report = monitor.get_cost_report()

        assert "generated_at" in report
        assert "categories" in report
        assert "alerts" in report
        assert "degraded_metrics" in report


class TestConvenienceFunctions:
    """Test convenience tracking functions"""

    def test_track_api_request(self):
        collector = get_cost_collector()
        initial = collector.get_counter("api_requests_daily")

        track_api_request()
        assert collector.get_counter("api_requests_daily") == initial + 1

    def test_track_api_request_with_bytes(self):
        collector = get_cost_collector()
        initial = collector.get_counter("api_egress_daily")

        track_api_request(bytes_out=1024 * 1024 * 1024)  # 1 GB
        assert collector.get_counter("api_egress_daily") >= initial + 1.0

    def test_track_tile_request(self):
        collector = get_cost_collector()
        initial_gen = collector.get_counter("tile_generations_daily")
        initial_egress = collector.get_counter("tile_egress_daily")

        track_tile_request(bytes_out=10 * 1024 * 1024)  # 10 MB

        assert collector.get_counter("tile_generations_daily") == initial_gen + 1
        assert collector.get_counter("tile_egress_daily") > initial_egress

    def test_track_reactor_event(self):
        collector = get_cost_collector()
        initial = collector.get_counter("reactor_events_daily")

        track_reactor_event()
        assert collector.get_counter("reactor_events_daily") == initial + 1

    def test_set_ws_connections(self):
        set_ws_connections(250)
        collector = get_cost_collector()
        assert collector.get_counter("ws_connections_concurrent") == 250

    def test_set_tracked_markets(self):
        set_tracked_markets(150)
        collector = get_cost_collector()
        assert collector.get_counter("tracked_markets") == 150


class TestCostCategories:
    """Test cost categories are properly defined"""

    def test_all_categories(self):
        assert CostCategory.BANDWIDTH.value == "BANDWIDTH"
        assert CostCategory.STORAGE.value == "STORAGE"
        assert CostCategory.COMPUTE.value == "COMPUTE"
        assert CostCategory.EXTERNAL.value == "EXTERNAL"

    def test_alert_severities(self):
        assert CostAlertSeverity.INFO.value == "INFO"
        assert CostAlertSeverity.WARNING.value == "WARNING"
        assert CostAlertSeverity.CRITICAL.value == "CRITICAL"


class TestChatGPTRedLines:
    """Test ChatGPT-recommended red line thresholds are configured"""

    def test_tile_monthly_egress_threshold(self):
        """5TB/month tile egress red line"""
        threshold = DEFAULT_THRESHOLDS.get("tile_egress_monthly")
        assert threshold is not None
        assert threshold.critical_threshold == 5.0  # 5 TB
        assert threshold.unit == "TB"

    def test_ws_connections_threshold(self):
        """1000 concurrent WS connections red line"""
        threshold = DEFAULT_THRESHOLDS.get("ws_connections_concurrent")
        assert threshold is not None
        assert threshold.critical_threshold == 1000

    def test_tracked_markets_threshold(self):
        """200+ markets = Stage 1 trigger"""
        threshold = DEFAULT_THRESHOLDS.get("tracked_markets")
        assert threshold is not None
        assert threshold.warning_threshold == 200


class TestIntegration:
    """Integration tests for cost monitoring flow"""

    def test_full_monitoring_cycle(self):
        """Test complete monitoring cycle"""
        alerts_received = []

        def alert_handler(alert):
            alerts_received.append(alert)

        config = CostMonitorConfig(
            check_interval_seconds=1,  # Fast for testing
            alert_cooldown_seconds=0,  # No cooldown for testing
            thresholds={
                "api_requests_daily": CostThreshold(
                    name="api_requests_daily",
                    category=CostCategory.COMPUTE,
                    unit="requests",
                    period="daily",
                    warning_threshold=100,
                    critical_threshold=200,
                ),
            }
        )

        collector = CostMetricsCollector()
        monitor = CostMonitor(
            config=config,
            collector=collector,
            alert_callback=alert_handler
        )

        # Simulate traffic
        for _ in range(150):
            collector.increment("api_requests_daily")

        # Check thresholds
        alerts = monitor.check_thresholds()

        # Should have warning (150 > 100 warning threshold)
        assert len(alerts) == 1
        assert alerts[0].severity == CostAlertSeverity.WARNING
        assert len(alerts_received) == 1

        # Generate report
        report = monitor.get_cost_report()
        assert report["categories"]["COMPUTE"]["api_requests_daily"]["current"] == 150
