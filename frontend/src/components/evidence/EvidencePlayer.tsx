'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import type { EvidenceResponse, ShockEvent, ReactionEvent, LeadingEvent, StateChange } from '@/types/api';
import { REACTION_COLORS, STATE_COLORS } from '@/types/api';
import { getHeatmapTiles, type HeatmapTileMeta } from '@/lib/api';
import { HeatmapRenderer } from './HeatmapRenderer';
import { HashVerificationBadge } from './HashVerification';
import TileStalenessIndicator from './TileStalenessIndicator';
import { EvidenceDisclaimer } from './EvidenceDisclaimer';
import { useTokenStream } from '@/hooks/useStream';

interface EvidencePlayerProps {
  evidence: EvidenceResponse;
  currentTime: number;
  selectedEventId: string | null;
  onTimeChange: (time: number) => void;
  onEventClick: (eventId: string, timestamp: number) => void;
  /** Enable real-time updates via WebSocket */
  enableRealtime?: boolean;
  /** Callback when new real-time event arrives */
  onRealtimeEvent?: (event: { type: string; data: unknown }) => void;
}

export function EvidencePlayer({
  evidence,
  currentTime,
  selectedEventId,
  onTimeChange,
  onEventClick,
  enableRealtime = false,
  onRealtimeEvent,
}: EvidencePlayerProps) {
  // DEBUG: count renders
  console.count('[DEBUG] EvidencePlayer render');
  console.log('[DEBUG] EvidencePlayer', { token_id: evidence.token_id, enableRealtime });

  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 400 });
  // v5.40: Separate bid and ask tiles for Bookmap-style rendering
  const [bidTiles, setBidTiles] = useState<HeatmapTileMeta[]>([]);
  const [askTiles, setAskTiles] = useState<HeatmapTileMeta[]>([]);
  const [tilesLoading, setTilesLoading] = useState(false);
  const [realtimeEventCount, setRealtimeEventCount] = useState(0);

  // Real-time WebSocket stream (optional)
  const { isConnected, connectionState } = useTokenStream(
    enableRealtime ? evidence.token_id : '',
    {
      onShock: (payload) => {
        setRealtimeEventCount((c) => c + 1);
        onRealtimeEvent?.({ type: 'shock', data: payload });
      },
      onReaction: (payload) => {
        setRealtimeEventCount((c) => c + 1);
        onRealtimeEvent?.({ type: 'reaction', data: payload });
      },
      onBeliefState: (payload) => {
        setRealtimeEventCount((c) => c + 1);
        onRealtimeEvent?.({ type: 'belief_state', data: payload });
      },
      onAlert: (payload) => {
        setRealtimeEventCount((c) => c + 1);
        onRealtimeEvent?.({ type: 'alert', data: payload });
      },
    }
  );

  // Get tile end time for staleness indicator (combine bid and ask tiles)
  const allTiles = [...bidTiles, ...askTiles];
  const tileEndTime = allTiles.length > 0
    ? Math.max(...allTiles.map((t) => t.t_end))
    : evidence.window_end;

  // Fetch tiles when evidence changes
  // v5.40: Now fetches separate bid and ask tiles for Bookmap-style rendering
  useEffect(() => {
    if (!evidence.token_id) return;

    const abortController = new AbortController();
    setTilesLoading(true);

    console.log('[TilesFetch] Fetching tiles for:', evidence.token_id);

    async function fetchTiles() {
      try {
        const response = await getHeatmapTiles(
          {
            token_id: evidence.token_id,
            from_ts: evidence.window_start,
            to_ts: evidence.window_end,
            lod: 250,
          },
          abortController.signal
        );

        if (!abortController.signal.aborted) {
          console.log('[TilesFetch] Success, tiles:', response.bid_tiles.length + response.ask_tiles.length);
          // v5.40: Use separate bid and ask tiles
          setBidTiles(response.bid_tiles || []);
          setAskTiles(response.ask_tiles || []);
        }
      } catch (err) {
        if (abortController.signal.aborted) {
          console.log('[TilesFetch] Request aborted');
          return;
        }
        console.warn('[TilesFetch] Failed:', err);
        setBidTiles([]);
        setAskTiles([]);
      } finally {
        if (!abortController.signal.aborted) {
          setTilesLoading(false);
        }
      }
    }

    fetchTiles();

    return () => {
      abortController.abort();
    };
  }, [evidence.token_id, evidence.window_start, evidence.window_end]);

  // Resize observer
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ width, height: Math.max(300, height - 100) }); // Reserve space for timeline
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Draw overlay (events, anchors, state changes) on top of heatmap
  useEffect(() => {
    const canvas = overlayCanvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear overlay
    ctx.clearRect(0, 0, dimensions.width, dimensions.height);

    // Draw overlay elements
    drawOverlay(ctx, evidence, dimensions, currentTime, selectedEventId);
  }, [evidence, dimensions, currentTime, selectedEventId]);

  // Handle click on heatmap
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const container = e.currentTarget;
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;

      // Convert x to time
      const timeRange = evidence.window_end - evidence.window_start;
      const clickTime = evidence.window_start + (x / dimensions.width) * timeRange;

      onTimeChange(clickTime);
    },
    [evidence, dimensions, onTimeChange]
  );

  // Get price range from tiles manifest or defaults
  const priceMin = parseFloat(evidence.tiles_manifest.normalization.price_min);
  const priceMax = parseFloat(evidence.tiles_manifest.normalization.price_max);
  const tickSize = parseFloat(evidence.tiles_manifest.normalization.tick_size);

  return (
    <div ref={containerRef} className="flex-1 flex flex-col p-4">
      {/* Status Bar - Hash, Staleness, Connection */}
      <div className="flex items-center justify-between mb-2 px-2">
        <div className="flex items-center gap-3">
          {/* Hash Verification */}
          {evidence.bundle_hash && (
            <HashVerificationBadge
              storedHash={evidence.bundle_hash}
              computedHash={evidence.bundle_hash} // Pre-verified from server
            />
          )}

          {/* Tile Staleness */}
          <TileStalenessIndicator
            tileEndTime={tileEndTime}
            warningThresholdMs={10000}
            criticalThresholdMs={30000}
          />
        </div>

        <div className="flex items-center gap-3">
          {/* Real-time Connection Status */}
          {enableRealtime && (
            <div className="flex items-center gap-1.5 text-xs">
              <span className="relative flex h-2 w-2">
                {isConnected && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                )}
                <span
                  className={`relative inline-flex rounded-full h-2 w-2 ${
                    connectionState === 'connected' ? 'bg-green-500' :
                    connectionState === 'connecting' ? 'bg-yellow-500' :
                    connectionState === 'reconnecting' ? 'bg-orange-500' :
                    'bg-gray-400'
                  }`}
                />
              </span>
              <span className={`${isConnected ? 'text-green-400' : 'text-gray-400'}`}>
                {connectionState === 'connected' ? 'Live' :
                 connectionState === 'connecting' ? 'Connecting...' :
                 connectionState === 'reconnecting' ? 'Reconnecting...' :
                 'Offline'}
              </span>
              {realtimeEventCount > 0 && (
                <span className="text-gray-500">({realtimeEventCount})</span>
              )}
            </div>
          )}

          {/* Tile count */}
          <span className="text-xs text-gray-500">
            {bidTiles.length + askTiles.length} tiles
          </span>
        </div>
      </div>

      {/* Heatmap */}
      <div
        className="flex-1 relative bg-gray-800 rounded-lg overflow-hidden cursor-crosshair"
        onClick={handleCanvasClick}
      >
        {/* Heatmap layer (rendered from tiles or placeholder) */}
        {/* v5.40: Now using separate bid/ask tiles for Bookmap-style rendering */}
        <HeatmapRenderer
          bidTiles={bidTiles}
          askTiles={askTiles}
          windowStart={evidence.window_start}
          windowEnd={evidence.window_end}
          priceMin={priceMin}
          priceMax={priceMax}
          tickSize={tickSize}
          width={dimensions.width}
          height={dimensions.height}
          currentTime={currentTime}
        />

        {/* Overlay layer (events, anchors) */}
        <canvas
          ref={overlayCanvasRef}
          width={dimensions.width}
          height={dimensions.height}
          className="absolute inset-0 pointer-events-none"
        />

        {/* Loading indicator */}
        {tilesLoading && (
          <div className="absolute top-2 left-2 px-2 py-1 bg-blue-600/80 rounded text-xs">
            Loading tiles...
          </div>
        )}

        {/* Current time indicator */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white/50 pointer-events-none"
          style={{
            left: `${((currentTime - evidence.window_start) / (evidence.window_end - evidence.window_start)) * 100}%`,
          }}
        />

        {/* Price axis (right) */}
        <PriceAxis
          priceMin={parseFloat(evidence.tiles_manifest.normalization.price_min)}
          priceMax={parseFloat(evidence.tiles_manifest.normalization.price_max)}
          height={dimensions.height}
        />

        {/* v5.36: Evidence disclaimer watermark */}
        <EvidenceDisclaimer position="bottom-left" compact />

        {/* v5.36: STALE/TAINTED data overlay */}
        {evidence.evidence_grade && ['C', 'D'].includes(evidence.evidence_grade) && (
          <DataDegradationOverlay grade={evidence.evidence_grade} />
        )}
      </div>

      {/* Timeline with events */}
      <div className="mt-4">
        <ReactionTimeline
          evidence={evidence}
          currentTime={currentTime}
          selectedEventId={selectedEventId}
          onTimeChange={onTimeChange}
          onEventClick={onEventClick}
        />
      </div>
    </div>
  );
}

// Draw overlay (events, anchors, state changes)
function drawOverlay(
  ctx: CanvasRenderingContext2D,
  evidence: EvidenceResponse,
  dimensions: { width: number; height: number },
  currentTime: number,
  selectedEventId: string | null
) {
  const { width, height } = dimensions;
  const timeRange = evidence.window_end - evidence.window_start;
  const priceMin = parseFloat(evidence.tiles_manifest.normalization.price_min);
  const priceMax = parseFloat(evidence.tiles_manifest.normalization.price_max);

  const timeToX = (ts: number) => ((ts - evidence.window_start) / timeRange) * width;
  const priceToY = (price: number) => height - ((price - priceMin) / (priceMax - priceMin)) * height;

  // Draw anchors as horizontal lines
  ctx.setLineDash([4, 4]);
  evidence.anchors.forEach((anchor) => {
    const y = priceToY(parseFloat(anchor.price));
    ctx.strokeStyle = anchor.side === 'bid' ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  });
  ctx.setLineDash([]);

  // Draw shocks as vertical markers
  evidence.shocks.forEach((shock) => {
    const x = timeToX(shock.timestamp);
    const y = priceToY(parseFloat(shock.price));
    const isSelected = shock.id === selectedEventId;

    ctx.fillStyle = isSelected ? '#fbbf24' : '#eab308';
    ctx.beginPath();
    ctx.arc(x, y, isSelected ? 8 : 5, 0, Math.PI * 2);
    ctx.fill();

    // Lightning bolt icon
    ctx.fillStyle = '#1f2937';
    ctx.font = `${isSelected ? 10 : 7}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('⚡', x, y);
  });

  // Draw reactions as markers
  evidence.reactions.forEach((reaction) => {
    const x = timeToX(reaction.timestamp);
    const y = priceToY(parseFloat(reaction.price));
    const isSelected = reaction.id === selectedEventId;
    const color = REACTION_COLORS[reaction.reaction_type];

    ctx.fillStyle = isSelected ? '#ffffff' : color;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;

    // Diamond shape
    const size = isSelected ? 10 : 7;
    ctx.beginPath();
    ctx.moveTo(x, y - size);
    ctx.lineTo(x + size, y);
    ctx.lineTo(x, y + size);
    ctx.lineTo(x - size, y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  });

  // Draw leading events as triangles
  evidence.leading_events.forEach((event) => {
    const x = timeToX(event.timestamp);
    const y = priceToY(parseFloat(event.price));
    const isSelected = event.id === selectedEventId;

    ctx.fillStyle = isSelected ? '#ffffff' : '#a855f7';
    const size = isSelected ? 10 : 7;

    ctx.beginPath();
    ctx.moveTo(x, y - size);
    ctx.lineTo(x + size, y + size);
    ctx.lineTo(x - size, y + size);
    ctx.closePath();
    ctx.fill();
  });

  // Draw state changes as vertical bands
  evidence.state_changes.forEach((change, i) => {
    const x = timeToX(change.timestamp);
    const nextChange = evidence.state_changes[i + 1];
    const endX = nextChange ? timeToX(nextChange.timestamp) : width;

    ctx.fillStyle = `${STATE_COLORS[change.new_state]}15`;
    ctx.fillRect(x, 0, endX - x, height);

    // State label
    ctx.fillStyle = STATE_COLORS[change.new_state];
    ctx.font = 'bold 10px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(change.new_state, x + 4, 14);
  });
}

// Price axis component
function PriceAxis({
  priceMin,
  priceMax,
  height,
}: {
  priceMin: number;
  priceMax: number;
  height: number;
}) {
  const steps = 5;
  const prices = Array.from({ length: steps + 1 }, (_, i) => priceMin + (i / steps) * (priceMax - priceMin));

  return (
    <div
      className="absolute right-0 top-0 w-12 flex flex-col justify-between text-xs text-gray-400 py-2"
      style={{ height }}
    >
      {prices.reverse().map((price, i) => (
        <div key={i} className="text-right pr-2">
          {(price * 100).toFixed(0)}%
        </div>
      ))}
    </div>
  );
}

// Timeline component with events
function ReactionTimeline({
  evidence,
  currentTime,
  selectedEventId,
  onTimeChange,
  onEventClick,
}: {
  evidence: EvidenceResponse;
  currentTime: number;
  selectedEventId: string | null;
  onTimeChange: (time: number) => void;
  onEventClick: (eventId: string, timestamp: number) => void;
}) {
  const timeRange = evidence.window_end - evidence.window_start;
  const timeToPercent = (ts: number) => ((ts - evidence.window_start) / timeRange) * 100;

  // Combine all events for timeline
  const events: Array<{
    id: string;
    timestamp: number;
    type: 'shock' | 'reaction' | 'leading' | 'state';
    label: string;
    color: string;
  }> = [
    ...evidence.shocks.map((s) => ({
      id: s.id,
      timestamp: s.timestamp,
      type: 'shock' as const,
      label: `Shock @ ${(parseFloat(s.price) * 100).toFixed(0)}%`,
      color: '#eab308',
    })),
    ...evidence.reactions.map((r) => ({
      id: r.id,
      timestamp: r.timestamp,
      type: 'reaction' as const,
      label: r.reaction_type,
      color: REACTION_COLORS[r.reaction_type],
    })),
    ...evidence.leading_events.map((e) => ({
      id: e.id,
      timestamp: e.timestamp,
      type: 'leading' as const,
      label: e.event_type.replace(/_/g, ' '),
      color: '#a855f7',
    })),
    ...evidence.state_changes.map((s) => ({
      id: s.id,
      timestamp: s.timestamp,
      type: 'state' as const,
      label: `→ ${s.new_state}`,
      color: STATE_COLORS[s.new_state],
    })),
  ].sort((a, b) => a.timestamp - b.timestamp);

  return (
    <div className="bg-gray-800 rounded-lg p-3">
      {/* Time labels */}
      <div className="flex justify-between text-xs text-gray-500 mb-2">
        <span>{formatTime(evidence.window_start)}</span>
        <span>{formatTime(evidence.window_end)}</span>
      </div>

      {/* Timeline bar */}
      <div className="relative h-8 bg-gray-700 rounded">
        {/* Event markers */}
        {events.map((event) => (
          <button
            key={event.id}
            onClick={() => onEventClick(event.id, event.timestamp)}
            className={`absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2 transition-transform hover:scale-150 ${
              event.id === selectedEventId ? 'scale-150 ring-2 ring-white' : ''
            }`}
            style={{
              left: `${timeToPercent(event.timestamp)}%`,
              backgroundColor: event.color,
              borderColor: event.color,
            }}
            title={event.label}
          />
        ))}

        {/* Current time indicator */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white"
          style={{ left: `${timeToPercent(currentTime)}%` }}
        />
      </div>

      {/* Scrubber */}
      <input
        type="range"
        min={evidence.window_start}
        max={evidence.window_end}
        value={currentTime}
        onChange={(e) => onTimeChange(parseInt(e.target.value))}
        className="w-full mt-2 accent-blue-500"
      />

      {/* Current time display */}
      <div className="text-center text-sm text-gray-400 mt-1">{formatTime(currentTime)}</div>
    </div>
  );
}

function formatTime(ts: number): string {
  const date = new Date(ts);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/**
 * v5.36: Data Degradation Overlay
 *
 * Shows prominent STALE or TAINTED warning when evidence grade is C or D.
 * This ensures users are aware of data quality issues.
 */
function DataDegradationOverlay({ grade }: { grade: string }) {
  const isTainted = grade === 'D';
  const label = isTainted ? 'TAINTED' : 'STALE';
  const color = isTainted ? 'rgba(239, 68, 68, 0.15)' : 'rgba(234, 179, 8, 0.12)';
  const borderColor = isTainted ? 'rgb(239, 68, 68)' : 'rgb(234, 179, 8)';
  const textColor = isTainted ? 'text-red-400' : 'text-yellow-400';

  return (
    <>
      {/* Semi-transparent overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ backgroundColor: color }}
      />

      {/* Diagonal stripes pattern for TAINTED */}
      {isTainted && (
        <div
          className="absolute inset-0 pointer-events-none opacity-10"
          style={{
            backgroundImage: `repeating-linear-gradient(
              45deg,
              transparent,
              transparent 10px,
              rgba(239, 68, 68, 0.3) 10px,
              rgba(239, 68, 68, 0.3) 20px
            )`,
          }}
        />
      )}

      {/* Status badge */}
      <div
        className={`absolute top-2 right-14 px-3 py-1.5 rounded-lg border-2 ${textColor}`}
        style={{ borderColor, backgroundColor: 'rgba(17, 24, 39, 0.9)' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">{isTainted ? '⚠️' : '⏳'}</span>
          <div>
            <div className="font-bold text-sm">{label} DATA</div>
            <div className="text-xs opacity-75">
              Grade {grade} - {isTainted ? 'Integrity compromised' : 'Data gaps detected'}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
