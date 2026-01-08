'use client';

import type { Anchor, ProofSummary, BeliefState, ReactionType, LeadingEventType } from '@/types/api';
import { STATE_COLORS, REACTION_COLORS } from '@/types/api';

interface ContextPanelProps {
  tokenId: string;
  marketInfo: {
    question: string;
    yes_price: number;
    tick_size: number;
    min_order_size: number;
  };
  anchors: Anchor[];
  proofSummary: ProofSummary;
  onAnchorClick?: (price: string) => void;
}

export function ContextPanel({
  tokenId,
  marketInfo,
  anchors,
  proofSummary,
  onAnchorClick,
}: ContextPanelProps) {
  return (
    <div className="p-4 space-y-6">
      {/* Market Info */}
      <Section title="Market">
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-400">Tick Size</span>
            <span>{marketInfo.tick_size}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Min Order</span>
            <span>{marketInfo.min_order_size}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Token ID</span>
            <span className="text-xs text-gray-500 truncate max-w-[120px]" title={tokenId}>
              {tokenId.slice(0, 8)}...
            </span>
          </div>
        </div>
      </Section>

      {/* Current State */}
      <Section title="Belief State">
        <StateDisplay state={proofSummary.current_state} confidence={proofSummary.confidence} />
        <div className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-400">Hold Ratio</span>
            <span className={proofSummary.hold_ratio >= 0.7 ? 'text-green-400' : 'text-yellow-400'}>
              {(proofSummary.hold_ratio * 100).toFixed(0)}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Fragile Signals</span>
            <span className={proofSummary.fragile_signals > 0 ? 'text-red-400' : 'text-gray-500'}>
              {proofSummary.fragile_signals}
            </span>
          </div>
        </div>
      </Section>

      {/* Key Anchors */}
      <Section title="Key Anchors">
        <div className="space-y-2">
          {anchors.length === 0 ? (
            <div className="text-gray-500 text-sm">No anchors detected</div>
          ) : (
            anchors.map((anchor, i) => (
              <AnchorItem key={i} anchor={anchor} onClick={() => onAnchorClick?.(anchor.price)} />
            ))
          )}
        </div>
      </Section>

      {/* Reaction Summary */}
      <Section title="Reactions (Window)">
        <div className="space-y-1">
          {Object.entries(proofSummary.reaction_counts)
            .filter(([, count]) => count > 0)
            .sort(([, a], [, b]) => b - a)
            .map(([type, count]) => (
              <ReactionCount key={type} type={type as ReactionType} count={count} />
            ))}
          {Object.values(proofSummary.reaction_counts).every((c) => c === 0) && (
            <div className="text-gray-500 text-sm">No reactions in window</div>
          )}
        </div>
      </Section>

      {/* Leading Events Summary */}
      <Section title="Leading Events">
        <div className="space-y-1">
          {Object.entries(proofSummary.leading_event_counts)
            .filter(([, count]) => count > 0)
            .map(([type, count]) => (
              <LeadingEventCount key={type} type={type as LeadingEventType} count={count} />
            ))}
          {Object.values(proofSummary.leading_event_counts).every((c) => c === 0) && (
            <div className="text-gray-500 text-sm">No leading events</div>
          )}
        </div>
      </Section>

      {/* Data Health */}
      <Section title="Data Health">
        <DataHealthDisplay health={proofSummary.data_health} />
      </Section>
    </div>
  );
}

// Helper components

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">{title}</h3>
      {children}
    </div>
  );
}

function StateDisplay({ state, confidence }: { state: BeliefState; confidence: number }) {
  const config: Record<BeliefState, { emoji: string; bg: string }> = {
    STABLE: { emoji: '🟢', bg: 'bg-green-500/10 border-green-500/30' },
    FRAGILE: { emoji: '🟡', bg: 'bg-yellow-500/10 border-yellow-500/30' },
    CRACKING: { emoji: '🟠', bg: 'bg-orange-500/10 border-orange-500/30' },
    BROKEN: { emoji: '🔴', bg: 'bg-red-500/10 border-red-500/30' },
  };

  const { emoji, bg } = config[state];

  return (
    <div className={`p-3 rounded-lg border ${bg}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl">{emoji}</span>
          <span className="font-semibold" style={{ color: STATE_COLORS[state] }}>
            {state}
          </span>
        </div>
        <div className="text-right">
          <div className="text-sm text-gray-400">Confidence</div>
          <div className="font-bold">{confidence}%</div>
        </div>
      </div>
    </div>
  );
}

function AnchorItem({ anchor, onClick }: { anchor: Anchor; onClick?: () => void }) {
  const sideColor = anchor.side === 'bid' ? 'text-green-400' : 'text-red-400';
  const scoreWidth = Math.round(anchor.score * 100);

  return (
    <button
      onClick={onClick}
      className="w-full p-2 rounded bg-gray-800 hover:bg-gray-700 transition-colors text-left"
    >
      <div className="flex items-center justify-between mb-1">
        <span className={`font-mono font-semibold ${sideColor}`}>
          {(parseFloat(anchor.price) * 100).toFixed(0)}%
        </span>
        <span className="text-xs text-gray-500 uppercase">{anchor.side}</span>
      </div>
      <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full"
          style={{ width: `${scoreWidth}%` }}
        />
      </div>
    </button>
  );
}

function ReactionCount({ type, count }: { type: ReactionType; count: number }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span style={{ color: REACTION_COLORS[type] }}>{type}</span>
      <span className="text-gray-400">{count}</span>
    </div>
  );
}

function LeadingEventCount({ type, count }: { type: LeadingEventType; count: number }) {
  const colors: Record<LeadingEventType, string> = {
    PRE_SHOCK_PULL: '#a855f7',
    DEPTH_COLLAPSE: '#ef4444',
    GRADUAL_THINNING: '#f97316',
  };

  return (
    <div className="flex items-center justify-between text-sm">
      <span style={{ color: colors[type] }}>{type.replace(/_/g, ' ')}</span>
      <span className="text-gray-400">{count}</span>
    </div>
  );
}

function DataHealthDisplay({
  health,
}: {
  health: ProofSummary['data_health'];
}) {
  const isHealthy =
    health.missing_buckets === 0 && health.rebuild_count === 0 && !health.hash_mismatch;

  return (
    <div className={`p-2 rounded text-sm ${isHealthy ? 'bg-green-500/10' : 'bg-yellow-500/10'}`}>
      {isHealthy ? (
        <div className="flex items-center gap-2 text-green-400">
          <span>✓</span>
          <span>All data healthy</span>
        </div>
      ) : (
        <div className="space-y-1">
          {health.missing_buckets > 0 && (
            <div className="text-yellow-400">⚠ {health.missing_buckets} missing buckets</div>
          )}
          {health.rebuild_count > 0 && (
            <div className="text-yellow-400">⚠ {health.rebuild_count} rebuilds</div>
          )}
          {health.hash_mismatch && <div className="text-red-400">✗ Hash mismatch</div>}
        </div>
      )}
    </div>
  );
}
