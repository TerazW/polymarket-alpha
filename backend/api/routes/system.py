"""
System API Routes (v5.32)

REST API endpoints for controlling the entire system.

Endpoints:
- GET /system/health - Overall system health
- GET /system/services - List all services status
- POST /system/start - Start all services
- POST /system/stop - Stop all services
- POST /system/restart - Restart all services
- POST /system/restart/{service} - Restart specific service
"""

import os
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

from backend.system.startup import (
    SystemStartupManager,
    ServiceStatus,
    get_system_manager,
    create_system_manager,
    reset_system_manager,
)

router = APIRouter(prefix="/system", tags=["system"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ServiceStatusResponse(BaseModel):
    """Status of a single service"""
    name: str
    status: str
    healthy: bool
    uptime_seconds: float = 0.0
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class SystemHealthResponse(BaseModel):
    """Overall system health response"""
    healthy: bool
    status: str  # healthy, degraded, unhealthy, stopped
    uptime_seconds: float = 0.0
    services: Dict[str, ServiceStatusResponse] = Field(default_factory=dict)


class StartRequest(BaseModel):
    """Request to start the system"""
    token_ids: Optional[List[str]] = Field(
        default=None,
        description="Initial token IDs for collector"
    )
    enable_reactor: bool = Field(default=True, description="Enable ReactorService")
    enable_collector: bool = Field(default=True, description="Enable CollectorService")
    enable_stream: bool = Field(default=True, description="Enable WebSocket streaming")
    persist_to_db: bool = Field(default=True, description="Persist events to database")


class StartResponse(BaseModel):
    """Response after starting system"""
    status: str
    message: str
    health: SystemHealthResponse


class StopResponse(BaseModel):
    """Response after stopping system"""
    status: str
    message: str
    health: SystemHealthResponse


class RestartServiceResponse(BaseModel):
    """Response after restarting a service"""
    status: str
    service: str
    service_status: ServiceStatusResponse


class ServicesListResponse(BaseModel):
    """List of all services"""
    services: List[ServiceStatusResponse]
    count: int


# =============================================================================
# Helper Functions
# =============================================================================

def _service_health_to_response(name: str, health) -> ServiceStatusResponse:
    """Convert ServiceHealth to response model."""
    if health is None:
        return ServiceStatusResponse(
            name=name,
            status="unknown",
            healthy=False,
        )

    data = health.to_dict()
    return ServiceStatusResponse(
        name=data["name"],
        status=data["status"],
        healthy=data["healthy"],
        uptime_seconds=data.get("uptime_seconds", 0.0),
        error=data.get("error"),
        details=data.get("details", {}),
    )


def _system_health_to_response(health) -> SystemHealthResponse:
    """Convert SystemHealth to response model."""
    if health is None:
        return SystemHealthResponse(
            healthy=True,
            status="not_started",
        )

    data = health.to_dict()
    return SystemHealthResponse(
        healthy=data["healthy"],
        status=data["status"],
        uptime_seconds=data.get("uptime_seconds", 0.0),
        services={
            name: ServiceStatusResponse(**svc)
            for name, svc in data.get("services", {}).items()
        },
    )


# =============================================================================
# Health Endpoints
# =============================================================================

@router.get("/health", response_model=SystemHealthResponse)
async def get_health():
    """
    Get overall system health status.

    Returns health information for the entire system,
    including status of all services.
    """
    manager = get_system_manager()

    if manager is None:
        return SystemHealthResponse(
            healthy=True,
            status="not_started",
            uptime_seconds=0.0,
            services={},
        )

    health = await manager.get_health()
    return _system_health_to_response(health)


@router.get("/services", response_model=ServicesListResponse)
async def get_services():
    """
    Get list of all services and their status.

    Returns detailed status for each service in the system.
    """
    manager = get_system_manager()

    if manager is None:
        return ServicesListResponse(services=[], count=0)

    health = await manager.get_health()
    services = [
        _service_health_to_response(name, svc)
        for name, svc in health.services.items()
    ]

    return ServicesListResponse(
        services=services,
        count=len(services),
    )


# =============================================================================
# Lifecycle Endpoints
# =============================================================================

@router.post("/start", response_model=StartResponse)
async def start_system(request: StartRequest = None):
    """
    Start the entire system.

    Starts all enabled services in the correct order:
    1. ReactorService (event processing)
    2. StreamManager (WebSocket publishing)
    3. CollectorService (data collection)

    If the system is already running, returns current status.
    """
    if request is None:
        request = StartRequest()

    manager = get_system_manager()

    if manager is not None and manager.is_running:
        health = await manager.get_health()
        return StartResponse(
            status="already_running",
            message="System is already running",
            health=_system_health_to_response(health),
        )

    # Get default tokens from environment if not provided
    token_ids = request.token_ids
    if token_ids is None:
        default_tokens = os.getenv("SYSTEM_DEFAULT_TOKENS", "")
        token_ids = [t.strip() for t in default_tokens.split(",") if t.strip()]

    # Create new manager
    manager = create_system_manager(
        token_ids=token_ids,
        enable_reactor=request.enable_reactor,
        enable_collector=request.enable_collector,
        enable_stream=request.enable_stream,
        persist_to_db=request.persist_to_db,
    )

    health = await manager.start_all()

    return StartResponse(
        status="started",
        message="System started successfully",
        health=_system_health_to_response(health),
    )


@router.post("/stop", response_model=StopResponse)
async def stop_system():
    """
    Stop the entire system.

    Gracefully stops all services in reverse order:
    1. CollectorService
    2. StreamManager
    3. ReactorService
    """
    manager = get_system_manager()

    if manager is None:
        return StopResponse(
            status="not_started",
            message="System was not started",
            health=SystemHealthResponse(
                healthy=True,
                status="not_started",
            ),
        )

    if not manager.is_running:
        health = await manager.get_health()
        return StopResponse(
            status="already_stopped",
            message="System is already stopped",
            health=_system_health_to_response(health),
        )

    health = await manager.stop_all()
    reset_system_manager()

    return StopResponse(
        status="stopped",
        message="System stopped successfully",
        health=_system_health_to_response(health),
    )


@router.post("/restart", response_model=StartResponse)
async def restart_system():
    """
    Restart the entire system.

    Stops all services and then starts them again
    with the same configuration.
    """
    manager = get_system_manager()

    if manager is None:
        return StartResponse(
            status="not_started",
            message="System was not started. Use /system/start instead.",
            health=SystemHealthResponse(
                healthy=True,
                status="not_started",
            ),
        )

    # Save configuration
    token_ids = manager.token_ids
    enable_reactor = manager.enable_reactor
    enable_collector = manager.enable_collector
    enable_stream = manager.enable_stream
    persist_to_db = manager.persist_to_db

    # Stop current manager
    await manager.stop_all()
    reset_system_manager()

    # Create new manager with same config
    new_manager = create_system_manager(
        token_ids=token_ids,
        enable_reactor=enable_reactor,
        enable_collector=enable_collector,
        enable_stream=enable_stream,
        persist_to_db=persist_to_db,
    )

    health = await new_manager.start_all()

    return StartResponse(
        status="restarted",
        message="System restarted successfully",
        health=_system_health_to_response(health),
    )


@router.post("/restart/{service_name}", response_model=RestartServiceResponse)
async def restart_service(service_name: str):
    """
    Restart a specific service.

    Available services: reactor, collector, stream
    """
    manager = get_system_manager()

    if manager is None:
        raise HTTPException(
            status_code=400,
            detail="System not started. Start the system first.",
        )

    valid_services = ["reactor", "collector", "stream"]
    if service_name not in valid_services:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid service. Must be one of: {', '.join(valid_services)}",
        )

    try:
        service_health = await manager.restart_service(service_name)
        return RestartServiceResponse(
            status="restarted",
            service=service_name,
            service_status=_service_health_to_response(
                service_name,
                service_health
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart service: {e}")


# =============================================================================
# Configuration Endpoint
# =============================================================================

@router.get("/config")
async def get_system_config():
    """
    Get current system configuration.

    Returns the configuration used to start the system.
    """
    manager = get_system_manager()

    if manager is None:
        return {
            "status": "not_started",
            "config": None,
        }

    return {
        "status": "running" if manager.is_running else "stopped",
        "config": {
            "token_ids": manager.token_ids,
            "enable_reactor": manager.enable_reactor,
            "enable_collector": manager.enable_collector,
            "enable_stream": manager.enable_stream,
            "persist_to_db": manager.persist_to_db,
        },
    }
