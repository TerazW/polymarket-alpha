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
 *
 * v5.41: Unified clipValue across all tiles (B1 improvement)
 * - Uses global max clipValue for intensity calculation
 * - Prevents banding artifacts at tile boundaries
 * - Per-tile clipValue still used for depth decoding (as encoded)
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
    console.log('[TileDecode] Starting decode:', {
      rows: tile.rows,
      cols: tile.cols,
      compression: tile.compression,
      payload_length: tile.payload_b64?.length ?? 0,
      price_range: `${tile.price_min} - ${tile.price_max}`,
      time_range: `${tile.t_start} - ${tile.t_end}`,
    });

    if (!tile.payload_b64) {
      console.warn('[TileDecode] No payload_b64 in tile!');
      return null;
    }

    // Decode base64 to bytes
    const binaryStr = atob(tile.payload_b64);
    const bytes = new Uint8Array(binaryStr.length);
    for (let i = 0; i < binaryStr.length; i++) {
      bytes[i] = binaryStr.charCodeAt(i);
    }
    console.log('[TileDecode] Decoded base64 to bytes:', bytes.length);

    // If compressed with zstd, we need to decompress
    if (tile.compression.algo === 'zstd' && tile.compression.level > 0) {
      console.log('[TileDecode] Attempting zstd decompression...');
      const fzstd = await loadFzstd();
      if (fzstd) {
        try {
          const decompressed = fzstd.decompress(bytes);
          console.log('[TileDecode] zstd decompressed:', decompressed.length, 'bytes');
          return new Uint16Array(decompressed.buffer);
        } catch (e) {
          console.warn('[TileDecode] zstd decompression failed:', e);
        }
      } else {
        console.warn('[TileDecode] fzstd module not available');
      }
      // If fzstd not available or failed, return null to show placeholder
      console.warn('Compressed tile cannot be decoded - fzstd not available');
      return null;
    }

    // No compression - parse directly as uint16
    if (tile.compression.algo === 'none' || tile.compression.level === 0) {
      // Ensure proper alignment for Uint16Array
      const expectedBytes = tile.rows * tile.cols * 2;
      console.log('[TileDecode] Uncompressed tile, expected bytes:', expectedBytes, 'actual:', bytes.length);
      if (bytes.length >= expectedBytes) {
        const result = new Uint16Array(bytes.buffer, bytes.byteOffset, tile.rows * tile.cols);
        // Check for non-zero values
        let nonZeroCount = 0;
        let maxValue = 0;
        for (let i = 0; i < result.length; i++) {
          if (result[i] > 0) nonZeroCount++;
          if (result[i] > maxValue) maxValue = result[i];
        }
        console.log('[TileDecode] Tile stats:', { nonZeroCount, maxValue, totalCells: result.length });
        return result;
      } else {
        console.warn('[TileDecode] Byte length mismatch! Expected:', expectedBytes, 'Got:', bytes.length);
      }
    }

    // Fallback: create empty matrix
    console.warn('[TileDecode] Using fallback empty matrix');
    return new Uint16Array(tile.rows * tile.cols);
  } catch (err) {
    console.error('[TileDecode] Failed to decode tile:', err);
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
    console.log('[HeatmapRenderer] Decode effect triggered:', {
      bidTilesCount: bidTiles.length,
      askTilesCount: askTiles.length,
    });

    const allTiles = [
      ...bidTiles.map(t => ({ tile: t, side: 'bid' as const })),
      ...askTiles.map(t => ({ tile: t, side: 'ask' as const })),
    ];

    if (allTiles.length === 0) {
      console.log('[HeatmapRenderer] No tiles to decode');
      setDecodedTiles([]);
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function decodeTiles() {
      console.log('[HeatmapRenderer] Starting decode of', allTiles.length, 'tiles');
      const decoded: DecodedTile[] = [];

      for (const { tile, side } of allTiles) {
        if (cancelled) {
          console.log('[HeatmapRenderer] Decode cancelled');
          break;
        }

        const matrix = await decodeTilePayload(tile);
        if (matrix) {
          decoded.push({
            tile,
            matrix,
            rows: tile.rows,
            cols: tile.cols,
            side,
          });
        } else {
          console.warn('[HeatmapRenderer] Failed to decode tile:', tile.t_start);
        }
      }

      console.log('[HeatmapRenderer] Decode complete:', {
        decodedCount: decoded.length,
        cancelled,
      });

      if (!cancelled) {
        setDecodedTiles(decoded);
        setLoading(false);
        onReady?.();
      }
    }

    setLoading(true);
    decodeTiles();

    return () => {
      console.log('[HeatmapRenderer] Decode effect cleanup');
      cancelled = true;
    };
  }, [bidTiles, askTiles, onReady]);

  // Render heatmap
  const renderHeatmap = useCallback(() => {
    console.log('[HeatmapRender] Starting render:', {
      decodedTilesCount: decodedTiles.length,
      windowStart,
      windowEnd,
      priceMin,
      priceMax,
      canvasSize: { width, height },
    });

    const canvas = canvasRef.current;
    if (!canvas) {
      console.warn('[HeatmapRender] No canvas ref!');
      return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      console.warn('[HeatmapRender] No canvas context!');
      return;
    }

    // Clear canvas with dark background
    ctx.fillStyle = '#1f2937'; // gray-800
    ctx.fillRect(0, 0, width, height);

    if (decodedTiles.length === 0) {
      // No tiles - show placeholder
      console.log('[HeatmapRender] No decoded tiles, showing placeholder');
      renderPlaceholder(ctx, width, height);
      return;
    }

    const timeRange = windowEnd - windowStart;
    const priceRange = priceMax - priceMin;
    console.log('[HeatmapRender] Ranges:', { timeRange, priceRange });

    // v5.41: Calculate global clipValue across all tiles for consistent intensity mapping
    // This prevents banding artifacts at tile boundaries where different tiles
    // might have different clip_values
    const globalClip = Math.max(
      ...decodedTiles.map(t => t.tile.encoding.clip_value || 10000)
    );

    // Enable additive blending for smoother overlapping
    ctx.globalCompositeOperation = 'lighter';

    // Render each tile
    let tileIndex = 0;
    for (const { tile, matrix, rows, cols, side } of decodedTiles) {
      // Per-tile clipValue for decoding (data was encoded with this value)
      const tileClipValue = tile.encoding.clip_value || 10000;
      const scale = tile.encoding.scale;

      // Calculate tile position in canvas
      const tileX = ((tile.t_start - windowStart) / timeRange) * width;
      const tileWidth = ((tile.t_end - tile.t_start) / timeRange) * width;

      const tilePriceMin = tile.price_min;
      const tilePriceMax = tile.price_max;
      const tileY = height - ((tilePriceMax - priceMin) / priceRange) * height;
      const tileHeight = ((tilePriceMax - tilePriceMin) / priceRange) * height;

      // Log first few tiles for debugging
      if (tileIndex < 3) {
        console.log(`[HeatmapRender] Tile ${tileIndex} (${side}):`, {
          position: { tileX, tileY, tileWidth, tileHeight },
          tileTime: { t_start: tile.t_start, t_end: tile.t_end },
          tilePrice: { tilePriceMin, tilePriceMax },
          windowPrice: { priceMin, priceMax },
          encoding: { scale, tileClipValue },
          matrixSize: matrix.length,
        });
      }
      tileIndex++;

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

          // Decode depth using tile's clipValue (as encoded)
          const depth = decodeDepth(value, tileClipValue, scale);
          // v5.41: Use globalClip for intensity to ensure consistent mapping across tiles
          const intensity = calculateIntensity(depth, globalClip);

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
