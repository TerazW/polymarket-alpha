'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import type { BeliefState } from '@/types/api';
import { STATE_COLORS } from '@/types/api';
import { getRadar, type RadarRow } from '@/lib/api';

interface Market {
  condition_id: string;
  token_id?: string;
  question: string;
  volume_24h: number;
  liquidity: number;
  yes_price: number | null;
  state?: BeliefState;
  confidence?: number;
  leading_rate_10m?: number;
}

interface Stats {
  trades: number;
  books: number;
  shocks: number;
  reactions: number;
  reaction_types: Record<string, number>;
}

// Mock markets with belief state for demo
const MOCK_MARKETS: Market[] = [
  {
    condition_id: '1',
    token_id: 'mock-token-123',
    question: 'Will Russia Invade Ukraine?',
    volume_24h: 125000,
    liquidity: 85000,
    yes_price: 0.72,
    state: 'BROKEN',
    confidence: 85,
    leading_rate_10m: 3,
  },
  {
    condition_id: '2',
    token_id: 'mock-token-456',
    question: 'BTC ETP Approval',
    volume_24h: 89000,
    liquidity: 62000,
    yes_price: 0.58,
    state: 'FRAGILE',
    confidence: 72,
    leading_rate_10m: 1,
  },
  {
    condition_id: '3',
    token_id: 'mock-token-789',
    question: 'Politics - Debate Outcome',
    volume_24h: 45000,
    liquidity: 38000,
    yes_price: 0.76,
    state: 'STABLE',
    confidence: 91,
    leading_rate_10m: 0,
  },
];

const STATE_EMOJIS: Record<BeliefState, string> = {
  STABLE: '🟢',
  FRAGILE: '🟡',
  CRACKING: '🟠',
  BROKEN: '🔴',
};

// Convert RadarRow to Market interface
function radarRowToMarket(row: RadarRow): Market {
  return {
    condition_id: row.market.condition_id,
    token_id: row.market.token_id,
    question: row.market.title,
    volume_24h: 0,
    liquidity: 0,
    yes_price: row.market.last_price ?? null,
    state: row.belief_state,
    confidence: row.confidence,
    leading_rate_10m: row.leading_rate_10m,
  };
}

export default function Dashboard() {
  const [markets, setMarkets] = useState<Market[]>(MOCK_MARKETS);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useMockData, setUseMockData] = useState(true);
  const [apiStatus, setApiStatus] = useState<'unknown' | 'online' | 'offline'>('unknown');

  const API_BASE = 'http://127.0.0.1:8000';

  const fetchRadar = useCallback(async () => {
    if (useMockData) return;
    try {
      const data = await getRadar({ limit: 50 });
      const convertedMarkets = data.rows.map(radarRowToMarket);
      setMarkets(convertedMarkets.length > 0 ? convertedMarkets : MOCK_MARKETS);
      setApiStatus('online');
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setApiStatus('offline');
      // Keep mock data on error
    }
  }, [useMockData]);

  const fetchStats = useCallback(async () => {
    if (useMockData) return;
    try {
      const res = await fetch(`${API_BASE}/api/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch {
      // Stats endpoint might not exist yet
    }
  }, [useMockData]);

  useEffect(() => {
    if (useMockData) {
      setMarkets(MOCK_MARKETS);
      setApiStatus('unknown');
      return;
    }

    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchRadar(), fetchStats()]);
      setLoading(false);
    };
    loadData();

    const interval = setInterval(() => {
      fetchRadar();
      fetchStats();
    }, 30000);
    return () => clearInterval(interval);
  }, [useMockData, fetchRadar, fetchStats]);

  // Sort markets by state priority (BROKEN > CRACKING > FRAGILE > STABLE)
  const sortedMarkets = [...markets].sort((a, b) => {
    const stateOrder: Record<BeliefState, number> = { BROKEN: 0, CRACKING: 1, FRAGILE: 2, STABLE: 3 };
    const aOrder = a.state ? stateOrder[a.state] : 4;
    const bOrder = b.state ? stateOrder[b.state] : 4;
    return aOrder - bOrder;
  });

  return (
    <main className="min-h-screen bg-gray-900 text-white p-8">
      <div className="max-w-6xl mx-auto">
        <div className="mb-8 flex justify-between items-start">
          <div>
            <h1 className="text-3xl font-bold mb-2">Belief Reaction System</h1>
            <p className="text-gray-400">&quot;看存在没意义，看反应才有意义&quot;</p>
          </div>
          <div className="flex items-center gap-2">
            {!useMockData && apiStatus !== 'unknown' && (
              <span className={`text-xs ${apiStatus === 'online' ? 'text-green-400' : 'text-red-400'}`}>
                {apiStatus === 'online' ? '● API Online' : '○ API Offline'}
              </span>
            )}
            <button
              onClick={() => setUseMockData(!useMockData)}
              className={`px-3 py-1 rounded text-sm ${
                useMockData ? 'bg-yellow-600' : 'bg-green-600'
              }`}
            >
              {useMockData ? 'Mock Data' : 'Live Data'}
            </button>
          </div>
        </div>

        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-green-400">{stats.trades.toLocaleString()}</div>
              <div className="text-gray-400 text-sm">Trades Collected</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-blue-400">{stats.books.toLocaleString()}</div>
              <div className="text-gray-400 text-sm">Book Snapshots</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-yellow-400">{stats.shocks.toLocaleString()}</div>
              <div className="text-gray-400 text-sm">Shock Events</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-purple-400">{stats.reactions.toLocaleString()}</div>
              <div className="text-gray-400 text-sm">Reactions</div>
            </div>
          </div>
        )}

        {/* State summary */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          {(['BROKEN', 'CRACKING', 'FRAGILE', 'STABLE'] as BeliefState[]).map((state) => {
            const count = markets.filter((m) => m.state === state).length;
            return (
              <div
                key={state}
                className="bg-gray-800 rounded-lg p-4 border-l-4"
                style={{ borderColor: STATE_COLORS[state] }}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xl">{STATE_EMOJIS[state]}</span>
                  <span className="font-semibold" style={{ color: STATE_COLORS[state] }}>
                    {state}
                  </span>
                </div>
                <div className="text-2xl font-bold mt-1">{count}</div>
              </div>
            );
          })}
        </div>

        {/* Market Radar */}
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <div className="p-4 border-b border-gray-700 flex justify-between items-center">
            <h2 className="text-xl font-semibold">Market Radar</h2>
            <span className="text-sm text-gray-500">Sorted by belief fragility</span>
          </div>

          {loading ? (
            <div className="p-8 text-center text-gray-400">Loading...</div>
          ) : error ? (
            <div className="p-8 text-center text-red-400">
              Error: {error}
              <br />
              <span className="text-sm text-gray-500">Make sure backend is running</span>
            </div>
          ) : (
            <div className="divide-y divide-gray-700">
              {sortedMarkets.map((market, index) => (
                <Link
                  key={market.condition_id || index}
                  href={`/market/${market.token_id || market.condition_id}`}
                  className="block p-4 hover:bg-gray-700/50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    {/* State indicator */}
                    <div className="flex-shrink-0 w-10 text-center">
                      {market.state && (
                        <span className="text-2xl">{STATE_EMOJIS[market.state]}</span>
                      )}
                    </div>

                    {/* Market info */}
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium mb-1 truncate">{market.question}</h3>
                      <div className="flex gap-4 text-sm text-gray-400">
                        <span>Vol: ${(market.volume_24h || 0).toLocaleString()}</span>
                        {market.confidence !== undefined && (
                          <span>Confidence: {market.confidence}%</span>
                        )}
                        {market.leading_rate_10m !== undefined && market.leading_rate_10m > 0 && (
                          <span className="text-yellow-400">
                            Leading: {market.leading_rate_10m}/10m
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Price and state */}
                    <div className="flex-shrink-0 text-right">
                      <div className="text-2xl font-bold text-green-400">
                        {market.yes_price != null ? (market.yes_price * 100).toFixed(0) : '??'}%
                      </div>
                      {market.state && (
                        <div
                          className="text-xs font-medium"
                          style={{ color: STATE_COLORS[market.state] }}
                        >
                          {market.state}
                        </div>
                      )}
                    </div>

                    {/* Arrow */}
                    <div className="flex-shrink-0 text-gray-500">&rarr;</div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
