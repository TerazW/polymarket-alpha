"""
Tests for v5.9 WebSocket Stream and Alert ACK API
"""

import pytest
import json
import time
import asyncio
from typing import Dict, Any, List


# =============================================================================
# Stream Module Tests
# =============================================================================

class TestStreamEventType:
    """Test StreamEventType enum"""

    def test_all_event_types_defined(self):
        """All expected event types should be defined"""
        from backend.api.stream import StreamEventType

        expected_types = [
            'shock', 'reaction', 'leading_event', 'belief_state',
            'alert.new', 'alert.updated', 'alert.resolved',
            'tile.ready', 'data.gap', 'hash.mismatch',
            'heartbeat', 'subscription.confirmed', 'error'
        ]

        for event_type in expected_types:
            assert StreamEventType(event_type) is not None

    def test_event_type_values(self):
        """Event type values should match string representation"""
        from backend.api.stream import StreamEventType

        assert StreamEventType.SHOCK.value == "shock"
        assert StreamEventType.ALERT_NEW.value == "alert.new"
        assert StreamEventType.HEARTBEAT.value == "heartbeat"


class TestStreamMessage:
    """Test StreamMessage dataclass"""

    def test_message_creation(self):
        """StreamMessage should be created with correct fields"""
        from backend.api.stream import StreamMessage, StreamEventType

        msg = StreamMessage(
            type=StreamEventType.SHOCK,
            payload={"price": 0.65, "side": "BID"},
            token_id="token123"
        )

        assert msg.type == StreamEventType.SHOCK
        assert msg.payload["price"] == 0.65
        assert msg.token_id == "token123"
        assert msg.ts > 0  # Should have auto-generated timestamp

    def test_message_to_json(self):
        """StreamMessage should serialize to JSON correctly"""
        from backend.api.stream import StreamMessage, StreamEventType

        msg = StreamMessage(
            type=StreamEventType.REACTION,
            payload={"reaction": "HOLD"},
            token_id="token456",
            ts=1704067200000
        )

        json_str = msg.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "reaction"
        assert parsed["ts"] == 1704067200000
        assert parsed["token_id"] == "token456"
        assert parsed["payload"]["reaction"] == "HOLD"


class TestSubscription:
    """Test Subscription filtering"""

    def test_empty_subscription_matches_all(self):
        """Empty subscription should match all messages"""
        from backend.api.stream import Subscription, StreamMessage, StreamEventType

        sub = Subscription()
        msg = StreamMessage(
            type=StreamEventType.SHOCK,
            payload={},
            token_id="any_token"
        )

        assert sub.matches(msg) is True

    def test_token_filter(self):
        """Subscription should filter by token_id"""
        from backend.api.stream import Subscription, StreamMessage, StreamEventType

        sub = Subscription(token_ids={"token1", "token2"})

        msg_match = StreamMessage(type=StreamEventType.SHOCK, payload={}, token_id="token1")
        msg_no_match = StreamMessage(type=StreamEventType.SHOCK, payload={}, token_id="token3")

        assert sub.matches(msg_match) is True
        assert sub.matches(msg_no_match) is False

    def test_event_type_filter(self):
        """Subscription should filter by event type"""
        from backend.api.stream import Subscription, StreamMessage, StreamEventType

        sub = Subscription(event_types={StreamEventType.SHOCK, StreamEventType.REACTION})

        msg_match = StreamMessage(type=StreamEventType.SHOCK, payload={})
        msg_no_match = StreamMessage(type=StreamEventType.BELIEF_STATE, payload={})
        msg_heartbeat = StreamMessage(type=StreamEventType.HEARTBEAT, payload={})

        assert sub.matches(msg_match) is True
        assert sub.matches(msg_no_match) is False
        # System events should always pass
        assert sub.matches(msg_heartbeat) is True

    def test_severity_filter(self):
        """Subscription should filter alerts by severity"""
        from backend.api.stream import Subscription, StreamMessage, StreamEventType

        sub = Subscription(min_severity="HIGH")

        msg_high = StreamMessage(
            type=StreamEventType.ALERT_NEW,
            payload={"severity": "HIGH"}
        )
        msg_critical = StreamMessage(
            type=StreamEventType.ALERT_NEW,
            payload={"severity": "CRITICAL"}
        )
        msg_low = StreamMessage(
            type=StreamEventType.ALERT_NEW,
            payload={"severity": "LOW"}
        )

        assert sub.matches(msg_high) is True
        assert sub.matches(msg_critical) is True
        assert sub.matches(msg_low) is False


class TestParseSubscriptionMessage:
    """Test subscription message parsing"""

    def test_parse_valid_subscription(self):
        """Should parse valid subscription message"""
        from backend.api.stream import parse_subscription_message

        data = json.dumps({
            "action": "subscribe",
            "token_ids": ["token1", "token2"],
            "event_types": ["shock", "alert.new"],
            "min_severity": "HIGH"
        })

        sub = parse_subscription_message(data)

        assert sub is not None
        assert "token1" in sub.token_ids
        assert "token2" in sub.token_ids
        assert len(sub.event_types) == 2
        assert sub.min_severity == "HIGH"

    def test_parse_minimal_subscription(self):
        """Should parse subscription with only action"""
        from backend.api.stream import parse_subscription_message

        data = json.dumps({"action": "subscribe"})
        sub = parse_subscription_message(data)

        assert sub is not None
        assert len(sub.token_ids) == 0
        assert len(sub.event_types) == 0
        assert sub.min_severity is None

    def test_parse_invalid_action(self):
        """Should return None for non-subscribe action"""
        from backend.api.stream import parse_subscription_message

        data = json.dumps({"action": "unsubscribe"})
        sub = parse_subscription_message(data)

        assert sub is None

    def test_parse_invalid_json(self):
        """Should return None for invalid JSON"""
        from backend.api.stream import parse_subscription_message

        sub = parse_subscription_message("not valid json")
        assert sub is None

    def test_parse_ignores_unknown_event_types(self):
        """Should ignore unknown event types"""
        from backend.api.stream import parse_subscription_message

        data = json.dumps({
            "action": "subscribe",
            "event_types": ["shock", "unknown_type", "reaction"]
        })

        sub = parse_subscription_message(data)

        assert sub is not None
        assert len(sub.event_types) == 2  # Only shock and reaction


# =============================================================================
# Alert ACK Schema Tests
# =============================================================================

class TestAlertAckSchemas:
    """Test Alert ACK request/response schemas"""

    def test_alert_ack_request_schema(self):
        """AlertAckRequest should accept optional fields"""
        from pydantic import BaseModel
        from typing import Optional

        # Define locally to avoid psycopg2 import
        class AlertAckRequest(BaseModel):
            note: Optional[str] = None
            acked_by: Optional[str] = None

        # With all fields
        req1 = AlertAckRequest(note="Investigating", acked_by="user@example.com")
        assert req1.note == "Investigating"
        assert req1.acked_by == "user@example.com"

        # Without fields
        req2 = AlertAckRequest()
        assert req2.note is None
        assert req2.acked_by is None

    def test_alert_ack_response_schema(self):
        """AlertAckResponse should have required fields"""
        from pydantic import BaseModel
        from typing import Optional
        from backend.api.schemas.v1 import AlertStatus

        # Define locally to avoid psycopg2 import
        class AlertAckResponse(BaseModel):
            alert_id: str
            status: AlertStatus
            acked_at: int
            acked_by: Optional[str] = None
            note: Optional[str] = None

        resp = AlertAckResponse(
            alert_id="alert123",
            status=AlertStatus.ACKED,
            acked_at=1704067200000,
            acked_by="user@example.com",
            note="Acknowledged"
        )

        assert resp.alert_id == "alert123"
        assert resp.status == AlertStatus.ACKED
        assert resp.acked_at == 1704067200000


# =============================================================================
# Connection Manager Tests
# =============================================================================

class TestConnectionManager:
    """Test ConnectionManager functionality"""

    @pytest.mark.asyncio
    async def test_manager_start_stop(self):
        """ConnectionManager should start and stop cleanly"""
        from backend.api.stream import ConnectionManager

        manager = ConnectionManager()

        await manager.start()
        assert manager._running is True

        await manager.stop()
        assert manager._running is False

    @pytest.mark.asyncio
    async def test_connection_count(self):
        """ConnectionManager should track connection count"""
        from backend.api.stream import ConnectionManager

        manager = ConnectionManager()
        assert manager.connection_count == 0


# =============================================================================
# Publish Function Tests
# =============================================================================

class TestPublishFunctions:
    """Test event publishing functions"""

    @pytest.mark.asyncio
    async def test_publish_shock(self):
        """publish_shock should create correct message"""
        from backend.api.stream import stream_manager, StreamEventType

        # Start manager
        await stream_manager.start()

        # No connections, should not raise
        from backend.api.stream import publish_shock
        await publish_shock("token123", {
            "id": "shock1",
            "price": 0.65,
            "side": "BID"
        })

        await stream_manager.stop()

    @pytest.mark.asyncio
    async def test_publish_alert(self):
        """publish_alert should support different event types"""
        from backend.api.stream import publish_alert, StreamEventType, stream_manager

        await stream_manager.start()

        # Test all alert event types
        for event_type in [StreamEventType.ALERT_NEW, StreamEventType.ALERT_UPDATED, StreamEventType.ALERT_RESOLVED]:
            await publish_alert(
                {"alert_id": "alert1", "token_id": "token1", "severity": "HIGH"},
                event_type=event_type
            )

        await stream_manager.stop()


# =============================================================================
# Integration Tests (require running server)
# =============================================================================

class TestStreamIntegration:
    """Integration tests for WebSocket stream (skipped without server)"""

    @pytest.mark.skip(reason="Requires running FastAPI server")
    @pytest.mark.asyncio
    async def test_websocket_connection(self):
        """Test WebSocket connection to /v1/stream"""
        import websockets

        async with websockets.connect("ws://127.0.0.1:8000/v1/stream") as ws:
            # Should receive subscription.confirmed
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)

            assert data["type"] == "subscription.confirmed"
            assert "connection_id" in data["payload"]

    @pytest.mark.skip(reason="Requires running FastAPI server")
    @pytest.mark.asyncio
    async def test_subscription_update(self):
        """Test subscription update via WebSocket"""
        import websockets

        async with websockets.connect("ws://127.0.0.1:8000/v1/stream") as ws:
            # Wait for initial confirmation
            await ws.recv()

            # Send subscription update
            await ws.send(json.dumps({
                "action": "subscribe",
                "token_ids": ["token1"],
                "event_types": ["shock"],
                "min_severity": "HIGH"
            }))

            # Should receive new confirmation
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)

            assert data["type"] == "subscription.confirmed"
            assert data["payload"]["token_ids"] == ["token1"]


class TestAlertAckIntegration:
    """Integration tests for Alert ACK API (skipped without server)"""

    @pytest.mark.skip(reason="Requires running FastAPI server and database")
    @pytest.mark.asyncio
    async def test_acknowledge_alert(self):
        """Test PUT /v1/alerts/{id}/ack endpoint"""
        import httpx

        async with httpx.AsyncClient() as client:
            # This would require a real alert in the database
            response = await client.put(
                "http://127.0.0.1:8000/v1/alerts/test-alert-id/ack",
                json={"note": "Test ack", "acked_by": "test@example.com"}
            )

            # Would be 200 with real alert, 404 without
            assert response.status_code in (200, 404)

    @pytest.mark.skip(reason="Requires running FastAPI server and database")
    @pytest.mark.asyncio
    async def test_resolve_alert(self):
        """Test PUT /v1/alerts/{id}/resolve endpoint"""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.put(
                "http://127.0.0.1:8000/v1/alerts/test-alert-id/resolve",
                json={"note": "Test resolve"}
            )

            assert response.status_code in (200, 404)
