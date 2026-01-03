"""
Belief Reaction System - Data Models
Core data structures for the reaction detection system.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional, Literal, List
import time
import uuid


class ReactionType(Enum):
    """Six atomic reaction types - the system's vocabulary."""
    HOLD = "HOLD"       # Defend: refills quickly after shock
    DELAY = "DELAY"     # Hesitate: partial/slow refill
    PULL = "PULL"       # Retreat: cancels immediately after shock
    VACUUM = "VACUUM"   # Vacuum: liquidity completely vanishes
    CHASE = "CHASE"     # Chase: anchor moved, belief repricing
    FAKE = "FAKE"       # Anchor: adds more after shock (psychological)


class BeliefState(Enum):
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


@dataclass
class PriceLevel:
    """
    Represents a single price level in the order book.
    This is the fundamental observation unit.
    """
    token_id: str
    price: Decimal
    side: Literal['bid', 'ask']

    # Current state
    size_now: float = 0.0
    size_peak: float = 0.0
    first_seen_ts: int = 0
    last_update_ts: int = 0

    # Behavioral statistics
    hit_count: int = 0
    last_hit_ts: int = 0
    refill_count: int = 0
    cancel_count: int = 0

    def __post_init__(self):
        if self.first_seen_ts == 0:
            self.first_seen_ts = int(time.time() * 1000)
        if self.last_update_ts == 0:
            self.last_update_ts = self.first_seen_ts

    def update_size(self, new_size: float, timestamp: int) -> float:
        """Update size and return delta."""
        old_size = self.size_now
        self.size_now = new_size
        self.size_peak = max(self.size_peak, new_size)
        self.last_update_ts = timestamp
        return new_size - old_size


@dataclass
class TradeEvent:
    """A single trade execution."""
    token_id: str
    price: Decimal
    size: float
    side: Literal['BUY', 'SELL']
    timestamp: int  # milliseconds

    @classmethod
    def from_ws_message(cls, msg: dict) -> 'TradeEvent':
        """Create from WebSocket last_trade_price message."""
        return cls(
            token_id=msg.get('asset_id', ''),
            price=Decimal(str(msg.get('price', '0'))),
            size=float(msg.get('size', 0)),
            side=msg.get('side', 'BUY').upper(),
            timestamp=int(msg.get('timestamp', 0))
        )


@dataclass
class ShockEvent:
    """
    A shock event where a price level is significantly impacted.
    Shock = discrete event where trading activity tests a level.
    """
    shock_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    token_id: str = ""
    price: Decimal = Decimal("0")
    side: Literal['bid', 'ask'] = 'bid'
    ts_start: int = 0
    trade_volume: float = 0.0
    liquidity_before: float = 0.0
    trigger_type: Literal['volume', 'consecutive'] = 'volume'

    # For tracking reaction
    reaction_window_end: int = 0  # When reaction window ends


@dataclass
class ReactionMetrics:
    """
    Metrics computed at the end of the reaction window.
    These determine the reaction classification.
    """
    # Liquidity changes
    net_liquidity_change: float = 0.0
    min_liquidity: float = 0.0
    max_liquidity: float = 0.0

    # Refill behavior
    refill_ratio: float = 0.0
    time_to_refill_ms: Optional[int] = None

    # Speed indicators
    cancel_speed: Literal['instant', 'fast', 'slow', 'none'] = 'none'

    # Price movement
    price_shift: Decimal = Decimal("0")


@dataclass
class ReactionEvent:
    """
    A classified reaction after observing the reaction window.
    This is what the system outputs.
    """
    reaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    shock_id: str = ""
    timestamp: int = 0
    token_id: str = ""
    price: Decimal = Decimal("0")
    side: Literal['bid', 'ask'] = 'bid'
    reaction_type: ReactionType = ReactionType.DELAY

    # Metrics snapshot
    refill_ratio: float = 0.0
    time_to_refill_ms: Optional[int] = None
    min_liquidity: float = 0.0
    price_shift: Decimal = Decimal("0")
    liquidity_before: float = 0.0  # For context


@dataclass
class BeliefStateChange:
    """Records a belief state transition."""
    timestamp: int
    token_id: str
    old_state: BeliefState
    new_state: BeliefState
    trigger_reaction_id: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
