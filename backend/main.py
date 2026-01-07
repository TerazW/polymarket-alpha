"""
Belief Reaction System - FastAPI Backend
Main application entry point.
"""

import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psutil

from common.config import config
from common.schemas import (
    BeliefState,
    ReactionType,
    MarketStateResponse,
    ReactionEventResponse,
    HeatmapResponse,
    STATE_INDICATORS,
)


# =============================================================================
# Lifespan management
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print(f"[{datetime.utcnow().isoformat()}] Belief Reaction System starting...")
    print(f"  Log level: {config.log_level}")
    print(f"  Database: {config.database.url[:30]}...")

    # TODO: Initialize database connection pool
    # TODO: Start background tasks (collector, reactor)

    yield

    # Shutdown
    print(f"[{datetime.utcnow().isoformat()}] Belief Reaction System shutting down...")
    # TODO: Cleanup resources


# =============================================================================
# Application setup
# =============================================================================

app = FastAPI(
    title="Belief Reaction System",
    description="Human Belief Reaction Sensing System for Polymarket",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint for load balancer."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "belief-reaction-api",
    }


@app.get("/health/detailed")
async def detailed_health():
    """Detailed health check with system metrics."""
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "belief-reaction-api",
        "version": "0.1.0",
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": memory.percent,
            "memory_available_mb": memory.available // (1024 * 1024),
            "disk_percent": disk.percent,
        },
        "config": {
            "log_level": config.log_level,
            "max_markets": config.collector.max_markets,
            "shock_threshold": config.shock.volume_threshold,
        },
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check for Kubernetes/ECS."""
    # TODO: Check database connectivity
    # TODO: Check Redis connectivity (if enabled)
    return {
        "ready": True,
        "timestamp": datetime.utcnow().isoformat(),
    }


# =============================================================================
# API endpoints
# =============================================================================

@app.get("/api/v1/markets")
async def list_markets(
    active_only: bool = Query(True, description="Only return active markets"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of markets"),
):
    """List monitored markets."""
    # TODO: Implement actual database query
    return {
        "markets": [],
        "total": 0,
        "limit": limit,
    }


@app.get("/api/v1/markets/{token_id}/state")
async def get_market_state(token_id: str) -> MarketStateResponse:
    """Get current belief state for a market."""
    # TODO: Implement actual state lookup
    return MarketStateResponse(
        token_id=token_id,
        state=BeliefState.STABLE,
        indicator=STATE_INDICATORS[BeliefState.STABLE],
        last_reaction=None,
        last_reaction_time=None,
    )


@app.get("/api/v1/markets/{token_id}/reactions")
async def get_market_reactions(
    token_id: str,
    hours: int = Query(24, ge=1, le=168, description="Lookback hours"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum reactions"),
):
    """Get recent reactions for a market."""
    # TODO: Implement actual reaction history query
    return {
        "token_id": token_id,
        "reactions": [],
        "total": 0,
        "hours": hours,
    }


@app.get("/api/v1/markets/{token_id}/heatmap")
async def get_market_heatmap(
    token_id: str,
    hours: int = Query(24, ge=1, le=168, description="Lookback hours"),
    resolution_ms: int = Query(60000, description="Bin resolution in ms"),
):
    """Get heatmap data for visualization."""
    # TODO: Implement actual heatmap data query
    return {
        "token_id": token_id,
        "from_ts": datetime.utcnow().isoformat(),
        "to_ts": datetime.utcnow().isoformat(),
        "resolution_ms": resolution_ms,
        "bins": [],
    }


@app.get("/api/v1/alerts")
async def get_recent_alerts(
    limit: int = Query(50, ge=1, le=200, description="Maximum alerts"),
    types: Optional[str] = Query(None, description="Comma-separated alert types"),
):
    """Get recent alerts (shocks, reactions, state changes)."""
    # TODO: Implement actual alerts query
    return {
        "alerts": [],
        "total": 0,
    }


# =============================================================================
# WebSocket endpoints (for real-time updates)
# =============================================================================

from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    """WebSocket connection manager."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """WebSocket endpoint for real-time alerts."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, wait for messages
            data = await websocket.receive_text()
            # Echo back for now
            await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# =============================================================================
# Error handlers
# =============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


# =============================================================================
# Main entry point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "production") == "development",
    )
