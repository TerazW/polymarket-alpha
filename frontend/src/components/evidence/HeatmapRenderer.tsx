'use client';

/**
 * HeatmapRenderer - Bookmap-style order book visualization
 *
 * v5.40: Rewritten to use separate bid/ask tiles for proper Bookmap rendering.
 * - bid_tiles rendered in GREEN (buy side liquidity)
 * - ask_tiles rendered in RED (sell side liquidity)
 * - No more midPrice-based color determination
 * - Log-based intensity mapping for heavy-tailed data
 * - Smooth rendering with additive blending
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import type { HeatmapTileMeta } from '@/lib/api';

interface HeatmapRendererProps {
  bidTiles: HeatmapTileMeta[];
  askTiles: HeatmapTileMeta[];
  windowStart: number;
  windowEnd: number;
  priceMin: number;
  priceMax: number;
  tickSize: number;
  width: number;
  height: number;
  currentTime: number;
  onReady?: () => void;
}

// Decoded tile data in memory
interface DecodedTile {
  tile: HeatmapTileMeta;
  matrix: Uint16Array;
  rows: number;
  cols: number;
  side: 'bid' | 'ask';
}

// Optional zstd decompression support
let fzstdModule: { decompress: (data: Uint8Array) => Uint8Array } | null = null;
let fzstdLoaded = false;

async function loadFzstd(): Promise<typeof fzstdModule> {
  if (fzstdLoaded) return fzstdModule;
  fzstdLoaded = true;

  try {
    // Dynamic import - will fail gracefully if not installed
    // @ts-expect-error - fzstd is optional
    fzstdModule = await import('fzstd');
  } catch {
    console.info('fzstd not available - tiles must be uncompressed');
  }
  return fzstdModule;
}

/**
 * Decode base64 payload to Uint16Array
 * Handles both compressed (zstd) and raw data
 */
async function decodeTilePayload(tile: HeatmapTileMeta): Promise<Uint16Array | null> {
  try {
    // Decode base64 to bytes
    const binaryStr = atob(tile.payload_b64);
    const bytes = new Uint8Array(binaryStr.length);
    for (let i = 0; i < binaryStr.length; i++) {
      bytes[i] = binaryStr.charCodeAt(i);
    }

    // If compressed with zstd, we need to decompress
    if (tile.compression.algo === 'zstd' && tile.compression.level > 0) {
      const fzstd = await loadFzstd();
      if (fzstd) {
        try {
          const decompressed = fzstd.decompress(bytes);
          return new Uint16Array(decompressed.buffer);
        } catch (e) {
          console.warn('zstd decompression failed:', e);
        }
      }
      // If fzstd not available or failed, return null to show placeholder
      console.warn('Compressed tile cannot be decoded - fzstd not available');
      return null;
    }

    // No compression - parse directly as uint16
    if (tile.compression.algo === 'none' || tile.compression.level === 0) {
      // Ensure proper alignment for Uint16Array
      const expectedBytes = tile.rows * tile.cols * 2;
      if (bytes.length >= expectedBytes) {
        return new Uint16Array(bytes.buffer, bytes.byteOffset, tile.rows * tile.cols);
      }
    }

    // Fallback: create empty matrix
    return new Uint16Array(tile.rows * tile.cols);
  } catch (err) {
    console.error('Failed to decode tile:', err);
    return null;
  }
}

/**
 * Convert uint16 value to depth using log1p inverse
 * scale='log1p' means: encoded = log1p(depth) * (65535 / log1p(clip_value))
 * So: depth = exp(encoded * log1p(clip_value) / 65535) - 1
 */
function decodeDepth(value: number, clipValue: number, scale: string): number {
  if (scale === 'log1p_clip' || scale === 'log1p') {
    const maxLog = Math.log1p(clipValue);
    const logValue = (value / 65535) * maxLog;
    return Math.expm1(logValue);
  }
  // Linear scale
  return (value / 65535) * clipValue;
}

/**
 * Calculate intensity using log-based mapping for Bookmap-style visualization
 * This handles the heavy-tailed distribution of order book depth
 */
function calculateIntensity(depth: number, clipValue: number): number {
  if (depth <= 0) return 0;

  // Use log-based intensity mapping with gamma correction
  // This spreads out the values better than linear mapping
  const logIntensity = Math.log1p(depth) / Math.log1p(clipValue);

  // Apply gamma correction (0.6) for better visual perception
  const gamma = 0.6;
  return Math.min(1, Math.pow(logIntensity, gamma));
}

export function HeatmapRenderer({
  bidTiles,
  askTiles,
  windowStart,
  windowEnd,
  priceMin,
  priceMax,
  tickSize,
  width,
  height,
  currentTime,
  onReady,
}: HeatmapRendererProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [decodedTiles, setDecodedTiles] = useState<DecodedTile[]>([]);
  const [loading, setLoading] = useState(true);

  // Decode tiles when they change
  useEffect(() => {
    const allTiles = [
      ...bidTiles.map(t => ({ tile: t, side: 'bid' as const })),
      ...askTiles.map(t => ({ tile: t, side: 'ask' as const })),
    ];

    if (allTiles.length === 0) {
      setDecodedTiles([]);
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function decodeTiles() {
      const decoded: DecodedTile[] = [];

      for (const { tile, side } of allTiles) {
        if (cancelled) break;

        const matrix = await decodeTilePayload(tile);
        if (matrix) {
          decoded.push({
            tile,
            matrix,
            rows: tile.rows,
            cols: tile.cols,
            side,
          });
        }
      }

      if (!cancelled) {
        setDecodedTiles(decoded);
        setLoading(false);
        onReady?.();
      }
    }

    setLoading(true);
    decodeTiles();

    return () => {
      cancelled = true;
    };
  }, [bidTiles, askTiles, onReady]);

  // Render heatmap
  const renderHeatmap = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear canvas with dark background
    ctx.fillStyle = '#1f2937'; // gray-800
    ctx.fillRect(0, 0, width, height);

    if (decodedTiles.length === 0) {
      // No tiles - show placeholder
      renderPlaceholder(ctx, width, height);
      return;
    }

    const timeRange = windowEnd - windowStart;
    const priceRange = priceMax - priceMin;

    // Enable additive blending for smoother overlapping
    ctx.globalCompositeOperation = 'lighter';

    // Render each tile
    for (const { tile, matrix, rows, cols, side } of decodedTiles) {
      const clipValue = tile.encoding.clip_value || 10000;
      const scale = tile.encoding.scale;

      // Calculate tile position in canvas
      const tileX = ((tile.t_start - windowStart) / timeRange) * width;
      const tileWidth = ((tile.t_end - tile.t_start) / timeRange) * width;

      const tilePriceMin = tile.price_min;
      const tilePriceMax = tile.price_max;
      const tileY = height - ((tilePriceMax - priceMin) / priceRange) * height;
      const tileHeight = ((tilePriceMax - tilePriceMin) / priceRange) * height;

      // Calculate cell dimensions
      const cellWidth = tileWidth / cols;
      const cellHeight = tileHeight / rows;

      // v5.40: Color based on side, not midPrice
      // Bid = green (buy side liquidity)
      // Ask = red (sell side liquidity)
      const baseColor = side === 'bid'
        ? { r: 34, g: 197, b: 94 }   // green-500
        : { r: 239, g: 68, b: 68 };  // red-500

      // Render each cell
      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const idx = row * cols + col;
          const value = matrix[idx];

          if (value === 0) continue;

          const depth = decodeDepth(value, clipValue, scale);
          const intensity = calculateIntensity(depth, clipValue);

          if (intensity < 0.02) continue; // Skip nearly invisible cells

          const x = tileX + col * cellWidth;
          const y = tileY + (rows - row - 1) * cellHeight;

          // Apply intensity to color with alpha
          const alpha = intensity * 0.85;
          ctx.fillStyle = `rgba(${baseColor.r}, ${baseColor.g}, ${baseColor.b}, ${alpha})`;

          ctx.fillRect(x, y, cellWidth, cellHeight);
        }
      }
    }

    // Reset composite operation
    ctx.globalCompositeOperation = 'source-over';

    // Draw price axis grid lines (subtle)
    ctx.strokeStyle = 'rgba(75, 85, 99, 0.3)'; // gray-600 with alpha
    ctx.lineWidth = 1;
    const priceSteps = Math.ceil(priceRange / tickSize / 10); // Every 10 ticks
    for (let i = 0; i <= priceSteps; i++) {
      const y = height - (i / priceSteps) * height;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

  }, [decodedTiles, width, height, windowStart, windowEnd, priceMin, priceMax, tickSize]);

  // Re-render when dependencies change
  useEffect(() => {
    renderHeatmap();
  }, [renderHeatmap]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="absolute inset-0"
      style={{ imageRendering: 'auto' }}  // v5.40: Removed 'pixelated' for smoother rendering
    />
  );
}

/**
 * Render placeholder when no tiles available
 */
function renderPlaceholder(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number
) {
  // Draw subtle gradient background
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, '#374151');  // gray-700
  gradient.addColorStop(0.5, '#1f2937'); // gray-800
  gradient.addColorStop(1, '#374151');  // gray-700
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  // Draw "Loading..." or "No Data" text
  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
  ctx.fillRect(width / 2 - 70, height / 2 - 15, 140, 30);
  ctx.fillStyle = '#9ca3af';
  ctx.font = '12px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('Waiting for data...', width / 2, height / 2);
}

export default HeatmapRenderer;
