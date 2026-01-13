import { useEffect, useState } from 'react';
import { getAlerts, type AlertRow } from '@/lib/api';

const ALERT_DISCLAIMER =
  'This alert indicates observed belief instability. It does NOT imply outcome direction or trading recommendation.';

function severityClass(severity: AlertRow['severity']): string {
  switch (severity) {
    case 'CRITICAL':
      return 'text-red-400';
    case 'HIGH':
      return 'text-orange-400';
    case 'MEDIUM':
      return 'text-yellow-400';
    default:
      return 'text-blue-400';
  }
}

export function AlertsPanel({ tokenId }: { tokenId: string }) {
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tokenId) return;
    const abortController = new AbortController();
    setLoading(true);
    setError(null);

    getAlerts({ token_id: tokenId, limit: 20 })
      .then((response) => {
        if (!abortController.signal.aborted) {
          setAlerts(response.rows);
        }
      })
      .catch((err) => {
        if (!abortController.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Failed to load alerts');
        }
      })
      .finally(() => {
        if (!abortController.signal.aborted) {
          setLoading(false);
        }
      });

    return () => abortController.abort();
  }, [tokenId]);

  return (
    <div className="p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-sm">Alerts</h3>
        <span className="text-xs text-gray-500">{alerts.length}</span>
      </div>

      <div className="text-[11px] text-gray-500 mb-2">{ALERT_DISCLAIMER}</div>

      {loading && <div className="text-xs text-gray-400">Loading alerts...</div>}
      {error && <div className="text-xs text-red-400">Error: {error}</div>}

      {!loading && !error && alerts.length === 0 && (
        <div className="text-xs text-gray-400">No alerts for this window.</div>
      )}

      <div className="space-y-2">
        {alerts.map((alert) => (
          <div
            key={alert.alert_id}
            className="border border-gray-700 bg-gray-800/70 rounded p-2"
          >
            <div className="flex items-center justify-between text-xs">
              <span className={`font-semibold ${severityClass(alert.severity)}`}>
                {alert.severity}
              </span>
              <span className="text-gray-500">{alert.status}</span>
            </div>
            <div className="text-sm text-gray-200 mt-1">{alert.summary}</div>
            <div className="text-[11px] text-gray-500 mt-1">
              {new Date(alert.ts).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
