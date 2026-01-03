'use client';

import { useState, useEffect } from 'react';

interface Market {
  id: string;
  question: string;
  volume_24h: number;
  liquidity: number;
  yes_price: number;
  last_trade_at: string;
}

interface Stats {
  trades: number;
  books: number;
}

export default function Dashboard() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = 'http://127.0.0.1:8000';

  // Fetch markets
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

  // Fetch DB stats
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

    // Refresh every 30 seconds
    const interval = setInterval(() => {
      fetchMarkets();
      fetchStats();
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  return (
    <main className="min-h-screen bg-gray-900 text-white p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">Belief Reaction System</h1>
          <p className="text-gray-400">
            Real-time market monitoring and belief state tracking
          </p>
        </div>

        {/* Stats Cards */}
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
              <div className="text-2xl font-bold text-yellow-400">{markets.length}</div>
              <div className="text-gray-400 text-sm">Active Markets</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-purple-400">STABLE</div>
              <div className="text-gray-400 text-sm">System State</div>
            </div>
          </div>
        )}

        {/* Markets List */}
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <div className="p-4 border-b border-gray-700">
            <h2 className="text-xl font-semibold">Hot Markets</h2>
          </div>

          {loading ? (
            <div className="p-8 text-center text-gray-400">Loading markets...</div>
          ) : error ? (
            <div className="p-8 text-center text-red-400">
              Error: {error}
              <br />
              <span className="text-sm text-gray-500">
                Make sure the backend is running: python run_api.py
              </span>
            </div>
          ) : markets.length === 0 ? (
            <div className="p-8 text-center text-gray-400">No markets found</div>
          ) : (
            <div className="divide-y divide-gray-700">
              {markets.map((market, index) => (
                <div
                  key={market.id || index}
                  className="p-4 hover:bg-gray-700/50 transition-colors"
                >
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
                        {((market.yes_price || 0.5) * 100).toFixed(0)}%
                      </div>
                      <div className="text-xs text-gray-500">YES Price</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Belief States Legend */}
        <div className="mt-8 bg-gray-800 rounded-lg p-4">
          <h3 className="font-semibold mb-3">Belief States</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-green-500"></div>
              <span>STABLE - Strong defense</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
              <span>FRAGILE - Mixed signals</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-orange-500"></div>
              <span>CRACKING - Defense failing</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-red-500"></div>
              <span>BROKEN - Belief collapsed</span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-8 text-center text-gray-500 text-sm">
          Data refreshes every 30 seconds | Collector status: Running
        </div>
      </div>
    </main>
  );
}
