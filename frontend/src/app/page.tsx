'use client';

import { useState, useEffect } from 'react';

interface Market {
  condition_id: string;
  question: string;
  volume_24h: number;
  liquidity: number;
  yes_price: number | null;
}

interface Stats {
  trades: number;
  books: number;
  shocks: number;
  reactions: number;
  reaction_types: Record<string, number>;
}

export default function Dashboard() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = 'http://127.0.0.1:8000';

  const fetchMarkets = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/markets?limit=20`);
      if (!res.ok) throw new Error('Failed to fetch markets');
      const data = await res.json();
      setMarkets(data.markets || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch {
      // Stats endpoint might not exist yet
    }
  };

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchMarkets(), fetchStats()]);
      setLoading(false);
    };
    loadData();
    const interval = setInterval(() => {
      fetchMarkets();
      fetchStats();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="min-h-screen bg-gray-900 text-white p-8">
      <div className="max-w-6xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">Belief Reaction System</h1>
          <p className="text-gray-400">Real-time market monitoring</p>
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
              <div className="text-gray-400 text-sm">⚡ Shock Events</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-purple-400">{stats.reactions.toLocaleString()}</div>
              <div className="text-gray-400 text-sm">🎯 Reactions</div>
            </div>
          </div>
        )}

        {stats && stats.reaction_types && Object.keys(stats.reaction_types).length > 0 && (
          <div className="bg-gray-800 rounded-lg p-4 mb-8">
            <h3 className="text-lg font-semibold mb-3">Reaction Types</h3>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.reaction_types).map(([type, count]) => {
                const colors: Record<string, string> = {
                  HOLD: 'bg-green-500/20 text-green-400',
                  DELAY: 'bg-yellow-500/20 text-yellow-400',
                  PULL: 'bg-orange-500/20 text-orange-400',
                  VACUUM: 'bg-red-500/20 text-red-400',
                  CHASE: 'bg-cyan-500/20 text-cyan-400',
                  FAKE: 'bg-purple-500/20 text-purple-400',
                };
                const emojis: Record<string, string> = {
                  HOLD: '🟢', DELAY: '🟡', PULL: '🟠',
                  VACUUM: '🔴', CHASE: '🔵', FAKE: '💜',
                };
                return (
                  <div key={type} className={`px-3 py-2 rounded-lg ${colors[type] || 'bg-gray-700'}`}>
                    <span className="mr-1">{emojis[type] || ''}</span>
                    <span className="font-medium">{type}</span>
                    <span className="ml-2 opacity-70">{count}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <div className="p-4 border-b border-gray-700">
            <h2 className="text-xl font-semibold">Hot Markets</h2>
          </div>

          {loading ? (
            <div className="p-8 text-center text-gray-400">Loading...</div>
          ) : error ? (
            <div className="p-8 text-center text-red-400">
              Error: {error}<br/>
              <span className="text-sm text-gray-500">Make sure backend is running: python run_api.py</span>
            </div>
          ) : (
            <div className="divide-y divide-gray-700">
              {markets.map((market, index) => (
                <div key={market.condition_id || index} className="p-4 hover:bg-gray-700/50">
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <h3 className="font-medium mb-1">{market.question}</h3>
                      <div className="flex gap-4 text-sm text-gray-400">
                        <span>Vol: ${(market.volume_24h || 0).toLocaleString()}</span>
                        <span>Liq: ${(market.liquidity || 0).toLocaleString()}</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold text-green-400">
                        {market.yes_price != null ? (market.yes_price * 100).toFixed(0) : '??'}%
                      </div>
                      <div className="text-xs text-gray-500">YES</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
