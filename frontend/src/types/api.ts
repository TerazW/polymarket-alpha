/**
 * Belief Reaction System - v5 API Types
 *
 * "看存在没意义，看反应才有意义"
 */

// =============================================================================
// ENUMS
// =============================================================================

export type BeliefState = 'STABLE' | 'FRAGILE' | 'CRACKING' | 'BROKEN';

export type ReactionType =
  | 'VACUUM'
  | 'SWEEP'
  | 'CHASE'
  | 'PULL'
  | 'HOLD'
  | 'DELAYED'
  | 'NO_IMPACT';

export type LeadingEventType =
  | 'PRE_SHOCK_PULL'
  | 'DEPTH_COLLAPSE'
  | 'GRADUAL_THINNING';

export type AlertType = 'SHOCK' | 'REACTION' | 'LEADING_EVENT' | 'STATE_CHANGE';

export type AlertPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

// =============================================================================
// STATE INDICATORS
// =============================================================================

export const STATE_INDICATORS: Record<BeliefState, string> = {
  STABLE: '🟢',
  FRAGILE: '🟡',
  CRACKING: '🟠',
  BROKEN: '🔴',
};

export const STATE_COLORS: Record<BeliefState, string> = {
  STABLE: '#22c55e',   // green-500
  FRAGILE: '#eab308',  // yellow-500
  CRACKING: '#f97316', // orange-500
  BROKEN: '#ef4444',   // red-500
};

export const REACTION_COLORS: Record<ReactionType, string> = {
  VACUUM: '#ef4444',   // red
  SWEEP: '#f97316',    // orange
  CHASE: '#06b6d4',    // cyan
  PULL: '#a855f7',     // purple
  HOLD: '#22c55e',     // green
  DELAYED: '#eab308',  // yellow
  NO_IMPACT: '#6b7280', // gray
};

// =============================================================================
// RADAR API - /v1/radar
// =============================================================================

export interface RadarMarket {
  token_id: string;
  condition_id: string;
  question: string;

  // Current state
  state: BeliefState;
  state_since: number;  // timestamp ms

  // Metrics (0-100)
  confidence: number;
  leading_rate_10m: number;   // leading events per 10 min
  fragile_index_10m: number;  // weighted fragility score

  // Latest alert
  last_critical_alert: {
    type: AlertType;
    timestamp: number;
    evidence_ref: string;  // evidence window ID
  } | null;

  // Market info
  yes_price: number | null;
  volume_24h: number;
}

export interface RadarResponse {
  event_id?: string;
  markets: RadarMarket[];
  updated_at: number;
}

// =============================================================================
// EVIDENCE API - /v1/evidence
// =============================================================================

export interface Anchor {
  price: string;  // Decimal as string
  side: 'bid' | 'ask';
  score: number;  // 0-1, importance score
}

export interface ShockEvent {
  id: string;
  timestamp: number;
  price: string;
  side: 'bid' | 'ask';
  trigger_type: 'volume' | 'consecutive';
  trade_volume: number;
  liquidity_before: number;
  baseline_size: number;
}

export interface ReactionEvent {
  id: string;
  timestamp: number;
  shock_id: string;
  price: string;
  side: 'bid' | 'ask';
  reaction_type: ReactionType;

  // Metrics
  drop_ratio: number;
  refill_ratio: number;
  min_size: number;
  max_size: number;
  time_to_min_ms: number;
  time_to_refill_ms: number | null;
  price_shift_ticks: number;

  // Proof
  proof: ReactionProof;
}

export interface ReactionProof {
  rule_triggered: string;
  thresholds: Record<string, number>;
  actual_values: Record<string, number>;
  window_type: 'FAST' | 'SLOW';
}

export interface LeadingEvent {
  id: string;
  timestamp: number;
  price: string;
  side: 'bid' | 'ask';
  event_type: LeadingEventType;

  // Metrics
  drop_ratio: number;
  trade_volume_nearby: number;
  levels_affected?: number;  // for DEPTH_COLLAPSE
  time_std_ms?: number;      // for DEPTH_COLLAPSE
}

export interface StateChange {
  id: string;
  timestamp: number;
  old_state: BeliefState;
  new_state: BeliefState;
  evidence: string[];
  evidence_refs: string[];  // reaction/leading event IDs
}

export interface ProofSummary {
  current_state: BeliefState;
  state_since: number;
  confidence: number;

  // Counts in window
  shock_count: number;
  reaction_counts: Record<ReactionType, number>;
  leading_event_counts: Record<LeadingEventType, number>;

  // Key metrics
  hold_ratio: number;  // HOLD / total reactions
  fragile_signals: number;  // PRE_SHOCK_PULL + DEPTH_COLLAPSE + VACUUM + PULL

  // Data health
  data_health: {
    missing_buckets: number;
    rebuild_count: number;
    last_rebuild_ts: number | null;
    hash_mismatch: boolean;
  };
}

export interface EvidenceResponse {
  token_id: string;
  t0: number;  // center timestamp

  // Window bounds
  window_start: number;
  window_end: number;

  // Data
  anchors: Anchor[];
  shocks: ShockEvent[];
  reactions: ReactionEvent[];
  leading_events: LeadingEvent[];
  state_changes: StateChange[];

  // Summary for right panel
  proof_summary: ProofSummary;

  // Heatmap tiles manifest
  tiles_manifest: TilesManifest;

  // v5.3: Cryptographic hash for evidence verification
  bundle_hash?: string;

  // v5.36: Evidence grade for data quality
  evidence_grade?: 'A' | 'B' | 'C' | 'D';
}

// =============================================================================
// HEATMAP TILES API - /v1/heatmap/tiles
// =============================================================================

export interface TilesManifest {
  token_id: string;
  lod: '250ms' | '1s' | '5s';
  tile_duration_ms: number;  // e.g., 10000 for 10s tiles

  tiles: TileInfo[];

  // Normalization metadata
  normalization: {
    method: 'log1p' | 'linear';
    clip_max: number;  // P95 depth
    price_min: string;
    price_max: string;
    tick_size: string;
  };
}

export interface TileInfo {
  tile_id: string;
  t_start: number;
  t_end: number;
  price_min: string;
  price_max: string;
  url: string;  // URL to fetch tile data
}

export interface TileData {
  tile_id: string;
  encoding: 'uint16' | 'float32';
  width: number;   // time buckets
  height: number;  // price levels

  // Binary data (base64 encoded)
  bid_data: string;
  ask_data: string;
}

// =============================================================================
// ALERTS API - /v1/alerts
// =============================================================================

export interface Alert {
  id: string;
  timestamp: number;
  token_id: string;

  alert_type: AlertType;
  priority: AlertPriority;

  // Content
  title: string;
  message: string;

  // Reference
  evidence_ref: string;

  // Status
  status: 'open' | 'ack' | 'resolved';
  ack_by?: string;
  ack_at?: number;
}

export interface AlertsResponse {
  alerts: Alert[];
  total: number;
  has_more: boolean;
}

// =============================================================================
// WEBSOCKET STREAM - /v1/stream
// =============================================================================

export type StreamMessage =
  | { type: 'alert'; data: Alert }
  | { type: 'state_update'; data: { token_id: string; state: BeliefState; timestamp: number } }
  | { type: 'data_health'; data: { token_id: string; issue: string; timestamp: number } };

// =============================================================================
// REPLAY API - /v1/replay
// =============================================================================

export interface ReplayCatalogItem {
  id: string;
  token_id: string;
  question: string;

  timestamp: number;
  event_type: AlertType;
  state_at_time: BeliefState;

  // Preview
  summary: string;
}

export interface ReplayCatalogResponse {
  items: ReplayCatalogItem[];
  total: number;
  has_more: boolean;
}
