"""
Tests for Fire Drill - Periodic Rebuild Verification (v5.36)
"""

import pytest
import time
from backend.audit.fire_drill import (
    FireDrillExecutor,
    FireDrillReport,
    FireDrillStatus,
    Discrepancy,
    DiscrepancyType,
    run_fire_drill,
    generate_fire_drill_summary,
)


class TestFireDrillStatus:
    """Test FireDrillStatus enum"""

    def test_status_values(self):
        assert FireDrillStatus.PENDING.value == "PENDING"
        assert FireDrillStatus.RUNNING.value == "RUNNING"
        assert FireDrillStatus.PASSED.value == "PASSED"
        assert FireDrillStatus.FAILED.value == "FAILED"
        assert FireDrillStatus.ERROR.value == "ERROR"


class TestDiscrepancyType:
    """Test DiscrepancyType enum"""

    def test_discrepancy_types(self):
        assert DiscrepancyType.MISSING_EVENT.value == "MISSING_EVENT"
        assert DiscrepancyType.EXTRA_EVENT.value == "EXTRA_EVENT"
        assert DiscrepancyType.STATE_MISMATCH.value == "STATE_MISMATCH"
        assert DiscrepancyType.HASH_MISMATCH.value == "HASH_MISMATCH"
        assert DiscrepancyType.COUNT_MISMATCH.value == "COUNT_MISMATCH"


class TestDiscrepancy:
    """Test Discrepancy dataclass"""

    def test_discrepancy_creation(self):
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.MISSING_EVENT,
            table_name="shock_events",
            record_id="shock_123",
            original_value="exists",
            rebuilt_value="missing",
            details="Shock event not rebuilt",
        )
        assert d.discrepancy_type == DiscrepancyType.MISSING_EVENT
        assert d.table_name == "shock_events"
        assert d.record_id == "shock_123"

    def test_discrepancy_to_dict(self):
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.COUNT_MISMATCH,
            table_name="alerts",
            record_id="*",
            original_value=10,
            rebuilt_value=8,
        )
        result = d.to_dict()
        assert result["type"] == "COUNT_MISMATCH"
        assert result["table"] == "alerts"
        assert result["original"] == "10"
        assert result["rebuilt"] == "8"


class TestFireDrillReport:
    """Test FireDrillReport dataclass"""

    def test_report_creation(self):
        report = FireDrillReport(
            drill_id="fd_test123",
            status=FireDrillStatus.RUNNING,
        )
        assert report.drill_id == "fd_test123"
        assert report.status == FireDrillStatus.RUNNING
        assert report.started_at > 0
        assert report.is_deterministic is False

    def test_report_add_discrepancy(self):
        report = FireDrillReport(
            drill_id="fd_test",
            status=FireDrillStatus.RUNNING,
        )
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.MISSING_EVENT,
            table_name="test",
            record_id="1",
            original_value="x",
            rebuilt_value="y",
        )
        report.add_discrepancy(d)
        assert len(report.discrepancies) == 1
        assert report.discrepancies[0].record_id == "1"

    def test_report_to_dict(self):
        report = FireDrillReport(
            drill_id="fd_test",
            status=FireDrillStatus.PASSED,
            window_start=1000,
            window_end=2000,
            shocks_original=5,
            shocks_rebuilt=5,
            is_deterministic=True,
        )
        result = report.to_dict()
        assert result["drill_id"] == "fd_test"
        assert result["status"] == "PASSED"
        assert result["window"]["start"] == 1000
        assert result["window"]["end"] == 2000
        assert result["counts"]["shocks"]["original"] == 5
        assert result["is_deterministic"] is True

    def test_report_to_json(self):
        report = FireDrillReport(
            drill_id="fd_json",
            status=FireDrillStatus.PASSED,
        )
        json_str = report.to_json()
        assert "fd_json" in json_str
        assert "PASSED" in json_str


class TestFireDrillExecutor:
    """Test FireDrillExecutor"""

    def test_dry_run(self):
        """Dry run should pass immediately"""
        executor = FireDrillExecutor()
        report = executor.run(
            window_hours=1,
            dry_run=True,
        )

        assert report.status == FireDrillStatus.PASSED
        assert report.is_deterministic is True
        assert report.completed_at >= report.started_at

    def test_dry_run_with_tokens(self):
        """Dry run with specific tokens"""
        executor = FireDrillExecutor()
        report = executor.run(
            window_hours=24,
            token_ids=["token1", "token2"],
            dry_run=True,
        )

        assert report.status == FireDrillStatus.PASSED
        assert report.token_ids == ["token1", "token2"]

    def test_no_db_without_dry_run(self):
        """Without DB and not dry run should error"""
        executor = FireDrillExecutor(db_connection=None)
        report = executor.run(
            window_hours=1,
            dry_run=False,
        )

        assert report.status == FireDrillStatus.ERROR
        assert "Database connection required" in report.error_message

    def test_custom_window(self):
        """Test custom time window"""
        executor = FireDrillExecutor()
        now = int(time.time() * 1000)
        start = now - 3600000  # 1 hour ago

        report = executor.run(
            window_start_ms=start,
            window_end_ms=now,
            dry_run=True,
        )

        assert report.window_start == start
        assert report.window_end == now


class TestConvenienceFunction:
    """Test module-level convenience function"""

    def test_run_fire_drill(self):
        """Test convenience function"""
        report = run_fire_drill(
            window_hours=1,
            dry_run=True,
        )
        assert isinstance(report, FireDrillReport)
        assert report.status == FireDrillStatus.PASSED


class TestReportSummary:
    """Test report summary generation"""

    def test_generate_summary_passed(self):
        """Test summary for passed drill"""
        report = FireDrillReport(
            drill_id="fd_test",
            status=FireDrillStatus.PASSED,
            window_start=int(time.time() * 1000) - 3600000,
            window_end=int(time.time() * 1000),
            raw_events_processed=1000,
            shocks_original=50,
            shocks_rebuilt=50,
            reactions_original=45,
            reactions_rebuilt=45,
            is_deterministic=True,
            engine_version="5.36",
            config_hash="abc123",
        )
        report.completed_at = report.started_at + 5000

        summary = generate_fire_drill_summary(report)

        assert "FIRE DRILL REPORT" in summary
        assert "fd_test" in summary
        assert "PASSED" in summary
        assert "YES ✓" in summary
        assert "NO DISCREPANCIES FOUND" in summary

    def test_generate_summary_failed(self):
        """Test summary for failed drill"""
        report = FireDrillReport(
            drill_id="fd_fail",
            status=FireDrillStatus.FAILED,
            window_start=int(time.time() * 1000) - 3600000,
            window_end=int(time.time() * 1000),
            shocks_original=50,
            shocks_rebuilt=48,
            is_deterministic=False,
        )
        report.completed_at = report.started_at + 3000

        report.add_discrepancy(Discrepancy(
            discrepancy_type=DiscrepancyType.COUNT_MISMATCH,
            table_name="shock_events",
            record_id="*",
            original_value=50,
            rebuilt_value=48,
            details="2 shocks missing",
        ))

        summary = generate_fire_drill_summary(report)

        assert "FAILED" in summary
        assert "NO ✗" in summary
        assert "DISCREPANCIES" in summary
        assert "COUNT_MISMATCH" in summary

    def test_generate_summary_error(self):
        """Test summary for errored drill"""
        report = FireDrillReport(
            drill_id="fd_error",
            status=FireDrillStatus.ERROR,
            error_message="Database connection failed",
        )
        report.completed_at = report.started_at + 100

        summary = generate_fire_drill_summary(report)

        assert "ERROR" in summary
        assert "Database connection failed" in summary
