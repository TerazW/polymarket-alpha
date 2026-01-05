"""
Reactor API Routes (v5.27)

Provides API endpoints for reactor service:
- GET /reactor/stats - Reactor statistics
- GET /reactor/reactions - Recent reaction events
- GET /reactor/states - All market belief states
- GET /reactor/state/{token_id} - Single market state
- GET /reactor/leading-events - Recent leading events
- POST /reactor/events - Inject test events (dev only, ADMIN only)

v5.28: WebSocket integration for real-time event broadcasting
v5.33: Enhanced security for /events endpoint (ACL + audit)
"""

from fastapi import APIRouter, Query, HTTPException, Depends, Request
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
import os
import asyncio
import time

from backend.reactor.service import ReactorService, BeliefMachineService

# v5.33: Security imports for event injection endpoint
from backend.security import (
    get_audit_logger,
    AuditAction,
    check_permission,
    Permission,
)

# v5.28: Import WebSocket publishing functions
from backend.api.stream import (
    publish_reaction,
    publish_belief_state,
    publish_leading_event,
    publish_alert,
    StreamEventType,
)


router = APIRouter(prefix="/reactor", tags=["reactor"])

# Global reactor service instance (singleton)
_reactor_service: Optional[ReactorService] = None
_belief_service: Optional[BeliefMachineService] = None

# Event loop reference for async callbacks
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_event_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Get or create event loop reference."""
    global _event_loop
    try:
        _event_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    return _event_loop


# =============================================================================
# WebSocket Callback Adapters (v5.28)
# =============================================================================

def _on_reaction_callback(reaction: Dict):
    """
    Callback for reaction events - publishes to WebSocket.

    Called by ReactorService when a reaction is classified.
    """
    loop = _get_event_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(
            publish_reaction(reaction.get('token_id', ''), reaction),
            loop
        )


def _on_state_change_callback(change: Dict):
    """
    Callback for state changes - publishes to WebSocket.

    Called by ReactorService when belief state transitions.
    """
    loop = _get_event_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(
            publish_belief_state(change.get('token_id', ''), change),
            loop
        )


def _on_leading_event_callback(event: Dict):
    """
    Callback for leading events - publishes to WebSocket.

    Called by ReactorService when leading event detected.
    """
    loop = _get_event_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(
            publish_leading_event(event.get('token_id', ''), event),
            loop
        )


def _on_alert_callback(alert: Dict):
    """
    Callback for alerts - publishes to WebSocket.

    Called by ReactorService when alert generated.
    """
    loop = _get_event_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(
            publish_alert(alert, StreamEventType.ALERT_NEW),
            loop
        )


def get_reactor_service() -> ReactorService:
    """Get or create reactor service singleton with WebSocket callbacks."""
    global _reactor_service
    if _reactor_service is None:
        # v5.28: Wire up WebSocket callbacks
        enable_ws = os.getenv("REACTOR_WEBSOCKET_ENABLED", "true").lower() == "true"

        _reactor_service = ReactorService(
            persist_to_db=os.getenv("REACTOR_PERSIST_DB", "true").lower() == "true",
            on_reaction=_on_reaction_callback if enable_ws else None,
            on_state_change=_on_state_change_callback if enable_ws else None,
            on_leading_event=_on_leading_event_callback if enable_ws else None,
            on_alert=_on_alert_callback if enable_ws else None,
        )
    return _reactor_service


def get_belief_service() -> BeliefMachineService:
    """Get or create belief machine service singleton."""
    global _belief_service
    if _belief_service is None:
        _belief_service = BeliefMachineService()
    return _belief_service


# =============================================================================
# Response Models
# =============================================================================

class BeliefStateEnum(str, Enum):
    STABLE = "STABLE"
    FRAGILE = "FRAGILE"
    CRACKING = "CRACKING"
    BROKEN = "BROKEN"


class ReactionTypeEnum(str, Enum):
    VACUUM = "VACUUM"
    SWEEP = "SWEEP"
    CHASE = "CHASE"
    PULL = "PULL"
    HOLD = "HOLD"
    DELAYED = "DELAYED"
    NO_IMPACT = "NO_IMPACT"


class WindowTypeEnum(str, Enum):
    FAST = "FAST"
    SLOW = "SLOW"


class LeadingEventTypeEnum(str, Enum):
    PRE_SHOCK_PULL = "PRE_SHOCK_PULL"
    DEPTH_COLLAPSE = "DEPTH_COLLAPSE"
    GRADUAL_THINNING = "GRADUAL_THINNING"


class ReactorStatsResponse(BaseModel):
    """Reactor statistics response"""
    events_processed: int = 0
    trades_processed: int = 0
    price_changes_processed: int = 0
    books_processed: int = 0
    shocks_detected: int = 0
    reactions_classified: int = 0
    leading_events_detected: int = 0
    state_changes: int = 0
    tracked_books: int = 0
    shock_detector: Dict[str, Any] = Field(default_factory=dict)
    classifier: Dict[str, Any] = Field(default_factory=dict)
    belief_engine: Dict[str, Any] = Field(default_factory=dict)
    alert_system: Optional[Dict[str, Any]] = None


class ReactionEventResponse(BaseModel):
    """Single reaction event"""
    reaction_id: str
    shock_id: str
    timestamp: int
    token_id: str
    price: str
    side: str
    reaction_type: ReactionTypeEnum
    window_type: WindowTypeEnum
    baseline_size: float
    refill_ratio: float
    drop_ratio: float
    time_to_refill_ms: Optional[int] = None
    min_liquidity: float
    max_liquidity: float
    vacuum_duration_ms: int
    shift_ticks: int
    indicator: str


class ReactionListResponse(BaseModel):
    """List of reaction events"""
    reactions: List[ReactionEventResponse]
    count: int
    limit: int


class MarketStateResponse(BaseModel):
    """Single market state"""
    token_id: str
    state: BeliefStateEnum
    indicator: str
    since_ts: int
    confidence: float


class AllStatesResponse(BaseModel):
    """All market states"""
    states: Dict[str, MarketStateResponse]
    total_markets: int
    distribution: Dict[str, int]


class StateChangeResponse(BaseModel):
    """State change event"""
    id: str
    timestamp: int
    old_state: BeliefStateEnum
    new_state: BeliefStateEnum
    trigger_reaction_id: Optional[str] = None
    evidence: List[str]
    old_indicator: str
    new_indicator: str


class StateHistoryResponse(BaseModel):
    """State change history"""
    token_id: str
    history: List[StateChangeResponse]
    count: int


class LeadingEventResponse(BaseModel):
    """Single leading event"""
    event_id: str
    event_type: LeadingEventTypeEnum
    timestamp: int
    token_id: str
    price: str
    side: str
    drop_ratio: float
    duration_ms: int
    trade_volume_nearby: float
    is_anchor: bool
    affected_levels: int


class LeadingEventListResponse(BaseModel):
    """List of leading events"""
    events: List[LeadingEventResponse]
    count: int
    limit: int


class MarketSummaryResponse(BaseModel):
    """Market summary from reactor"""
    token_id: str
    state: str
    indicator: str
    state_v2: str
    indicator_v2: str
    best_bid: Optional[str] = None
    best_ask: Optional[str] = None
    bid_key_levels: List[str]
    ask_key_levels: List[str]
    last_update: int


class AllMarketsResponse(BaseModel):
    """All tracked markets"""
    markets: List[MarketSummaryResponse]
    count: int


class EventInjectionRequest(BaseModel):
    """Request to inject test event"""
    event_type: str = Field(..., description="book, trade, or price_change")
    token_id: str
    payload: Dict[str, Any]
    server_ts: Optional[int] = None


class EventInjectionResponse(BaseModel):
    """Response after event injection"""
    success: bool
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/stats", response_model=ReactorStatsResponse)
async def get_reactor_stats():
    """
    Get reactor statistics.

    Returns processing counts, detector stats, and engine metrics.
    """
    service = get_reactor_service()
    stats = await service.get_stats()
    return ReactorStatsResponse(**stats)


@router.get("/reactions", response_model=ReactionListResponse)
async def get_recent_reactions(
    token_id: Optional[str] = Query(None, description="Filter by token ID"),
    limit: int = Query(100, ge=1, le=1000, description="Max reactions to return"),
):
    """
    Get recent reaction events.

    Returns classified reactions (VACUUM, SWEEP, PULL, HOLD, etc.)
    """
    service = get_reactor_service()
    reactions = await service.get_recent_reactions(token_id=token_id, limit=limit)

    return ReactionListResponse(
        reactions=[ReactionEventResponse(**r) for r in reactions],
        count=len(reactions),
        limit=limit,
    )


@router.get("/states", response_model=AllStatesResponse)
async def get_all_belief_states():
    """
    Get current belief states for all tracked markets.

    Returns state, indicator, confidence, and distribution.
    """
    belief_service = get_belief_service()
    states = await belief_service.get_all_states()
    distribution = await belief_service.get_state_distribution()

    formatted_states = {
        token_id: MarketStateResponse(
            token_id=token_id,
            state=BeliefStateEnum(data['state']),
            indicator=data['indicator'],
            since_ts=data['since_ts'],
            confidence=data['confidence'],
        )
        for token_id, data in states.items()
    }

    return AllStatesResponse(
        states=formatted_states,
        total_markets=len(states),
        distribution=distribution,
    )


@router.get("/state/{token_id}", response_model=MarketStateResponse)
async def get_market_state(token_id: str):
    """
    Get belief state for a specific market.
    """
    belief_service = get_belief_service()
    state_data = await belief_service.get_state(token_id)

    return MarketStateResponse(
        token_id=token_id,
        state=BeliefStateEnum(state_data['state']),
        indicator=state_data['indicator'],
        since_ts=state_data['since_ts'],
        confidence=state_data['confidence'],
    )


@router.get("/state/{token_id}/history", response_model=StateHistoryResponse)
async def get_state_history(
    token_id: str,
    limit: int = Query(100, ge=1, le=500),
):
    """
    Get state change history for a market.
    """
    belief_service = get_belief_service()
    history = await belief_service.get_state_history(token_id, limit=limit)

    return StateHistoryResponse(
        token_id=token_id,
        history=[
            StateChangeResponse(
                id=h['id'],
                timestamp=h['timestamp'],
                old_state=BeliefStateEnum(h['old_state']),
                new_state=BeliefStateEnum(h['new_state']),
                trigger_reaction_id=h.get('trigger_reaction_id'),
                evidence=h.get('evidence', []),
                old_indicator=h['old_indicator'],
                new_indicator=h['new_indicator'],
            )
            for h in history
        ],
        count=len(history),
    )


@router.get("/leading-events", response_model=LeadingEventListResponse)
async def get_leading_events(
    token_id: Optional[str] = Query(None, description="Filter by token ID"),
    limit: int = Query(100, ge=1, le=1000),
):
    """
    Get recent leading events.

    Leading events are pre-shock signals that don't require trades:
    - PRE_SHOCK_PULL: Depth pulled without trades
    - DEPTH_COLLAPSE: Multiple levels collapse simultaneously
    - GRADUAL_THINNING: Slow depth withdrawal
    """
    service = get_reactor_service()
    events = service.reactor.get_recent_leading_events(limit=limit)

    if token_id:
        events = [e for e in events if e['token_id'] == token_id]

    return LeadingEventListResponse(
        events=[LeadingEventResponse(**e) for e in events[:limit]],
        count=len(events),
        limit=limit,
    )


@router.get("/markets", response_model=AllMarketsResponse)
async def get_tracked_markets():
    """
    Get all markets currently tracked by the reactor.

    Returns order book state and key levels for each market.
    """
    service = get_reactor_service()
    markets = await service.get_all_markets()

    return AllMarketsResponse(
        markets=[MarketSummaryResponse(**m) for m in markets],
        count=len(markets),
    )


@router.get("/markets/{token_id}", response_model=MarketSummaryResponse)
async def get_market_summary(token_id: str):
    """
    Get summary for a specific market.
    """
    service = get_reactor_service()
    summary = await service.get_market_summary(token_id)

    if not summary:
        raise HTTPException(status_code=404, detail=f"Market {token_id} not tracked")

    return MarketSummaryResponse(**summary)


@router.post("/events", response_model=EventInjectionResponse)
async def inject_event(
    request: EventInjectionRequest,
    http_request: Request,
):
    """
    Inject a test event into the reactor.

    **DANGEROUS OPERATION** - Requires:
    1. Environment: REACTOR_ALLOW_INJECTION=true
    2. Authentication: Valid API key with ADMIN role
    3. Permission: dangerous:inject

    All injection attempts are logged to audit trail.

    Event types:
    - book: Order book snapshot
    - trade: Trade execution
    - price_change: Price level update

    Returns:
    - EventInjectionResponse with success status
    """
    audit_logger = get_audit_logger()
    client_ip = http_request.client.host if http_request.client else "unknown"
    user_agent = http_request.headers.get("user-agent", "unknown")

    # Extract roles from request state (set by auth middleware)
    roles = getattr(http_request.state, "roles", [])
    api_key_id = getattr(http_request.state, "api_key_id", "anonymous")

    # Security Check 1: Environment flag
    if os.getenv("REACTOR_ALLOW_INJECTION", "false").lower() != "true":
        # Log denied attempt
        audit_logger.log(
            action=AuditAction.DATA_INJECTION_DENIED,
            actor_type="key",
            actor_id=api_key_id,
            resource_type="reactor",
            resource_id=request.token_id,
            result="denied",
            details={
                "reason": "injection_disabled",
                "event_type": request.event_type,
            },
            ip_address=client_ip,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=403,
            detail="Event injection disabled. Set REACTOR_ALLOW_INJECTION=true to enable."
        )

    # Security Check 2: Permission check (ADMIN only)
    has_permission = check_permission(
        roles=roles,
        required_permission="dangerous:inject",
    )

    if not has_permission:
        # Log authorization failure
        audit_logger.log(
            action=AuditAction.AUTHZ_DENIED,
            actor_type="key",
            actor_id=api_key_id,
            resource_type="reactor",
            resource_id=request.token_id,
            result="denied",
            details={
                "reason": "insufficient_permission",
                "required": "dangerous:inject",
                "roles": roles,
                "event_type": request.event_type,
            },
            ip_address=client_ip,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=403,
            detail="Permission denied. Event injection requires ADMIN role with dangerous:inject permission."
        )

    # Process the event
    service = get_reactor_service()

    event_data = {
        'event_type': request.event_type,
        'token_id': request.token_id,
        'payload': request.payload,
        'server_ts': request.server_ts or int(time.time() * 1000),
    }

    try:
        await service.process_event(event_data)

        # Log successful injection (DANGEROUS operation)
        audit_logger.log(
            action=AuditAction.DANGEROUS_EVENT_INJECTION,
            actor_type="key",
            actor_id=api_key_id,
            resource_type="reactor",
            resource_id=request.token_id,
            result="success",
            details={
                "event_type": request.event_type,
                "payload_size": len(str(request.payload)),
                "server_ts": event_data['server_ts'],
            },
            ip_address=client_ip,
            user_agent=user_agent,
        )

        return EventInjectionResponse(
            success=True,
            message=f"Event {request.event_type} injected for {request.token_id}"
        )

    except Exception as e:
        # Log failed injection
        audit_logger.log(
            action=AuditAction.DANGEROUS_EVENT_INJECTION,
            actor_type="key",
            actor_id=api_key_id,
            resource_type="reactor",
            resource_id=request.token_id,
            result="failure",
            details={
                "event_type": request.event_type,
                "error": str(e),
            },
            ip_address=client_ip,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Event injection failed: {str(e)}"
        )


@router.post("/start")
async def start_reactor():
    """
    Start the reactor service.

    The reactor must be started before it can process events.
    """
    service = get_reactor_service()
    await service.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_reactor():
    """
    Stop the reactor service.
    """
    service = get_reactor_service()
    await service.stop()
    return {"status": "stopped"}


@router.get("/health")
async def reactor_health():
    """
    Reactor health check.
    """
    service = get_reactor_service()
    stats = await service.get_stats()

    return {
        "healthy": True,
        "running": service._started,
        "events_processed": stats.get('events_processed', 0),
        "tracked_markets": stats.get('tracked_books', 0),
    }
