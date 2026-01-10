'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { getReplayCatalog, type ReplayCatalogEntry } from '@/lib/api';

type EventKind = 'SHOCK' | 'REACTION' | 'LEADING' | 'BELIEF_STATE' | 'ALERT';
type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

const EVENT_COLORS: Record<EventKind, string> = {
  SHOCK: '#eab308',      // yellow
  REACTION: '#06b6d4',   // cyan
  LEADING: '#a855f7',    // purple
  BELIEF_STATE: '#ef4444', // red
  ALERT: '#f97316',      // orange
};

const EVENT_ICONS: Record<EventKind, string> = {
  SHOCK: '⚡',
  REACTION: '◆',
  LEADING: '▲',
  BELIEF_STATE: '●',
  ALERT: '🔔',
};

const SEVERITY_COLORS: Record<Severity, string> = {
  LOW: '#6b7280',
  MEDIUM: '#eab308',
  HIGH: '#f97316',
  CRITICAL: '#ef4444',
};

export default function ReplayCatalogPage() {
  const [entries, setEntries] = useState<ReplayCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiStatus, setApiStatus] = useState<'loading' | 'online' | 'offline'>('loading');

  // Filters
  const [timeRange, setTimeRange] = useState<'1h' | '6h' | '24h' | '7d'>('24h');
  const [eventType, setEventType] = useState<EventKind | 'ALL'>('ALL');
  const [severityFilter, setSeverityFilter] = useState<Severity | 'ALL'>('ALL');

  const getTimeRangeMs = (range: string): number => {
    switch (range) {
      case '1h': return 60 * 60 * 1000;
      case '6h': return 6 * 60 * 60 * 1000;
      case '24h': return 24 * 60 * 60 * 1000;
      case '7d': return 7 * 24 * 60 * 60 * 1000;
      default: return 24 * 60 * 60 * 1000;
    }
  };

  const fetchCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const now = Date.now();
      const from_ts = now - getTimeRangeMs(timeRange);

      const response = await getReplayCatalog({
        from_ts,
        to_ts: now,
        event_type: eventType === 'ALL' ? undefined : eventType,
        severity: severityFilter === 'ALL' ? undefined : severityFilter,
        limit: 100,
      });

      setEntries(response.rows);
      setApiStatus('online');
    } catch (err) {
      console.error('Failed to fetch catalog:', err);
      setApiStatus('offline');
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setError(`Failed to load catalog: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  }, [timeRange, eventType, severityFilter]);

  useEffect(() => {
    fetchCatalog();
  }, [fetchCatalog]);

  // Filter entries client-side
  const filteredEntries = entries.filter((entry) => {
    if (eventType !== 'ALL' && entry.kind !== eventType) return false;
    if (severityFilter !== 'ALL' && entry.severity !== severityFilter) return false;
    return true;
  });

  // Group entries by date
  const groupedEntries = filteredEntries.reduce((groups, entry) => {
    const date = new Date(entry.ts).toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
    if (!groups[date]) groups[date] = [];
    groups[date].push(entry);
    return groups;
  }, {} as Record<string, ReplayCatalogEntry[]>);

  return (
    <main className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-gray-400 hover:text-white">
              ← Back
            </Link>
            <h1 className="text-xl font-semibold">Replay Catalog</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className={`text-xs ${apiStatus === 'online' ? 'text-green-400' : 'text-red-400'}`}>
              {apiStatus === 'online' ? '● API Online' : '○ API Offline'}
            </span>
          </div>
        </div>
      </header>

      <div className="max-w-6xl mx-auto p-6">
        {/* Filters */}
        <div className="bg-gray-800 rounded-lg p-4 mb-6">
          <div className="flex flex-wrap gap-4 items-center">
            {/* Time range */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">Time:</span>
              <div className="flex rounded-lg overflow-hidden">
                {(['1h', '6h', '24h', '7d'] as const).map((range) => (
                  <button
                    key={range}
                    onClick={() => setTimeRange(range)}
                    className={`px-3 py-1 text-sm ${
                      timeRange === range
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    }`}
                  >
                    {range}
                  </button>
                ))}
              </div>
            </div>

            {/* Event type */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">Type:</span>
              <select
                value={eventType}
                onChange={(e) => setEventType(e.target.value as EventKind | 'ALL')}
                className="bg-gray-700 text-white rounded px-3 py-1 text-sm"
              >
                <option value="ALL">All Types</option>
                <option value="SHOCK">⚡ Shocks</option>
                <option value="REACTION">◆ Reactions</option>
                <option value="LEADING">▲ Leading Events</option>
                <option value="BELIEF_STATE">● State Changes</option>
                <option value="ALERT">🔔 Alerts</option>
              </select>
            </div>

            {/* Severity */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">Severity:</span>
              <select
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value as Severity | 'ALL')}
                className="bg-gray-700 text-white rounded px-3 py-1 text-sm"
              >
                <option value="ALL">All</option>
                <option value="CRITICAL">🔴 Critical</option>
                <option value="HIGH">🟠 High</option>
                <option value="MEDIUM">🟡 Medium</option>
                <option value="LOW">⚪ Low</option>
              </select>
            </div>

            {/* Results count */}
            <div className="ml-auto text-sm text-gray-500">
              {filteredEntries.length} events
            </div>
          </div>
        </div>

        {/* Event list */}
        {loading ? (
          <div className="text-center py-12 text-gray-400">Loading catalog...</div>
        ) : error ? (
          <div className="text-center py-12 text-red-400">{error}</div>
        ) : filteredEntries.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            No events found in the selected time range.
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(groupedEntries).map(([date, dateEntries]) => (
              <div key={date}>
                <h3 className="text-sm text-gray-500 mb-2 sticky top-0 bg-gray-900 py-1">
                  {date}
                </h3>
                <div className="bg-gray-800 rounded-lg overflow-hidden divide-y divide-gray-700">
                  {dateEntries.map((entry) => (
                    <Link
                      key={entry.id}
                      href={`/market/${entry.token_id}?t0=${entry.evidence_ref.t0}`}
                      className="block p-4 hover:bg-gray-700/50 transition-colors"
                    >
                      <div className="flex items-center gap-4">
                        {/* Event icon */}
                        <div
                          className="w-8 h-8 rounded-full flex items-center justify-center text-lg"
                          style={{ backgroundColor: `${EVENT_COLORS[entry.kind]}20` }}
                        >
                          <span style={{ color: EVENT_COLORS[entry.kind] }}>
                            {EVENT_ICONS[entry.kind]}
                          </span>
                        </div>

                        {/* Event info */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span
                              className="text-xs px-2 py-0.5 rounded"
                              style={{
                                backgroundColor: `${EVENT_COLORS[entry.kind]}20`,
                                color: EVENT_COLORS[entry.kind],
                              }}
                            >
                              {entry.kind}
                            </span>
                            {entry.severity && (
                              <span
                                className="text-xs px-2 py-0.5 rounded"
                                style={{
                                  backgroundColor: `${SEVERITY_COLORS[entry.severity as Severity]}20`,
                                  color: SEVERITY_COLORS[entry.severity as Severity],
                                }}
                              >
                                {entry.severity}
                              </span>
                            )}
                          </div>
                          <p className="font-medium mt-1">{entry.label}</p>
                          <p className="text-sm text-gray-500 truncate">
                            Token: {entry.token_id.slice(0, 20)}...
                          </p>
                        </div>

                        {/* Time */}
                        <div className="text-right">
                          <div className="text-sm text-gray-400">
                            {new Date(entry.ts).toLocaleTimeString('en-US', {
                              hour: '2-digit',
                              minute: '2-digit',
                              second: '2-digit',
                            })}
                          </div>
                          <div className="text-xs text-gray-500">
                            {getRelativeTime(entry.ts)}
                          </div>
                        </div>

                        {/* Arrow */}
                        <div className="text-gray-500">→</div>
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

function getRelativeTime(ts: number): string {
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}
