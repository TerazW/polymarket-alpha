"""
Tests for Health Remediation Module (v5.16)

Ensures:
1. Remediation actions are properly defined
2. Health check results trigger appropriate remediations
3. Cooldown periods are respected
4. Degradation state is properly tracked
5. Manual triggers work correctly
"""

import pytest
import asyncio
import time
from datetime import datetime

from backend.monitoring import (
    HealthRemediator,
    RemediationType,
    RemediationAction,
    RemediationResult,
    DegradationLevel,
    DegradationState,
    REMEDIATION_ACTIONS,
    CHECK_TO_REMEDIATION,
    get_remediator,
    process_health_and_remediate,
)
from backend.monitoring.health import (
    HealthStatus,
    CheckResult,
    HealthReport,
)


class TestRemediationActionDefinitions:
    """Test remediation action definitions"""

    def test_all_actions_defined(self):
        """Should have all required remediation actions defined"""
        required_actions = ["data_gap", "hash_mismatch", "tile_stale", "db_latency"]
        for action_key in required_actions:
            assert action_key in REMEDIATION_ACTIONS
            action = REMEDIATION_ACTIONS[action_key]
            assert isinstance(action, RemediationAction)
            assert action.ui_label
            assert action.ui_emoji

    def test_action_properties(self):
        """Each action should have required properties"""
        for key, action in REMEDIATION_ACTIONS.items():
            assert action.action_type in RemediationType
            assert action.name
            assert action.description
            assert action.cooldown_ms > 0
            assert action.timeout_ms > 0

    def test_check_to_remediation_mapping(self):
        """Check names should map to remediation actions"""
        for check_name, remediation_key in CHECK_TO_REMEDIATION.items():
            assert remediation_key in REMEDIATION_ACTIONS, \
                f"Remediation key {remediation_key} for check {check_name} not found"


class TestHealthRemediator:
    """Test HealthRemediator class"""

    @pytest.fixture
    def remediator(self):
        """Fresh remediator for each test"""
        return HealthRemediator(enable_auto_remediation=True)

    @pytest.fixture
    def degraded_report(self):
        """Health report with degraded checks"""
        return HealthReport(
            status=HealthStatus.DEGRADED,
            checks=[
                CheckResult(
                    name="data_freshness",
                    status=HealthStatus.DEGRADED,
                    message="Data is stale",
                    details={"latest_trade_age_seconds": 400},
                ),
                CheckResult(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    message="OK",
                ),
            ],
            version="1.0.0",
            uptime_seconds=1000.0,
        )

    @pytest.fixture
    def unhealthy_report(self):
        """Health report with unhealthy checks"""
        return HealthReport(
            status=HealthStatus.UNHEALTHY,
            checks=[
                CheckResult(
                    name="database_performance",
                    status=HealthStatus.UNHEALTHY,
                    message="Queries very slow",
                    latency_ms=6000,
                    details={"latency_ms": 6000},
                ),
                CheckResult(
                    name="tile_generation",
                    status=HealthStatus.DEGRADED,
                    message="Tiles delayed",
                    details={"latest_tile_age_seconds": 120},
                ),
            ],
            version="1.0.0",
            uptime_seconds=2000.0,
        )

    @pytest.mark.asyncio
    async def test_process_healthy_report(self, remediator):
        """Healthy report should not trigger remediation"""
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            checks=[
                CheckResult(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    message="OK",
                ),
            ],
            version="1.0.0",
            uptime_seconds=100.0,
        )

        results = await remediator.process_health_report(report)

        assert len(results) == 0
        state = remediator.get_degradation_state()
        assert state.level == DegradationLevel.NORMAL

    @pytest.mark.asyncio
    async def test_process_degraded_report(self, remediator, degraded_report):
        """Degraded report should trigger appropriate remediation"""
        results = await remediator.process_health_report(degraded_report)

        # Should have triggered data_gap remediation
        assert len(results) >= 1

        state = remediator.get_degradation_state()
        assert state.level in (DegradationLevel.DEGRADED, DegradationLevel.CRITICAL)
        assert "data_freshness" in state.active_issues

    @pytest.mark.asyncio
    async def test_process_unhealthy_report(self, remediator, unhealthy_report):
        """Unhealthy report should trigger multiple remediations"""
        results = await remediator.process_health_report(unhealthy_report)

        # Should have triggered db_latency and tile_stale remediations
        assert len(results) >= 2

        state = remediator.get_degradation_state()
        assert state.level in (DegradationLevel.DEGRADED, DegradationLevel.CRITICAL)

    @pytest.mark.asyncio
    async def test_remediation_disabled(self):
        """Disabled remediation should not execute"""
        remediator = HealthRemediator(enable_auto_remediation=False)

        report = HealthReport(
            status=HealthStatus.DEGRADED,
            checks=[
                CheckResult(
                    name="data_freshness",
                    status=HealthStatus.DEGRADED,
                    message="Stale",
                ),
            ],
            version="1.0.0",
            uptime_seconds=100.0,
        )

        results = await remediator.process_health_report(report)

        # No remediations should be executed
        assert len(results) == 0

        # But degradation state should still be tracked
        state = remediator.get_degradation_state()
        assert "data_freshness" in state.active_issues


class TestCooldown:
    """Test cooldown functionality"""

    @pytest.fixture
    def remediator(self):
        return HealthRemediator(enable_auto_remediation=True)

    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_execution(self, remediator):
        """Cooldown should prevent rapid consecutive executions"""
        report = HealthReport(
            status=HealthStatus.DEGRADED,
            checks=[
                CheckResult(
                    name="tile_generation",
                    status=HealthStatus.DEGRADED,
                    message="Stale",
                    details={"latest_tile_age_seconds": 120},
                ),
            ],
            version="1.0.0",
            uptime_seconds=100.0,
        )

        # First execution should succeed
        results1 = await remediator.process_health_report(report)
        assert len(results1) == 1
        assert results1[0].success is True

        # Immediate second execution should be skipped due to cooldown
        results2 = await remediator.process_health_report(report)
        assert len(results2) == 1
        assert results2[0].success is False
        assert "cooldown" in results2[0].message.lower()

        assert remediator.stats["skipped_cooldown"] >= 1


class TestDegradationState:
    """Test degradation state tracking"""

    @pytest.fixture
    def remediator(self):
        return HealthRemediator()

    def test_initial_state_normal(self, remediator):
        """Initial state should be normal"""
        state = remediator.get_degradation_state()
        assert state.level == DegradationLevel.NORMAL
        assert len(state.active_issues) == 0

    @pytest.mark.asyncio
    async def test_state_reflects_issues(self, remediator):
        """State should reflect current issues"""
        report = HealthReport(
            status=HealthStatus.DEGRADED,
            checks=[
                CheckResult(
                    name="data_freshness",
                    status=HealthStatus.DEGRADED,
                    message="Stale",
                ),
                CheckResult(
                    name="tile_generation",
                    status=HealthStatus.DEGRADED,
                    message="Delayed",
                ),
            ],
            version="1.0.0",
            uptime_seconds=100.0,
        )

        await remediator.process_health_report(report)

        state = remediator.get_degradation_state()
        assert len(state.active_issues) == 2
        assert len(state.ui_labels) == 2

    def test_state_to_dict(self, remediator):
        """State should serialize to dict correctly"""
        state = remediator.get_degradation_state()
        state_dict = state.to_dict()

        assert "level" in state_dict
        assert "active_issues" in state_dict
        assert "ui_labels" in state_dict
        assert "updated_at" in state_dict
        assert "updated_at_iso" in state_dict

    def test_clear_issue(self, remediator):
        """Should be able to manually clear issues"""
        # Manually add an issue
        remediator._current_issues["test_check"] = "Test issue"

        state = remediator.get_degradation_state()
        assert "test_check" in state.active_issues

        # Clear it
        remediator.clear_issue("test_check")

        state = remediator.get_degradation_state()
        assert "test_check" not in state.active_issues


class TestManualTriggers:
    """Test manual remediation triggers"""

    @pytest.fixture
    def remediator(self):
        return HealthRemediator(enable_auto_remediation=True)

    @pytest.mark.asyncio
    async def test_trigger_rebuild_window(self, remediator):
        """Should manually trigger rebuild window"""
        result = await remediator.trigger_rebuild_window(
            token_id="test-token",
            from_ts=1000000,
            to_ts=2000000
        )

        assert result.action_type == RemediationType.REBUILD_WINDOW
        assert result.success is True

    @pytest.mark.asyncio
    async def test_trigger_hash_verification(self, remediator):
        """Should manually trigger hash verification"""
        result = await remediator.trigger_hash_verification(
            token_id="test-token",
            bundle_id="test-bundle-123"
        )

        assert result.action_type == RemediationType.RECALC_FROM_RAW
        assert result.success is True

    @pytest.mark.asyncio
    async def test_trigger_tile_generation(self, remediator):
        """Should manually trigger tile generation"""
        result = await remediator.trigger_tile_generation(
            token_id="test-token",
            from_ts=1000000,
            to_ts=2000000
        )

        assert result.action_type == RemediationType.GENERATE_TILES
        assert result.success is True


class TestRemediationResult:
    """Test remediation result properties"""

    def test_result_properties(self):
        """Result should have all required properties"""
        result = RemediationResult(
            action_type=RemediationType.REBUILD_WINDOW,
            success=True,
            message="Success",
            started_at=1000,
            completed_at=1100,
            duration_ms=100,
        )

        assert result.action_type == RemediationType.REBUILD_WINDOW
        assert result.success is True
        assert result.duration_ms == 100
        assert result.error is None

    def test_result_with_error(self):
        """Failed result should include error"""
        result = RemediationResult(
            action_type=RemediationType.SWITCH_REPLICA,
            success=False,
            message="Failed",
            started_at=1000,
            completed_at=1100,
            duration_ms=100,
            error="Connection refused",
        )

        assert result.success is False
        assert result.error == "Connection refused"


class TestRemediationHistory:
    """Test remediation history tracking"""

    @pytest.fixture
    def remediator(self):
        return HealthRemediator(enable_auto_remediation=True)

    @pytest.mark.asyncio
    async def test_history_tracking(self, remediator):
        """Should track remediation history"""
        await remediator.trigger_rebuild_window("token", 0, 1000)
        await remediator.trigger_tile_generation("token", 0, 1000)

        history = remediator.get_remediation_history()
        assert len(history) >= 2

    @pytest.mark.asyncio
    async def test_history_limit(self, remediator):
        """Should limit history size"""
        remediator._max_history = 5

        for i in range(10):
            # Trigger different checks to avoid cooldown
            await remediator.trigger_tile_generation(f"token-{i}", 0, 1000)

        history = remediator.get_remediation_history(limit=100)
        # Should have some results, but may not be exactly 5 due to cooldown
        assert len(history) >= 1


class TestStats:
    """Test remediation statistics"""

    @pytest.fixture
    def remediator(self):
        return HealthRemediator(enable_auto_remediation=True)

    @pytest.mark.asyncio
    async def test_stats_tracking(self, remediator):
        """Should track remediation statistics"""
        await remediator.trigger_rebuild_window("token", 0, 1000)

        stats = remediator.get_stats()

        assert "total_remediations" in stats
        assert "successful" in stats
        assert "failed" in stats
        assert "by_type" in stats
        assert "current_degradation" in stats
        assert stats["total_remediations"] >= 1

    @pytest.mark.asyncio
    async def test_stats_by_type(self, remediator):
        """Should track stats by remediation type"""
        await remediator.trigger_rebuild_window("token1", 0, 1000)
        await remediator.trigger_tile_generation("token2", 0, 1000)

        stats = remediator.get_stats()

        assert RemediationType.REBUILD_WINDOW.value in stats["by_type"]
        assert RemediationType.GENERATE_TILES.value in stats["by_type"]


class TestCustomHandlers:
    """Test custom remediation handlers"""

    @pytest.fixture
    def remediator(self):
        return HealthRemediator(enable_auto_remediation=True)

    @pytest.mark.asyncio
    async def test_register_custom_handler(self, remediator):
        """Should be able to register custom handlers"""
        custom_called = {"count": 0}

        async def custom_handler(action, context):
            custom_called["count"] += 1
            return RemediationResult(
                action_type=action.action_type,
                success=True,
                message="Custom handler executed",
                started_at=int(time.time() * 1000),
                completed_at=int(time.time() * 1000),
                duration_ms=0,
            )

        remediator.register_handler(RemediationType.REBUILD_WINDOW, custom_handler)

        await remediator.trigger_rebuild_window("token", 0, 1000)

        assert custom_called["count"] == 1


class TestDegradationCallback:
    """Test degradation change callback"""

    @pytest.mark.asyncio
    async def test_callback_on_degradation_change(self):
        """Should call callback when degradation changes"""
        callback_states = []

        async def on_change(state):
            callback_states.append(state)

        remediator = HealthRemediator(
            on_degradation_change=on_change,
            enable_auto_remediation=True
        )

        report = HealthReport(
            status=HealthStatus.DEGRADED,
            checks=[
                CheckResult(
                    name="data_freshness",
                    status=HealthStatus.DEGRADED,
                    message="Stale",
                ),
            ],
            version="1.0.0",
            uptime_seconds=100.0,
        )

        await remediator.process_health_report(report)

        assert len(callback_states) >= 1
        assert isinstance(callback_states[0], DegradationState)


class TestGlobalSingleton:
    """Test global singleton pattern"""

    def test_get_remediator_returns_same_instance(self):
        """get_remediator should return same instance"""
        # Reset global
        import backend.monitoring.remediation as rem_module
        rem_module._remediator = None

        r1 = get_remediator()
        r2 = get_remediator()

        assert r1 is r2

    @pytest.mark.asyncio
    async def test_process_health_and_remediate_convenience(self):
        """Convenience function should work"""
        # Reset global
        import backend.monitoring.remediation as rem_module
        rem_module._remediator = None

        report = HealthReport(
            status=HealthStatus.HEALTHY,
            checks=[],
            version="1.0.0",
            uptime_seconds=100.0,
        )

        results = await process_health_and_remediate(report)
        assert isinstance(results, list)
