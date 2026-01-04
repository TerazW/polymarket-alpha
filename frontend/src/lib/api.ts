/**
 * Belief Reaction System - API Client
 * Connects to /v1 endpoints
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

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
  fragile_index_10m: number;
  leading_rate_10m: number;
  confidence: number;
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
  status: 'OPEN' | 'ACKED' | 'RESOLVED';
  type: string;
  summary: string;
  confidence: number;
  evidence_ref: { token_id: string; t0: number };
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
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;

  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!res.ok) {
      throw new ApiError(res.status, `API error: ${res.status}`);
    }

    return res.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, `Network error: ${error}`);
  }
}

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

export async function getEvidence(params: {
  token_id: string;
  t0: number;
  window_before_ms?: number;
  window_after_ms?: number;
  include_tiles_manifest?: boolean;
  lod?: 250 | 1000 | 5000;
}): Promise<EvidenceResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set('token_id', params.token_id);
  searchParams.set('t0', String(params.t0));
  if (params.window_before_ms) searchParams.set('window_before_ms', String(params.window_before_ms));
  if (params.window_after_ms) searchParams.set('window_after_ms', String(params.window_after_ms));
  if (params.include_tiles_manifest !== undefined) {
    searchParams.set('include_tiles_manifest', String(params.include_tiles_manifest));
  }
  if (params.lod) searchParams.set('lod', String(params.lod));

  return fetchApi<EvidenceResponse>(`/v1/evidence?${searchParams.toString()}`);
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
