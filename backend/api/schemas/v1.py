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
    MUTED = "MUTED"       # v5.36: Temporarily suppressed
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


# v5.36: False positive reason categories for algorithm improvement
class FalsePositiveReason(str, Enum):
    """
    Reason categories for false positive alerts.
    This data feeds back into algorithm improvement.

    v5.36: False positive tracking is critical for algorithm evolution.
    """
    THIN_MARKET = "THIN_MARKET"      # Low liquidity caused false trigger
    NOISE = "NOISE"                   # Random noise, not meaningful signal
    MANIPULATION = "MANIPULATION"     # Detected manipulation pattern
    STALE_DATA = "STALE_DATA"         # Data lag/staleness caused false trigger
    THRESHOLD_TOO_SENSITIVE = "THRESHOLD_TOO_SENSITIVE"  # Need to adjust thresholds
    OTHER = "OTHER"                   # Other reason (requires note)


# v5.34: Evidence Grade - mandatory quality indicator
class EvidenceGrade(str, Enum):
    """
    Evidence quality grade - determines what actions can be taken.

    v5.34: World-class evidence integrity requirement.

    Grade A: Full integrity - all data complete, hashes verified
    Grade B: Minor issues - small gaps but replayable
    Grade C: Degraded - significant gaps, use with caution
    Grade D: Tainted - data integrity compromised, manual review required

    Alert Policy Binding:
    - CRITICAL alerts ONLY allowed for Grade A/B evidence
    - Grade C/D evidence can only trigger MEDIUM/LOW with manual confirmation
    """
    A = "A"  # Full integrity
    B = "B"  # Minor issues
    C = "C"  # Degraded
    D = "D"  # Tainted


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

class LatencyInfo(BaseModel):
    """
    Detection latency disclosure.

    v5.36: Per expert review - "让用户明确知道你什么时候才知道"
    Prevents system from being mistaken as "prediction".
    """
    event_ts: int = Field(..., description="When the market event occurred (ms)")
    detected_ts: int = Field(..., description="When the system detected it (ms)")
    detection_latency_ms: int = Field(..., description="Detection delay in ms")
    window_type: Optional[str] = Field(None, description="FAST/SLOW/IMMEDIATE")
    observation_end_ts: Optional[int] = Field(None, description="When observation window ended (ms)")


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
    # v5.36: Latency disclosure
    latency: Optional[LatencyInfo] = Field(None, description="v5.36: Detection latency disclosure")


class ReactionProof(BaseModel):
    """Proof data for reaction classification"""
    drop_ratio: Optional[float] = None
    refill_ratio: Optional[float] = None
    vacuum_duration_ms: Optional[int] = None
    shift_ticks: Optional[int] = None
    time_to_refill_ms: Optional[int] = None


class ReactionAttributionSummary(BaseModel):
    """Compact attribution summary for reactions (v5.25)"""
    trade_driven_ratio: float = Field(..., ge=0, le=1)
    cancel_driven_ratio: float = Field(..., ge=0, le=1)
    attribution_type: str  # TRADE_DRIVEN, CANCEL_DRIVEN, MIXED, etc.


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
    attribution: Optional[ReactionAttributionSummary] = Field(None, description="v5.25: Attribution data")
    # v5.36: Latency disclosure
    latency: Optional[LatencyInfo] = Field(None, description="v5.36: Detection latency disclosure")


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


class RadarStateExplanationCompact(BaseModel):
    """Compact state explanation for radar display (v5.25)"""
    headline: str
    trend: str = "STABLE"  # IMPROVING, STABLE, WORSENING, VOLATILE
    top_factors: List[str] = Field(default_factory=list, max_length=3)


class RadarRow(BaseModel):
    """Single row in radar response"""
    market: MarketSummary
    belief_state: BeliefState
    state_since_ts: int
    state_severity: int = Field(..., ge=0, le=3, description="STABLE=0..BROKEN=3")
    evidence_grade: EvidenceGrade = Field(..., description="v5.34: Evidence quality grade (A/B/C/D)")
    fragile_index_10m: float = Field(..., ge=0)
    leading_rate_10m: float = Field(..., ge=0)
    evidence_confidence: float = Field(..., ge=0, le=100, description="v5.36: Evidence completeness confidence (NOT market confidence)")
    data_health: DataHealth
    last_critical_alert: Optional[LastCriticalAlert] = None
    explanation: Optional[RadarStateExplanationCompact] = Field(None, description="v5.25: State explanation")


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
    evidence_grade: EvidenceGrade = Field(..., description="v5.34: Evidence quality grade (A/B/C/D)")
    anchors: List[AnchorLevel]
    shocks: List[ShockEvent]
    reactions: List[ReactionEvent]
    leading_events: List[LeadingEvent]
    belief_states: List[BeliefStateChange]
    data_health: DataHealth
    tiles_manifest: Optional[TilesManifest] = None
    bundle_hash: Optional[str] = Field(None, description="Cryptographic hash for evidence verification (v5.3)")
    state_explanation: Optional["StateExplanationInfo"] = Field(None, description="v5.25: Detailed state explanation")


# =============================================================================
# Alerts API
# =============================================================================

class Alert(BaseModel):
    """
    Alert notification

    v5.34: evidence_grade determines allowed severity:
    - Grade A/B: Can trigger any severity including CRITICAL
    - Grade C/D: Can only trigger MEDIUM/LOW, requires manual confirmation for escalation

    v5.36: Recovery evidence required for resolution
    - resolution requires system-generated recovery_evidence
    - false_positive tracking for algorithm improvement
    - counterfactual disclaimer for CRITICAL/HIGH alerts
    """
    alert_id: str
    token_id: str
    ts: int
    severity: AlertSeverity
    evidence_grade: EvidenceGrade = Field(..., description="v5.34: Evidence quality grade")
    status: AlertStatus
    type: str
    summary: str
    evidence_confidence: float = Field(..., ge=0, le=100, description="v5.36: Evidence completeness confidence (NOT market confidence)")
    evidence_ref: EvidenceRef
    payload: Optional[Dict[str, Any]] = None
    # v5.36: Recovery evidence for resolution
    recovery_evidence: Optional[List[str]] = Field(None, description="v5.36: System-generated evidence supporting resolution")
    resolved_at: Optional[int] = Field(None, description="Timestamp when resolved")
    resolved_by: Optional[str] = Field(None, description="Who resolved (user_id or 'system')")
    # v5.36: False positive tracking
    is_false_positive: bool = Field(False, description="v5.36: Marked as false positive")
    false_positive_reason: Optional[str] = Field(None, description="v5.36: Reason for false positive (thin_market, noise, manipulation, other)")
    # v5.36: Counterfactual disclaimer (required for CRITICAL/HIGH)
    disclaimer: str = Field(
        default="This alert indicates observed belief instability. It does NOT imply outcome direction or trading recommendation.",
        description="v5.36: Counterfactual disclaimer - alerts are evidence, not predictions"
    )


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
# Attribution (v5.25)
# =============================================================================

class AttributionTypeEnum(str, Enum):
    """Primary attribution type for depth changes"""
    TRADE_DRIVEN = "TRADE_DRIVEN"
    CANCEL_DRIVEN = "CANCEL_DRIVEN"
    MIXED = "MIXED"
    REPLENISHMENT = "REPLENISHMENT"
    NO_CHANGE = "NO_CHANGE"


class DepthChangeAttributionInfo(BaseModel):
    """Attribution for a single depth change event"""
    depth_before: float
    depth_after: float
    trade_volume: float
    depth_removed: float
    trade_driven_volume: float
    cancel_driven_volume: float
    trade_driven_ratio: float = Field(..., ge=0, le=1)
    cancel_driven_ratio: float = Field(..., ge=0, le=1)
    attribution_type: AttributionTypeEnum
    price_level: Optional[str] = None


class MultiLevelAttributionInfo(BaseModel):
    """Attribution aggregated across multiple price levels"""
    levels_affected: int
    total_depth_removed: float
    total_trade_driven: float
    total_cancel_driven: float
    trade_driven_ratio: float = Field(..., ge=0, le=1)
    cancel_driven_ratio: float = Field(..., ge=0, le=1)
    attribution_type: AttributionTypeEnum


# =============================================================================
# Explainability (v5.25)
# =============================================================================

class TrendDirection(str, Enum):
    """Belief state trend direction"""
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    WORSENING = "WORSENING"
    VOLATILE = "VOLATILE"


class ExplainFactorType(str, Enum):
    """Factors that contribute to belief state"""
    HIGH_HOLD_RATIO = "HIGH_HOLD_RATIO"
    LOW_FRAGILE_SIGNALS = "LOW_FRAGILE_SIGNALS"
    CONSISTENT_DEPTH = "CONSISTENT_DEPTH"
    QUICK_REFILL = "QUICK_REFILL"
    NO_VACUUM = "NO_VACUUM"
    LOW_HOLD_RATIO = "LOW_HOLD_RATIO"
    VACUUM_AT_KEY_LEVEL = "VACUUM_AT_KEY_LEVEL"
    PULL_AT_KEY_LEVEL = "PULL_AT_KEY_LEVEL"
    DEPTH_COLLAPSE = "DEPTH_COLLAPSE"
    PRE_SHOCK_PULL = "PRE_SHOCK_PULL"
    MULTIPLE_VACUUM = "MULTIPLE_VACUUM"
    GRADUAL_THINNING = "GRADUAL_THINNING"
    CANCEL_DOMINATED = "CANCEL_DOMINATED"
    HIGH_FRAGILITY_INDEX = "HIGH_FRAGILITY_INDEX"
    RECENT_STATE_CHANGE = "RECENT_STATE_CHANGE"
    ACTIVE_ALERTS = "ACTIVE_ALERTS"


class ExplainFactor(BaseModel):
    """A single explanatory factor"""
    factor: ExplainFactorType
    weight: float = Field(..., ge=-1.0, le=1.0)
    value: Any
    threshold: Optional[Any] = None
    description: Dict[str, str] = Field(default_factory=dict)


class CounterfactualCondition(BaseModel):
    """What would need to change to reach a different state"""
    target_state: str
    conditions: List[str]
    likelihood: str = Field(..., description="high, medium, or low")


class StateExplanationInfo(BaseModel):
    """
    Complete explanation for a belief state.

    v5.36: Renamed confidence → classification_confidence to avoid confusion.
    This is the confidence in the state CLASSIFICATION, not in the evidence or market.
    """
    token_id: str
    current_state: str
    classification_confidence: float = Field(..., ge=0, le=100, description="v5.36: Confidence in state classification (NOT evidence or market confidence)")
    headline: str
    summary: str
    positive_factors: List[ExplainFactor] = Field(default_factory=list)
    negative_factors: List[ExplainFactor] = Field(default_factory=list)
    trend: TrendDirection = TrendDirection.STABLE
    trend_reason: str = ""
    counterfactuals: List[CounterfactualCondition] = Field(default_factory=list)
    generated_at: int
    window_minutes: int = 10


# =============================================================================
# Evidence Chain API (v5.36)
# =============================================================================

class EvidenceChainNode(BaseModel):
    """
    Single node in the evidence chain.

    v5.36: Evidence chain enforces complete lineage visibility.
    """
    node_type: str = Field(..., description="Type: SHOCK, REACTION, LEADING_EVENT, STATE_CHANGE, ALERT")
    node_id: str
    ts: int
    summary: str = Field(..., description="Human-readable summary of this node")
    details: Dict[str, Any] = Field(default_factory=dict, description="Type-specific details")
    evidence_refs: List[str] = Field(default_factory=list, description="References to upstream nodes")


class EvidenceChainResponse(BaseModel):
    """
    Complete evidence chain for an alert.

    v5.36: Per expert review - "反应 → 状态 → 告警 的证据链视图"
    Forces users to see the complete lineage, not just the final state.

    Chain structure:
    - Shock(s) → Reaction(s) → Leading Event(s) → State Change(s) → Alert
    """
    alert_id: str
    token_id: str
    generated_at: int

    # The evidence chain nodes in causal order
    chain: List[EvidenceChainNode] = Field(..., description="Nodes in causal order (earliest first)")

    # Summary statistics
    shock_count: int = 0
    reaction_count: int = 0
    leading_event_count: int = 0
    state_change_count: int = 0

    # Time span
    chain_start_ts: int
    chain_end_ts: int
    chain_duration_ms: int


class ReactionDistribution(BaseModel):
    """
    Reaction type distribution over a time window.

    v5.36: Per expert review - shows distribution instead of single events.
    """
    reaction_type: ReactionType
    count: int
    ratio: float = Field(..., ge=0, le=1, description="Ratio of total reactions")


class ReactionDistributionResponse(BaseModel):
    """
    Aggregated reaction distribution for a token.

    v5.36: "强调结构，淡化事件"
    """
    token_id: str
    from_ts: int
    to_ts: int
    window_minutes: int
    total_reactions: int
    distribution: List[ReactionDistribution]
    # Structural summary
    hold_dominant: bool = Field(..., description="True if HOLD > 50%")
    stress_ratio: float = Field(..., ge=0, le=1, description="Ratio of stress reactions (VACUUM+PULL+SWEEP)")


# =============================================================================
# Error Response
# =============================================================================

class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
