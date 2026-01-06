'use client';

/**
 * v5.36: Similar Cases Panel
 *
 * Shows historically similar reaction patterns.
 * CRITICAL: Does NOT show outcomes - only evidence comparison.
 *
 * "不给结果，只给对齐后的证据"
 */

import { useState, useEffect } from 'react';
import { getSimilarCases, type SimilarCasesResponse } from '@/lib/api';

interface Props {
  tokenId: string;
  windowMinutes?: number;
  searchDays?: number;
}

const STATE_COLORS: Record<string, string> = {
  STABLE: '#22c55e',
  FRAGILE: '#eab308',
  CRACKING: '#f97316',
  BROKEN: '#ef4444',
  UNKNOWN: '#6b7280',
};

export default function SimilarCasesPanel({ tokenId, windowMinutes = 30, searchDays = 30 }: Props) {
  const [data, setData] = useState<SimilarCasesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        const result = await getSimilarCases({
          token_id: tokenId,
          window_minutes: windowMinutes,
          search_days: searchDays,
          max_results: 5,
        });
        setData(result);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [tokenId, windowMinutes, searchDays]);

  if (loading) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="text-gray-400 text-sm">Searching for similar patterns...</div>
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

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Similar Historical Patterns</h3>
        <span className="text-xs text-gray-500">{searchDays} day search</span>
      </div>

      {/* Current Pattern */}
      {data && data.query_pattern.length > 0 && (
        <div className="mb-4 p-3 bg-gray-700 rounded">
          <div className="text-xs text-gray-400 mb-1">Current Pattern:</div>
          <div className="flex items-center gap-1">
            {data.query_pattern.map((r, i) => (
              <span key={i} className="px-2 py-0.5 bg-gray-600 rounded text-xs font-mono">
                {r}
              </span>
            ))}
            <span className="mx-2 text-gray-500">→</span>
            <span
              className="px-2 py-0.5 rounded text-xs font-semibold"
              style={{ backgroundColor: STATE_COLORS[data.query_state] + '33', color: STATE_COLORS[data.query_state] }}
            >
              {data.query_state}
            </span>
          </div>
        </div>
      )}

      {/* Matches */}
      {data && data.matches.length > 0 ? (
        <div className="space-y-3">
          {data.matches.map((match) => (
            <div key={match.match_id} className="p-3 bg-gray-700/50 rounded border border-gray-600">
              <div className="flex justify-between items-start mb-2">
                <div className="text-sm text-gray-300 truncate flex-1">
                  {match.market_title || match.token_id}
                </div>
                <div className="text-xs text-gray-500 ml-2">
                  {(match.similarity_score * 100).toFixed(0)}% match
                </div>
              </div>
              <div className="flex items-center gap-1 mb-2">
                {match.reaction_sequence.map((r, i) => (
                  <span key={i} className="px-2 py-0.5 bg-gray-600 rounded text-xs font-mono">
                    {r}
                  </span>
                ))}
              </div>
              <div className="flex justify-between items-center text-xs">
                <span
                  className="px-2 py-0.5 rounded"
                  style={{ backgroundColor: STATE_COLORS[match.state_at_match] + '33', color: STATE_COLORS[match.state_at_match] }}
                >
                  State: {match.state_at_match}
                </span>
                <span className="text-gray-500">
                  {new Date(match.match_ts).toLocaleDateString()}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-gray-400 text-sm text-center py-4">
          {data?.paradigm_note || 'No similar patterns found'}
        </div>
      )}

      {/* Paradigm Note */}
      <div className="mt-4 pt-3 border-t border-gray-700">
        <div className="text-xs text-gray-500 italic">
          {data?.paradigm_note || 'Similar patterns shown for evidence comparison. No outcomes displayed.'}
        </div>
      </div>
    </div>
  );
}
