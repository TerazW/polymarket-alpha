'use client';

import { useState, useEffect, use } from 'react';
import { ContextPanel } from '@/components/evidence/ContextPanel';
import { EvidencePlayer } from '@/components/evidence/EvidencePlayer';
import { TapePanel } from '@/components/evidence/TapePanel';
import type { EvidenceResponse, BeliefState } from '@/types/api';

interface PageProps {
  params: Promise<{ tokenId: string }>;
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
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState<number>(Date.now());

  // Market info (would come from API)
  const marketInfo = {
    question: 'Will Russia Invade Ukraine?',
    yes_price: 0.72,
    tick_size: 0.01,
    min_order_size: 5,
  };

  useEffect(() => {
    const fetchEvidence = async () => {
      setLoading(true);
      try {
        // TODO: Replace with actual API call
        // const res = await fetch(`/api/v1/evidence?token_id=${tokenId}&t0=${Date.now()}`);
        // const data = await res.json();

        // Using mock data for now
        await new Promise((resolve) => setTimeout(resolve, 500));
        setEvidence(MOCK_EVIDENCE);
        setCurrentTime(MOCK_EVIDENCE.t0);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load evidence');
      } finally {
        setLoading(false);
      }
    };

    fetchEvidence();
  }, [tokenId]);

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
            <h1 className="text-lg font-semibold">{marketInfo.question}</h1>
          </div>
          <div className="flex items-center gap-4">
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
