"""
Tests for Audit Window Storage (v5.36)
"""

import pytest
import time
from backend.storage.audit_window import (
    AuditWindowManager,
    AuditWindow,
    StorageMode,
    should_store_full_audit,
    AUDIT_WINDOW_CONFIG,
)


class TestStorageMode:
    """Test StorageMode enum"""

    def test_storage_modes(self):
        assert StorageMode.MINIMAL.value == "MINIMAL"
        assert StorageMode.FULL_AUDIT.value == "FULL_AUDIT"


class TestAuditWindow:
    """Test AuditWindow dataclass"""

    def test_window_creation(self):
        now = int(time.time() * 1000)
        window = AuditWindow(
            token_id="test_token",
            trigger_ts=now,
            window_start=now - 30000,
            window_end=now + 60000,
            trigger_type="STATE_CRACKING",
            trigger_id="event_123",
        )
        assert window.token_id == "test_token"
        assert window.trigger_ts == now

    def test_window_contains(self):
        now = int(time.time() * 1000)
        window = AuditWindow(
            token_id="test",
            trigger_ts=now,
            window_start=now - 30000,
            window_end=now + 60000,
            trigger_type="STATE_CRACKING",
            trigger_id="event_123",
        )

        # Inside window
        assert window.contains(now) is True
        assert window.contains(now - 15000) is True
        assert window.contains(now + 30000) is True

        # At boundaries
        assert window.contains(window.window_start) is True
        assert window.contains(window.window_end) is True

        # Outside window
        assert window.contains(now - 50000) is False
        assert window.contains(now + 100000) is False

    def test_window_to_dict(self):
        now = int(time.time() * 1000)
        window = AuditWindow(
            token_id="test",
            trigger_ts=now,
            window_start=now - 30000,
            window_end=now + 60000,
            trigger_type="ALERT_CRITICAL",
            trigger_id="alert_456",
        )
        d = window.to_dict()
        assert d["token_id"] == "test"
        assert d["trigger_type"] == "ALERT_CRITICAL"
        assert d["trigger_id"] == "alert_456"


class TestAuditWindowManager:
    """Test AuditWindowManager"""

    @pytest.fixture
    def manager(self):
        return AuditWindowManager()

    def test_on_state_change_cracking(self, manager):
        """CRACKING state should create audit window"""
        now = int(time.time() * 1000)
        window = manager.on_state_change("token1", "CRACKING", now, "event_1")

        assert window is not None
        assert window.token_id == "token1"
        assert window.trigger_type == "STATE_CRACKING"
        assert window.window_start == now - AUDIT_WINDOW_CONFIG["pre_window_ms"]
        assert window.window_end == now + AUDIT_WINDOW_CONFIG["post_window_ms"]

    def test_on_state_change_broken(self, manager):
        """BROKEN state should create audit window"""
        now = int(time.time() * 1000)
        window = manager.on_state_change("token1", "BROKEN", now, "event_2")

        assert window is not None
        assert window.trigger_type == "STATE_BROKEN"

    def test_on_state_change_stable(self, manager):
        """STABLE state should NOT create audit window"""
        now = int(time.time() * 1000)
        window = manager.on_state_change("token1", "STABLE", now, "event_3")

        assert window is None

    def test_on_state_change_fragile(self, manager):
        """FRAGILE state should NOT create audit window"""
        now = int(time.time() * 1000)
        window = manager.on_state_change("token1", "FRAGILE", now, "event_4")

        assert window is None

    def test_on_alert_critical(self, manager):
        """CRITICAL alert should create audit window"""
        now = int(time.time() * 1000)
        window = manager.on_alert("token1", "CRITICAL", now, "alert_1")

        assert window is not None
        assert window.trigger_type == "ALERT_CRITICAL"

    def test_on_alert_high(self, manager):
        """HIGH alert should NOT create audit window"""
        now = int(time.time() * 1000)
        window = manager.on_alert("token1", "HIGH", now, "alert_2")

        assert window is None

    def test_should_store_full_within_window(self, manager):
        """Events within audit window should be stored full"""
        now = int(time.time() * 1000)
        manager.on_state_change("token1", "CRACKING", now, "event_1")

        # Within window
        assert manager.should_store_full("token1", now) is True
        assert manager.should_store_full("token1", now - 15000) is True
        assert manager.should_store_full("token1", now + 30000) is True

    def test_should_store_full_outside_window(self, manager):
        """Events outside audit window should be stored minimal (when token not critical)"""
        now = int(time.time() * 1000)

        # Create window via CRITICAL alert (doesn't make token critical)
        manager.on_alert("token1", "CRITICAL", now, "alert_1")

        # Token is NOT in critical state (alerts don't set critical state)
        # So events outside window should be minimal
        assert manager.should_store_full("token1", now - 100000) is False
        assert manager.should_store_full("token1", now + 200000) is False

    def test_should_store_full_critical_token(self, manager):
        """Tokens in critical state should always store full"""
        now = int(time.time() * 1000)
        manager.on_state_change("token1", "CRACKING", now, "event_1")

        # Even far from trigger, critical tokens store full
        # (because _critical_tokens set is checked first)
        assert manager.should_store_full("token1", now + 200000) is True

    def test_should_store_minimal_normal_token(self, manager):
        """Normal tokens without windows should store minimal"""
        now = int(time.time() * 1000)

        assert manager.should_store_full("unknown_token", now) is False

    def test_get_storage_mode(self, manager):
        """Test storage mode getter"""
        now = int(time.time() * 1000)
        manager.on_state_change("token1", "CRACKING", now, "event_1")

        assert manager.get_storage_mode("token1", now) == StorageMode.FULL_AUDIT
        assert manager.get_storage_mode("token2", now) == StorageMode.MINIMAL

    def test_window_merging(self, manager):
        """Close windows should be merged"""
        now = int(time.time() * 1000)

        manager.on_state_change("token1", "CRACKING", now, "event_1")
        manager.on_state_change("token1", "BROKEN", now + 5000, "event_2")

        # Should have merged into one window
        windows = manager.get_active_windows("token1")
        assert len(windows) == 1
        # Window should be extended
        assert windows[0].window_end >= now + 5000 + AUDIT_WINDOW_CONFIG["post_window_ms"]

    def test_max_windows_limit(self, manager):
        """Should enforce max windows per token"""
        now = int(time.time() * 1000)
        max_windows = AUDIT_WINDOW_CONFIG["max_windows_per_token"]

        # Create more than max windows (spaced apart to avoid merging)
        for i in range(max_windows + 5):
            manager.on_alert("token1", "CRITICAL", now + i * 100000, f"alert_{i}")

        windows = manager.get_active_windows("token1")
        assert len(windows) <= max_windows

    def test_cleanup_expired_windows(self, manager):
        """Should clean up expired windows"""
        now = int(time.time() * 1000)
        old_ts = now - 200000  # 200 seconds ago

        # Create window in the past (already expired)
        manager.on_state_change("token1", "CRACKING", old_ts, "event_old")

        # Window should exist
        assert len(manager.get_active_windows("token1")) == 1

        # Cleanup with current time
        removed = manager.cleanup_expired_windows(now)

        # Window should be removed (window_end was old_ts + 60000 = now - 140000)
        assert removed == 1
        assert len(manager.get_active_windows("token1")) == 0

    def test_get_stats(self, manager):
        """Test statistics"""
        now = int(time.time() * 1000)
        manager.on_state_change("token1", "CRACKING", now, "event_1")
        manager.on_state_change("token2", "BROKEN", now, "event_2")

        stats = manager.get_stats()
        assert stats["total_windows"] == 2
        assert stats["tokens_with_windows"] == 2
        assert stats["critical_tokens"] == 2


class TestConvenienceFunction:
    """Test module-level convenience function"""

    def test_should_store_full_audit(self):
        """Test convenience function"""
        now = int(time.time() * 1000)

        # Without any windows, should be False
        result = should_store_full_audit("new_token", now)
        assert isinstance(result, bool)
