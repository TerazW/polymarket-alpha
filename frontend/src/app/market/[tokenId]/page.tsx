'use client';

import { useState, useEffect, use, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { ContextPanel } from '@/components/evidence/ContextPanel';
import { EvidencePlayer } from '@/components/evidence/EvidencePlayer';
import { TapePanel } from '@/components/evidence/TapePanel';
import type { EvidenceResponse, BeliefState, ShockEvent, ReactionEvent, LeadingEvent, StateChange, ProofSummary } from '@/types/api';
import { getEvidence, type EvidenceResponse as ApiEvidenceResponse } from '@/lib/api';

interface PageProps {
  params: Promise<{ tokenId: string }>;
}

// Convert API response to frontend types
function convertApiEvidence(api: ApiEvidenceResponse): EvidenceResponse {
  return {
    token_id: api.token_id,
    t0: api.t0,
    window_start: api.window.from_ts,
    window_end: api.window.to_ts,
    anchors: api.anchors.map(a => ({
      price: String(a.price),
      side: a.side.toLowerCase() as 'bid' | 'ask',
      score: a.score,
    })),
    shocks: api.shocks.map(s => ({
      id: s.id,
      timestamp: s.ts,
      price: String(s.price),
      side: s.side.toLowerCase() as 'bid' | 'ask',
      trigger_type: s.trigger.toLowerCase() as 'volume' | 'consecutive',
      trade_volume: s.trade_vol || 0,
      liquidity_before: s.baseline_size || 0,
      baseline_size: s.baseline_size || 0,
    })),
    reactions: api.reactions.map(r => ({
      id: r.id,
      timestamp: r.ts_start,
      shock_id: r.shock_id || '',
      price: String(r.price),
      side: r.side.toLowerCase() as 'bid' | 'ask',
      reaction_type: r.reaction as ReactionEvent['reaction_type'],
      drop_ratio: r.proof?.drop_ratio || 0,
      refill_ratio: r.proof?.refill_ratio || 0,
      min_size: 0,
      max_size: 0,
      time_to_min_ms: 0,
      time_to_refill_ms: r.proof?.time_to_refill_ms || null,
      price_shift_ticks: r.proof?.shift_ticks || 0,
      proof: {
        rule_triggered: `${r.reaction} reaction`,
        thresholds: { drop_min: 0, refill_max: 1 },
        actual_values: { drop: r.proof?.drop_ratio || 0, refill: r.proof?.refill_ratio || 0 },
        window_type: r.window,
      },
    })),
    leading_events: api.leading_events.map(e => ({
      id: e.id,
      timestamp: e.ts,
      price: String((e.price_band.price_min + e.price_band.price_max) / 2),
      side: e.side.toLowerCase() as 'bid' | 'ask',
      event_type: e.type as LeadingEvent['event_type'],
      drop_ratio: (e.proof as Record<string, number>)?.drop_ratio || 0,
      trade_volume_nearby: (e.proof as Record<string, number>)?.trade_volume_nearby || 0,
    })),
    state_changes: api.belief_states.map(s => ({
      id: s.id,
      timestamp: s.ts,
      old_state: 'STABLE' as BeliefState, // API doesn't provide old_state directly
      new_state: s.belief_state as BeliefState,
      evidence: [s.note || ''],
      evidence_refs: s.evidence_refs,
    })),
    proof_summary: {
      current_state: (api.belief_states[api.belief_states.length - 1]?.belief_state || 'STABLE') as BeliefState,
      state_since: api.belief_states[api.belief_states.length - 1]?.ts || api.t0,
      confidence: 80,
      shock_count: api.shocks.length,
      reaction_counts: {
        VACUUM: api.reactions.filter(r => r.reaction === 'VACUUM').length,
        SWEEP: api.reactions.filter(r => r.reaction === 'SWEEP').length,
        CHASE: api.reactions.filter(r => r.reaction === 'CHASE').length,
        PULL: api.reactions.filter(r => r.reaction === 'PULL').length,
        HOLD: api.reactions.filter(r => r.reaction === 'HOLD').length,
        DELAYED: api.reactions.filter(r => r.reaction === 'DELAYED').length,
        NO_IMPACT: api.reactions.filter(r => r.reaction === 'NO_IMPACT').length,
      },
      leading_event_counts: {
        PRE_SHOCK_PULL: api.leading_events.filter(e => e.type === 'PRE_SHOCK_PULL').length,
        DEPTH_COLLAPSE: api.leading_events.filter(e => e.type === 'DEPTH_COLLAPSE').length,
        GRADUAL_THINNING: api.leading_events.filter(e => e.type === 'GRADUAL_THINNING').length,
      },
      hold_ratio: api.reactions.length > 0
        ? api.reactions.filter(r => r.reaction === 'HOLD').length / api.reactions.length
        : 0,
      fragile_signals: api.leading_events.length + api.reactions.filter(r => ['VACUUM', 'PULL'].includes(r.reaction)).length,
      data_health: {
        missing_buckets: Math.round(api.data_health.missing_bucket_ratio_10m * 100),
        rebuild_count: api.data_health.rebuild_count_10m,
        last_rebuild_ts: null,
        hash_mismatch: api.data_health.hash_mismatch_count_10m > 0,
      },
    },
    tiles_manifest: api.tiles_manifest ? {
      token_id: api.tiles_manifest.token_id,
      lod: `${api.tiles_manifest.lod_ms}ms` as '250ms' | '1s' | '5s',
      tile_duration_ms: api.tiles_manifest.tile_ms,
      tiles: [],
      normalization: {
        method: 'log1p',
        clip_max: 10000,
        price_min: '0.00',
        price_max: '1.00',
        tick_size: '0.01',
      },
    } : {
      token_id: api.token_id,
      lod: '250ms',
      tile_duration_ms: 10000,
      tiles: [],
      normalization: {
        method: 'log1p',
        clip_max: 10000,
        price_min: '0.00',
        price_max: '1.00',
        tick_size: '0.01',
      },
    },
  };
}

// Mock data for development
const MOCK_EVIDENCE: EvidenceResponse = {
  token_id: 'mock-token-123',
  t0: Date.now() - 30000,
  window_start: Date.now() - 90000,
  window_end: Date.now(),
  anchors: [
    { price: '0.72', side: 'bid', score: 0.95 },
    { price: '0.68', side: 'bid', score: 0.82 },
    { price: '0.76', side: 'ask', score: 0.78 },
  ],
  shocks: [
    {
      id: 'shock-1',
      timestamp: Date.now() - 60000,
      price: '0.72',
      side: 'bid',
      trigger_type: 'volume',
      trade_volume: 1500,
      liquidity_before: 5000,
      baseline_size: 4800,
    },
    {
      id: 'shock-2',
      timestamp: Date.now() - 25000,
      price: '0.72',
      side: 'bid',
      trigger_type: 'consecutive',
      trade_volume: 800,
      liquidity_before: 3200,
      baseline_size: 3500,
    },
  ],
  reactions: [
    {
      id: 'reaction-1',
      timestamp: Date.now() - 52000,
      shock_id: 'shock-1',
      price: '0.72',
      side: 'bid',
      reaction_type: 'PULL',
      drop_ratio: 0.65,
      refill_ratio: 0.22,
      min_size: 1750,
      max_size: 2800,
      time_to_min_ms: 3200,
      time_to_refill_ms: null,
      price_shift_ticks: 0,
      proof: {
        rule_triggered: 'PULL: drop >= 60% AND refill < 30%',
        thresholds: { drop_min: 0.6, refill_max: 0.3 },
        actual_values: { drop: 0.65, refill: 0.22 },
        window_type: 'SLOW',
      },
    },
    {
      id: 'reaction-2',
      timestamp: Date.now() - 17000,
      shock_id: 'shock-2',
      price: '0.72',
      side: 'bid',
      reaction_type: 'VACUUM',
      drop_ratio: 0.92,
      refill_ratio: 0.08,
      min_size: 280,
      max_size: 850,
      time_to_min_ms: 1800,
      time_to_refill_ms: null,
      price_shift_ticks: 0,
      proof: {
        rule_triggered: 'VACUUM: min_size <= 5% baseline AND <= 10 abs, duration >= 3s',
        thresholds: { size_ratio_max: 0.05, abs_max: 10, duration_min_ms: 3000 },
        actual_values: { size_ratio: 0.08, abs_size: 280, duration_ms: 4200 },
        window_type: 'FAST',
      },
    },
  ],
  leading_events: [
    {
      id: 'leading-1',
      timestamp: Date.now() - 70000,
      price: '0.72',
      side: 'bid',
      event_type: 'PRE_SHOCK_PULL',
      drop_ratio: 0.75,
      trade_volume_nearby: 12,
    },
  ],
  state_changes: [
    {
      id: 'state-1',
      timestamp: Date.now() - 50000,
      old_state: 'STABLE',
      new_state: 'FRAGILE',
      evidence: ['PRE_SHOCK_PULL at 72%', 'PULL reaction'],
      evidence_refs: ['leading-1', 'reaction-1'],
    },
    {
      id: 'state-2',
      timestamp: Date.now() - 15000,
      old_state: 'FRAGILE',
      new_state: 'BROKEN',
      evidence: ['VACUUM at 72%', 'No refill after 8s'],
      evidence_refs: ['reaction-2'],
    },
  ],
  proof_summary: {
    current_state: 'BROKEN',
    state_since: Date.now() - 15000,
    confidence: 85,
    shock_count: 2,
    reaction_counts: { VACUUM: 1, PULL: 1, SWEEP: 0, CHASE: 0, HOLD: 0, DELAYED: 0, NO_IMPACT: 0 },
    leading_event_counts: { PRE_SHOCK_PULL: 1, DEPTH_COLLAPSE: 0, GRADUAL_THINNING: 0 },
    hold_ratio: 0,
    fragile_signals: 3,
    data_health: {
      missing_buckets: 0,
      rebuild_count: 0,
      last_rebuild_ts: null,
      hash_mismatch: false,
    },
  },
  tiles_manifest: {
    token_id: 'mock-token-123',
    lod: '250ms',
    tile_duration_ms: 10000,
    tiles: [],
    normalization: {
      method: 'log1p',
      clip_max: 10000,
      price_min: '0.60',
      price_max: '0.80',
      tick_size: '0.01',
    },
  },
};

export default function MarketDetailPage({ params }: PageProps) {
  const { tokenId } = use(params);
  const searchParams = useSearchParams();
  const t0Param = searchParams.get('t0');
  const initialT0 = t0Param ? parseInt(t0Param, 10) : Date.now();

  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState<number>(initialT0);
  const [useMockData, setUseMockData] = useState(false);
  const [apiStatus, setApiStatus] = useState<'loading' | 'online' | 'offline'>('loading');

  // Market info from evidence or default
  const marketInfo = evidence ? {
    question: evidence.token_id,
    yes_price: 0.72, // Would come from market data
    tick_size: 0.01,
    min_order_size: 5,
  } : {
    question: 'Loading...',
    yes_price: 0,
    tick_size: 0.01,
    min_order_size: 5,
  };

  const fetchEvidenceData = useCallback(async () => {
    setLoading(true);
    try {
      // Try to fetch from API first
      // Use t0 from URL param or current time
      const t0 = initialT0;
      const apiData = await getEvidence({
        token_id: tokenId,
        t0,
        window_before_ms: 60000,
        window_after_ms: 30000,
      });

      const converted = convertApiEvidence(apiData);
      setEvidence(converted);
      setCurrentTime(converted.t0);
      setApiStatus('online');
      setError(null);
    } catch (err) {
      console.warn('API failed, using mock data:', err);
      setApiStatus('offline');
      // Fallback to mock data
      setEvidence(MOCK_EVIDENCE);
      setCurrentTime(MOCK_EVIDENCE.t0);
      setUseMockData(true);
    } finally {
      setLoading(false);
    }
  }, [tokenId, initialT0]);

  useEffect(() => {
    if (useMockData) {
      setEvidence(MOCK_EVIDENCE);
      setCurrentTime(MOCK_EVIDENCE.t0);
      setLoading(false);
      return;
    }
    fetchEvidenceData();
  }, [tokenId, useMockData, fetchEvidenceData]);

  const handleEventClick = (eventId: string, timestamp: number) => {
    setSelectedEventId(eventId);
    setCurrentTime(timestamp);
  };

  const handleTimeChange = (newTime: number) => {
    setCurrentTime(newTime);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-gray-400">Loading evidence...</div>
      </div>
    );
  }

  if (error || !evidence) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-red-400">Error: {error || 'No evidence data'}</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="border-b border-gray-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a href="/" className="text-gray-400 hover:text-white">
              &larr; Back
            </a>
            <h1 className="text-lg font-semibold truncate max-w-md">{marketInfo.question}</h1>
          </div>
          <div className="flex items-center gap-4">
            {apiStatus !== 'loading' && (
              <span className={`text-xs ${apiStatus === 'online' ? 'text-green-400' : 'text-yellow-400'}`}>
                {apiStatus === 'online' ? '● Live' : '○ Mock'}
              </span>
            )}
            <button
              onClick={() => setUseMockData(!useMockData)}
              className={`px-2 py-1 rounded text-xs ${useMockData ? 'bg-yellow-600' : 'bg-green-600'}`}
            >
              {useMockData ? 'Mock' : 'Live'}
            </button>
            <span className="text-2xl font-bold text-green-400">
              {(marketInfo.yes_price * 100).toFixed(0)}%
            </span>
            <StateIndicator state={evidence.proof_summary.current_state} />
          </div>
        </div>
      </header>

      {/* Three-column layout */}
      <div className="flex h-[calc(100vh-57px)]">
        {/* Left: Context Panel */}
        <div className="w-72 border-r border-gray-800 overflow-y-auto">
          <ContextPanel
            tokenId={tokenId}
            marketInfo={marketInfo}
            anchors={evidence.anchors}
            proofSummary={evidence.proof_summary}
            onAnchorClick={(price) => console.log('Anchor clicked:', price)}
          />
        </div>

        {/* Center: Evidence Player (Heatmap + Timeline) */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <EvidencePlayer
            evidence={evidence}
            currentTime={currentTime}
            selectedEventId={selectedEventId}
            onTimeChange={handleTimeChange}
            onEventClick={handleEventClick}
          />
        </div>

        {/* Right: Tape + Proof Panel */}
        <div className="w-80 border-l border-gray-800 overflow-y-auto">
          <TapePanel
            shocks={evidence.shocks}
            reactions={evidence.reactions}
            leadingEvents={evidence.leading_events}
            stateChanges={evidence.state_changes}
            selectedEventId={selectedEventId}
            onEventClick={handleEventClick}
          />
        </div>
      </div>
    </div>
  );
}

// State indicator component
function StateIndicator({ state }: { state: BeliefState }) {
  const config: Record<BeliefState, { emoji: string; color: string; label: string }> = {
    STABLE: { emoji: '🟢', color: 'text-green-400', label: 'Stable' },
    FRAGILE: { emoji: '🟡', color: 'text-yellow-400', label: 'Fragile' },
    CRACKING: { emoji: '🟠', color: 'text-orange-400', label: 'Cracking' },
    BROKEN: { emoji: '🔴', color: 'text-red-400', label: 'Broken' },
  };

  const { emoji, color, label } = config[state];

  return (
    <div className={`flex items-center gap-2 px-3 py-1 rounded-full bg-gray-800 ${color}`}>
      <span>{emoji}</span>
      <span className="font-medium">{label}</span>
    </div>
  );
}
