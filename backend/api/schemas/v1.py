"""
Belief Reaction System - v1 API Schemas
Matches OpenAPI spec (openapi.yaml)
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class BeliefState(str, Enum):
    STABLE = "STABLE"
    FRAGILE = "FRAGILE"
    CRACKING = "CRACKING"
    BROKEN = "BROKEN"


class ReactionType(str, Enum):
    VACUUM = "VACUUM"
    SWEEP = "SWEEP"
    CHASE = "CHASE"
    PULL = "PULL"
    HOLD = "HOLD"
    DELAYED = "DELAYED"
    NO_IMPACT = "NO_IMPACT"


class LeadingEventType(str, Enum):
    PRE_SHOCK_PULL = "PRE_SHOCK_PULL"
    DEPTH_COLLAPSE = "DEPTH_COLLAPSE"
    GRADUAL_THINNING = "GRADUAL_THINNING"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    RESOLVED = "RESOLVED"


class Side(str, Enum):
    BID = "BID"
    ASK = "ASK"


class ShockTrigger(str, Enum):
    VOLUME = "VOLUME"
    CONSECUTIVE = "CONSECUTIVE"
    BOTH = "BOTH"


class ReactionWindow(str, Enum):
    FAST = "FAST"
    SLOW = "SLOW"


class TileBand(str, Enum):
    FULL = "FULL"
    BEST_5 = "BEST_5"
    BEST_10 = "BEST_10"
    BEST_20 = "BEST_20"


class ReplayCatalogKind(str, Enum):
    SHOCK = "SHOCK"
    REACTION = "REACTION"
    LEADING = "LEADING"
    BELIEF_STATE = "BELIEF_STATE"
    ALERT = "ALERT"


# =============================================================================
# Shared Components
# =============================================================================

class EvidenceRef(BaseModel):
    """Reference to evidence window"""
    token_id: str
    t0: int = Field(..., description="ms since epoch")


class DataHealth(BaseModel):
    """Data health metrics"""
    missing_bucket_ratio_10m: float = Field(..., ge=0, le=1)
    rebuild_count_10m: int = Field(..., ge=0)
    hash_mismatch_count_10m: int = Field(..., ge=0)
    last_rebuild_ts: Optional[int] = None
    last_hash_mismatch_ts: Optional[int] = None


class MarketSummary(BaseModel):
    """Market metadata summary"""
    token_id: str
    condition_id: str
    event_id: Optional[int] = None
    title: str
    event_slug: Optional[str] = None
    market_slug: Optional[str] = None
    outcome: str
    tick_size: float
    last_price: Optional[float] = Field(None, ge=0, le=1)


class AnchorLevel(BaseModel):
    """Anchor price level"""
    price: float = Field(..., ge=0, le=1)
    side: Side
    score: float
    rank: int = Field(..., ge=1)


# =============================================================================
# Event Schemas
# =============================================================================

class ShockEvent(BaseModel):
    """Shock detection event"""
    id: str
    token_id: str
    ts: int = Field(..., description="ms since epoch")
    price: float
    side: Side
    trade_vol: Optional[float] = None
    baseline_size: Optional[float] = None
    tick_size: float
    trigger: ShockTrigger


class ReactionProof(BaseModel):
    """Proof data for reaction classification"""
    drop_ratio: Optional[float] = None
    refill_ratio: Optional[float] = None
    vacuum_duration_ms: Optional[int] = None
    shift_ticks: Optional[int] = None
    time_to_refill_ms: Optional[int] = None


class ReactionEvent(BaseModel):
    """Reaction classification event"""
    id: str
    token_id: str
    shock_id: Optional[str] = None
    ts_start: int
    ts_end: int
    window: ReactionWindow
    price: float
    side: Side
    reaction: ReactionType
    proof: Optional[ReactionProof] = None


class PriceBand(BaseModel):
    """Price band for leading events"""
    price_min: float
    price_max: float


class LeadingEvent(BaseModel):
    """Leading indicator event"""
    id: str
    token_id: str
    ts: int
    type: LeadingEventType
    side: Side
    price_band: PriceBand
    proof: Optional[Dict[str, Any]] = None


class BeliefStateChange(BaseModel):
    """Belief state change event"""
    id: str
    token_id: str
    ts: int
    belief_state: BeliefState
    evidence_refs: List[str]
    note: Optional[str] = None


# =============================================================================
# Radar API
# =============================================================================

class LastCriticalAlert(BaseModel):
    """Last critical alert reference"""
    ts: int
    alert_id: str
    type: str
    evidence_ref: EvidenceRef


class RadarRow(BaseModel):
    """Single row in radar response"""
    market: MarketSummary
    belief_state: BeliefState
    state_since_ts: int
    state_severity: int = Field(..., ge=0, le=3, description="STABLE=0..BROKEN=3")
    fragile_index_10m: float = Field(..., ge=0)
    leading_rate_10m: float = Field(..., ge=0)
    confidence: float = Field(..., ge=0, le=100)
    data_health: DataHealth
    last_critical_alert: Optional[LastCriticalAlert] = None


class RadarResponse(BaseModel):
    """GET /v1/radar response"""
    rows: List[RadarRow]
    limit: int
    offset: int
    total: int


# =============================================================================
# Evidence API
# =============================================================================

class EvidenceWindow(BaseModel):
    """Time window for evidence"""
    from_ts: int
    to_ts: int


class TilesManifest(BaseModel):
    """Heatmap tiles manifest"""
    token_id: str
    lod_ms: int = Field(..., description="250, 1000, or 5000")
    tile_ms: int = Field(..., description="5000, 10000, or 15000")
    band: TileBand
    available_from_ts: int
    available_to_ts: int


class EvidenceResponse(BaseModel):
    """GET /v1/evidence response"""
    token_id: str
    t0: int
    window: EvidenceWindow
    market: MarketSummary
    anchors: List[AnchorLevel]
    shocks: List[ShockEvent]
    reactions: List[ReactionEvent]
    leading_events: List[LeadingEvent]
    belief_states: List[BeliefStateChange]
    data_health: DataHealth
    tiles_manifest: Optional[TilesManifest] = None
    bundle_hash: Optional[str] = Field(None, description="Cryptographic hash for evidence verification (v5.3)")


# =============================================================================
# Alerts API
# =============================================================================

class Alert(BaseModel):
    """Alert notification"""
    alert_id: str
    token_id: str
    ts: int
    severity: AlertSeverity
    status: AlertStatus
    type: str
    summary: str
    confidence: float = Field(..., ge=0, le=100)
    evidence_ref: EvidenceRef
    payload: Optional[Dict[str, Any]] = None


class AlertsResponse(BaseModel):
    """GET /v1/alerts response"""
    rows: List[Alert]
    limit: int
    offset: int
    total: int


# =============================================================================
# Replay Catalog API
# =============================================================================

class ReplayCatalogEntry(BaseModel):
    """Single entry in replay catalog"""
    kind: ReplayCatalogKind
    id: str
    token_id: str
    ts: int
    severity: Optional[AlertSeverity] = None
    label: str
    evidence_ref: EvidenceRef


class ReplayCatalogResponse(BaseModel):
    """GET /v1/replay/catalog response"""
    rows: List[ReplayCatalogEntry]
    limit: int
    offset: int
    total: int


# =============================================================================
# Heatmap Tiles API
# =============================================================================

class TileEncoding(BaseModel):
    """Tile encoding metadata"""
    dtype: str = "uint16"
    layout: str = "row_major"
    scale: str = "log1p_clip"
    clip_pctl: float = 0.95
    clip_value: Optional[float] = None
    endian: str = "little"


class TileCompression(BaseModel):
    """Tile compression metadata"""
    algo: str = "zstd"
    level: Optional[int] = None


class TileChecksum(BaseModel):
    """Tile checksum"""
    algo: str = "xxh3_64"
    value: str


class HeatmapTileMeta(BaseModel):
    """Heatmap tile with metadata and payload"""
    tile_id: str
    token_id: str
    lod_ms: int
    tile_ms: int
    band: TileBand
    t_start: int
    t_end: int
    tick_size: float
    price_min: float
    price_max: float
    rows: int = Field(..., ge=1)
    cols: int = Field(..., ge=1)
    encoding: TileEncoding
    compression: TileCompression
    payload_b64: str = Field(..., description="Base64 of compressed bytes")
    checksum: TileChecksum


class HeatmapTilesManifest(BaseModel):
    """Tiles manifest in response"""
    token_id: str
    from_ts: int
    to_ts: int
    lod_ms: int
    tile_ms: int
    band: TileBand


class HeatmapTilesResponse(BaseModel):
    """GET /v1/heatmap/tiles response"""
    manifest: HeatmapTilesManifest
    tiles: List[HeatmapTileMeta]


# =============================================================================
# Error Response
# =============================================================================

class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
