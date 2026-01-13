/**
 * Belief Reaction System - API Client
 * Connects to /v1 endpoints
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://api.marketsensemaking.com';

// =============================================================================
// Types matching backend response
// =============================================================================

export interface RadarRow {
  market: {
    token_id: string;
    condition_id: string;
    title: string;
    market_slug?: string;
    outcome: string;
    tick_size: number;
    last_price?: number;
  };
  belief_state: 'STABLE' | 'FRAGILE' | 'CRACKING' | 'BROKEN';
  state_since_ts: number;
  state_severity: number;
  evidence_grade: 'A' | 'B' | 'C' | 'D';  // v5.34
  fragile_index_10m: number;
  leading_rate_10m: number;
  data_health: {
    missing_bucket_ratio_10m: number;
    rebuild_count_10m: number;
    hash_mismatch_count_10m: number;
  };
  last_critical_alert?: {
    ts: number;
    alert_id: string;
    type: string;
    evidence_ref: { token_id: string; t0: number };
  };
}

export interface RadarResponse {
  rows: RadarRow[];
  limit: number;
  offset: number;
  total: number;
}

export interface EvidenceResponse {
  token_id: string;
  t0: number;
  window: { from_ts: number; to_ts: number };
  market: {
    token_id: string;
    condition_id: string;
    title: string;
    outcome: string;
    tick_size: number;
    last_price?: number | null;
  };
  anchors: Array<{
    price: number;
    side: 'BID' | 'ASK';
    score: number;
    rank: number;
  }>;
  shocks: Array<{
    id: string;
    token_id: string;
    ts: number;
    price: number;
    side: 'BID' | 'ASK';
    trade_vol?: number;
    baseline_size?: number;
    tick_size: number;
    trigger: 'VOLUME' | 'CONSECUTIVE' | 'BOTH';
  }>;
  reactions: Array<{
    id: string;
    token_id: string;
    shock_id?: string;
    ts_start: number;
    ts_end: number;
    window: 'FAST' | 'SLOW';
    price: number;
    side: 'BID' | 'ASK';
    reaction: string;
    proof?: {
      drop_ratio?: number;
      refill_ratio?: number;
      vacuum_duration_ms?: number;
      shift_ticks?: number;
      time_to_refill_ms?: number;
    };
  }>;
  leading_events: Array<{
    id: string;
    token_id: string;
    ts: number;
    type: string;
    side: 'BID' | 'ASK';
    price_band: { price_min: number; price_max: number };
    proof?: Record<string, unknown>;
  }>;
  belief_states: Array<{
    id: string;
    token_id: string;
    ts: number;
    belief_state: string;
    evidence_refs: string[];
    note?: string;
  }>;
  data_health: {
    missing_bucket_ratio_10m: number;
    rebuild_count_10m: number;
    hash_mismatch_count_10m: number;
  };
  tiles_manifest?: {
    token_id: string;
    lod_ms: number;
    tile_ms: number;
    band: string;
    available_from_ts: number;
    available_to_ts: number;
  };
  bundle_hash?: string;  // v5.3: Cryptographic hash for evidence verification
}

export interface AlertRow {
  alert_id: string;
  token_id: string;
  ts: number;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: 'OPEN' | 'ACKED' | 'RESOLVED' | 'MUTED';
  type: string;
  summary: string;
  evidence_ref: { token_id: string; t0: number };
  evidence_grade?: 'A' | 'B' | 'C' | 'D';
  disclaimer?: string;
  recovery_evidence?: string[];
  resolved_at?: number;
  resolved_by?: string;
  muted_until?: number;
}

export interface AlertsResponse {
  rows: AlertRow[];
  limit: number;
  offset: number;
  total: number;
}

export interface ReplayCatalogEntry {
  kind: 'SHOCK' | 'REACTION' | 'LEADING' | 'BELIEF_STATE' | 'ALERT';
  id: string;
  token_id: string;
  ts: number;
  severity?: string;
  label: string;
  evidence_ref: { token_id: string; t0: number };
}

export interface ReplayCatalogResponse {
  rows: ReplayCatalogEntry[];
  limit: number;
  offset: number;
  total: number;
}

// =============================================================================
// API Functions
// =============================================================================

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfter?: number
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const method = (options.method || 'GET').toUpperCase();

  // Build headers - only add Content-Type when there's a body
  // GET without Content-Type = simple request = no preflight
  const headers: Record<string, string> = {};
  if (options.headers) {
    Object.assign(headers, options.headers);
  }
  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  try {
    const res = await fetch(url, {
      ...options,
      method,
      headers,
      // Don't send credentials for simple CORS
      credentials: 'omit',
    });

    if (!res.ok) {
      // Handle 429 with Retry-After header
      if (res.status === 429) {
        const retryAfter = parseInt(res.headers.get('Retry-After') || '1', 10);
        throw new ApiError(429, `Rate limited. Retry after ${retryAfter}s`, retryAfter);
      }
      throw new ApiError(res.status, `API error: ${res.status}`);
    }

    return res.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // Check if aborted
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError(-1, 'Request aborted');
    }
    throw new ApiError(0, `Network error: ${error}`);
  }
}

// Export ApiError for external handling
export { ApiError };

// =============================================================================
// Radar API
// =============================================================================

export async function getRadar(params?: {
  event_id?: number;
  tag?: string;
  limit?: number;
  offset?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}): Promise<RadarResponse> {
  const searchParams = new URLSearchParams();
  if (params?.event_id) searchParams.set('event_id', String(params.event_id));
  if (params?.tag) searchParams.set('tag', params.tag);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  if (params?.offset) searchParams.set('offset', String(params.offset));
  if (params?.sort) searchParams.set('sort', params.sort);
  if (params?.order) searchParams.set('order', params.order);

  const query = searchParams.toString();
  return fetchApi<RadarResponse>(`/v1/radar${query ? `?${query}` : ''}`);
}

// =============================================================================
// Evidence API
// =============================================================================

export async function getEvidence(
  params: {
    token_id: string;
    t0: number;
    window_before_ms?: number;
    window_after_ms?: number;
    include_tiles_manifest?: boolean;
    lod?: 250 | 1000 | 5000;
  },
  signal?: AbortSignal
): Promise<EvidenceResponse> {
  // DEBUG: trace who is calling getEvidence
  console.trace('[DEBUG] getEvidence called', { token_id: params.token_id, t0: params.t0 });
  const searchParams = new URLSearchParams();
  searchParams.set('token_id', params.token_id);
  searchParams.set('t0', String(params.t0));
  if (params.window_before_ms) searchParams.set('window_before_ms', String(params.window_before_ms));
  if (params.window_after_ms) searchParams.set('window_after_ms', String(params.window_after_ms));
  if (params.include_tiles_manifest !== undefined) {
    searchParams.set('include_tiles_manifest', String(params.include_tiles_manifest));
  }
  if (params.lod) searchParams.set('lod', String(params.lod));

  return fetchApi<EvidenceResponse>(`/v1/evidence?${searchParams.toString()}`, { signal });
}

// =============================================================================
// Alerts API
// =============================================================================

export async function getAlerts(params?: {
  since?: number;
  token_id?: string;
  severity?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status?: 'OPEN' | 'ACKED' | 'RESOLVED';
  limit?: number;
  offset?: number;
}): Promise<AlertsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.since) searchParams.set('since', String(params.since));
  if (params?.token_id) searchParams.set('token_id', params.token_id);
  if (params?.severity) searchParams.set('severity', params.severity);
  if (params?.status) searchParams.set('status', params.status);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  if (params?.offset) searchParams.set('offset', String(params.offset));

  const query = searchParams.toString();
  return fetchApi<AlertsResponse>(`/v1/alerts${query ? `?${query}` : ''}`);
}

// =============================================================================
// Replay Catalog API
// =============================================================================

export async function getReplayCatalog(params: {
  from_ts: number;
  to_ts: number;
  token_id?: string;
  event_type?: 'SHOCK' | 'REACTION' | 'LEADING' | 'BELIEF_STATE' | 'ALERT';
  severity?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  limit?: number;
  offset?: number;
}): Promise<ReplayCatalogResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set('from_ts', String(params.from_ts));
  searchParams.set('to_ts', String(params.to_ts));
  if (params.token_id) searchParams.set('token_id', params.token_id);
  if (params.event_type) searchParams.set('event_type', params.event_type);
  if (params.severity) searchParams.set('severity', params.severity);
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));

  return fetchApi<ReplayCatalogResponse>(`/v1/replay/catalog?${searchParams.toString()}`);
}

// =============================================================================
// Health Check
// =============================================================================

export async function checkHealth(): Promise<{ ok: boolean; version: string }> {
  return fetchApi<{ ok: boolean; version: string }>('/v1/health');
}

// =============================================================================
// Heatmap Tiles API
// =============================================================================

export interface HeatmapTileEncoding {
  dtype: string;
  layout: string;
  scale: string;
  clip_pctl: number;
  clip_value?: number;
}

export interface HeatmapTileCompression {
  algo: string;
  level: number;
}

export interface HeatmapTileChecksum {
  algo: string;
  value: string;
}

export interface HeatmapTileMeta {
  tile_id: string;
  token_id: string;
  lod_ms: number;
  tile_ms: number;
  band: string;
  t_start: number;
  t_end: number;
  tick_size: number;
  price_min: number;
  price_max: number;
  rows: number;
  cols: number;
  encoding: HeatmapTileEncoding;
  compression: HeatmapTileCompression;
  payload_b64: string;
  checksum: HeatmapTileChecksum;
}

export interface HeatmapTilesManifest {
  token_id: string;
  from_ts: number;
  to_ts: number;
  lod_ms: number;
  tile_ms: number;
  band: string;
}

export interface HeatmapTilesResponse {
  manifest: HeatmapTilesManifest;
  bid_tiles: HeatmapTileMeta[];  // Green layer (bid side liquidity)
  ask_tiles: HeatmapTileMeta[];  // Red layer (ask side liquidity)
}

export async function getHeatmapTiles(
  params: {
    token_id: string;
    from_ts: number;
    to_ts: number;
    lod?: 250 | 1000 | 5000;
    tile_ms?: 5000 | 10000 | 15000;
    band?: 'FULL' | 'BID' | 'ASK';
    value_mode?: 'max' | 'sum' | 'last';
    synthetic?: boolean;
  },
  signal?: AbortSignal
): Promise<HeatmapTilesResponse> {
  // DEBUG: trace who is calling getHeatmapTiles
  console.trace('[DEBUG] getHeatmapTiles called', { token_id: params.token_id });
  const searchParams = new URLSearchParams();
  searchParams.set('token_id', params.token_id);
  searchParams.set('from_ts', String(params.from_ts));
  searchParams.set('to_ts', String(params.to_ts));
  if (params.lod) searchParams.set('lod', String(params.lod));
  if (params.tile_ms) searchParams.set('tile_ms', String(params.tile_ms));
  if (params.band) searchParams.set('band', params.band);
  if (params.value_mode) searchParams.set('value_mode', params.value_mode);
  if (params.synthetic) searchParams.set('synthetic', 'true');

  return fetchApi<HeatmapTilesResponse>(`/v1/heatmap/tiles?${searchParams.toString()}`, { signal });
}

// =============================================================================
// Heatmap Debug API (dev-only)
// =============================================================================

export interface HeatmapDebugResponse {
  token_id: string;
  from_ts: number;
  to_ts: number;
  lod_ms: number;
  tile_ms: number;
  band: string;
  value_mode: string;
  raw_counts?: Record<string, unknown>;
  size_stats?: Record<string, unknown>;
  tiles?: Record<string, unknown>;
  possible_zero_causes?: string[];
  errors?: string[];
}

export async function getHeatmapDebug(
  params: {
    token_id: string;
    from_ts: number;
    to_ts: number;
    lod?: 250 | 1000 | 5000;
    tile_ms?: 5000 | 10000 | 15000;
    band?: 'FULL' | 'BEST_5' | 'BEST_10' | 'BEST_20';
    value_mode?: 'max' | 'sum' | 'last';
    sample_tiles?: number;
  },
  signal?: AbortSignal
): Promise<HeatmapDebugResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set('token_id', params.token_id);
  searchParams.set('from_ts', String(params.from_ts));
  searchParams.set('to_ts', String(params.to_ts));
  if (params.lod) searchParams.set('lod', String(params.lod));
  if (params.tile_ms) searchParams.set('tile_ms', String(params.tile_ms));
  if (params.band) searchParams.set('band', params.band);
  if (params.value_mode) searchParams.set('value_mode', params.value_mode);
  if (params.sample_tiles) searchParams.set('sample_tiles', String(params.sample_tiles));

  return fetchApi<HeatmapDebugResponse>(`/v1/heatmap/debug?${searchParams.toString()}`, { signal });
}

// =============================================================================
// Alert Actions API (v5.9)
// =============================================================================

export interface AlertAckResponse {
  alert_id: string;
  status: 'OPEN' | 'ACKED' | 'RESOLVED';
  acked_at: number;
  acked_by?: string;
  note?: string;
}

export async function acknowledgeAlert(
  alertId: string,
  params?: { note?: string; acked_by?: string }
): Promise<AlertAckResponse> {
  return fetchApi<AlertAckResponse>(`/v1/alerts/${alertId}/ack`, {
    method: 'PUT',
    body: JSON.stringify(params || {}),
  });
}

export async function resolveAlert(
  alertId: string,
  params?: { note?: string; acked_by?: string }
): Promise<AlertAckResponse> {
  return fetchApi<AlertAckResponse>(`/v1/alerts/${alertId}/resolve`, {
    method: 'PUT',
    body: JSON.stringify(params || {}),
  });
}

// =============================================================================
// v5.36: Evidence Chain API
// =============================================================================

export interface EvidenceChainNode {
  node_type: 'SHOCK' | 'REACTION' | 'LEADING_EVENT' | 'STATE_CHANGE' | 'ALERT';
  node_id: string;
  ts: number;
  summary: string;
  details: Record<string, unknown>;
  evidence_refs: string[];
}

export interface EvidenceChainResponse {
  alert_id: string;
  token_id: string;
  generated_at: number;
  chain: EvidenceChainNode[];
  shock_count: number;
  reaction_count: number;
  leading_event_count: number;
  state_change_count: number;
  chain_start_ts: number;
  chain_end_ts: number;
  chain_duration_ms: number;
}

export async function getAlertEvidenceChain(
  alertId: string,
  params?: { window_before_ms?: number }
): Promise<EvidenceChainResponse> {
  const searchParams = new URLSearchParams();
  if (params?.window_before_ms) searchParams.set('window_before_ms', String(params.window_before_ms));
  const query = searchParams.toString();
  return fetchApi<EvidenceChainResponse>(`/v1/alerts/${alertId}/chain${query ? `?${query}` : ''}`);
}

// =============================================================================
// v5.36: Reaction Distribution API
// =============================================================================

export interface ReactionDistribution {
  reaction_type: string;
  count: number;
  ratio: number;
}

export interface ReactionDistributionResponse {
  token_id: string;
  from_ts: number;
  to_ts: number;
  window_minutes: number;
  total_reactions: number;
  distribution: ReactionDistribution[];
  hold_dominant: boolean;
  stress_ratio: number;
}

export async function getReactionDistribution(params: {
  token_id: string;
  window_minutes?: number;
}): Promise<ReactionDistributionResponse> {
  // DEBUG: trace who is calling getReactionDistribution
  console.trace('[DEBUG] getReactionDistribution called', { token_id: params.token_id });
  const searchParams = new URLSearchParams();
  searchParams.set('token_id', params.token_id);
  if (params.window_minutes) searchParams.set('window_minutes', String(params.window_minutes));
  return fetchApi<ReactionDistributionResponse>(`/v1/reactions/distribution?${searchParams.toString()}`);
}

// =============================================================================
// v5.36: Similar Cases API
// =============================================================================

export interface SimilarCaseMatch {
  match_id: string;
  token_id: string;
  market_title?: string;
  match_ts: number;
  similarity_score: number;
  pattern_summary: string;
  reaction_sequence: string[];
  state_at_match: string;
}

export interface SimilarCasesResponse {
  query_pattern: string[];
  query_state: string;
  query_ts: number;
  matches: SimilarCaseMatch[];
  total_matches: number;
  search_window_days: number;
  paradigm_note: string;
}

export async function getSimilarCases(params: {
  token_id: string;
  window_minutes?: number;
  search_days?: number;
  max_results?: number;
}): Promise<SimilarCasesResponse> {
  // DEBUG: trace who is calling getSimilarCases
  console.trace('[DEBUG] getSimilarCases called', { token_id: params.token_id });
  const searchParams = new URLSearchParams();
  searchParams.set('token_id', params.token_id);
  if (params.window_minutes) searchParams.set('window_minutes', String(params.window_minutes));
  if (params.search_days) searchParams.set('search_days', String(params.search_days));
  if (params.max_results) searchParams.set('max_results', String(params.max_results));
  return fetchApi<SimilarCasesResponse>(`/v1/similar-cases?${searchParams.toString()}`);
}

// =============================================================================
// v5.36: Multi-Market Comparison API
// =============================================================================

export interface MarketTimePoint {
  ts: number;
  state: string;
  hold_ratio?: number;
  reaction_type?: string;
}

export interface MarketTimeSeries {
  token_id: string;
  market_title?: string;
  time_series: MarketTimePoint[];
  final_state: string;
}

export interface EventComparisonResponse {
  event_id: string;
  event_ts: number;
  event_type: string;
  markets: MarketTimeSeries[];
  divergence_detected: boolean;
  divergence_summary?: string;
  paradigm_note: string;
}

export async function getEventComparison(
  eventId: string,
  params: { token_ids: string[]; window_before_ms?: number; window_after_ms?: number }
): Promise<EventComparisonResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set('token_ids', params.token_ids.join(','));
  if (params.window_before_ms) searchParams.set('window_before_ms', String(params.window_before_ms));
  if (params.window_after_ms) searchParams.set('window_after_ms', String(params.window_after_ms));
  return fetchApi<EventComparisonResponse>(`/events/${eventId}/compare?${searchParams.toString()}`);
}

// =============================================================================
// v5.36: Enhanced Alert Resolution
// =============================================================================

export interface AlertResolveResponseV536 {
  alert_id: string;
  status: 'OPEN' | 'ACKED' | 'RESOLVED';
  resolved_at: number;
  resolved_by?: string;
  note?: string;
  recovery_evidence: string[];
  is_false_positive: boolean;
  false_positive_reason?: string;
}

export async function resolveAlertV536(
  alertId: string,
  params?: {
    note?: string;
    resolved_by?: string;
    is_false_positive?: boolean;
    false_positive_reason?: string;
  }
): Promise<AlertResolveResponseV536> {
  return fetchApi<AlertResolveResponseV536>(`/v1/alerts/${alertId}/resolve`, {
    method: 'PUT',
    body: JSON.stringify(params || {}),
  });
}

// =============================================================================
// WebSocket Stream URL
// =============================================================================

export function getStreamUrl(): string {
  const wsProtocol = API_BASE.startsWith('https') ? 'wss' : 'ws';
  const wsHost = API_BASE.replace(/^https?:\/\//, '');
  return `${wsProtocol}://${wsHost}/v1/stream`;
}
