"""
Belief Reaction System - Real-time WebSocket Stream
v5.9: Implements /v1/stream for real-time event broadcasting
"""

import asyncio
import json
import time
from typing import Dict, Set, Optional, Any, List
from dataclasses import dataclass, field
from enum import Enum
from fastapi import WebSocket, WebSocketDisconnect
import logging

logger = logging.getLogger(__name__)


class StreamEventType(str, Enum):
    """Event types that can be streamed"""
    # Market events
    SHOCK = "shock"
    REACTION = "reaction"
    LEADING_EVENT = "leading_event"
    BELIEF_STATE = "belief_state"

    # Alert events
    ALERT_NEW = "alert.new"
    ALERT_UPDATED = "alert.updated"
    ALERT_RESOLVED = "alert.resolved"

    # Data health events
    TILE_READY = "tile.ready"
    DATA_GAP = "data.gap"
    HASH_MISMATCH = "hash.mismatch"

    # System events
    HEARTBEAT = "heartbeat"
    SUBSCRIPTION_CONFIRMED = "subscription.confirmed"
    ERROR = "error"


@dataclass
class StreamMessage:
    """Message to be sent over WebSocket"""
    type: StreamEventType
    payload: Dict[str, Any]
    ts: int = field(default_factory=lambda: int(time.time() * 1000))
    token_id: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "ts": self.ts,
            "token_id": self.token_id,
            "payload": self.payload
        })


@dataclass
class Subscription:
    """Client subscription preferences"""
    token_ids: Set[str] = field(default_factory=set)  # Empty = all tokens
    event_types: Set[StreamEventType] = field(default_factory=set)  # Empty = all types
    min_severity: Optional[str] = None  # For alerts: LOW, MEDIUM, HIGH, CRITICAL

    def matches(self, msg: StreamMessage) -> bool:
        """Check if message matches subscription filters"""
        # Check token filter
        if self.token_ids and msg.token_id and msg.token_id not in self.token_ids:
            return False

        # Check event type filter
        if self.event_types and msg.type not in self.event_types:
            # Always allow system events
            if msg.type not in (StreamEventType.HEARTBEAT, StreamEventType.ERROR, StreamEventType.SUBSCRIPTION_CONFIRMED):
                return False

        # Check severity filter for alerts
        if self.min_severity and msg.type in (StreamEventType.ALERT_NEW, StreamEventType.ALERT_UPDATED):
            severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
            msg_severity = msg.payload.get("severity", "LOW")
            if severity_order.get(msg_severity, 0) < severity_order.get(self.min_severity, 0):
                return False

        return True


class ConnectionManager:
    """Manages WebSocket connections and message broadcasting"""

    def __init__(self):
        # Map of connection_id -> (websocket, subscription)
        self.connections: Dict[str, tuple[WebSocket, Subscription]] = {}
        self._lock = asyncio.Lock()
        self._connection_counter = 0
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the connection manager"""
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("[STREAM] Connection manager started")

    async def stop(self):
        """Stop the connection manager"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Close all connections
        async with self._lock:
            for conn_id, (ws, _) in list(self.connections.items()):
                try:
                    await ws.close()
                except Exception:
                    pass
            self.connections.clear()

        logger.info("[STREAM] Connection manager stopped")

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection"""
        await websocket.accept()

        async with self._lock:
            self._connection_counter += 1
            conn_id = f"conn_{self._connection_counter}"
            self.connections[conn_id] = (websocket, Subscription())

        logger.info(f"[STREAM] New connection: {conn_id} (total: {len(self.connections)})")

        # Send confirmation
        await self._send_to_connection(conn_id, StreamMessage(
            type=StreamEventType.SUBSCRIPTION_CONFIRMED,
            payload={"connection_id": conn_id, "subscribed_to": "all"}
        ))

        return conn_id

    async def disconnect(self, conn_id: str):
        """Remove a WebSocket connection"""
        async with self._lock:
            if conn_id in self.connections:
                del self.connections[conn_id]
        logger.info(f"[STREAM] Disconnected: {conn_id} (remaining: {len(self.connections)})")

    async def update_subscription(self, conn_id: str, subscription: Subscription):
        """Update subscription for a connection"""
        async with self._lock:
            if conn_id in self.connections:
                ws, _ = self.connections[conn_id]
                self.connections[conn_id] = (ws, subscription)

        # Confirm subscription update
        await self._send_to_connection(conn_id, StreamMessage(
            type=StreamEventType.SUBSCRIPTION_CONFIRMED,
            payload={
                "connection_id": conn_id,
                "token_ids": list(subscription.token_ids) if subscription.token_ids else "all",
                "event_types": [e.value for e in subscription.event_types] if subscription.event_types else "all",
                "min_severity": subscription.min_severity
            }
        ))

    async def broadcast(self, message: StreamMessage):
        """Broadcast message to all matching connections"""
        async with self._lock:
            connections = list(self.connections.items())

        for conn_id, (ws, sub) in connections:
            if sub.matches(message):
                try:
                    await ws.send_text(message.to_json())
                except Exception as e:
                    logger.warning(f"[STREAM] Failed to send to {conn_id}: {e}")
                    # Will be cleaned up by heartbeat or next message

    async def _send_to_connection(self, conn_id: str, message: StreamMessage):
        """Send message to specific connection"""
        async with self._lock:
            if conn_id not in self.connections:
                return
            ws, _ = self.connections[conn_id]

        try:
            await ws.send_text(message.to_json())
        except Exception as e:
            logger.warning(f"[STREAM] Failed to send to {conn_id}: {e}")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to all connections"""
        while self._running:
            try:
                await asyncio.sleep(30)  # Heartbeat every 30 seconds

                msg = StreamMessage(
                    type=StreamEventType.HEARTBEAT,
                    payload={"connections": len(self.connections)}
                )

                async with self._lock:
                    connections = list(self.connections.items())

                dead_connections = []
                for conn_id, (ws, _) in connections:
                    try:
                        await ws.send_text(msg.to_json())
                    except Exception:
                        dead_connections.append(conn_id)

                # Clean up dead connections
                for conn_id in dead_connections:
                    await self.disconnect(conn_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[STREAM] Heartbeat error: {e}")

    @property
    def connection_count(self) -> int:
        return len(self.connections)


# Global connection manager instance
stream_manager = ConnectionManager()


# =============================================================================
# Event Publishing Functions (called by other parts of the system)
# =============================================================================

async def publish_shock(token_id: str, shock_data: Dict[str, Any]):
    """Publish a shock event to all subscribers"""
    await stream_manager.broadcast(StreamMessage(
        type=StreamEventType.SHOCK,
        token_id=token_id,
        payload=shock_data
    ))


async def publish_reaction(token_id: str, reaction_data: Dict[str, Any]):
    """Publish a reaction event to all subscribers"""
    await stream_manager.broadcast(StreamMessage(
        type=StreamEventType.REACTION,
        token_id=token_id,
        payload=reaction_data
    ))


async def publish_leading_event(token_id: str, event_data: Dict[str, Any]):
    """Publish a leading event to all subscribers"""
    await stream_manager.broadcast(StreamMessage(
        type=StreamEventType.LEADING_EVENT,
        token_id=token_id,
        payload=event_data
    ))


async def publish_belief_state(token_id: str, state_data: Dict[str, Any]):
    """Publish a belief state change to all subscribers"""
    await stream_manager.broadcast(StreamMessage(
        type=StreamEventType.BELIEF_STATE,
        token_id=token_id,
        payload=state_data
    ))


async def publish_alert(alert_data: Dict[str, Any], event_type: StreamEventType = StreamEventType.ALERT_NEW):
    """Publish an alert event to all subscribers"""
    await stream_manager.broadcast(StreamMessage(
        type=event_type,
        token_id=alert_data.get("token_id"),
        payload=alert_data
    ))


async def publish_tile_ready(token_id: str, tile_data: Dict[str, Any]):
    """Publish tile ready notification"""
    await stream_manager.broadcast(StreamMessage(
        type=StreamEventType.TILE_READY,
        token_id=token_id,
        payload=tile_data
    ))


async def publish_data_gap(token_id: str, gap_data: Dict[str, Any]):
    """Publish data gap warning"""
    await stream_manager.broadcast(StreamMessage(
        type=StreamEventType.DATA_GAP,
        token_id=token_id,
        payload=gap_data
    ))


async def publish_hash_mismatch(token_id: str, mismatch_data: Dict[str, Any]):
    """Publish hash mismatch alert"""
    await stream_manager.broadcast(StreamMessage(
        type=StreamEventType.HASH_MISMATCH,
        token_id=token_id,
        payload=mismatch_data
    ))


# =============================================================================
# Subscription Message Parser
# =============================================================================

def parse_subscription_message(data: str) -> Optional[Subscription]:
    """
    Parse subscription update message from client.

    Expected format:
    {
        "action": "subscribe",
        "token_ids": ["token1", "token2"],  // optional, empty = all
        "event_types": ["shock", "alert.new"],  // optional, empty = all
        "min_severity": "HIGH"  // optional, for alerts
    }
    """
    try:
        msg = json.loads(data)

        if msg.get("action") != "subscribe":
            return None

        sub = Subscription()

        # Parse token_ids
        if "token_ids" in msg and msg["token_ids"]:
            sub.token_ids = set(msg["token_ids"])

        # Parse event_types
        if "event_types" in msg and msg["event_types"]:
            for et in msg["event_types"]:
                try:
                    sub.event_types.add(StreamEventType(et))
                except ValueError:
                    pass  # Ignore unknown event types

        # Parse min_severity
        if "min_severity" in msg:
            if msg["min_severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                sub.min_severity = msg["min_severity"]

        return sub

    except (json.JSONDecodeError, KeyError, TypeError):
        return None
