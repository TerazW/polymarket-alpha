"""
Belief Reaction System - Pydantic Schemas
WebSocket message models and API schemas.

WebSocket Message Types:
- book: Full orderbook snapshot
- price_change: Incremental update (size = NEW value, NOT delta!)
- last_trade_price: Trade execution
- tick_size_change: Tick size change (at price extremes)
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class ReactionType(str, Enum):
    """
    Seven atomic reaction types - the system's core vocabulary.
    Ordered by priority (higher priority checked first during classification).

    MUST match poc/models.py ReactionType exactly.
    """
    VACUUM = "VACUUM"       # 1. Highest: liquidity completely vanishes
    SWEEP = "SWEEP"         # 2. Multiple levels swept / rapid repricing
    CHASE = "CHASE"         # 3. Anchor moved, belief repricing
    PULL = "PULL"           # 4. Retreat: cancels immediately after shock
    HOLD = "HOLD"           # 5. Defend: refills quickly after shock
    DELAYED = "DELAYED"     # 6. Hesitate: partial/slow refill
    NO_IMPACT = "NO_IMPACT" # 7. Drop too small, no meaningful reaction


class BeliefState(str, Enum):
    """Four belief states for the state machine."""
    STABLE = "STABLE"       # Market belief is firm/consistent
    FRAGILE = "FRAGILE"     # Market belief shows weakness
    CRACKING = "CRACKING"   # Market belief actively breaking
    BROKEN = "BROKEN"       # Market belief has collapsed


# State indicators for display
STATE_INDICATORS = {
    BeliefState.STABLE: "🟢",
    BeliefState.FRAGILE: "🟡",
    BeliefState.CRACKING: "🟠",
    BeliefState.BROKEN: "🔴",
}


# =============================================================================
# WebSocket Message Schemas
# =============================================================================

class OrderBookLevel(BaseModel):
    """Single price level in order book."""
    price: str
    size: str


class BookMessage(BaseModel):
    """
    Full orderbook snapshot.

    Emitted on:
    - First subscription
    - After trade affects book
    """
    event_type: Literal["book"] = "book"
    asset_id: str
    market: str  # condition_id
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    timestamp: str
    hash: Optional[str] = None


class PriceChange(BaseModel):
    """Single price change in price_change message."""
    asset_id: str
    price: str
    size: str  # NEW aggregate size, NOT delta!
    side: str  # "BUY" or "SELL"
    hash: Optional[str] = None
    best_bid: Optional[str] = None
    best_ask: Optional[str] = None


class PriceChangeMessage(BaseModel):
    """
    Incremental orderbook update.

    CRITICAL: size field is NEW AGGREGATE SIZE, not delta!

    Emitted on:
    - New order placed
    - Order cancelled
    """
    event_type: Literal["price_change"] = "price_change"
    market: str  # condition_id
    timestamp: str
    price_changes: List[PriceChange]


class LastTradePriceMessage(BaseModel):
    """
    Trade execution message.

    Used for shock detection.
    """
    event_type: Literal["last_trade_price"] = "last_trade_price"
    asset_id: str
    market: str  # condition_id
    price: str
    side: str  # "BUY" or "SELL" (aggressor side)
    size: str
    timestamp: str


class TickSizeChangeMessage(BaseModel):
    """
    Tick size change message.

    Emitted when price > 0.96 or < 0.04.
    Tick changes from 0.01 to 0.001.
    """
    event_type: Literal["tick_size_change"] = "tick_size_change"
    asset_id: str
    old_tick_size: str
    new_tick_size: str
    timestamp: str


# =============================================================================
# API Response Schemas
# =============================================================================

class MarketResponse(BaseModel):
    """Market metadata response."""
    condition_id: str
    question: str
    slug: Optional[str] = None
    yes_token_id: str
    no_token_id: str
    tick_size: float = 0.01
    active: bool = True
    closed: bool = False
    volume_24h: Optional[float] = None
    liquidity: Optional[float] = None


class MarketStateResponse(BaseModel):
    """Market belief state response."""
    token_id: str
    state: BeliefState
    indicator: str
    last_reaction: Optional[str] = None
    last_reaction_time: Optional[datetime] = None


class HeatmapBin(BaseModel):
    """Single bin in heatmap data."""
    ts: datetime
    price: float
    size: float
    side: str


class HeatmapResponse(BaseModel):
    """Heatmap data response."""
    token_id: str
    from_ts: datetime
    to_ts: datetime
    resolution_ms: int
    bins: List[HeatmapBin]


class ReactionEventResponse(BaseModel):
    """Reaction event response."""
    reaction_id: str
    shock_id: str
    ts: datetime
    token_id: str
    price: float
    side: str
    reaction_type: ReactionType
    refill_ratio: Optional[float] = None
    time_to_refill_ms: Optional[int] = None
    min_liquidity: Optional[float] = None
    price_shift: Optional[float] = None


class AlertResponse(BaseModel):
    """Alert response."""
    type: str  # SHOCK, REACTION, STATE_CHANGE
    token_id: str
    ts: datetime
    message: str
    evidence: Optional[List[str]] = None
