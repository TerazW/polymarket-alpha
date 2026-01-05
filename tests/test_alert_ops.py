"""
Tests for Alert Ops Manager (v5.15)

Ensures:
1. Deduplication works within window
2. Auto-resolve on TTL and state recovery
3. Manual override prevents auto-resolve
4. Explain log tracks all changes
5. Supersession replaces old alerts
"""

import pytest
import asyncio
import time
from datetime import datetime

from backend.alerting import (
    AlertPayload,
    AlertPriority,
    AlertCategory,
    AlertOpsManager,
    AlertStatus,
    ResolutionRule,
    ManagedAlert,
    ExplainLogEntry,
    generate_dedup_key,
    DEDUP_WINDOW_MS,
    STATE_RECOVERY_GRACE_MS,
)


class TestDedupKeyGeneration:
    """Test dedup key generation"""

    def test_basic_key_generation(self):
        """Should generate key from category and token"""
        payload = AlertPayload(
            alert_id="test-1",
            category=AlertCategory.BELIEF_STATE,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            token_id="token-abc",
        )

        key = generate_dedup_key(payload)
        assert "belief_state" in key
        assert "token-abc" in key

    def test_custom_dedup_key(self):
        """Should use custom key if provided"""
        payload = AlertPayload(
            alert_id="test-1",
            category=AlertCategory.BELIEF_STATE,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        )

        key = generate_dedup_key(payload, custom_key="my-custom-key")
        assert key == "my-custom-key"

    def test_dedup_key_from_data(self):
        """Should use dedup_key from payload data"""
        payload = AlertPayload(
            alert_id="test-1",
            category=AlertCategory.BELIEF_STATE,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            data={"dedup_key": "data-provided-key"},
        )

        key = generate_dedup_key(payload)
        assert key == "data-provided-key"

    def test_price_bucketing(self):
        """Should bucket price in dedup key"""
        payload = AlertPayload(
            alert_id="test-1",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            token_id="token-xyz",
            data={"price": 123.456},
        )

        key = generate_dedup_key(payload)
        assert "p12345" in key  # 123.456 * 100 = 12345.6 -> int = 12345


class TestAlertOpsManager:
    """Test AlertOpsManager core functionality"""

    @pytest.fixture
    def ops(self):
        """Fresh ops manager for each test"""
        return AlertOpsManager(
            dedup_window_ms=1000,  # 1 second for testing
            enable_auto_resolve=True,
        )

    @pytest.mark.asyncio
    async def test_new_alert_is_tracked(self, ops):
        """New alert should be tracked and returned as new"""
        payload = AlertPayload(
            alert_id="alert-1",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test Alert",
            message="Test message",
            token_id="token-1",
        )

        managed, is_new = await ops.process_alert(payload)

        assert is_new is True
        assert managed.status == AlertStatus.OPEN
        assert managed.alert_id == "alert-1"
        assert ops.stats["total_processed"] == 1

    @pytest.mark.asyncio
    async def test_dedup_within_window(self, ops):
        """Duplicate alert within window should be merged"""
        payload1 = AlertPayload(
            alert_id="alert-1",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            token_id="token-1",
            data={"dedup_key": "same-key"},
        )

        payload2 = AlertPayload(
            alert_id="alert-2",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            token_id="token-1",
            data={"dedup_key": "same-key"},
        )

        managed1, is_new1 = await ops.process_alert(payload1)
        managed2, is_new2 = await ops.process_alert(payload2)

        assert is_new1 is True
        assert is_new2 is False  # Deduplicated
        assert managed1.alert_id == managed2.alert_id
        assert managed1.merged_count == 1
        assert "alert-2" in managed1.related_ids
        assert ops.stats["total_deduplicated"] == 1

    @pytest.mark.asyncio
    async def test_different_dedup_keys_not_merged(self, ops):
        """Alerts with different dedup keys should not merge"""
        payload1 = AlertPayload(
            alert_id="alert-1",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            data={"dedup_key": "key-1"},
        )

        payload2 = AlertPayload(
            alert_id="alert-2",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            data={"dedup_key": "key-2"},
        )

        _, is_new1 = await ops.process_alert(payload1)
        _, is_new2 = await ops.process_alert(payload2)

        assert is_new1 is True
        assert is_new2 is True
        assert len(ops.alerts) == 2


class TestAutoResolve:
    """Test auto-resolution functionality"""

    @pytest.fixture
    def ops(self):
        return AlertOpsManager(enable_auto_resolve=True)

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, ops):
        """Alert should expire after TTL"""
        payload = AlertPayload(
            alert_id="alert-exp",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.LOW,  # 30 min TTL
            title="Test",
            message="Test",
        )

        managed, _ = await ops.process_alert(payload)

        # Simulate time passing beyond TTL
        future_time = int(time.time() * 1000) + (35 * 60 * 1000)  # 35 minutes later
        resolved = ops.tick(current_time=future_time)

        assert len(resolved) == 1
        assert managed.status == AlertStatus.EXPIRED
        assert managed.resolution_rule == ResolutionRule.TTL_EXPIRED
        assert ops.stats["expired"] == 1

    @pytest.mark.asyncio
    async def test_state_recovery_auto_resolve(self, ops):
        """Alert should auto-resolve after state recovery grace period"""
        payload = AlertPayload(
            alert_id="alert-state",
            category=AlertCategory.BELIEF_STATE,
            priority=AlertPriority.HIGH,
            title="State Change",
            message="State changed",
            token_id="token-1",
        )

        managed, _ = await ops.process_alert(payload)
        now = int(time.time() * 1000)

        # Notify state became stable
        ops.on_state_change("token-1", is_stable=True, timestamp=now)

        # Before grace period - should not resolve
        ops.tick(current_time=now + 1000)
        assert managed.status == AlertStatus.OPEN

        # After grace period - should resolve
        future = now + STATE_RECOVERY_GRACE_MS + 1000
        resolved = ops.tick(current_time=future)

        assert len(resolved) == 1
        assert managed.status == AlertStatus.AUTO_RESOLVED
        assert managed.resolution_rule == ResolutionRule.STATE_RECOVERED

    @pytest.mark.asyncio
    async def test_manual_override_prevents_auto_resolve(self, ops):
        """Manual override should prevent auto-resolution"""
        payload = AlertPayload(
            alert_id="alert-override",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.LOW,
            title="Test",
            message="Test",
            token_id="token-1",
        )

        managed, _ = await ops.process_alert(payload)

        # User keeps it open
        ops.keep_open("alert-override", user_id="admin")
        assert managed.manual_override is True

        # Simulate TTL expiration
        future = int(time.time() * 1000) + (35 * 60 * 1000)
        resolved = ops.tick(current_time=future)

        # Should NOT be resolved due to manual override
        assert len(resolved) == 0
        assert managed.status == AlertStatus.OPEN


class TestManualActions:
    """Test manual actions on alerts"""

    @pytest.fixture
    def ops(self):
        return AlertOpsManager()

    @pytest.mark.asyncio
    async def test_manual_resolve(self, ops):
        """Should manually resolve alert"""
        payload = AlertPayload(
            alert_id="alert-manual",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        )

        await ops.process_alert(payload)

        success = ops.resolve_manual("alert-manual", "Fixed by operator", "admin")

        assert success is True
        managed = ops.get_alert("alert-manual")
        assert managed.status == AlertStatus.MANUAL_RESOLVED
        assert managed.resolution_reason == "Fixed by operator"
        assert ops.stats["manual_resolved"] == 1

    @pytest.mark.asyncio
    async def test_keep_open_reopens_auto_resolved(self, ops):
        """keep_open should reopen auto-resolved alerts"""
        payload = AlertPayload(
            alert_id="alert-reopen",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.LOW,
            title="Test",
            message="Test",
        )

        managed, _ = await ops.process_alert(payload)

        # Simulate TTL expiration
        future = int(time.time() * 1000) + (35 * 60 * 1000)
        ops.tick(current_time=future)
        assert managed.status == AlertStatus.EXPIRED

        # User reopens
        ops.keep_open("alert-reopen", user_id="admin")

        assert managed.status == AlertStatus.OPEN
        assert managed.manual_override is True

    @pytest.mark.asyncio
    async def test_acknowledge(self, ops):
        """Should acknowledge alert and log it"""
        payload = AlertPayload(
            alert_id="alert-ack",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        )

        await ops.process_alert(payload)

        success = ops.acknowledge("alert-ack", "user-1")

        assert success is True
        # Check explain log has ack entry
        log = ops.get_explain_log(alert_id="alert-ack")
        assert any(e.reason == "Acknowledged" for e in log)


class TestExplainLog:
    """Test explain log functionality"""

    @pytest.fixture
    def ops(self):
        return AlertOpsManager()

    @pytest.mark.asyncio
    async def test_creation_logged(self, ops):
        """Alert creation should be logged"""
        payload = AlertPayload(
            alert_id="alert-log",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        )

        await ops.process_alert(payload)

        log = ops.get_explain_log(alert_id="alert-log")
        assert len(log) >= 1
        assert log[0].reason == "Alert created"

    @pytest.mark.asyncio
    async def test_resolution_logged(self, ops):
        """Resolution should be logged with details"""
        payload = AlertPayload(
            alert_id="alert-res-log",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        )

        await ops.process_alert(payload)
        ops.resolve_manual("alert-res-log", "Test resolution", "test-user")

        log = ops.get_explain_log(alert_id="alert-res-log")
        resolution_entry = next(
            (e for e in log if e.new_status == AlertStatus.MANUAL_RESOLVED),
            None
        )

        assert resolution_entry is not None
        assert resolution_entry.reason == "Test resolution"
        assert resolution_entry.triggered_by == "test-user"
        assert resolution_entry.rule == ResolutionRule.MANUAL

    @pytest.mark.asyncio
    async def test_explain_log_to_dict(self, ops):
        """ExplainLogEntry should serialize to dict"""
        payload = AlertPayload(
            alert_id="alert-dict",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        )

        await ops.process_alert(payload)

        log = ops.get_explain_log(alert_id="alert-dict")
        entry_dict = log[0].to_dict()

        assert "log_id" in entry_dict
        assert "alert_id" in entry_dict
        assert "timestamp" in entry_dict
        assert "timestamp_iso" in entry_dict
        assert "old_status" in entry_dict
        assert "new_status" in entry_dict
        assert "rule" in entry_dict
        assert "triggered_by" in entry_dict

    @pytest.mark.asyncio
    async def test_get_alert_history(self, ops):
        """get_alert_history should return full history"""
        payload = AlertPayload(
            alert_id="alert-history",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        )

        await ops.process_alert(payload)
        ops.acknowledge("alert-history", "user-1")
        ops.resolve_manual("alert-history", "Done", "user-2")

        history = ops.get_alert_history("alert-history")

        assert "alert" in history
        assert "explain_log" in history
        assert len(history["explain_log"]) >= 3  # created, ack, resolved


class TestSupersession:
    """Test alert supersession"""

    @pytest.fixture
    def ops(self):
        # Use longer dedup window so we can test supersession
        return AlertOpsManager(dedup_window_ms=100)

    @pytest.mark.asyncio
    async def test_old_alert_superseded(self, ops):
        """Old alert should be superseded when new arrives after window"""
        payload1 = AlertPayload(
            alert_id="alert-old",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
            data={"dedup_key": "same-condition"},
        )

        managed1, _ = await ops.process_alert(payload1)

        # Wait for dedup window to pass
        await asyncio.sleep(0.15)  # 150ms > 100ms window

        payload2 = AlertPayload(
            alert_id="alert-new",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test Updated",
            message="Test Updated",
            data={"dedup_key": "same-condition"},
        )

        managed2, is_new = await ops.process_alert(payload2)

        assert is_new is True
        assert managed1.status == AlertStatus.SUPERSEDED
        assert managed1.superseded_by == "alert-new"
        assert ops.stats["total_superseded"] == 1


class TestClearCondition:
    """Test clear_condition functionality"""

    @pytest.fixture
    def ops(self):
        return AlertOpsManager()

    @pytest.mark.asyncio
    async def test_clear_condition(self, ops):
        """Should auto-resolve when condition is cleared"""
        payload = AlertPayload(
            alert_id="alert-condition",
            category=AlertCategory.DATA_GAP,
            priority=AlertPriority.HIGH,
            title="Data Gap",
            message="Missing data",
            data={"dedup_key": "gap:token-1:field-x"},
        )

        await ops.process_alert(payload)

        # Clear the condition
        resolved = ops.clear_condition(
            "gap:token-1:field-x",
            reason="Data received"
        )

        assert resolved is not None
        assert resolved.status == AlertStatus.AUTO_RESOLVED
        assert resolved.resolution_rule == ResolutionRule.CONDITION_CLEARED


class TestStats:
    """Test statistics and queries"""

    @pytest.fixture
    def ops(self):
        return AlertOpsManager()

    @pytest.mark.asyncio
    async def test_get_active_alerts(self, ops):
        """Should return only active alerts"""
        for i in range(5):
            await ops.process_alert(AlertPayload(
                alert_id=f"alert-{i}",
                category=AlertCategory.DETECTION,
                priority=AlertPriority.HIGH,
                title="Test",
                message="Test",
                data={"dedup_key": f"unique-key-{i}"},  # Unique dedup keys
            ))

        # Resolve some
        ops.resolve_manual("alert-0", "Done", "user")
        ops.resolve_manual("alert-2", "Done", "user")

        active = ops.get_active_alerts()
        assert len(active) == 3

    @pytest.mark.asyncio
    async def test_get_stats(self, ops):
        """Should return accurate stats"""
        await ops.process_alert(AlertPayload(
            alert_id="alert-stat",
            category=AlertCategory.DETECTION,
            priority=AlertPriority.HIGH,
            title="Test",
            message="Test",
        ))

        ops.resolve_manual("alert-stat", "Done", "user")

        stats = ops.get_stats()

        assert stats["total_processed"] == 1
        assert stats["manual_resolved"] == 1
        assert stats["current_active"] == 0
        assert stats["total_tracked"] == 1
        assert AlertStatus.MANUAL_RESOLVED.value in stats["by_status"]
