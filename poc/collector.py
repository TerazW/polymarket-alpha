"""
Belief Reaction System - Data Collector v1
Handles WebSocket connection and publishes raw events to EventBus.

Responsibilities:
1. WebSocket connection management
2. Message parsing and normalization
3. Publishing to EventBus (with timestamps and sequence numbers)
4. Connection state management (disconnect/reconnect)

Does NOT:
- Process events (that's the Reactor's job)
- Maintain order book state
- Classify reactions

"看存在没意义，看反应才有意义"
"""

import json
import time
import threading
from typing import List, Optional, Callable, Dict
from enum import Enum
from dataclasses import dataclass
from decimal import Decimal

from websocket import WebSocketApp

from .event_bus import EventBus, RawEvent, EventType
from .config import WS_ENDPOINT, WS_PING_INTERVAL


class ConnectionState(Enum):
    """WebSocket connection state"""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"


@dataclass
class CollectorStats:
    """Collector statistics"""
    messages_received: int = 0
    messages_published: int = 0
    parse_errors: int = 0
    connection_count: int = 0
    disconnect_count: int = 0
    last_message_ts: int = 0


class DataCollector:
    """
    WebSocket data collector.

    Connects to Polymarket WebSocket and publishes raw events to EventBus.
    """

    def __init__(
        self,
        event_bus: EventBus,
        token_ids: List[str],
        on_state_change: Optional[Callable[[ConnectionState], None]] = None,
    ):
        self.event_bus = event_bus
        self.token_ids = token_ids
        self.on_state_change_callback = on_state_change

        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self.ws: Optional[WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ping_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

        # Reconnection parameters
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0
        self.reconnect_multiplier = 2.0

        # Stats
        self.stats = CollectorStats()

    def start(self):
        """Start the collector"""
        self.stop_event.clear()
        self._connect()

    def stop(self):
        """Stop the collector"""
        self.stop_event.set()

        if self.ws:
            self.ws.close()

        if self.ws_thread:
            self.ws_thread.join(timeout=5)

        self._set_state(ConnectionState.DISCONNECTED)

    def _set_state(self, new_state: ConnectionState):
        """Update connection state"""
        if new_state != self.state:
            old_state = self.state
            self.state = new_state

            if self.on_state_change_callback:
                self.on_state_change_callback(new_state)

    def _connect(self):
        """Establish WebSocket connection"""
        self._set_state(ConnectionState.CONNECTING)

        self.ws = WebSocketApp(
            WS_ENDPOINT,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ws_thread.start()

    def _run_ws(self):
        """Run WebSocket in thread"""
        while not self.stop_event.is_set():
            try:
                self.ws.run_forever()
            except Exception as e:
                print(f"WebSocket error: {e}")

            if self.stop_event.is_set():
                break

            # Reconnect with backoff
            self._set_state(ConnectionState.RECONNECTING)
            time.sleep(self.reconnect_delay)
            self.reconnect_delay = min(
                self.reconnect_delay * self.reconnect_multiplier,
                self.max_reconnect_delay
            )

    def _on_open(self, ws):
        """Handle WebSocket open"""
        self._set_state(ConnectionState.CONNECTED)
        self.reconnect_delay = 1.0  # Reset backoff
        self.stats.connection_count += 1

        # Subscribe to markets
        subscribe_msg = {
            "assets_ids": self.token_ids,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))

        # Start ping loop
        self.ping_thread = threading.Thread(
            target=self._ping_loop,
            daemon=True
        )
        self.ping_thread.start()

    def _on_message(self, ws, message: str):
        """Handle WebSocket message"""
        server_ts = int(time.time() * 1000)
        self.stats.messages_received += 1
        self.stats.last_message_ts = server_ts

        # Ignore PONG
        if message == "PONG":
            return

        try:
            data = json.loads(message)
            events = self._parse_message(data, server_ts)

            for event in events:
                self.event_bus.publish(event)
                self.stats.messages_published += 1

        except json.JSONDecodeError:
            self.stats.parse_errors += 1
        except Exception as e:
            self.stats.parse_errors += 1
            print(f"Error parsing message: {e}")

    def _on_error(self, ws, error):
        """Handle WebSocket error"""
        print(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        self.stats.disconnect_count += 1

        if not self.stop_event.is_set():
            self._set_state(ConnectionState.RECONNECTING)

    def _ping_loop(self):
        """Send periodic pings"""
        while not self.stop_event.is_set() and self.state == ConnectionState.CONNECTED:
            try:
                if self.ws:
                    self.ws.send("PING")
            except:
                break

            self.stop_event.wait(WS_PING_INTERVAL)

    def _parse_message(self, data: dict, server_ts: int) -> List[RawEvent]:
        """
        Parse WebSocket message into RawEvents.

        Returns list of events (usually 1, but price_change can have multiple).
        """
        events = []
        event_type_str = data.get("event_type", "")

        if event_type_str == "book":
            # Book snapshot
            token_id = data.get("asset_id", "")
            ws_ts = int(data.get("timestamp", 0))

            events.append(RawEvent(
                event_type=EventType.BOOK,
                server_ts=server_ts,
                token_id=token_id,
                payload=data,
                ws_ts=ws_ts,
            ))

        elif event_type_str == "last_trade_price":
            # Trade
            token_id = data.get("asset_id", "")
            ws_ts = int(data.get("timestamp", 0))

            events.append(RawEvent(
                event_type=EventType.TRADE,
                server_ts=server_ts,
                token_id=token_id,
                payload=data,
                ws_ts=ws_ts,
            ))

        elif event_type_str == "price_change":
            # Price change - may contain multiple changes
            ws_ts = int(data.get("timestamp", 0))

            for change in data.get("price_changes", []):
                token_id = change.get("asset_id", "")

                events.append(RawEvent(
                    event_type=EventType.PRICE_CHANGE,
                    server_ts=server_ts,
                    token_id=token_id,
                    payload=change,  # Just the change, not the wrapper
                    ws_ts=ws_ts,
                ))

        return events

    def get_stats(self) -> dict:
        """Get collector statistics"""
        return {
            "state": self.state.value,
            "messages_received": self.stats.messages_received,
            "messages_published": self.stats.messages_published,
            "parse_errors": self.stats.parse_errors,
            "connection_count": self.stats.connection_count,
            "disconnect_count": self.stats.disconnect_count,
            "last_message_ts": self.stats.last_message_ts,
            "subscribed_tokens": len(self.token_ids),
        }

    def add_tokens(self, token_ids: List[str]):
        """Add tokens to subscription (requires reconnect)"""
        new_tokens = [t for t in token_ids if t not in self.token_ids]
        if new_tokens:
            self.token_ids.extend(new_tokens)

            # Re-subscribe if connected
            if self.ws and self.state == ConnectionState.CONNECTED:
                subscribe_msg = {
                    "assets_ids": new_tokens,
                    "type": "market"
                }
                self.ws.send(json.dumps(subscribe_msg))

    def remove_tokens(self, token_ids: List[str]):
        """Remove tokens from subscription"""
        self.token_ids = [t for t in self.token_ids if t not in token_ids]
