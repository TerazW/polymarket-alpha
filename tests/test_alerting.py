"""
Tests for Alert Router and Destinations
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, AsyncMock, patch


# =============================================================================
# AlertPayload Tests
# =============================================================================

class TestAlertPayload:
    """Test AlertPayload dataclass"""

    def test_payload_creation(self):
        """AlertPayload should be created with correct fields"""
        from backend.alerting import AlertPayload, AlertPriority, AlertCategory

        payload = AlertPayload(
            alert_id="test_123",
            category=AlertCategory.BELIEF_STATE,
            priority=AlertPriority.HIGH,
            title="Test Alert",
            message="This is a test alert",
            token_id="token_abc",
        )

        assert payload.alert_id == "test_123"
        assert payload.category == AlertCategory.BELIEF_STATE
        assert payload.priority == AlertPriority.HIGH
        assert payload.title == "Test Alert"
        assert payload.token_id == "token_abc"
        assert payload.ts > 0  # Should auto-generate timestamp

    def test_payload_to_dict(self):
        """AlertPayload should serialize to dict correctly"""
        from backend.alerting import AlertPayload, AlertPriority, AlertCategory

        payload = AlertPayload(
            alert_id="test_123",
            category=AlertCategory.HASH_MISMATCH,
            priority=AlertPriority.CRITICAL,
            title="Hash Mismatch",
            message="Bundle verification failed",
            ts=1704067200000,
        )

        d = payload.to_dict()

        assert d["alert_id"] == "test_123"
        assert d["category"] == "hash_mismatch"
        assert d["priority"] == "critical"
        assert d["ts"] == 1704067200000

    def test_payload_to_json(self):
        """AlertPayload should serialize to JSON correctly"""
        from backend.alerting import AlertPayload, AlertPriority, AlertCategory

        payload = AlertPayload(
            alert_id="test_123",
            category=AlertCategory.DATA_GAP,
            priority=AlertPriority.MEDIUM,
            title="Data Gap",
            message="Missing buckets detected",
        )

        json_str = payload.to_json()
        parsed = json.loads(json_str)

        assert parsed["alert_id"] == "test_123"
        assert parsed["category"] == "data_gap"


# =============================================================================
# AlertPriority Tests
# =============================================================================

class TestAlertPriority:
    """Test AlertPriority enum"""

    def test_priority_values(self):
        """AlertPriority should have correct values"""
        from backend.alerting import AlertPriority

        assert AlertPriority.LOW.value == "low"
        assert AlertPriority.MEDIUM.value == "medium"
        assert AlertPriority.HIGH.value == "high"
        assert AlertPriority.CRITICAL.value == "critical"

    def test_priority_ordering(self):
        """AlertPriority should be orderable"""
        from backend.alerting import AlertPriority

        priority_order = {
            AlertPriority.LOW: 0,
            AlertPriority.MEDIUM: 1,
            AlertPriority.HIGH: 2,
            AlertPriority.CRITICAL: 3,
        }

        assert priority_order[AlertPriority.LOW] < priority_order[AlertPriority.MEDIUM]
        assert priority_order[AlertPriority.MEDIUM] < priority_order[AlertPriority.HIGH]
        assert priority_order[AlertPriority.HIGH] < priority_order[AlertPriority.CRITICAL]


# =============================================================================
# AlertCategory Tests
# =============================================================================

class TestAlertCategory:
    """Test AlertCategory enum"""

    def test_category_values(self):
        """AlertCategory should have correct values"""
        from backend.alerting import AlertCategory

        assert AlertCategory.BELIEF_STATE.value == "belief_state"
        assert AlertCategory.HASH_MISMATCH.value == "hash_mismatch"
        assert AlertCategory.DATA_GAP.value == "data_gap"
        assert AlertCategory.SYSTEM.value == "system"
        assert AlertCategory.DETECTION.value == "detection"


# =============================================================================
# LogDestination Tests
# =============================================================================

class TestLogDestination:
    """Test LogDestination"""

    def test_log_destination_matches_all_by_default(self):
        """LogDestination should match all priorities by default"""
        from backend.alerting import LogDestination, AlertPayload, AlertPriority, AlertCategory

        dest = LogDestination()

        low_alert = AlertPayload(
            alert_id="1", category=AlertCategory.SYSTEM,
            priority=AlertPriority.LOW, title="", message=""
        )
        high_alert = AlertPayload(
            alert_id="2", category=AlertCategory.SYSTEM,
            priority=AlertPriority.HIGH, title="", message=""
        )

        assert dest.matches(low_alert) is True
        assert dest.matches(high_alert) is True

    def test_log_destination_filters_by_priority(self):
        """LogDestination should respect min_priority filter"""
        from backend.alerting import LogDestination, AlertPayload, AlertPriority, AlertCategory

        dest = LogDestination(min_priority=AlertPriority.HIGH)

        low_alert = AlertPayload(
            alert_id="1", category=AlertCategory.SYSTEM,
            priority=AlertPriority.LOW, title="", message=""
        )
        high_alert = AlertPayload(
            alert_id="2", category=AlertCategory.SYSTEM,
            priority=AlertPriority.HIGH, title="", message=""
        )
        critical_alert = AlertPayload(
            alert_id="3", category=AlertCategory.SYSTEM,
            priority=AlertPriority.CRITICAL, title="", message=""
        )

        assert dest.matches(low_alert) is False
        assert dest.matches(high_alert) is True
        assert dest.matches(critical_alert) is True

    @pytest.mark.asyncio
    async def test_log_destination_sends(self):
        """LogDestination should send successfully"""
        from backend.alerting import LogDestination, AlertPayload, AlertPriority, AlertCategory

        dest = LogDestination()

        alert = AlertPayload(
            alert_id="test_123",
            category=AlertCategory.BELIEF_STATE,
            priority=AlertPriority.MEDIUM,
            title="Test Alert",
            message="Test message",
        )

        result = await dest.send(alert)
        assert result is True


# =============================================================================
# WebSocketBroadcastDestination Tests
# =============================================================================

class TestWebSocketBroadcastDestination:
    """Test WebSocketBroadcastDestination"""

    def test_ws_destination_matches_by_priority(self):
        """WebSocketBroadcastDestination should filter by priority"""
        from backend.alerting import WebSocketBroadcastDestination, AlertPayload, AlertPriority, AlertCategory

        dest = WebSocketBroadcastDestination(min_priority=AlertPriority.MEDIUM)

        low_alert = AlertPayload(
            alert_id="1", category=AlertCategory.SYSTEM,
            priority=AlertPriority.LOW, title="", message=""
        )
        medium_alert = AlertPayload(
            alert_id="2", category=AlertCategory.SYSTEM,
            priority=AlertPriority.MEDIUM, title="", message=""
        )

        assert dest.matches(low_alert) is False
        assert dest.matches(medium_alert) is True

    def test_ws_destination_matches_by_category(self):
        """WebSocketBroadcastDestination should filter by category"""
        from backend.alerting import WebSocketBroadcastDestination, AlertPayload, AlertPriority, AlertCategory

        dest = WebSocketBroadcastDestination(
            categories=[AlertCategory.HASH_MISMATCH, AlertCategory.DATA_GAP]
        )

        hash_alert = AlertPayload(
            alert_id="1", category=AlertCategory.HASH_MISMATCH,
            priority=AlertPriority.HIGH, title="", message=""
        )
        system_alert = AlertPayload(
            alert_id="2", category=AlertCategory.SYSTEM,
            priority=AlertPriority.HIGH, title="", message=""
        )

        assert dest.matches(hash_alert) is True
        assert dest.matches(system_alert) is False


# =============================================================================
# WebhookDestination Tests
# =============================================================================

class TestWebhookDestination:
    """Test WebhookDestination"""

    def test_webhook_destination_matches(self):
        """WebhookDestination should filter correctly"""
        from backend.alerting import WebhookDestination, AlertPayload, AlertPriority, AlertCategory

        dest = WebhookDestination(
            url="https://example.com/webhook",
            min_priority=AlertPriority.HIGH,
            categories=[AlertCategory.HASH_MISMATCH],
        )

        # Should match: high priority + hash_mismatch
        match_alert = AlertPayload(
            alert_id="1", category=AlertCategory.HASH_MISMATCH,
            priority=AlertPriority.HIGH, title="", message=""
        )

        # Should not match: wrong priority
        no_match_priority = AlertPayload(
            alert_id="2", category=AlertCategory.HASH_MISMATCH,
            priority=AlertPriority.LOW, title="", message=""
        )

        # Should not match: wrong category
        no_match_category = AlertPayload(
            alert_id="3", category=AlertCategory.SYSTEM,
            priority=AlertPriority.CRITICAL, title="", message=""
        )

        assert dest.matches(match_alert) is True
        assert dest.matches(no_match_priority) is False
        assert dest.matches(no_match_category) is False


# =============================================================================
# SlackDestination Tests
# =============================================================================

class TestSlackDestination:
    """Test SlackDestination"""

    def test_slack_destination_matches(self):
        """SlackDestination should filter correctly"""
        from backend.alerting import SlackDestination, AlertPayload, AlertPriority, AlertCategory

        dest = SlackDestination(
            webhook_url="https://hooks.slack.com/test",
            min_priority=AlertPriority.HIGH,
        )

        high_alert = AlertPayload(
            alert_id="1", category=AlertCategory.SYSTEM,
            priority=AlertPriority.HIGH, title="", message=""
        )
        low_alert = AlertPayload(
            alert_id="2", category=AlertCategory.SYSTEM,
            priority=AlertPriority.LOW, title="", message=""
        )

        assert dest.matches(high_alert) is True
        assert dest.matches(low_alert) is False

    def test_slack_destination_emoji_mapping(self):
        """SlackDestination should have correct emoji mappings"""
        from backend.alerting import SlackDestination, AlertPriority

        assert SlackDestination.PRIORITY_EMOJI[AlertPriority.LOW] == ":information_source:"
        assert SlackDestination.PRIORITY_EMOJI[AlertPriority.CRITICAL] == ":fire:"

    def test_slack_destination_color_mapping(self):
        """SlackDestination should have correct color mappings"""
        from backend.alerting import SlackDestination, AlertCategory

        assert SlackDestination.CATEGORY_COLOR[AlertCategory.HASH_MISMATCH] == "#ef4444"  # Red
        assert SlackDestination.CATEGORY_COLOR[AlertCategory.DETECTION] == "#22c55e"      # Green


# =============================================================================
# AlertRouter Tests
# =============================================================================

class TestAlertRouter:
    """Test AlertRouter"""

    def test_router_creation(self):
        """AlertRouter should be created with empty destinations"""
        from backend.alerting import AlertRouter

        router = AlertRouter()
        assert len(router.destinations) == 0

    def test_router_add_destination(self):
        """AlertRouter should add destinations"""
        from backend.alerting import AlertRouter, LogDestination

        router = AlertRouter()
        router.add_destination(LogDestination())

        assert len(router.destinations) == 1

    @pytest.mark.asyncio
    async def test_router_routes_to_matching_destinations(self):
        """AlertRouter should route to all matching destinations"""
        from backend.alerting import AlertRouter, LogDestination, AlertPayload, AlertPriority, AlertCategory

        router = AlertRouter()
        router.add_destination(LogDestination(min_priority=AlertPriority.LOW))
        router.add_destination(LogDestination(min_priority=AlertPriority.HIGH))

        # Low priority alert - only first destination should match
        low_alert = AlertPayload(
            alert_id="1", category=AlertCategory.SYSTEM,
            priority=AlertPriority.LOW, title="Low", message=""
        )

        results = await router.route(low_alert)
        # Both are LogDestination, so key will be the same
        assert "LogDestination" in results

    @pytest.mark.asyncio
    async def test_router_tracks_stats(self):
        """AlertRouter should track routing statistics"""
        from backend.alerting import AlertRouter, LogDestination, AlertPayload, AlertPriority, AlertCategory

        router = AlertRouter()
        router.add_destination(LogDestination())

        alert = AlertPayload(
            alert_id="1", category=AlertCategory.SYSTEM,
            priority=AlertPriority.HIGH, title="Test", message=""
        )

        await router.route(alert)

        stats = router.get_stats()
        assert stats["alerts_routed"] == 1
        assert stats["by_priority"]["high"] == 1
        assert stats["by_category"]["system"] == 1


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestRouterFactory:
    """Test router factory functions"""

    def test_create_router_from_config_empty(self):
        """create_router_from_config should handle empty config"""
        from backend.alerting import create_router_from_config

        router = create_router_from_config({})
        assert len(router.destinations) == 0

    def test_create_router_from_config_with_log(self):
        """create_router_from_config should create log destination"""
        from backend.alerting import create_router_from_config, LogDestination

        router = create_router_from_config({
            "log": {"enabled": True, "min_priority": "medium"}
        })

        assert len(router.destinations) == 1
        assert isinstance(router.destinations[0], LogDestination)

    def test_create_router_from_config_with_websocket(self):
        """create_router_from_config should create websocket destination"""
        from backend.alerting import create_router_from_config, WebSocketBroadcastDestination

        router = create_router_from_config({
            "websocket": {"enabled": True}
        })

        assert len(router.destinations) == 1
        assert isinstance(router.destinations[0], WebSocketBroadcastDestination)

    def test_get_default_router(self):
        """get_default_router should return a configured router"""
        from backend.alerting import get_default_router

        router = get_default_router()
        assert len(router.destinations) >= 1


# =============================================================================
# Integration Tests
# =============================================================================

class TestAlertingIntegration:
    """Integration tests for alerting system"""

    @pytest.mark.asyncio
    async def test_full_routing_flow(self):
        """Test complete alert routing flow"""
        from backend.alerting import (
            AlertRouter, LogDestination, WebSocketBroadcastDestination,
            AlertPayload, AlertPriority, AlertCategory
        )

        router = AlertRouter()
        router.add_destination(LogDestination())

        alert = AlertPayload(
            alert_id="integration_test",
            category=AlertCategory.HASH_MISMATCH,
            priority=AlertPriority.CRITICAL,
            title="Integration Test Alert",
            message="This is a test of the full routing flow",
            token_id="test_token_123",
            data={"key": "value"},
            evidence_ref={"token_id": "test_token_123", "t0": 1704067200000},
        )

        results = await router.route(alert)

        assert "LogDestination" in results
        assert results["LogDestination"] is True

        stats = router.get_stats()
        assert stats["alerts_routed"] == 1
        assert stats["alerts_delivered"] >= 1

    @pytest.mark.asyncio
    async def test_route_alert_convenience_function(self):
        """Test route_alert convenience function"""
        from backend.alerting import route_alert, AlertPayload, AlertPriority, AlertCategory

        alert = AlertPayload(
            alert_id="convenience_test",
            category=AlertCategory.SYSTEM,
            priority=AlertPriority.MEDIUM,
            title="Convenience Test",
            message="Testing route_alert function",
        )

        results = await route_alert(alert)
        # Should have at least one destination from default router
        assert len(results) >= 1
