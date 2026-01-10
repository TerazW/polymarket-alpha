'use client';

/**
 * v5.36: Reaction Distribution Panel
 *
 * Shows structural view of reactions - "强调结构，淡化事件"
 * Displays distribution percentages instead of individual events.
 */

import { useState, useEffect, useRef } from 'react';
import { getReactionDistribution, type ReactionDistributionResponse } from '@/lib/api';

interface Props {
  tokenId: string;
  windowMinutes?: number;
}

const REACTION_COLORS: Record<string, string> = {
  HOLD: '#22c55e',     // green
  VACUUM: '#ef4444',   // red
  PULL: '#f97316',     // orange
  SWEEP: '#eab308',    // yellow
  CHASE: '#3b82f6',    // blue
  DELAYED: '#8b5cf6',  // purple
  NO_IMPACT: '#6b7280', // gray
};

const REACTION_LABELS: Record<string, string> = {
  HOLD: 'HOLD (depth defended)',
  VACUUM: 'VACUUM (liquidity void)',
  PULL: 'PULL (MM withdrawal)',
  SWEEP: 'SWEEP (aggressive take)',
  CHASE: 'CHASE (follow-through)',
  DELAYED: 'DELAYED (slow response)',
  NO_IMPACT: 'NO_IMPACT (absorbed)',
};

export default function ReactionDistributionPanel({ tokenId, windowMinutes = 30 }: Props) {
  const [data, setData] = useState<ReactionDistributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inflightRef = useRef(false);
  const lastKeyRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    if (!tokenId) {
      setLoading(false);
      return;
    }

    const key = `${tokenId}|${windowMinutes}`;
    if (inflightRef.current || lastKeyRef.current === key) {
      return;
    }
    lastKeyRef.current = key;
    inflightRef.current = true;

    async function fetchData() {
      try {
        setLoading(true);
        const result = await getReactionDistribution({ token_id: tokenId, window_minutes: windowMinutes });
        if (mountedRef.current) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : 'Failed to load');
        }
      } finally {
        inflightRef.current = false;
        if (mountedRef.current) {
          setLoading(false);
        }
      }
    }
    fetchData();

    return () => {
      mountedRef.current = false;
    };
  }, [tokenId, windowMinutes]);

  if (loading) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="text-gray-400 text-sm">Loading reaction distribution...</div>
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

  if (!data || data.total_reactions === 0) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-lg font-semibold mb-2">Reaction Distribution</h3>
        <div className="text-gray-400 text-sm">No reactions in the last {windowMinutes} minutes</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Reaction Distribution</h3>
        <span className="text-xs text-gray-500">{windowMinutes}min window</span>
      </div>

      {/* Structural Summary */}
      <div className="flex gap-4 mb-4">
        <div className={`px-3 py-1 rounded text-sm ${data.hold_dominant ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}`}>
          {data.hold_dominant ? 'HOLD Dominant' : 'Not HOLD Dominant'}
        </div>
        <div className={`px-3 py-1 rounded text-sm ${data.stress_ratio > 0.3 ? 'bg-red-900 text-red-300' : 'bg-gray-700 text-gray-400'}`}>
          Stress: {(data.stress_ratio * 100).toFixed(0)}%
        </div>
      </div>

      {/* Distribution Bars */}
      <div className="space-y-2">
        {data.distribution.map((item) => (
          <div key={item.reaction_type} className="flex items-center gap-2">
            <div className="w-24 text-xs font-mono text-gray-400">{item.reaction_type}</div>
            <div className="flex-1 h-4 bg-gray-700 rounded overflow-hidden">
              <div
                className="h-full transition-all duration-500"
                style={{
                  width: `${item.ratio * 100}%`,
                  backgroundColor: REACTION_COLORS[item.reaction_type] || '#6b7280',
                }}
              />
            </div>
            <div className="w-16 text-right text-xs text-gray-400">
              {(item.ratio * 100).toFixed(0)}% ({item.count})
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-4 border-t border-gray-700 text-xs text-gray-500">
        Total: {data.total_reactions} reactions
      </div>
    </div>
  );
}
