'use client';

import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { ContextPanel } from '@/components/evidence/ContextPanel';
import { EvidencePlayer } from '@/components/evidence/EvidencePlayer';
import { TapePanel } from '@/components/evidence/TapePanel';
// v5.36: New evidence panels
import ReactionDistributionPanel from '@/components/evidence/ReactionDistributionPanel';
import SimilarCasesPanel from '@/components/evidence/SimilarCasesPanel';
import type { EvidenceResponse, BeliefState, ShockEvent, ReactionEvent, LeadingEvent, StateChange, ProofSummary } from '@/types/api';
import { type EvidenceResponse as ApiEvidenceResponse } from '@/lib/api';
import { useEvidenceFetch } from '@/hooks/useEvidenceFetch';

interface PageProps {
  params: { tokenId: string };
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

export default function MarketDetailPage({ params }: PageProps) {
  const { tokenId } = params;
  const searchParams = useSearchParams();
  const t0Param = searchParams.get('t0');

  // Stabilize the t0 we fetch against: only change when tokenId or ?t0 changes
  const initialT0 = useMemo(
    () => (t0Param ? parseInt(t0Param, 10) : Date.now()),
    [tokenId, t0Param]
  );

  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState<number>(initialT0);

  // Use safe evidence fetch hook with debounce and in-flight protection
  const {
    evidence: apiEvidence,
    loading,
    error: fetchError,
    refetch,
  } = useEvidenceFetch({
    tokenId,
    t0: initialT0,
    windowBeforeMs: 60000,
    windowAfterMs: 30000,
    debounceMs: 300,
  });

  // Convert API response to frontend types
  const evidence = useMemo(() => {
    if (!apiEvidence) return null;
    return convertApiEvidence(apiEvidence);
  }, [apiEvidence]);

  // Reset UI time/selection when switching markets or t0
  useEffect(() => {
    setSelectedEventId(null);
    setCurrentTime(initialT0);
  }, [tokenId, initialT0]);

  // Update currentTime when evidence loads
  useEffect(() => {
    if (evidence) {
      setCurrentTime(evidence.t0);
    }
  }, [evidence]);

  const error = fetchError ? `Failed to load evidence: ${fetchError}` : null;
  const apiStatus = loading ? 'loading' : (evidence ? 'online' : 'offline');

  // Market info from evidence API
  const marketInfo = apiEvidence ? {
    question: apiEvidence.market.title || apiEvidence.token_id,
    yes_price: apiEvidence.market.last_price ?? null,
    tick_size: apiEvidence.market.tick_size || 0.01,
    min_order_size: 5,
  } : {
    question: 'Loading...',
    yes_price: null,
    tick_size: 0.01,
    min_order_size: 5,
  };

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
            <span className={`text-xs ${apiStatus === 'online' ? 'text-green-400' : 'text-red-400'}`}>
              {apiStatus === 'online' ? '● API Online' : '○ API Offline'}
            </span>
            <span className="text-2xl font-bold text-green-400">
              {marketInfo.yes_price != null ? (marketInfo.yes_price * 100).toFixed(0) : '??'}%
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

        {/* Right: Tape + Proof Panel + v5.36 Panels */}
        <div className="w-80 border-l border-gray-800 overflow-y-auto">
          <TapePanel
            shocks={evidence.shocks}
            reactions={evidence.reactions}
            leadingEvents={evidence.leading_events}
            stateChanges={evidence.state_changes}
            selectedEventId={selectedEventId}
            onEventClick={handleEventClick}
          />

          {/* v5.36: Reaction Distribution */}
          <div className="p-3 border-t border-gray-700">
            <ReactionDistributionPanel tokenId={tokenId} windowMinutes={30} />
          </div>

          {/* v5.36: Similar Historical Cases */}
          <div className="p-3 border-t border-gray-700">
            <SimilarCasesPanel tokenId={tokenId} windowMinutes={30} searchDays={30} />
          </div>
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
