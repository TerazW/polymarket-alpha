"""
Collector API Routes (v5.30)

REST API endpoints for controlling the CollectorService.

Endpoints:
- GET /collector/health - Health check
- GET /collector/stats - Collector statistics
- GET /collector/status - Connection status
- GET /collector/tokens - List subscribed tokens
- POST /collector/start - Start collector
- POST /collector/stop - Stop collector
- POST /collector/tokens - Add tokens to subscription
- DELETE /collector/tokens - Remove tokens from subscription
"""

import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

from backend.collector.service import CollectorService
from poc.collector import ConnectionState

router = APIRouter(prefix="/collector", tags=["collector"])


# =============================================================================
# Request/Response Models
# =============================================================================

class TokensRequest(BaseModel):
    """Request to add/remove tokens"""
    token_ids: List[str] = Field(..., min_length=1, description="Token IDs to add/remove")


class MarketsRequest(BaseModel):
    """Request to add markets by condition_id (v5.35)"""
    condition_ids: List[str] = Field(..., min_length=1, description="Market condition IDs to add")
    include_yes: bool = Field(True, description="Include YES tokens")
    include_no: bool = Field(True, description="Include NO tokens")


class CollectorStatusResponse(BaseModel):
    """Collector status response"""
    running: bool
    connection_state: str
    is_connected: bool
    token_count: int


class CollectorStatsResponse(BaseModel):
    """Collector statistics response"""
    messages_received: int = 0
    messages_published: int = 0
    events_forwarded_to_reactor: int = 0
    connection_attempts: int = 0
    reconnections: int = 0
    errors: int = 0
    uptime_seconds: float = 0.0


class CollectorHealthResponse(BaseModel):
    """Collector health check response"""
    healthy: bool
    running: bool
    connection_state: str
    token_count: int
    events_forwarded: int


class TokensResponse(BaseModel):
    """Token list response"""
    tokens: List[str]
    count: int


class StartResponse(BaseModel):
    """Start collector response"""
    status: str
    message: str
    token_count: int


class StopResponse(BaseModel):
    """Stop collector response"""
    status: str
    message: str


class TokensModifyResponse(BaseModel):
    """Response after modifying tokens"""
    status: str
    added: Optional[List[str]] = None
    removed: Optional[List[str]] = None
    current_count: int


# =============================================================================
# Service Singleton
# =============================================================================

_collector_service: Optional[CollectorService] = None


def get_collector_service() -> Optional[CollectorService]:
    """Get the collector service singleton (may be None if not started)."""
    return _collector_service


def create_collector_service(token_ids: List[str], reactor_service=None) -> CollectorService:
    """Create and store the collector service singleton."""
    global _collector_service
    if _collector_service is None:
        _collector_service = CollectorService(
            token_ids=token_ids,
            reactor_service=reactor_service,
        )
    return _collector_service


def reset_collector_service():
    """Reset the collector service singleton (for testing)."""
    global _collector_service
    _collector_service = None


# =============================================================================
# Health and Status Endpoints
# =============================================================================

@router.get("/health", response_model=CollectorHealthResponse)
async def get_health():
    """
    Check collector health status.

    Returns health information including connection state
    and event processing metrics.
    """
    service = get_collector_service()

    if service is None:
        return CollectorHealthResponse(
            healthy=True,
            running=False,
            connection_state="NOT_STARTED",
            token_count=0,
            events_forwarded=0,
        )

    return CollectorHealthResponse(
        healthy=True,
        running=service._started,
        connection_state=service.state.value if service._started else "STOPPED",
        token_count=len(service.token_ids),
        events_forwarded=service._events_forwarded,
    )


@router.get("/status", response_model=CollectorStatusResponse)
async def get_status():
    """
    Get current collector status.

    Returns detailed connection status information.
    """
    service = get_collector_service()

    if service is None:
        return CollectorStatusResponse(
            running=False,
            connection_state="NOT_STARTED",
            is_connected=False,
            token_count=0,
        )

    return CollectorStatusResponse(
        running=service._started,
        connection_state=service.state.value if service._started else "STOPPED",
        is_connected=service.is_connected if service._started else False,
        token_count=len(service.token_ids),
    )


@router.get("/stats", response_model=CollectorStatsResponse)
async def get_stats():
    """
    Get collector statistics.

    Returns message counts, connection attempts, and performance metrics.
    """
    service = get_collector_service()

    if service is None:
        return CollectorStatsResponse()

    stats = await service.get_stats()

    return CollectorStatsResponse(
        messages_received=stats.get('messages_received', 0),
        messages_published=stats.get('messages_published', 0),
        events_forwarded_to_reactor=stats.get('events_forwarded_to_reactor', 0),
        connection_attempts=stats.get('connection_attempts', 0),
        reconnections=stats.get('reconnections', 0),
        errors=stats.get('errors', 0),
        uptime_seconds=stats.get('uptime_seconds', 0.0),
    )


# =============================================================================
# Token Management Endpoints
# =============================================================================

@router.get("/tokens", response_model=TokensResponse)
async def get_tokens():
    """
    Get list of subscribed tokens.

    Returns all token IDs currently being tracked by the collector.
    """
    service = get_collector_service()

    if service is None:
        return TokensResponse(tokens=[], count=0)

    return TokensResponse(
        tokens=service.token_ids,
        count=len(service.token_ids),
    )


@router.post("/tokens", response_model=TokensModifyResponse)
async def add_tokens(request: TokensRequest):
    """
    Add tokens to subscription.

    Adds new token IDs to the collector's subscription list.
    Collector must be running for tokens to be actively tracked.
    """
    service = get_collector_service()

    if service is None:
        raise HTTPException(
            status_code=400,
            detail="Collector not initialized. Start the collector first.",
        )

    # Filter out already subscribed tokens
    new_tokens = [t for t in request.token_ids if t not in service.token_ids]

    if new_tokens:
        await service.add_tokens(new_tokens)

    return TokensModifyResponse(
        status="success",
        added=new_tokens,
        current_count=len(service.token_ids),
    )


@router.delete("/tokens", response_model=TokensModifyResponse)
async def remove_tokens(request: TokensRequest):
    """
    Remove tokens from subscription.

    Removes token IDs from the collector's subscription list.
    """
    service = get_collector_service()

    if service is None:
        raise HTTPException(
            status_code=400,
            detail="Collector not initialized.",
        )

    # Filter to only subscribed tokens
    tokens_to_remove = [t for t in request.token_ids if t in service.token_ids]

    if tokens_to_remove:
        await service.remove_tokens(tokens_to_remove)

    return TokensModifyResponse(
        status="success",
        removed=tokens_to_remove,
        current_count=len(service.token_ids),
    )


@router.post("/markets", response_model=TokensModifyResponse)
async def add_markets(request: MarketsRequest):
    """
    Add complete markets by condition_id (v5.35).

    Looks up the market and adds both YES and NO token IDs.
    This is the recommended way to track complete markets.

    Args:
        condition_ids: List of market condition IDs
        include_yes: Whether to track YES tokens (default: True)
        include_no: Whether to track NO tokens (default: True)
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    service = get_collector_service()

    if service is None:
        raise HTTPException(
            status_code=400,
            detail="Collector not initialized. Start the collector first.",
        )

    if not request.include_yes and not request.include_no:
        raise HTTPException(
            status_code=400,
            detail="At least one of include_yes or include_no must be True.",
        )

    # Look up token IDs from database
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', '127.0.0.1'),
        'port': int(os.getenv('DB_PORT', '5432')),
        'database': os.getenv('DB_NAME', 'belief_reaction'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'postgres'),
    }

    try:
        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        tokens_to_add = []

        with conn.cursor() as cur:
            for condition_id in request.condition_ids:
                cur.execute("""
                    SELECT yes_token_id, no_token_id
                    FROM markets
                    WHERE condition_id = %s
                """, (condition_id,))
                row = cur.fetchone()

                if row:
                    if request.include_yes and row['yes_token_id']:
                        tokens_to_add.append(row['yes_token_id'])
                    if request.include_no and row['no_token_id']:
                        tokens_to_add.append(row['no_token_id'])

        conn.close()

        # Filter out already subscribed tokens
        new_tokens = [t for t in tokens_to_add if t not in service.token_ids]

        if new_tokens:
            await service.add_tokens(new_tokens)

        return TokensModifyResponse(
            status="success",
            added=new_tokens,
            current_count=len(service.token_ids),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to look up markets: {str(e)}",
        )


# =============================================================================
# Lifecycle Endpoints
# =============================================================================

@router.post("/start", response_model=StartResponse)
async def start_collector(
    token_ids: Optional[List[str]] = Body(
        default=None,
        description="Initial token IDs to subscribe to"
    ),
):
    """
    Start the collector service.

    If collector is not initialized, creates it with the provided token_ids.
    If already running, returns current status.
    """
    global _collector_service

    # Get or create service
    service = get_collector_service()

    if service is None:
        if not token_ids:
            # Use default tokens from environment or empty
            default_tokens = os.getenv("COLLECTOR_DEFAULT_TOKENS", "")
            token_ids = [t.strip() for t in default_tokens.split(",") if t.strip()]

        # Try to get reactor service for integration
        try:
            from backend.api.routes.reactor import get_reactor_service
            reactor_service = get_reactor_service()
        except ImportError:
            reactor_service = None

        service = create_collector_service(
            token_ids=token_ids or [],
            reactor_service=reactor_service,
        )

    if service._started:
        return StartResponse(
            status="already_running",
            message="Collector is already running",
            token_count=len(service.token_ids),
        )

    await service.start()

    return StartResponse(
        status="started",
        message="Collector started successfully",
        token_count=len(service.token_ids),
    )


@router.post("/stop", response_model=StopResponse)
async def stop_collector():
    """
    Stop the collector service.

    Gracefully stops the collector, closing WebSocket connection.
    """
    service = get_collector_service()

    if service is None:
        return StopResponse(
            status="not_initialized",
            message="Collector was not initialized",
        )

    if not service._started:
        return StopResponse(
            status="already_stopped",
            message="Collector is already stopped",
        )

    await service.stop()

    return StopResponse(
        status="stopped",
        message="Collector stopped successfully",
    )


# =============================================================================
# Connection State Endpoint
# =============================================================================

@router.get("/connection-states")
async def get_connection_states():
    """
    Get available connection state values.

    Returns the possible connection states for reference.
    """
    return {
        "states": [
            {"value": "DISCONNECTED", "description": "Not connected to WebSocket"},
            {"value": "CONNECTING", "description": "Establishing WebSocket connection"},
            {"value": "CONNECTED", "description": "WebSocket connection active"},
            {"value": "RECONNECTING", "description": "Attempting to reconnect after disconnect"},
        ]
    }
