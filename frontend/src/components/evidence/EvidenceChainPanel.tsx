'use client';

/**
 * v5.36: Evidence Chain Panel
 *
 * Shows complete lineage for an alert:
 * Shock(s) → Reaction(s) → Leading Event(s) → State Change(s) → Alert
 *
 * "不能只看最终状态"
 */

import { useState, useEffect } from 'react';
import { getAlertEvidenceChain, type EvidenceChainResponse, type EvidenceChainNode } from '@/lib/api';

interface Props {
  alertId: string;
  windowBeforeMs?: number;
}

const NODE_COLORS: Record<string, string> = {
  SHOCK: '#ef4444',        // red
  REACTION: '#f97316',     // orange
  LEADING_EVENT: '#eab308', // yellow
  STATE_CHANGE: '#3b82f6',  // blue
  ALERT: '#8b5cf6',        // purple
};

const NODE_ICONS: Record<string, string> = {
  SHOCK: '⚡',
  REACTION: '🔄',
  LEADING_EVENT: '📍',
  STATE_CHANGE: '🔀',
  ALERT: '🚨',
};

function formatTime(ts: number): string {
  const date = new Date(ts);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

export default function EvidenceChainPanel({ alertId, windowBeforeMs = 60000 }: Props) {
  const [data, setData] = useState<EvidenceChainResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        const result = await getAlertEvidenceChain(alertId, { window_before_ms: windowBeforeMs });
        setData(result);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [alertId, windowBeforeMs]);

  if (loading) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="text-gray-400 text-sm">Loading evidence chain...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="text-red-400 text-sm">{error}</div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Evidence Chain</h3>
        <span className="text-xs text-gray-500">
          {formatDuration(data.chain_duration_ms)} span
        </span>
      </div>

      {/* Summary Stats */}
      <div className="flex gap-3 mb-4 text-xs">
        <div className="flex items-center gap-1">
          <span style={{ color: NODE_COLORS.SHOCK }}>{NODE_ICONS.SHOCK}</span>
          <span className="text-gray-400">{data.shock_count} shocks</span>
        </div>
        <div className="flex items-center gap-1">
          <span style={{ color: NODE_COLORS.REACTION }}>{NODE_ICONS.REACTION}</span>
          <span className="text-gray-400">{data.reaction_count} reactions</span>
        </div>
        <div className="flex items-center gap-1">
          <span style={{ color: NODE_COLORS.LEADING_EVENT }}>{NODE_ICONS.LEADING_EVENT}</span>
          <span className="text-gray-400">{data.leading_event_count} leading</span>
        </div>
        <div className="flex items-center gap-1">
          <span style={{ color: NODE_COLORS.STATE_CHANGE }}>{NODE_ICONS.STATE_CHANGE}</span>
          <span className="text-gray-400">{data.state_change_count} state changes</span>
        </div>
      </div>

      {/* Timeline */}
      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-700" />

        {/* Nodes */}
        <div className="space-y-3">
          {data.chain.map((node, index) => (
            <div key={node.node_id} className="relative flex items-start gap-3">
              {/* Node marker */}
              <div
                className="relative z-10 w-8 h-8 flex items-center justify-center rounded-full text-lg"
                style={{ backgroundColor: NODE_COLORS[node.node_type] + '33' }}
              >
                {NODE_ICONS[node.node_type]}
              </div>

              {/* Node content */}
              <div className="flex-1 pb-3">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="text-xs font-semibold px-2 py-0.5 rounded"
                    style={{ backgroundColor: NODE_COLORS[node.node_type], color: 'white' }}
                  >
                    {node.node_type}
                  </span>
                  <span className="text-xs text-gray-500">{formatTime(node.ts)}</span>
                </div>
                <div className="text-sm text-gray-300">{node.summary}</div>

                {/* Evidence refs */}
                {node.evidence_refs.length > 0 && (
                  <div className="mt-1 text-xs text-gray-500">
                    ← refs: {node.evidence_refs.join(', ')}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-gray-700 text-xs text-gray-500">
        Complete lineage from shock to alert - &quot;不能只看最终状态&quot;
      </div>
    </div>
  );
}
