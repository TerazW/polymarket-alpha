'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import type { EvidenceResponse, ShockEvent, ReactionEvent, LeadingEvent, StateChange } from '@/types/api';
import { REACTION_COLORS, STATE_COLORS } from '@/types/api';
import { getHeatmapTiles, type HeatmapTileMeta } from '@/lib/api';
import { HeatmapRenderer } from './HeatmapRenderer';

interface EvidencePlayerProps {
  evidence: EvidenceResponse;
  currentTime: number;
  selectedEventId: string | null;
  onTimeChange: (time: number) => void;
  onEventClick: (eventId: string, timestamp: number) => void;
}

export function EvidencePlayer({
  evidence,
  currentTime,
  selectedEventId,
  onTimeChange,
  onEventClick,
}: EvidencePlayerProps) {
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 400 });
  const [tiles, setTiles] = useState<HeatmapTileMeta[]>([]);
  const [tilesLoading, setTilesLoading] = useState(false);

  // Fetch tiles when evidence changes
  useEffect(() => {
    if (!evidence.token_id) return;

    let cancelled = false;
    setTilesLoading(true);

    async function fetchTiles() {
      try {
        const response = await getHeatmapTiles({
          token_id: evidence.token_id,
          from_ts: evidence.window_start,
          to_ts: evidence.window_end,
          lod: 250,
        });

        if (!cancelled) {
          setTiles(response.tiles);
        }
      } catch (err) {
        console.warn('Failed to fetch heatmap tiles:', err);
        if (!cancelled) {
          setTiles([]);
        }
      } finally {
        if (!cancelled) {
          setTilesLoading(false);
        }
      }
    }

    fetchTiles();

    return () => {
      cancelled = true;
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
      {/* Heatmap */}
      <div
        className="flex-1 relative bg-gray-800 rounded-lg overflow-hidden cursor-crosshair"
        onClick={handleCanvasClick}
      >
        {/* Heatmap layer (rendered from tiles or placeholder) */}
        <HeatmapRenderer
          tiles={tiles}
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
