"""
Belief Reaction System - Event Bus v1
Abstract interface for event passing between Collector and Reactor.

Supports:
1. In-memory queue (for single-process deployment)
2. DB-backed queue (for multi-process/replay scenarios)

"看存在没意义，看反应才有意义"
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Callable, Any, Iterator
from queue import Queue, Empty
from decimal import Decimal
import threading
import time
import json
import uuid


class EventType(Enum):
    """Raw event types from WebSocket"""
    BOOK = "book"
    TRADE = "trade"
    PRICE_CHANGE = "price_change"


@dataclass
class RawEvent:
    """
    Raw event from WebSocket, ready for processing.

    This is the standard format between Collector and Reactor.
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.TRADE
    server_ts: int = 0           # Server receive timestamp (milliseconds)
    seq_num: int = 0             # Monotonic sequence number
    token_id: str = ""
    payload: Dict = field(default_factory=dict)

    # Original timestamps for reference
    client_ts: Optional[int] = None  # Client local time
    ws_ts: Optional[int] = None      # WebSocket message timestamp

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "server_ts": self.server_ts,
            "seq_num": self.seq_num,
            "token_id": self.token_id,
            "payload": self.payload,
            "client_ts": self.client_ts,
            "ws_ts": self.ws_ts,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict) -> 'RawEvent':
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=EventType(data.get("event_type", "trade")),
            server_ts=data.get("server_ts", 0),
            seq_num=data.get("seq_num", 0),
            token_id=data.get("token_id", ""),
            payload=data.get("payload", {}),
            client_ts=data.get("client_ts"),
            ws_ts=data.get("ws_ts"),
        )

    @property
    def sort_key(self) -> tuple:
        """Deterministic sort key for replay"""
        return (self.server_ts, self.seq_num)


class EventBus(ABC):
    """
    Abstract event bus interface.

    Collector publishes events → EventBus → Reactor consumes events
    """

    @abstractmethod
    def publish(self, event: RawEvent) -> None:
        """Publish an event to the bus"""
        pass

    @abstractmethod
    def subscribe(self, callback: Callable[[RawEvent], None]) -> None:
        """Subscribe to events with a callback"""
        pass

    @abstractmethod
    def poll(self, timeout_ms: int = 100) -> Optional[RawEvent]:
        """Poll for next event (blocking with timeout)"""
        pass

    @abstractmethod
    def get_stats(self) -> dict:
        """Get bus statistics"""
        pass


class InMemoryEventBus(EventBus):
    """
    In-memory event bus using Python Queue.

    Suitable for single-process deployment.
    """

    def __init__(self, max_size: int = 10000):
        self.queue: Queue = Queue(maxsize=max_size)
        self.subscribers: List[Callable[[RawEvent], None]] = []
        self.lock = threading.Lock()

        # Sequence number generator
        self._seq_counter = 0
        self._seq_lock = threading.Lock()

        # Stats
        self.stats = {
            "published": 0,
            "consumed": 0,
            "dropped": 0,
        }

    def next_seq(self) -> int:
        """Generate next sequence number"""
        with self._seq_lock:
            self._seq_counter += 1
            return self._seq_counter

    def publish(self, event: RawEvent) -> None:
        """Publish event to queue and notify subscribers"""
        # Assign sequence number if not set
        if event.seq_num == 0:
            event.seq_num = self.next_seq()

        # Try to add to queue
        try:
            self.queue.put_nowait(event)
            self.stats["published"] += 1
        except:
            self.stats["dropped"] += 1
            return

        # Notify subscribers (non-blocking)
        with self.lock:
            for callback in self.subscribers:
                try:
                    callback(event)
                except Exception as e:
                    print(f"Subscriber error: {e}")

    def subscribe(self, callback: Callable[[RawEvent], None]) -> None:
        """Add a subscriber callback"""
        with self.lock:
            self.subscribers.append(callback)

    def poll(self, timeout_ms: int = 100) -> Optional[RawEvent]:
        """Poll for next event"""
        try:
            event = self.queue.get(timeout=timeout_ms / 1000)
            self.stats["consumed"] += 1
            return event
        except Empty:
            return None

    def poll_batch(self, max_count: int = 100, timeout_ms: int = 100) -> List[RawEvent]:
        """Poll for a batch of events"""
        events = []
        deadline = time.time() + (timeout_ms / 1000)

        while len(events) < max_count and time.time() < deadline:
            remaining = int((deadline - time.time()) * 1000)
            if remaining <= 0:
                break

            event = self.poll(min(remaining, 10))
            if event:
                events.append(event)
            else:
                break

        return events

    def get_stats(self) -> dict:
        return {
            **self.stats,
            "queue_size": self.queue.qsize(),
            "subscribers": len(self.subscribers),
        }


class DBBackedEventBus(EventBus):
    """
    Database-backed event bus using raw_events table.

    Suitable for:
    - Multi-process deployment
    - Replay scenarios
    - Audit trail
    """

    def __init__(self, db_conn, write_through: bool = True):
        """
        Args:
            db_conn: Database connection
            write_through: If True, also keeps in-memory queue for low latency
        """
        self.db = db_conn
        self.write_through = write_through

        # In-memory queue for write-through
        if write_through:
            self.memory_bus = InMemoryEventBus()
        else:
            self.memory_bus = None

        # Sequence number generator
        self._seq_counter = 0
        self._seq_lock = threading.Lock()

        # Last consumed position
        self._last_consumed_ts = 0
        self._last_consumed_seq = 0

        # Stats
        self.stats = {
            "published": 0,
            "consumed": 0,
            "db_writes": 0,
            "db_reads": 0,
        }

    def next_seq(self) -> int:
        """Generate next sequence number"""
        with self._seq_lock:
            self._seq_counter += 1
            return self._seq_counter

    def publish(self, event: RawEvent) -> None:
        """Publish event to DB and optionally to memory queue"""
        # Assign sequence number
        if event.seq_num == 0:
            event.seq_num = self.next_seq()

        # Write to database
        self._write_to_db(event)
        self.stats["published"] += 1
        self.stats["db_writes"] += 1

        # Write-through to memory
        if self.memory_bus:
            self.memory_bus.publish(event)

    def _write_to_db(self, event: RawEvent):
        """Write event to raw_events table"""
        query = """
            INSERT INTO raw_events (
                event_id, server_ts, seq_num, token_id,
                msg_type, raw_payload, client_ts, ws_ts
            ) VALUES (
                %s, to_timestamp(%s/1000.0), %s, %s,
                %s, %s, to_timestamp(%s/1000.0), to_timestamp(%s/1000.0)
            )
        """
        self.db.execute(query, (
            event.event_id,
            event.server_ts,
            event.seq_num,
            event.token_id,
            event.event_type.value,
            json.dumps(event.payload),
            event.client_ts,
            event.ws_ts,
        ))

    def subscribe(self, callback: Callable[[RawEvent], None]) -> None:
        """Subscribe to events (only works with write-through)"""
        if self.memory_bus:
            self.memory_bus.subscribe(callback)
        else:
            raise NotImplementedError("Subscribe requires write_through=True")

    def poll(self, timeout_ms: int = 100) -> Optional[RawEvent]:
        """Poll for next event from memory queue (write-through mode)"""
        if self.memory_bus:
            return self.memory_bus.poll(timeout_ms)
        else:
            # Poll from DB (for replay mode)
            return self._poll_from_db()

    def _poll_from_db(self) -> Optional[RawEvent]:
        """Poll next event from database"""
        query = """
            SELECT event_id, server_ts, seq_num, token_id,
                   msg_type, raw_payload, client_ts, ws_ts
            FROM raw_events
            WHERE (server_ts, seq_num) > (to_timestamp(%s/1000.0), %s)
            ORDER BY server_ts, seq_num
            LIMIT 1
        """
        row = self.db.fetchone(query, (
            self._last_consumed_ts,
            self._last_consumed_seq
        ))

        if row:
            event = self._row_to_event(row)
            self._last_consumed_ts = event.server_ts
            self._last_consumed_seq = event.seq_num
            self.stats["consumed"] += 1
            self.stats["db_reads"] += 1
            return event

        return None

    def _row_to_event(self, row: tuple) -> RawEvent:
        """Convert DB row to RawEvent"""
        return RawEvent(
            event_id=str(row[0]),
            server_ts=int(row[1].timestamp() * 1000) if row[1] else 0,
            seq_num=row[2],
            token_id=row[3],
            event_type=EventType(row[4]),
            payload=row[5] if isinstance(row[5], dict) else json.loads(row[5]),
            client_ts=int(row[6].timestamp() * 1000) if row[6] else None,
            ws_ts=int(row[7].timestamp() * 1000) if row[7] else None,
        )

    def replay(
        self,
        start_ts: int,
        end_ts: int,
        token_ids: Optional[List[str]] = None
    ) -> Iterator[RawEvent]:
        """
        Replay events from database.

        Yields events in deterministic order.
        """
        query = """
            SELECT event_id, server_ts, seq_num, token_id,
                   msg_type, raw_payload, client_ts, ws_ts
            FROM raw_events
            WHERE server_ts >= to_timestamp(%s/1000.0)
              AND server_ts < to_timestamp(%s/1000.0)
        """
        params = [start_ts, end_ts]

        if token_ids:
            query += " AND token_id = ANY(%s)"
            params.append(token_ids)

        query += " ORDER BY server_ts, seq_num"

        rows = self.db.fetchall(query, tuple(params))

        for row in rows:
            self.stats["db_reads"] += 1
            yield self._row_to_event(row)

    def get_stats(self) -> dict:
        stats = {**self.stats}
        if self.memory_bus:
            stats["memory_bus"] = self.memory_bus.get_stats()
        return stats


# Factory function
def create_event_bus(
    mode: str = "memory",
    db_conn=None,
    **kwargs
) -> EventBus:
    """
    Create an event bus.

    Args:
        mode: "memory" or "db"
        db_conn: Database connection (required for "db" mode)
    """
    if mode == "memory":
        return InMemoryEventBus(**kwargs)
    elif mode == "db":
        if db_conn is None:
            raise ValueError("db_conn required for DB mode")
        return DBBackedEventBus(db_conn, **kwargs)
    else:
        raise ValueError(f"Unknown mode: {mode}")
