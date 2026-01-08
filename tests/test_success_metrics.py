"""
Tests for Success Metrics Module (v5.17)

Ensures:
1. Metric targets are properly defined
2. Percentile calculations work correctly
3. Metric status evaluation is accurate
4. Report generation works correctly
5. CI gate logic functions properly
"""

import pytest
import math
import time
from datetime import datetime

from backend.monitoring import (
    SuccessMetricsTracker,
    SuccessReport,
    MetricResult,
    MetricTarget,
    MetricStatus,
    METRIC_TARGETS,
    calculate_percentile,
    ci_gate_check,
    get_success_tracker,
)
from backend.monitoring.metrics import MetricsRegistry, Histogram


class TestMetricTargets:
    """Test metric target definitions"""

    def test_all_targets_defined(self):
        """Should have all required metric targets"""
        required = [
            "latency_p50",
            "latency_p99",
            "audit_rate",
            "replay_match_rate",
            "alert_dedup_ratio",
            "data_freshness",
        ]
        for name in required:
            assert name in METRIC_TARGETS, f"Missing target: {name}"

    def test_target_properties(self):
        """Each target should have required properties"""
        for name, target in METRIC_TARGETS.items():
            assert target.name == name
            assert target.description
            assert target.target_value is not None
            assert target.warning_threshold is not None
            assert target.comparison in ("lt", "gt", "eq")
            assert target.unit is not None

    def test_latency_targets_sensible(self):
        """Latency targets should have sensible values"""
        p50 = METRIC_TARGETS["latency_p50"]
        p99 = METRIC_TARGETS["latency_p99"]

        # p50 should be less than p99
        assert p50.target_value < p99.target_value

        # Both should be "less than" comparison
        assert p50.comparison == "lt"
        assert p99.comparison == "lt"


class TestMetricTargetEvaluation:
    """Test metric target evaluation logic"""

    def test_lt_passing(self):
        """Value below target should pass for 'lt' comparison"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=100,
            warning_threshold=150,
            comparison="lt",
        )
        assert target.evaluate(50) == MetricStatus.PASSING

    def test_lt_warning(self):
        """Value between target and warning should warn for 'lt'"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=100,
            warning_threshold=150,
            comparison="lt",
        )
        assert target.evaluate(120) == MetricStatus.WARNING

    def test_lt_failing(self):
        """Value above warning should fail for 'lt'"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=100,
            warning_threshold=150,
            comparison="lt",
        )
        assert target.evaluate(200) == MetricStatus.FAILING

    def test_gt_passing(self):
        """Value above target should pass for 'gt' comparison"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=95,
            warning_threshold=90,
            comparison="gt",
        )
        assert target.evaluate(99) == MetricStatus.PASSING

    def test_gt_warning(self):
        """Value between target and warning should warn for 'gt'"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=95,
            warning_threshold=90,
            comparison="gt",
        )
        assert target.evaluate(92) == MetricStatus.WARNING

    def test_gt_failing(self):
        """Value below warning should fail for 'gt'"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=95,
            warning_threshold=90,
            comparison="gt",
        )
        assert target.evaluate(80) == MetricStatus.FAILING

    def test_nan_returns_unknown(self):
        """NaN value should return unknown status"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=100,
            warning_threshold=150,
            comparison="lt",
        )
        assert target.evaluate(float('nan')) == MetricStatus.UNKNOWN

    def test_none_returns_unknown(self):
        """None value should return unknown status"""
        target = MetricTarget(
            name="test",
            description="test",
            target_value=100,
            warning_threshold=150,
            comparison="lt",
        )
        assert target.evaluate(None) == MetricStatus.UNKNOWN


class TestPercentileCalculation:
    """Test percentile calculation from histogram data"""

    def test_p50_calculation(self):
        """Should calculate 50th percentile correctly"""
        # Simulate histogram with buckets [0.01, 0.05, 0.1, 0.5]
        # 100 observations: 20 at 0.01, 30 at 0.05, 30 at 0.1, 20 at 0.5
        hist_data = {
            'buckets': {
                0.01: 20,   # 20 observations <= 0.01
                0.05: 50,   # 50 observations <= 0.05
                0.1: 80,    # 80 observations <= 0.1
                0.5: 100,   # 100 observations <= 0.5
                float('inf'): 100,
            },
            'sum': 15.0,
            'count': 100,
        }

        p50 = calculate_percentile(hist_data, 50)

        # 50th percentile = 50th observation
        # Falls in the 0.05-0.1 bucket
        assert 0.01 < p50 < 0.1

    def test_p99_calculation(self):
        """Should calculate 99th percentile correctly"""
        hist_data = {
            'buckets': {
                0.01: 20,
                0.05: 50,
                0.1: 80,
                0.5: 99,
                1.0: 100,
                float('inf'): 100,
            },
            'sum': 20.0,
            'count': 100,
        }

        p99 = calculate_percentile(hist_data, 99)

        # 99th percentile = 99th observation, falls in 0.5-1.0 bucket
        assert 0.1 < p99 <= 1.0

    def test_empty_histogram(self):
        """Empty histogram should return NaN"""
        hist_data = {
            'buckets': {},
            'sum': 0,
            'count': 0,
        }

        p50 = calculate_percentile(hist_data, 50)
        assert math.isnan(p50)

    def test_none_histogram(self):
        """None histogram should return NaN"""
        p50 = calculate_percentile(None, 50)
        assert math.isnan(p50)


class TestMetricResult:
    """Test MetricResult dataclass"""

    def test_result_creation(self):
        """Should create result with all fields"""
        result = MetricResult(
            name="test_metric",
            value=0.05,
            status=MetricStatus.PASSING,
            target=0.1,
            unit="s",
            measured_at=1000000,
        )

        assert result.name == "test_metric"
        assert result.value == 0.05
        assert result.status == MetricStatus.PASSING

    def test_result_to_dict(self):
        """Should serialize to dict correctly"""
        result = MetricResult(
            name="test_metric",
            value=0.05,
            status=MetricStatus.PASSING,
            target=0.1,
            unit="s",
            measured_at=1000000000000,  # ms
            details={"sample": 100},
        )

        d = result.to_dict()

        assert d["name"] == "test_metric"
        assert d["value"] == 0.05
        assert d["status"] == "PASSING"
        assert d["target"] == 0.1
        assert d["unit"] == "s"
        assert "measured_at_iso" in d
        assert d["details"]["sample"] == 100


class TestSuccessReport:
    """Test SuccessReport dataclass"""

    @pytest.fixture
    def passing_report(self):
        """Report with all passing metrics"""
        return SuccessReport(
            metrics=[
                MetricResult(
                    name="metric1",
                    value=50,
                    status=MetricStatus.PASSING,
                    target=100,
                    unit="ms",
                    measured_at=int(time.time() * 1000),
                ),
                MetricResult(
                    name="metric2",
                    value=99.9,
                    status=MetricStatus.PASSING,
                    target=99.0,
                    unit="%",
                    measured_at=int(time.time() * 1000),
                ),
            ],
            overall_status=MetricStatus.PASSING,
            generated_at=int(time.time() * 1000),
            period_hours=1.0,
        )

    @pytest.fixture
    def mixed_report(self):
        """Report with mixed statuses"""
        return SuccessReport(
            metrics=[
                MetricResult(
                    name="metric1",
                    value=50,
                    status=MetricStatus.PASSING,
                    target=100,
                    unit="ms",
                    measured_at=int(time.time() * 1000),
                ),
                MetricResult(
                    name="metric2",
                    value=95,
                    status=MetricStatus.WARNING,
                    target=99.0,
                    unit="%",
                    measured_at=int(time.time() * 1000),
                ),
                MetricResult(
                    name="metric3",
                    value=80,
                    status=MetricStatus.FAILING,
                    target=99.0,
                    unit="%",
                    measured_at=int(time.time() * 1000),
                ),
            ],
            overall_status=MetricStatus.FAILING,
            generated_at=int(time.time() * 1000),
            period_hours=1.0,
        )

    def test_report_to_dict(self, passing_report):
        """Should serialize report to dict"""
        d = passing_report.to_dict()

        assert d["overall_status"] == "PASSING"
        assert d["summary"]["total"] == 2
        assert d["summary"]["passing"] == 2
        assert d["summary"]["failing"] == 0
        assert len(d["metrics"]) == 2

    def test_report_to_markdown(self, passing_report):
        """Should generate markdown report"""
        md = passing_report.to_markdown()

        assert "# Success Metrics Report" in md
        assert "metric1" in md
        assert "metric2" in md
        assert "PASSING" in md

    def test_mixed_report_to_dict(self, mixed_report):
        """Mixed report should have correct summary"""
        d = mixed_report.to_dict()

        assert d["overall_status"] == "FAILING"
        assert d["summary"]["passing"] == 1
        assert d["summary"]["warning"] == 1
        assert d["summary"]["failing"] == 1


class TestCIGate:
    """Test CI gate functionality"""

    def test_ci_gate_passing(self):
        """Passing report should pass gate"""
        report = SuccessReport(
            metrics=[
                MetricResult(
                    name="test",
                    value=50,
                    status=MetricStatus.PASSING,
                    target=100,
                    unit="ms",
                    measured_at=int(time.time() * 1000),
                )
            ],
            overall_status=MetricStatus.PASSING,
            generated_at=int(time.time() * 1000),
        )

        passed, message = ci_gate_check(report)

        assert passed is True
        assert "passed" in message.lower()

    def test_ci_gate_warning(self):
        """Warning report should pass gate with warning"""
        report = SuccessReport(
            metrics=[
                MetricResult(
                    name="test",
                    value=110,
                    status=MetricStatus.WARNING,
                    target=100,
                    unit="ms",
                    measured_at=int(time.time() * 1000),
                )
            ],
            overall_status=MetricStatus.WARNING,
            generated_at=int(time.time() * 1000),
        )

        passed, message = ci_gate_check(report)

        assert passed is True
        assert "warning" in message.lower()

    def test_ci_gate_failing(self):
        """Failing report should fail gate"""
        report = SuccessReport(
            metrics=[
                MetricResult(
                    name="latency",
                    value=500,
                    status=MetricStatus.FAILING,
                    target=100,
                    unit="ms",
                    measured_at=int(time.time() * 1000),
                )
            ],
            overall_status=MetricStatus.FAILING,
            generated_at=int(time.time() * 1000),
        )

        passed, message = ci_gate_check(report)

        assert passed is False
        assert "failed" in message.lower()
        assert "latency" in message


class TestSuccessMetricsTracker:
    """Test SuccessMetricsTracker class"""

    @pytest.fixture
    def tracker(self):
        """Fresh tracker with clean registry"""
        registry = MetricsRegistry()
        return SuccessMetricsTracker(registry=registry)

    def test_tracker_creation(self, tracker):
        """Should create tracker"""
        assert tracker is not None
        assert tracker.registry is not None

    def test_get_targets(self, tracker):
        """Should return all targets"""
        targets = tracker.get_targets()
        assert len(targets) >= 6

    def test_update_target(self, tracker):
        """Should update target values"""
        original = METRIC_TARGETS["latency_p50"].target_value

        tracker.update_target("latency_p50", target_value=0.100)

        assert METRIC_TARGETS["latency_p50"].target_value == 0.100

        # Restore
        METRIC_TARGETS["latency_p50"].target_value = original

    def test_update_nonexistent_target_raises(self, tracker):
        """Should raise for unknown metric"""
        with pytest.raises(ValueError):
            tracker.update_target("nonexistent_metric", target_value=100)


class TestLatencyMetrics:
    """Test latency metric collection from histogram"""

    @pytest.fixture
    def tracker_with_histogram(self):
        """Tracker with populated histogram"""
        registry = MetricsRegistry()

        # Create and populate histogram
        hist = registry.histogram(
            "http_request_duration_seconds",
            "HTTP request latency",
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, float('inf'))
        )

        # Add some observations
        for _ in range(50):
            hist.observe(0.03)  # 30ms
        for _ in range(30):
            hist.observe(0.08)  # 80ms
        for _ in range(15):
            hist.observe(0.15)  # 150ms
        for _ in range(5):
            hist.observe(0.4)   # 400ms

        return SuccessMetricsTracker(registry=registry)

    def test_collect_latency_metrics(self, tracker_with_histogram):
        """Should collect latency metrics from histogram"""
        results = tracker_with_histogram._collect_latency_metrics()

        assert len(results) == 2

        p50 = next((r for r in results if r.name == "latency_p50"), None)
        p99 = next((r for r in results if r.name == "latency_p99"), None)

        assert p50 is not None
        assert p99 is not None
        assert not math.isnan(p50.value)
        assert not math.isnan(p99.value)

        # p50 should be around 0.03-0.08
        assert 0.01 < p50.value < 0.2

        # p99 should be around 0.15-0.4
        assert 0.1 < p99.value < 0.5

    def test_empty_histogram_returns_unknown(self):
        """Empty histogram should return unknown status"""
        # Create tracker with empty registry (no histogram data)
        registry = MetricsRegistry()
        tracker = SuccessMetricsTracker(registry=registry)
        results = tracker._collect_latency_metrics()

        for r in results:
            assert r.status == MetricStatus.UNKNOWN


class TestGlobalSingleton:
    """Test global singleton pattern"""

    def test_get_success_tracker_returns_same_instance(self):
        """get_success_tracker should return same instance"""
        # Reset global
        import backend.monitoring.success_metrics as sm_module
        sm_module._tracker = None

        t1 = get_success_tracker()
        t2 = get_success_tracker()

        assert t1 is t2


class TestCollectMetrics:
    """Test full metric collection"""

    @pytest.fixture
    def tracker(self):
        """Fresh tracker"""
        registry = MetricsRegistry()
        return SuccessMetricsTracker(registry=registry)

    @pytest.mark.asyncio
    async def test_collect_all_metrics(self, tracker):
        """Should collect all metrics (some may be unknown without DB)"""
        report = await tracker.collect_metrics()

        assert isinstance(report, SuccessReport)
        assert len(report.metrics) >= 4  # At least latency + other metrics
        assert report.generated_at > 0

    @pytest.mark.asyncio
    async def test_report_has_valid_structure(self, tracker):
        """Report should have valid structure"""
        report = await tracker.collect_metrics()
        d = report.to_dict()

        assert "overall_status" in d
        assert "summary" in d
        assert "metrics" in d
        assert "generated_at" in d
