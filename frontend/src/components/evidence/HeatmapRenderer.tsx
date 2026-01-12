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

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
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
  renderConfig?: HeatmapRenderConfig;
  debugOptions?: HeatmapDebugOptions;
}

type NormalizeMode = 'log1p' | 'sqrt' | 'linear';
type HoldMode = 'hold' | 'decay' | 'off';
type DecayCurve = 'linear' | 'half-life';

interface HeatmapRenderConfig {
  normalizeMode: NormalizeMode;
  clipPercentile: number;
  rollingWindowSec: number;
  holdMode: HoldMode;
  holdSeconds: number;
  decaySeconds: number;
  decayHalfLifeSec: number;
  decayCurve: DecayCurve;
  binaryMode: boolean;
}

interface HeatmapDebugOptions {
  enabled: boolean;
  showTileBounds: boolean;
  showTileLabels: boolean;
}

// Decoded tile data in memory
interface DecodedTile {
  tile: HeatmapTileMeta;
  matrix: Uint16Array;
  rows: number;
  cols: number;
  side: 'bid' | 'ask';
  hasNonZero: boolean;
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

// Pako (zlib) decompression support
let pakoModule: { inflate: (data: Uint8Array) => Uint8Array } | null = null;
let pakoLoaded = false;

async function loadPako(): Promise<typeof pakoModule> {
  if (pakoLoaded) return pakoModule;
  pakoLoaded = true;

  try {
    pakoModule = await import('pako');
    console.log('[TileDecode] pako module loaded successfully');
  } catch {
    console.info('pako not available - zlib tiles cannot be decompressed');
  }
  return pakoModule;
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
    // Note: algo might be 'zstd' or 'ZSTD' depending on backend
    const algo = tile.compression.algo?.toLowerCase() ?? '';
    console.log('[TileDecode] Compression algo:', tile.compression.algo, '→', algo, 'level:', tile.compression.level);

    if (algo === 'zstd' && tile.compression.level > 0) {
      console.log('[TileDecode] Attempting zstd decompression...');
      const fzstd = await loadFzstd();
      if (fzstd) {
        try {
          const decompressed = fzstd.decompress(bytes);
          console.log('[TileDecode] zstd decompressed:', decompressed.length, 'bytes, byteOffset:', decompressed.byteOffset);
          // Slice buffer to get only the decompressed bytes
          const arrayBuffer = decompressed.buffer.slice(
            decompressed.byteOffset,
            decompressed.byteOffset + decompressed.byteLength
          );
          return new Uint16Array(arrayBuffer);
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

    // If compressed with zlib, use pako to decompress
    if (algo === 'zlib' && tile.compression.level > 0) {
      console.log('[TileDecode] Attempting zlib decompression with pako...');
      const pako = await loadPako();
      if (pako) {
        try {
          const decompressed = pako.inflate(bytes);
          console.log('[TileDecode] zlib decompressed:', decompressed.length, 'bytes, byteOffset:', decompressed.byteOffset);

          // IMPORTANT: Create Uint16Array correctly from decompressed data
          // decompressed.buffer might be a larger shared buffer, so we need to
          // slice it to get just the decompressed bytes
          const arrayBuffer = decompressed.buffer.slice(
            decompressed.byteOffset,
            decompressed.byteOffset + decompressed.byteLength
          );
          const result = new Uint16Array(arrayBuffer);

          // Check for non-zero values
          let nonZeroCount = 0;
          let maxValue = 0;
          for (let i = 0; i < result.length; i++) {
            if (result[i] > 0) nonZeroCount++;
            if (result[i] > maxValue) maxValue = result[i];
          }
          console.log('[TileDecode] Tile stats:', { nonZeroCount, maxValue, totalCells: result.length });
          return result;
        } catch (e) {
          console.warn('[TileDecode] zlib decompression failed:', e);
        }
      } else {
        console.warn('[TileDecode] pako module not available');
      }
      console.warn('Compressed tile cannot be decoded - pako not available');
      return null;
    }

    // No compression - parse directly as uint16
    if (algo === 'none' || algo === '' || tile.compression.level === 0) {
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
function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = (sorted.length - 1) * p;
  const lower = Math.floor(idx);
  const upper = Math.ceil(idx);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (idx - lower);
}

function normalizeDepth(depth: number, clipValue: number, mode: NormalizeMode): number {
  if (depth <= 0 || clipValue <= 0) return 0;
  const clipped = Math.min(depth, clipValue);
  const ratio = clipped / clipValue;

  if (mode === 'sqrt') {
    return Math.sqrt(ratio);
  }
  if (mode === 'linear') {
    return ratio;
  }
  // log1p default
  return Math.log1p(clipped) / Math.log1p(clipValue);
}

function applyGamma(intensity: number, gamma: number): number {
  return Math.min(1, Math.pow(intensity, gamma));
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
  renderConfig,
  debugOptions,
}: HeatmapRendererProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const offscreenRef = useRef<HTMLCanvasElement | null>(null);
  const [decodedTiles, setDecodedTiles] = useState<DecodedTile[]>([]);
  const [loading, setLoading] = useState(true);
  const decodeCacheRef = useRef<Map<string, Uint16Array>>(new Map());
  const carryOverCache = useRef<{
    side: 'bid' | 'ask';
    rangeKey: string;
    values: Float32Array;
    seenTs: Float64Array;
  } | null>(null);

  const config: HeatmapRenderConfig = {
    normalizeMode: renderConfig?.normalizeMode ?? 'log1p',
    clipPercentile: renderConfig?.clipPercentile ?? 0.99,
    rollingWindowSec: renderConfig?.rollingWindowSec ?? 0,
    holdMode: renderConfig?.holdMode ?? 'hold',
    holdSeconds: renderConfig?.holdSeconds ?? 5,
    decaySeconds: renderConfig?.decaySeconds ?? 10,
    decayHalfLifeSec: renderConfig?.decayHalfLifeSec ?? 8,
    decayCurve: renderConfig?.decayCurve ?? 'half-life',
    binaryMode: renderConfig?.binaryMode ?? false,
  };

  const debugConfig: HeatmapDebugOptions = {
    enabled: debugOptions?.enabled ?? false,
    showTileBounds: debugOptions?.showTileBounds ?? false,
    showTileLabels: debugOptions?.showTileLabels ?? false,
  };

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

        const cacheKey = `${tile.tile_id}:${tile.checksum?.value ?? tile.payload_b64?.length}:${side}`;
        let matrix = decodeCacheRef.current.get(cacheKey) || null;
        if (!matrix) {
          matrix = await decodeTilePayload(tile);
          if (matrix) {
            decodeCacheRef.current.set(cacheKey, matrix);
          }
        }
        if (matrix) {
          let hasNonZero = false;
          for (let i = 0; i < matrix.length; i++) {
            if (matrix[i] > 0) {
              hasNonZero = true;
              break;
            }
          }
          decoded.push({
            tile,
            matrix,
            rows: tile.rows,
            cols: tile.cols,
            side,
            hasNonZero,
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

  const normalization = useMemo(() => {
    const cutoffMs = config.rollingWindowSec > 0
      ? windowEnd - config.rollingWindowSec * 1000
      : Number.NEGATIVE_INFINITY;
    const samplesBySide: Record<'bid' | 'ask', number[]> = { bid: [], ask: [] };
    const fallbackClipBySide: Record<'bid' | 'ask', number[]> = { bid: [], ask: [] };
    const maxSamples = 120000;
    const strideTarget = 8000;

    for (const { tile, matrix, side } of decodedTiles) {
      if (tile.t_end < cutoffMs) continue;
      const tileClipValue = tile.encoding.clip_value || 10000;
      fallbackClipBySide[side].push(tileClipValue);
      if (samplesBySide[side].length >= maxSamples) continue;

      const stride = Math.max(1, Math.floor(matrix.length / strideTarget));
      for (let i = 0; i < matrix.length; i += stride) {
        const raw = matrix[i];
        if (raw === 0) continue;
        const depth = decodeDepth(raw, tileClipValue, tile.encoding.scale);
        if (depth > 0) {
          samplesBySide[side].push(depth);
          if (samplesBySide[side].length >= maxSamples) break;
        }
      }
    }

    const buildStats = (side: 'bid' | 'ask') => {
      const samples = samplesBySide[side];
      const fallbackClip = fallbackClipBySide[side].length > 0
        ? Math.max(...fallbackClipBySide[side])
        : 1;
      const clip = samples.length > 0
        ? percentile(samples, config.clipPercentile)
        : fallbackClip;
      return {
        clip: Math.max(1, clip || fallbackClip),
        p90: samples.length > 0 ? percentile(samples, 0.9) : 0,
        p99: samples.length > 0 ? percentile(samples, 0.99) : 0,
        max: samples.length > 0 ? Math.max(...samples) : 0,
        sampleCount: samples.length,
        cutoffMs: cutoffMs === Number.NEGATIVE_INFINITY ? null : cutoffMs,
      };
    };

    return {
      bid: buildStats('bid'),
      ask: buildStats('ask'),
    };
  }, [decodedTiles, windowEnd, config.clipPercentile, config.rollingWindowSec]);

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

    const offscreen = offscreenRef.current || document.createElement('canvas');
    offscreenRef.current = offscreen;
    if (offscreen.width !== width) offscreen.width = width;
    if (offscreen.height !== height) offscreen.height = height;

    const ctx = offscreen.getContext('2d');
    if (!ctx) {
      console.warn('[HeatmapRender] No canvas context!');
      return;
    }

    // Clear canvas with dark background
    ctx.fillStyle = '#1f2937'; // gray-800
    ctx.fillRect(0, 0, width, height);

    carryOverCache.current = null;

    if (decodedTiles.length === 0) {
      // No tiles - show placeholder
      console.log('[HeatmapRender] No decoded tiles, showing placeholder');
      renderPlaceholder(ctx, width, height, 'Waiting for data...');
      const outputCtx = canvas.getContext('2d');
      if (outputCtx) {
        outputCtx.clearRect(0, 0, width, height);
        outputCtx.drawImage(offscreen, 0, 0);
      }
      return;
    }

    const timeRange = windowEnd - windowStart;
    const priceRange = priceMax - priceMin;
    console.log('[HeatmapRender] Ranges:', { timeRange, priceRange });

    if (timeRange <= 0 || priceRange <= 0) {
      console.warn('[HeatmapRender] Invalid ranges, showing placeholder');
      renderPlaceholder(ctx, width, height, 'Invalid window');
      const outputCtx = canvas.getContext('2d');
      if (outputCtx) {
        outputCtx.clearRect(0, 0, width, height);
        outputCtx.drawImage(offscreen, 0, 0);
      }
      return;
    }

    const hasAnyDepth = decodedTiles.some((tile) => tile.hasNonZero);
    if (!hasAnyDepth) {
      renderPlaceholder(ctx, width, height, 'No depth data');
      const outputCtx = canvas.getContext('2d');
      if (outputCtx) {
        outputCtx.clearRect(0, 0, width, height);
        outputCtx.drawImage(offscreen, 0, 0);
      }
      return;
    }

    const clipBySide = {
      bid: normalization.bid.clip,
      ask: normalization.ask.clip,
    };

    // Enable additive blending for smoother overlapping
    ctx.globalCompositeOperation = 'lighter';

    const sortedTiles = [...decodedTiles].sort((a, b) => {
      if (a.side !== b.side) return a.side === 'bid' ? -1 : 1;
      return a.tile.t_start - b.tile.t_start;
    });

    // Render each tile
    let tileIndex = 0;
    for (const { tile, matrix, rows, cols, side } of sortedTiles) {
      // Per-tile clipValue for decoding (data was encoded with this value)
      const tileClipValue = tile.encoding.clip_value || 10000;
      const scale = tile.encoding.scale;
      const sideClip = clipBySide[side];

      // Calculate tile position in canvas
      const tileX = ((tile.t_start - windowStart) / timeRange) * width;
      const tileWidth = ((tile.t_end - tile.t_start) / timeRange) * width;

      const tilePriceMin = tile.price_min;
      const tilePriceMax = tile.price_max;
      const tileY = height - ((tilePriceMax - priceMin) / priceRange) * height;
      const tileHeight = ((tilePriceMax - tilePriceMin) / priceRange) * height;

      // Calculate cell dimensions (moved up for logging)
      const cellWidth = tileWidth / cols;
      const cellHeight = tileHeight / rows;

      // Log first few tiles for debugging
      if (tileIndex < 3) {
        // Count non-zero values and find sample positions
        let nonZeroCount = 0;
        const samplePositions: string[] = [];
        for (let r = 0; r < rows && samplePositions.length < 5; r++) {
          for (let c = 0; c < cols && samplePositions.length < 5; c++) {
            if (matrix[r * cols + c] > 0) {
              nonZeroCount++;
              if (samplePositions.length < 5) {
                samplePositions.push(`[row=${r},col=${c}]=>${matrix[r * cols + c]}`);
              }
            }
          }
        }
        // Continue counting rest
        for (let i = rows * cols - 1; i >= 0; i--) {
          if (matrix[i] > 0) nonZeroCount++;
        }
        // Subtract double-counted first 5
        nonZeroCount = Math.max(0, nonZeroCount - samplePositions.length);

        console.log(`[HeatmapRender] Tile ${tileIndex} (${side}):`, {
          position: { tileX: tileX.toFixed(1), tileY: tileY.toFixed(1), tileWidth: tileWidth.toFixed(1), tileHeight: tileHeight.toFixed(1) },
          cells: { cellWidth: cellWidth.toFixed(2), cellHeight: cellHeight.toFixed(2), rows, cols },
          tileTime: { t_start: tile.t_start, t_end: tile.t_end },
          tilePrice: { tilePriceMin, tilePriceMax },
          windowPrice: { priceMin, priceMax },
          encoding: { scale, tileClipValue, sideClip, mode: config.normalizeMode },
          nonZeroCount,
          samplePositions,
        });
      }
      tileIndex++;

      // v5.40: Color based on side, not midPrice
      // Bid = green (buy side liquidity)
      // Ask = red (sell side liquidity)
      const baseColor = side === 'bid'
        ? { r: 34, g: 197, b: 94 }   // green-500
        : { r: 239, g: 68, b: 68 };  // red-500

      // Render each cell with persistence model
      const rangeKey = `${tilePriceMin}-${tilePriceMax}-${rows}-${cols}`;
      let carryOver: Float32Array | null = null;
      let carrySeen: Float64Array | null = null;
      if (config.holdMode !== 'off' && carryOverCache.current?.side === side && carryOverCache.current?.rangeKey === rangeKey) {
        carryOver = carryOverCache.current?.values || null;
        carrySeen = carryOverCache.current?.seenTs || null;
      }

      const lastDepthByRow = carryOver ? new Float32Array(carryOver) : new Float32Array(rows);
      const lastSeenByRow = carrySeen ? new Float64Array(carrySeen) : new Float64Array(rows);
      const holdMs = Math.max(0, config.holdSeconds) * 1000;
      const decayMs = Math.max(0, config.decaySeconds) * 1000;
      const halfLifeMs = Math.max(1, config.decayHalfLifeSec) * 1000;

      const decayFactor = (elapsedMs: number) => {
        if (decayMs <= 0) return 0;
        if (elapsedMs >= decayMs) return 0;
        if (config.decayCurve === 'linear') {
          return Math.max(0, 1 - elapsedMs / decayMs);
        }
        return Math.exp(-Math.LN2 * (elapsedMs / halfLifeMs));
      };

      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const idx = row * cols + col;
          const value = matrix[idx];
          const ts = tile.t_start + col * tile.lod_ms;
          let depth = 0;

          if (value > 0) {
            depth = decodeDepth(value, tileClipValue, scale);
            lastDepthByRow[row] = depth;
            lastSeenByRow[row] = ts;
          } else if (config.holdMode !== 'off') {
            const lastSeen = lastSeenByRow[row];
            if (lastSeen > 0) {
              const elapsed = ts - lastSeen;
              if (config.holdMode === 'hold') {
                if (elapsed <= holdMs) {
                  depth = lastDepthByRow[row];
                } else {
                  const decayElapsed = elapsed - holdMs;
                  const factor = decayFactor(decayElapsed);
                  depth = lastDepthByRow[row] * factor;
                  if (factor <= 0) {
                    lastDepthByRow[row] = 0;
                    lastSeenByRow[row] = 0;
                  }
                }
              } else if (config.holdMode === 'decay') {
                const factor = decayFactor(elapsed);
                depth = lastDepthByRow[row] * factor;
                if (factor <= 0) {
                  lastDepthByRow[row] = 0;
                  lastSeenByRow[row] = 0;
                }
              }
            }
          }

          if (depth <= 0) continue;

          const intensityBase = config.binaryMode
            ? 1
            : normalizeDepth(depth, sideClip, config.normalizeMode);
          const intensity = applyGamma(intensityBase, 0.7);

          if (intensity < 0.005) continue;

          const x = tileX + col * cellWidth;
          const y = tileY + (rows - row - 1) * cellHeight;

          const alpha = Math.min(0.95, intensity * 0.9);
          ctx.fillStyle = `rgba(${baseColor.r}, ${baseColor.g}, ${baseColor.b}, ${alpha})`;

          ctx.fillRect(x, y, cellWidth, cellHeight);
        }
      }

      if (config.holdMode !== 'off') {
        carryOverCache.current = {
          side,
          rangeKey,
          values: lastDepthByRow,
          seenTs: lastSeenByRow,
        };
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

    if (debugConfig.enabled) {
      const sampleTile = sortedTiles[0];
      const sampleCellWidth = sampleTile
        ? (((sampleTile.tile.t_end - sampleTile.tile.t_start) / timeRange) * width) / sampleTile.cols
        : 0;
      const sampleCellHeight = sampleTile
        ? (((sampleTile.tile.price_max - sampleTile.tile.price_min) / priceRange) * height) / sampleTile.rows
        : 0;
      const windowDurationSec = timeRange / 1000;
      const lodMs = sampleTile?.tile.lod_ms ?? 0;
      const tileMs = sampleTile?.tile.tile_ms ?? 0;

      ctx.save();
      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = 'rgba(17, 24, 39, 0.85)';
      ctx.fillRect(8, 8, 300, 124);
      ctx.fillStyle = '#e5e7eb';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      const lines = [
        `window: ${windowDurationSec.toFixed(1)}s (${windowStart}..${windowEnd})`,
        `price: ${priceMin.toFixed(4)} -> ${priceMax.toFixed(4)}`,
        `tiles: ${sortedTiles.length} | lod: ${lodMs}ms | tile: ${tileMs}ms`,
        `cell: ${sampleCellWidth.toFixed(2)}x${sampleCellHeight.toFixed(2)} px`,
        `clip(bid/ask): ${clipBySide.bid.toFixed(2)} / ${clipBySide.ask.toFixed(2)}`,
        `mode: ${config.normalizeMode} | pctl: ${config.clipPercentile}`,
        `roll: ${config.rollingWindowSec}s | hold: ${config.holdMode}`,
        `persist: h${config.holdSeconds}s d${config.decaySeconds}s ${config.decayCurve}`,
      ];
      lines.forEach((line, idx) => {
        ctx.fillText(line, 14, 14 + idx * 14);
      });

      if (debugConfig.showTileBounds) {
        for (const { tile, rows, cols, side } of sortedTiles) {
          const tileX = ((tile.t_start - windowStart) / timeRange) * width;
          const tileWidth = ((tile.t_end - tile.t_start) / timeRange) * width;
          const tileY = height - ((tile.price_max - priceMin) / priceRange) * height;
          const tileHeight = ((tile.price_max - tile.price_min) / priceRange) * height;

          ctx.strokeStyle = side === 'bid'
            ? 'rgba(34, 197, 94, 0.6)'
            : 'rgba(239, 68, 68, 0.6)';
          ctx.lineWidth = 1;
          ctx.strokeRect(tileX, tileY, tileWidth, tileHeight);

          if (debugConfig.showTileLabels) {
            ctx.fillStyle = 'rgba(243, 244, 246, 0.9)';
            ctx.fillText(
              `${side} ${tile.t_start}..${tile.t_end} (${rows}x${cols})`,
              tileX + 4,
              tileY + 4
            );
          }
        }
      }
      ctx.restore();
    }

    const outputCtx = canvas.getContext('2d');
    if (outputCtx) {
      outputCtx.clearRect(0, 0, width, height);
      outputCtx.drawImage(offscreen, 0, 0);
    }

  }, [
    decodedTiles,
    normalization,
    width,
    height,
    windowStart,
    windowEnd,
    priceMin,
    priceMax,
    tickSize,
    config.normalizeMode,
    config.clipPercentile,
    config.rollingWindowSec,
    config.holdMode,
    config.holdSeconds,
    config.decaySeconds,
    config.decayHalfLifeSec,
    config.decayCurve,
    config.binaryMode,
    debugConfig.enabled,
    debugConfig.showTileBounds,
    debugConfig.showTileLabels,
  ]);

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
  height: number,
  message: string
) {
  // Draw subtle gradient background
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, '#374151');  // gray-700
  gradient.addColorStop(0.5, '#1f2937'); // gray-800
  gradient.addColorStop(1, '#374151');  // gray-700
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  // Draw message text
  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
  ctx.fillRect(width / 2 - 90, height / 2 - 15, 180, 30);
  ctx.fillStyle = '#9ca3af';
  ctx.font = '12px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(message, width / 2, height / 2);
}

export default HeatmapRenderer;
