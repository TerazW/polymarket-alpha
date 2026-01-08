"""
Collector Service Layer (v5.29)

Integrates POC DataCollector with ReactorService for the backend.

Architecture:
    Polymarket WebSocket
           │
           ▼
    DataCollector (POC)
           │
           ▼
    EventBus (shared)
           │
           ▼
    ReactorWrapper
           │
           ▼
    WebSocket + DB

Usage:
    from backend.collector import CollectorService

    # Create with shared reactor
    collector = CollectorService(
        token_ids=['token1', 'token2'],
        reactor_service=reactor_service,
    )

    await collector.start()
    # ... data flows automatically
    await collector.stop()
"""

import asyncio
import time
from typing import List, Optional, Dict, Any, Callable
from enum import Enum
import threading

from poc.collector import DataCollector, ConnectionState
from poc.event_bus import InMemoryEventBus, RawEvent, EventType

# Re-export ConnectionState
__all__ = ['CollectorService', 'ConnectionState']


class CollectorService:
    """
    Async service wrapper for POC DataCollector.

    Features:
    - Async start/stop
    - Connection state monitoring
    - Integration with ReactorService (optional)
    - Statistics tracking
    """

    def __init__(
        self,
        token_ids: List[str],
        reactor_service: Optional[Any] = None,
        on_connection_change: Optional[Callable[[ConnectionState], None]] = None,
    ):
        """
        Initialize collector service.

        Args:
            token_ids: List of token IDs to subscribe to
            reactor_service: Optional ReactorService to feed events to
            on_connection_change: Optional callback for connection state changes
        """
        self.token_ids = token_ids
        self.reactor_service = reactor_service
        self._on_connection_change = on_connection_change

        # Create shared event bus
        self.event_bus = InMemoryEventBus()

        # Create collector
        self.collector = DataCollector(
            event_bus=self.event_bus,
            token_ids=token_ids,
            on_state_change=self._handle_state_change,
        )

        self._started = False
        self._event_consumer_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Stats
        self._events_forwarded = 0

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self.collector.state

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.collector.state == ConnectionState.CONNECTED

    async def start(self):
        """Start the collector service."""
        async with self._lock:
            if self._started:
                return

            # Start collector (runs in threads)
            self.collector.start()

            # Start event consumer if reactor is provided
            if self.reactor_service:
                self._event_consumer_task = asyncio.create_task(
                    self._consume_events()
                )

            self._started = True

    async def stop(self):
        """Stop the collector service."""
        async with self._lock:
            if not self._started:
                return

            # Stop event consumer
            if self._event_consumer_task:
                self._event_consumer_task.cancel()
                try:
                    await self._event_consumer_task
                except asyncio.CancelledError:
                    pass
                self._event_consumer_task = None

            # Stop collector
            self.collector.stop()
            self._started = False

    async def add_tokens(self, token_ids: List[str]):
        """Add tokens to subscription."""
        # Run in thread pool since collector uses threads
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self.collector.add_tokens,
            token_ids
        )
        self.token_ids.extend([t for t in token_ids if t not in self.token_ids])

    async def remove_tokens(self, token_ids: List[str]):
        """Remove tokens from subscription."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self.collector.remove_tokens,
            token_ids
        )
        self.token_ids = [t for t in self.token_ids if t not in token_ids]

    async def get_stats(self) -> Dict[str, Any]:
        """Get collector statistics."""
        stats = self.collector.get_stats()
        stats['events_forwarded_to_reactor'] = self._events_forwarded
        return stats

    def _handle_state_change(self, new_state: ConnectionState):
        """Handle connection state change."""
        if self._on_connection_change:
            self._on_connection_change(new_state)

    async def _consume_events(self):
        """
        Consume events from event bus and forward to reactor.

        Runs in async loop, polling the EventBus.
        """
        loop = asyncio.get_event_loop()

        while True:
            try:
                # Poll event bus (runs in thread pool)
                event = await loop.run_in_executor(
                    None,
                    self.event_bus.poll,
                    50  # 50ms timeout
                )

                if event:
                    # Convert RawEvent to dict for ReactorService
                    event_dict = self._raw_event_to_dict(event)

                    # Forward to reactor
                    if self.reactor_service:
                        await self.reactor_service.process_event(event_dict)
                        self._events_forwarded += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[CollectorService] Error consuming event: {e}")
                await asyncio.sleep(0.1)

    def _raw_event_to_dict(self, event: RawEvent) -> Dict[str, Any]:
        """Convert RawEvent to dict for ReactorService."""
        event_type_map = {
            EventType.BOOK: 'book',
            EventType.TRADE: 'trade',
            EventType.PRICE_CHANGE: 'price_change',
        }

        return {
            'event_type': event_type_map.get(event.event_type, 'unknown'),
            'token_id': event.token_id,
            'payload': event.payload,
            'server_ts': event.server_ts,
            'ws_ts': event.ws_ts,
        }


class IntegratedCollectorReactor:
    """
    Combined Collector + Reactor service for convenience.

    Provides a single service that manages both data collection
    and reaction processing.
    """

    def __init__(
        self,
        token_ids: List[str],
        persist_to_db: bool = True,
        enable_websocket: bool = True,
    ):
        """
        Initialize integrated service.

        Args:
            token_ids: List of token IDs to subscribe to
            persist_to_db: Whether to persist events to database
            enable_websocket: Whether to publish to WebSocket stream
        """
        # Import here to avoid circular imports
        from backend.reactor.service import ReactorService

        self.token_ids = token_ids

        # Create reactor service
        self.reactor_service = ReactorService(
            persist_to_db=persist_to_db,
        )

        # Create collector service (will wire up callbacks)
        self.collector_service = CollectorService(
            token_ids=token_ids,
            reactor_service=self.reactor_service,
        )

        self._started = False

    @property
    def state(self) -> ConnectionState:
        """Get connection state."""
        return self.collector_service.state

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.collector_service.is_connected

    async def start(self):
        """Start both services."""
        if not self._started:
            await self.reactor_service.start()
            await self.collector_service.start()
            self._started = True

    async def stop(self):
        """Stop both services."""
        if self._started:
            await self.collector_service.stop()
            await self.reactor_service.stop()
            self._started = False

    async def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics."""
        return {
            'collector': await self.collector_service.get_stats(),
            'reactor': await self.reactor_service.get_stats(),
        }

    async def add_tokens(self, token_ids: List[str]):
        """Add tokens to subscription."""
        await self.collector_service.add_tokens(token_ids)
        self.token_ids.extend([t for t in token_ids if t not in self.token_ids])

    async def remove_tokens(self, token_ids: List[str]):
        """Remove tokens from subscription."""
        await self.collector_service.remove_tokens(token_ids)
        self.token_ids = [t for t in self.token_ids if t not in token_ids]
