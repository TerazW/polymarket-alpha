"""
Determinism Infrastructure

Ensures reproducible event processing for audit and replay.

Core principles:
1. Event time is the ONLY source of truth (never wall clock)
2. Single token = serial processing (no concurrent state mutation)
3. Sort key (token_id, ts_ms, sort_seq) is canonical ordering

"确定性是可审计性的基石"
"""

import threading
import asyncio
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from contextlib import contextmanager
from enum import Enum
from collections import defaultdict
import queue


class DeterminismError(Exception):
    """Raised when determinism constraints are violated"""
    pass


class ProcessingMode(Enum):
    """Processing mode affects time source"""
    LIVE = "live"        # Wall clock allowed for non-critical paths
    REPLAY = "replay"    # Event time ONLY, strict determinism


@dataclass
class EventSortKey:
    """
    Canonical sort key for event ordering.

    All events MUST be processed in this order for deterministic results.
    """
    token_id: str
    ts_ms: int
    sort_seq: int = 0  # Tie-breaker for same-timestamp events

    def __lt__(self, other: 'EventSortKey') -> bool:
        if self.token_id != other.token_id:
            return self.token_id < other.token_id
        if self.ts_ms != other.ts_ms:
            return self.ts_ms < other.ts_ms
        return self.sort_seq < other.sort_seq

    def __eq__(self, other: 'EventSortKey') -> bool:
        return (self.token_id == other.token_id and
                self.ts_ms == other.ts_ms and
                self.sort_seq == other.sort_seq)

    def __hash__(self) -> int:
        return hash((self.token_id, self.ts_ms, self.sort_seq))

    def to_tuple(self) -> tuple:
        return (self.token_id, self.ts_ms, self.sort_seq)


class EventClock:
    """
    Single source of truth for event time.

    In REPLAY mode: Only returns explicitly set event time
    In LIVE mode: Returns event time if set, otherwise wall clock (with warning)
    """

    _instance: Optional['EventClock'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._mode = ProcessingMode.LIVE
        self._current_event_ts: Optional[int] = None
        self._wall_clock_warnings: int = 0
        self._local = threading.local()

    @property
    def mode(self) -> ProcessingMode:
        return self._mode

    def set_mode(self, mode: ProcessingMode):
        """Set processing mode (affects time behavior)"""
        self._mode = mode
        if mode == ProcessingMode.REPLAY:
            self._wall_clock_warnings = 0

    def set_event_time(self, ts_ms: int):
        """Set current event timestamp (must be called before processing)"""
        self._current_event_ts = ts_ms

    def clear_event_time(self):
        """Clear event timestamp after processing"""
        self._current_event_ts = None

    def now_ms(self, context: str = "unknown") -> int:
        """
        Get current time in milliseconds.

        Args:
            context: Description of why time is needed (for debugging)

        Returns:
            Event timestamp if set, otherwise raises in REPLAY mode
        """
        if self._current_event_ts is not None:
            return self._current_event_ts

        if self._mode == ProcessingMode.REPLAY:
            raise DeterminismError(
                f"Wall clock access forbidden in REPLAY mode. "
                f"Context: {context}. "
                f"Set event time with EventClock().set_event_time(ts_ms) first."
            )

        # LIVE mode: allow wall clock but warn
        import time
        self._wall_clock_warnings += 1
        if self._wall_clock_warnings <= 10:
            import warnings
            warnings.warn(
                f"Wall clock used in LIVE mode ({context}). "
                f"This would fail in REPLAY mode. Warning {self._wall_clock_warnings}/10"
            )
        return int(time.time() * 1000)

    @contextmanager
    def event_context(self, ts_ms: int):
        """Context manager for processing an event with its timestamp"""
        self.set_event_time(ts_ms)
        try:
            yield
        finally:
            self.clear_event_time()


# Global event clock instance
def get_event_clock() -> EventClock:
    """Get the global EventClock instance"""
    return EventClock()


class ReplayContext:
    """
    Context manager for deterministic replay.

    Usage:
        with ReplayContext() as ctx:
            # All time.time() calls will fail
            # Must use event timestamps explicitly
            for event in events:
                with ctx.process_event(event.ts_ms):
                    process(event)
    """

    def __init__(self, strict: bool = True):
        """
        Args:
            strict: If True, wall clock access raises error. If False, just warns.
        """
        self.strict = strict
        self._clock = get_event_clock()
        self._previous_mode: Optional[ProcessingMode] = None
        self._events_processed: int = 0
        self._sort_violations: List[str] = []
        self._last_sort_key: Optional[EventSortKey] = None

    def __enter__(self) -> 'ReplayContext':
        self._previous_mode = self._clock.mode
        self._clock.set_mode(ProcessingMode.REPLAY)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._clock.set_mode(self._previous_mode or ProcessingMode.LIVE)
        self._clock.clear_event_time()
        return False

    @contextmanager
    def process_event(self, ts_ms: int, token_id: str = "", sort_seq: int = 0):
        """
        Context for processing a single event.

        Validates sort order and sets event time.
        """
        sort_key = EventSortKey(token_id, ts_ms, sort_seq)

        # Validate sort order
        if self._last_sort_key is not None and sort_key < self._last_sort_key:
            violation = f"Sort order violation: {sort_key.to_tuple()} < {self._last_sort_key.to_tuple()}"
            self._sort_violations.append(violation)
            if self.strict:
                raise DeterminismError(violation)

        self._last_sort_key = sort_key
        self._events_processed += 1

        with self._clock.event_context(ts_ms):
            yield

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "events_processed": self._events_processed,
            "sort_violations": len(self._sort_violations),
            "violations": self._sort_violations[:10],  # First 10
        }


class TokenEventQueue:
    """
    Serial event queue per token.

    Ensures single-token events are processed in order without concurrency.
    This is CRITICAL for deterministic state transitions.
    """

    def __init__(self):
        self._queues: Dict[str, queue.Queue] = defaultdict(queue.Queue)
        self._locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._processing: Dict[str, bool] = defaultdict(bool)

    def enqueue(self, token_id: str, event: Any, ts_ms: int, sort_seq: int = 0):
        """Add event to token's queue"""
        self._queues[token_id].put((EventSortKey(token_id, ts_ms, sort_seq), event))

    def process_token(self, token_id: str, handler: Callable[[Any], None]):
        """
        Process all queued events for a token serially.

        Only one thread can process a token's events at a time.
        """
        with self._locks[token_id]:
            if self._processing[token_id]:
                raise DeterminismError(f"Token {token_id} is already being processed")
            self._processing[token_id] = True

        try:
            q = self._queues[token_id]
            events = []

            # Drain queue
            while not q.empty():
                try:
                    events.append(q.get_nowait())
                except queue.Empty:
                    break

            # Sort by key (should already be sorted, but enforce)
            events.sort(key=lambda x: x[0])

            # Process in order
            clock = get_event_clock()
            for sort_key, event in events:
                with clock.event_context(sort_key.ts_ms):
                    handler(event)
        finally:
            with self._locks[token_id]:
                self._processing[token_id] = False


class AsyncTokenEventQueue:
    """
    Async version of TokenEventQueue for async handlers.
    """

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._processing: Dict[str, bool] = defaultdict(bool)

    def _get_queue(self, token_id: str) -> asyncio.Queue:
        if token_id not in self._queues:
            self._queues[token_id] = asyncio.Queue()
        return self._queues[token_id]

    def _get_lock(self, token_id: str) -> asyncio.Lock:
        if token_id not in self._locks:
            self._locks[token_id] = asyncio.Lock()
        return self._locks[token_id]

    async def enqueue(self, token_id: str, event: Any, ts_ms: int, sort_seq: int = 0):
        """Add event to token's queue"""
        q = self._get_queue(token_id)
        await q.put((EventSortKey(token_id, ts_ms, sort_seq), event))

    async def process_token(self, token_id: str, handler: Callable[[Any], Any]):
        """Process all queued events for a token serially"""
        lock = self._get_lock(token_id)

        async with lock:
            if self._processing[token_id]:
                raise DeterminismError(f"Token {token_id} is already being processed")
            self._processing[token_id] = True

        try:
            q = self._get_queue(token_id)
            events = []

            # Drain queue
            while not q.empty():
                try:
                    events.append(q.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Sort by key
            events.sort(key=lambda x: x[0])

            # Process in order
            clock = get_event_clock()
            for sort_key, event in events:
                with clock.event_context(sort_key.ts_ms):
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
        finally:
            async with lock:
                self._processing[token_id] = False


# Utility functions

def deterministic_now(context: str = "unknown") -> int:
    """
    Get current time in milliseconds, determinism-safe.

    Use this instead of time.time() * 1000 everywhere.
    """
    return get_event_clock().now_ms(context)


def validate_event_order(events: List[Any], key_fn: Callable[[Any], EventSortKey]) -> List[str]:
    """
    Validate that events are in correct sort order.

    Returns list of violation descriptions (empty if valid).
    """
    violations = []
    last_key = None

    for i, event in enumerate(events):
        key = key_fn(event)
        if last_key is not None and key < last_key:
            violations.append(
                f"Event {i}: {key.to_tuple()} < previous {last_key.to_tuple()}"
            )
        last_key = key

    return violations


def sort_events(events: List[Any], key_fn: Callable[[Any], EventSortKey]) -> List[Any]:
    """Sort events by canonical sort key"""
    return sorted(events, key=key_fn)
