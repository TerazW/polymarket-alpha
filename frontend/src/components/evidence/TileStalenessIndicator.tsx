'use client';

import { useMemo } from 'react';

interface TileStalenessIndicatorProps {
  tileEndTime: number;     // When the tile data ends (ms)
  currentTime?: number;    // Current time (defaults to now)
  alertAgeMs?: number;     // Age of most recent alert (ms since alert)
  warningThresholdMs?: number;  // Show warning if stale > this (default 10s)
  criticalThresholdMs?: number; // Show critical if stale > this (default 30s)
}

type StalenessLevel = 'fresh' | 'stale' | 'critical' | 'unknown';

/**
 * Tile Staleness Indicator
 *
 * Shows how fresh/stale the heatmap tile data is compared to real-time alerts.
 * Critical for user trust - they need to know if they're seeing delayed data.
 *
 * "Tiles 不能成为落后于实时告警的'真相源'"
 */
export default function TileStalenessIndicator({
  tileEndTime,
  currentTime,
  alertAgeMs,
  warningThresholdMs = 10000,   // 10 seconds
  criticalThresholdMs = 30000,  // 30 seconds
}: TileStalenessIndicatorProps) {
  const now = currentTime ?? Date.now();

  const { level, staleMs, message } = useMemo(() => {
    if (!tileEndTime) {
      return {
        level: 'unknown' as StalenessLevel,
        staleMs: 0,
        message: 'No tile data',
      };
    }

    const stale = now - tileEndTime;

    if (stale < 0) {
      // Tile is in the future? Clock issue
      return {
        level: 'unknown' as StalenessLevel,
        staleMs: stale,
        message: 'Clock sync issue',
      };
    }

    if (stale < warningThresholdMs) {
      return {
        level: 'fresh' as StalenessLevel,
        staleMs: stale,
        message: 'Live',
      };
    }

    if (stale < criticalThresholdMs) {
      return {
        level: 'stale' as StalenessLevel,
        staleMs: stale,
        message: `${Math.floor(stale / 1000)}s behind`,
      };
    }

    return {
      level: 'critical' as StalenessLevel,
      staleMs: stale,
      message: `${Math.floor(stale / 1000)}s behind`,
    };
  }, [tileEndTime, now, warningThresholdMs, criticalThresholdMs]);

  // Style based on staleness level
  const getStyles = () => {
    switch (level) {
      case 'fresh':
        return {
          bg: 'bg-green-100',
          text: 'text-green-700',
          dot: 'bg-green-500',
          pulse: true,
        };
      case 'stale':
        return {
          bg: 'bg-yellow-100',
          text: 'text-yellow-700',
          dot: 'bg-yellow-500',
          pulse: false,
        };
      case 'critical':
        return {
          bg: 'bg-red-100',
          text: 'text-red-700',
          dot: 'bg-red-500',
          pulse: true,
        };
      default:
        return {
          bg: 'bg-gray-100',
          text: 'text-gray-500',
          dot: 'bg-gray-400',
          pulse: false,
        };
    }
  };

  const styles = getStyles();

  // Calculate alert vs tile discrepancy
  const alertDiscrepancy = alertAgeMs !== undefined ?
    Math.max(0, staleMs - alertAgeMs) : null;

  return (
    <div
      className={`inline-flex items-center gap-2 px-2 py-1 rounded text-xs ${styles.bg}`}
      title={`Tile data ends at ${new Date(tileEndTime).toLocaleTimeString()}`}
    >
      {/* Pulsing dot for live/critical */}
      <span className="relative flex h-2 w-2">
        {styles.pulse && (
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full ${styles.dot} opacity-75`}
          />
        )}
        <span
          className={`relative inline-flex rounded-full h-2 w-2 ${styles.dot}`}
        />
      </span>

      {/* Status text */}
      <span className={styles.text}>
        {message}
      </span>

      {/* Alert discrepancy warning */}
      {alertDiscrepancy !== null && alertDiscrepancy > 5000 && (
        <span className="text-orange-600 text-[10px]">
          (alerts {Math.floor(alertDiscrepancy / 1000)}s ahead)
        </span>
      )}
    </div>
  );
}


/**
 * Compact version for inline use
 */
export function TileStalenessBadge({
  tileEndTime,
  size = 'sm',
}: {
  tileEndTime: number;
  size?: 'sm' | 'md';
}) {
  const now = Date.now();
  const staleMs = now - tileEndTime;

  const isFresh = staleMs < 10000;
  const isStale = staleMs >= 10000 && staleMs < 30000;
  const isCritical = staleMs >= 30000;

  const sizeClass = size === 'sm' ? 'text-[10px] px-1' : 'text-xs px-2';

  if (isFresh) {
    return (
      <span className={`${sizeClass} py-0.5 rounded bg-green-100 text-green-700`}>
        LIVE
      </span>
    );
  }

  if (isStale) {
    return (
      <span className={`${sizeClass} py-0.5 rounded bg-yellow-100 text-yellow-700`}>
        {Math.floor(staleMs / 1000)}s
      </span>
    );
  }

  if (isCritical) {
    return (
      <span className={`${sizeClass} py-0.5 rounded bg-red-100 text-red-700 animate-pulse`}>
        {Math.floor(staleMs / 1000)}s OLD
      </span>
    );
  }

  return null;
}


/**
 * Full status panel with explanation
 */
export function TileStalenessPanel({
  tileEndTime,
  alertTimestamp,
  lastTradeTimestamp,
}: {
  tileEndTime: number;
  alertTimestamp?: number;
  lastTradeTimestamp?: number;
}) {
  const now = Date.now();

  const tileAge = now - tileEndTime;
  const alertAge = alertTimestamp ? now - alertTimestamp : null;
  const tradeAge = lastTradeTimestamp ? now - lastTradeTimestamp : null;

  return (
    <div className="p-3 bg-gray-50 rounded-lg text-sm">
      <div className="font-medium mb-2">Data Freshness</div>

      <div className="space-y-1 text-gray-600">
        <div className="flex justify-between">
          <span>Heatmap tiles:</span>
          <TileStalenessBadge tileEndTime={tileEndTime} />
        </div>

        {alertAge !== null && (
          <div className="flex justify-between">
            <span>Last alert:</span>
            <span className={alertAge < 60000 ? 'text-green-600' : 'text-gray-500'}>
              {alertAge < 1000 ? 'just now' : `${Math.floor(alertAge / 1000)}s ago`}
            </span>
          </div>
        )}

        {tradeAge !== null && (
          <div className="flex justify-between">
            <span>Last trade:</span>
            <span className={tradeAge < 60000 ? 'text-green-600' : 'text-gray-500'}>
              {tradeAge < 1000 ? 'just now' : `${Math.floor(tradeAge / 1000)}s ago`}
            </span>
          </div>
        )}
      </div>

      {tileAge > 30000 && (
        <div className="mt-2 text-xs text-red-600 bg-red-50 p-2 rounded">
          Heatmap data is significantly behind real-time events.
          Alerts and trades may show activity not yet visible in the heatmap.
        </div>
      )}
    </div>
  );
}
