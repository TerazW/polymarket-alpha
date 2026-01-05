"""
System Startup Manager (v5.31)

Coordinates startup and shutdown of all backend services:
- ReactorService: Event processing and belief state
- CollectorService: Data collection from Polymarket
- StreamManager: WebSocket streaming

Usage:
    from backend.system import SystemStartupManager

    manager = SystemStartupManager()
    await manager.start_all()

    # ... application runs ...

    await manager.stop_all()

Or with context manager:
    async with SystemStartupManager() as manager:
        # All services running
        pass
    # All services stopped
"""

import asyncio
import time
import os
from typing import Optional, Dict, List, Any, Callable
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


class ServiceStatus(Enum):
    """Service status states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    DEGRADED = "degraded"  # Running with limited functionality


@dataclass
class ServiceHealth:
    """Health status for a single service"""
    name: str
    status: ServiceStatus
    healthy: bool
    started_at: Optional[float] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "healthy": self.healthy,
            "started_at": self.started_at,
            "uptime_seconds": time.time() - self.started_at if self.started_at else 0,
            "error": self.error,
            "details": self.details,
        }


@dataclass
class SystemHealth:
    """Aggregated health status for all services"""
    healthy: bool
    status: str  # "healthy", "degraded", "unhealthy"
    services: Dict[str, ServiceHealth] = field(default_factory=dict)
    started_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "status": self.status,
            "uptime_seconds": time.time() - self.started_at if self.started_at else 0,
            "services": {
                name: svc.to_dict() for name, svc in self.services.items()
            }
        }


class SystemStartupManager:
    """
    Unified manager for all backend services.

    Features:
    - Coordinated startup sequence
    - Graceful shutdown
    - Health monitoring
    - Service dependency management
    - Error handling and recovery
    """

    def __init__(
        self,
        token_ids: Optional[List[str]] = None,
        enable_reactor: bool = True,
        enable_collector: bool = True,
        enable_stream: bool = True,
        persist_to_db: bool = True,
        on_health_change: Optional[Callable[[SystemHealth], None]] = None,
    ):
        """
        Initialize system manager.

        Args:
            token_ids: Initial token IDs for collector
            enable_reactor: Whether to start ReactorService
            enable_collector: Whether to start CollectorService
            enable_stream: Whether to start WebSocket streaming
            persist_to_db: Whether to persist events to database
            on_health_change: Callback when health status changes
        """
        self.token_ids = token_ids or []
        self.enable_reactor = enable_reactor
        self.enable_collector = enable_collector
        self.enable_stream = enable_stream
        self.persist_to_db = persist_to_db
        self._on_health_change = on_health_change

        # Service instances (initialized on start)
        self._reactor_service = None
        self._collector_service = None
        self._stream_manager = None

        # Health tracking
        self._services: Dict[str, ServiceHealth] = {}
        self._started_at: Optional[float] = None
        self._lock = asyncio.Lock()

    async def start_all(self) -> SystemHealth:
        """
        Start all enabled services in the correct order.

        Order:
        1. ReactorService (processes events)
        2. StreamManager (publishes to WebSocket)
        3. CollectorService (collects data, depends on 1 & 2)

        Returns:
            SystemHealth with status of all services
        """
        async with self._lock:
            self._started_at = time.time()
            self._services = {}

            # 1. Start ReactorService first (event processing)
            if self.enable_reactor:
                await self._start_reactor()

            # 2. Start StreamManager (WebSocket publishing)
            if self.enable_stream:
                await self._start_stream_manager()

            # 3. Start CollectorService last (depends on reactor)
            if self.enable_collector:
                await self._start_collector()

            health = self._compute_health()
            self._notify_health_change(health)
            return health

    async def stop_all(self) -> SystemHealth:
        """
        Stop all services in reverse order.

        Order:
        1. CollectorService (stop data collection)
        2. StreamManager (stop publishing)
        3. ReactorService (stop processing)

        Returns:
            SystemHealth with final status
        """
        async with self._lock:
            # 1. Stop collector first
            if self._collector_service:
                await self._stop_collector()

            # 2. Stop stream manager
            if self._stream_manager:
                await self._stop_stream_manager()

            # 3. Stop reactor last
            if self._reactor_service:
                await self._stop_reactor()

            self._started_at = None
            health = self._compute_health()
            self._notify_health_change(health)
            return health

    async def get_health(self) -> SystemHealth:
        """Get current health status of all services."""
        async with self._lock:
            return self._compute_health()

    async def restart_service(self, service_name: str) -> ServiceHealth:
        """
        Restart a specific service.

        Args:
            service_name: Name of service ("reactor", "collector", "stream")

        Returns:
            ServiceHealth of restarted service
        """
        async with self._lock:
            if service_name == "reactor":
                await self._stop_reactor()
                await self._start_reactor()
                return self._services.get("reactor")

            elif service_name == "collector":
                await self._stop_collector()
                await self._start_collector()
                return self._services.get("collector")

            elif service_name == "stream":
                await self._stop_stream_manager()
                await self._start_stream_manager()
                return self._services.get("stream")

            else:
                raise ValueError(f"Unknown service: {service_name}")

    # =========================================================================
    # Service Management (Private)
    # =========================================================================

    async def _start_reactor(self):
        """Start ReactorService."""
        try:
            self._services["reactor"] = ServiceHealth(
                name="reactor",
                status=ServiceStatus.STARTING,
                healthy=False,
            )

            from backend.reactor.service import ReactorService

            # Get WebSocket callbacks if stream is enabled
            on_reaction = None
            on_state_change = None
            on_leading_event = None
            on_alert = None

            if self.enable_stream and self._stream_manager:
                from backend.api.stream import (
                    publish_reaction,
                    publish_state_change,
                    publish_alert,
                )
                # These will be wired in the reactor routes

            self._reactor_service = ReactorService(
                persist_to_db=self.persist_to_db,
                on_reaction=on_reaction,
                on_state_change=on_state_change,
                on_leading_event=on_leading_event,
                on_alert=on_alert,
            )

            await self._reactor_service.start()

            self._services["reactor"] = ServiceHealth(
                name="reactor",
                status=ServiceStatus.RUNNING,
                healthy=True,
                started_at=time.time(),
                details={"persist_to_db": self.persist_to_db},
            )

        except Exception as e:
            self._services["reactor"] = ServiceHealth(
                name="reactor",
                status=ServiceStatus.ERROR,
                healthy=False,
                error=str(e),
            )

    async def _stop_reactor(self):
        """Stop ReactorService."""
        if self._reactor_service:
            try:
                self._services["reactor"].status = ServiceStatus.STOPPING
                await self._reactor_service.stop()
                self._reactor_service = None
                self._services["reactor"] = ServiceHealth(
                    name="reactor",
                    status=ServiceStatus.STOPPED,
                    healthy=True,
                )
            except Exception as e:
                self._services["reactor"] = ServiceHealth(
                    name="reactor",
                    status=ServiceStatus.ERROR,
                    healthy=False,
                    error=str(e),
                )

    async def _start_collector(self):
        """Start CollectorService."""
        try:
            self._services["collector"] = ServiceHealth(
                name="collector",
                status=ServiceStatus.STARTING,
                healthy=False,
            )

            from backend.collector.service import CollectorService

            self._collector_service = CollectorService(
                token_ids=self.token_ids,
                reactor_service=self._reactor_service,
            )

            await self._collector_service.start()

            self._services["collector"] = ServiceHealth(
                name="collector",
                status=ServiceStatus.RUNNING,
                healthy=True,
                started_at=time.time(),
                details={"token_count": len(self.token_ids)},
            )

        except Exception as e:
            self._services["collector"] = ServiceHealth(
                name="collector",
                status=ServiceStatus.ERROR,
                healthy=False,
                error=str(e),
            )

    async def _stop_collector(self):
        """Stop CollectorService."""
        if self._collector_service:
            try:
                self._services["collector"].status = ServiceStatus.STOPPING
                await self._collector_service.stop()
                self._collector_service = None
                self._services["collector"] = ServiceHealth(
                    name="collector",
                    status=ServiceStatus.STOPPED,
                    healthy=True,
                )
            except Exception as e:
                self._services["collector"] = ServiceHealth(
                    name="collector",
                    status=ServiceStatus.ERROR,
                    healthy=False,
                    error=str(e),
                )

    async def _start_stream_manager(self):
        """Start WebSocket stream manager."""
        try:
            self._services["stream"] = ServiceHealth(
                name="stream",
                status=ServiceStatus.STARTING,
                healthy=False,
            )

            from backend.api.stream import stream_manager

            self._stream_manager = stream_manager
            await self._stream_manager.start()

            self._services["stream"] = ServiceHealth(
                name="stream",
                status=ServiceStatus.RUNNING,
                healthy=True,
                started_at=time.time(),
            )

        except Exception as e:
            self._services["stream"] = ServiceHealth(
                name="stream",
                status=ServiceStatus.ERROR,
                healthy=False,
                error=str(e),
            )

    async def _stop_stream_manager(self):
        """Stop WebSocket stream manager."""
        if self._stream_manager:
            try:
                self._services["stream"].status = ServiceStatus.STOPPING
                await self._stream_manager.stop()
                self._stream_manager = None
                self._services["stream"] = ServiceHealth(
                    name="stream",
                    status=ServiceStatus.STOPPED,
                    healthy=True,
                )
            except Exception as e:
                self._services["stream"] = ServiceHealth(
                    name="stream",
                    status=ServiceStatus.ERROR,
                    healthy=False,
                    error=str(e),
                )

    # =========================================================================
    # Health Computation
    # =========================================================================

    def _compute_health(self) -> SystemHealth:
        """Compute aggregated health status."""
        if not self._services:
            return SystemHealth(
                healthy=True,
                status="stopped",
                services={},
                started_at=None,
            )

        running_count = sum(
            1 for s in self._services.values()
            if s.status == ServiceStatus.RUNNING
        )
        stopped_count = sum(
            1 for s in self._services.values()
            if s.status == ServiceStatus.STOPPED
        )
        error_count = sum(
            1 for s in self._services.values()
            if s.status == ServiceStatus.ERROR
        )
        total_enabled = len(self._services)

        # All services stopped cleanly
        if stopped_count == total_enabled:
            status = "stopped"
            healthy = True
        # All services running normally
        elif error_count == 0 and running_count == total_enabled:
            status = "healthy"
            healthy = True
        # All services in error
        elif error_count == total_enabled:
            status = "unhealthy"
            healthy = False
        # Mixed state (some errors, some running, some stopped)
        else:
            status = "degraded"
            healthy = False

        return SystemHealth(
            healthy=healthy,
            status=status,
            services=self._services.copy(),
            started_at=self._started_at,
        )

    def _notify_health_change(self, health: SystemHealth):
        """Notify health change callback."""
        if self._on_health_change:
            try:
                self._on_health_change(health)
            except Exception:
                pass  # Don't let callback errors affect operation

    # =========================================================================
    # Context Manager
    # =========================================================================

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start_all()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop_all()
        return False  # Don't suppress exceptions

    # =========================================================================
    # Service Access
    # =========================================================================

    @property
    def reactor(self):
        """Get ReactorService instance."""
        return self._reactor_service

    @property
    def collector(self):
        """Get CollectorService instance."""
        return self._collector_service

    @property
    def stream(self):
        """Get StreamManager instance."""
        return self._stream_manager

    @property
    def is_running(self) -> bool:
        """Check if any service is running."""
        return any(
            s.status == ServiceStatus.RUNNING
            for s in self._services.values()
        )


# =============================================================================
# Global Manager Singleton
# =============================================================================

_system_manager: Optional[SystemStartupManager] = None


def get_system_manager() -> Optional[SystemStartupManager]:
    """Get the global system manager singleton."""
    return _system_manager


def create_system_manager(**kwargs) -> SystemStartupManager:
    """Create and store the global system manager."""
    global _system_manager
    _system_manager = SystemStartupManager(**kwargs)
    return _system_manager


def reset_system_manager():
    """Reset the global system manager (for testing)."""
    global _system_manager
    _system_manager = None


__all__ = [
    'SystemStartupManager',
    'ServiceStatus',
    'ServiceHealth',
    'SystemHealth',
    'get_system_manager',
    'create_system_manager',
    'reset_system_manager',
]
