'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { HeatmapTileMeta } from '@/lib/api';

interface HeatmapRendererProps {
  tiles: HeatmapTileMeta[];
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
  if (scale === 'log1p') {
    const maxLog = Math.log1p(clipValue);
    const logValue = (value / 65535) * maxLog;
    return Math.expm1(logValue);
  }
  // Linear scale
  return (value / 65535) * clipValue;
}

export function HeatmapRenderer({
  tiles,
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
    if (tiles.length === 0) {
      setDecodedTiles([]);
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function decodeTiles() {
      const decoded: DecodedTile[] = [];

      for (const tile of tiles) {
        if (cancelled) break;

        const matrix = await decodeTilePayload(tile);
        if (matrix) {
          decoded.push({
            tile,
            matrix,
            rows: tile.rows,
            cols: tile.cols,
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
  }, [tiles, onReady]);

  // Render heatmap
  const renderHeatmap = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear canvas
    ctx.fillStyle = '#1f2937'; // gray-800
    ctx.fillRect(0, 0, width, height);

    if (decodedTiles.length === 0) {
      // No tiles - show placeholder pattern
      renderPlaceholder(ctx, width, height, windowStart, windowEnd, priceMin, priceMax, tickSize);
      return;
    }

    const timeRange = windowEnd - windowStart;
    const priceRange = priceMax - priceMin;

    // Render each tile
    for (const { tile, matrix, rows, cols } of decodedTiles) {
      const clipValue = tile.encoding.clip_value || 10000;
      const scale = tile.encoding.scale;

      // Calculate tile position in canvas
      const tileX = ((tile.t_start - windowStart) / timeRange) * width;
      const tileWidth = ((tile.t_end - tile.t_start) / timeRange) * width;

      const tilePriceMin = tile.price_min;
      const tilePriceMax = tile.price_max;
      const tileY = height - ((tilePriceMax - priceMin) / priceRange) * height;
      const tileHeight = ((tilePriceMax - tilePriceMin) / priceRange) * height;

      // Render each cell
      const cellWidth = tileWidth / cols;
      const cellHeight = tileHeight / rows;

      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const idx = row * cols + col;
          const value = matrix[idx];

          if (value === 0) continue;

          const depth = decodeDepth(value, clipValue, scale);
          const intensity = Math.min(1, depth / clipValue);

          // Determine color based on tile band or position
          // For FULL band, we use price to determine bid/ask
          const cellPrice = tilePriceMin + (row / rows) * (tilePriceMax - tilePriceMin);
          const midPrice = (priceMin + priceMax) / 2;
          const isBid = cellPrice < midPrice;

          const x = tileX + col * cellWidth;
          const y = tileY + (rows - row - 1) * cellHeight;

          if (isBid) {
            ctx.fillStyle = `rgba(34, 197, 94, ${intensity * 0.9})`; // green
          } else {
            ctx.fillStyle = `rgba(239, 68, 68, ${intensity * 0.9})`; // red
          }

          ctx.fillRect(x, y, cellWidth + 0.5, cellHeight + 0.5);
        }
      }
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
      style={{ imageRendering: 'pixelated' }}
    />
  );
}

/**
 * Render placeholder pattern when no tiles available
 */
function renderPlaceholder(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  windowStart: number,
  windowEnd: number,
  priceMin: number,
  priceMax: number,
  tickSize: number
) {
  const timeRange = windowEnd - windowStart;
  const priceSteps = Math.round((priceMax - priceMin) / tickSize);

  const bucketWidth = 4;
  const bucketHeight = height / priceSteps;
  const timeBuckets = Math.ceil(width / bucketWidth);

  for (let t = 0; t < timeBuckets; t++) {
    for (let p = 0; p < priceSteps; p++) {
      const price = priceMin + p * tickSize;
      const midPrice = (priceMin + priceMax) / 2;
      const isBid = price < midPrice;

      // Generate procedural pattern
      let depth = Math.random() * 0.3;

      // Add some structure near mid price
      const distFromMid = Math.abs(price - midPrice) / (priceMax - priceMin);
      depth += (1 - distFromMid) * 0.4;

      const intensity = Math.min(1, depth);
      const x = t * bucketWidth;
      const y = height - (p + 1) * bucketHeight;

      if (isBid) {
        ctx.fillStyle = `rgba(34, 197, 94, ${intensity * 0.6})`;
      } else {
        ctx.fillStyle = `rgba(239, 68, 68, ${intensity * 0.6})`;
      }

      ctx.fillRect(x, y, bucketWidth - 1, bucketHeight - 1);
    }
  }

  // Draw "No Data" overlay
  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
  ctx.fillRect(width / 2 - 60, height / 2 - 15, 120, 30);
  ctx.fillStyle = '#9ca3af';
  ctx.font = '12px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('Generating tiles...', width / 2, height / 2);
}

export default HeatmapRenderer;
