"""
Dual-Track Heatmap Tile System (v5.18)

Provides two tracks for heatmap tile delivery:
1. **Warm Track**: Pre-computed tiles from cache with freshness metadata
2. **Cold Track**: On-demand generation with staleness indication

Features:
- Cache hit/miss/stale tracking
- Staleness detection (tiles older than data)
- Priority-based precomputation queuing
- UI metadata for tile source indication

UI Labels:
- "预热缓存" (Warm Cache) - Fresh pre-computed tiles
- "按需生成" (On-Demand) - Generated on request
- "陈旧数据" (Stale) - Cached but data has updated since

Usage:
    manager = DualTrackTileManager(db_config=DB_CONFIG)

    # Get tiles with source tracking
    tiles, metadata = manager.get_tiles_with_metadata(
        token_id="abc",
        from_ts=1000000,
        to_ts=2000000,
        lod_ms=250
    )

"冷热分离，各取所需"
"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import logging

from .tile_generator import HeatmapTileGenerator, HeatmapTile, TileBand


logger = logging.getLogger(__name__)


class TileSource(str, Enum):
    """Source of heatmap tile"""
    PRECOMPUTED = "PRECOMPUTED"   # From warm cache, fresh
    ON_DEMAND = "ON_DEMAND"       # Generated on request
    STALE = "STALE"               # From cache but data has updated
    MISS = "MISS"                 # Cache miss, no tile available


@dataclass
class TileMetadata:
    """Metadata about a tile's source and freshness"""
    tile_id: str
    source: TileSource
    cached_at: Optional[int]  # When tile was cached (ms)
    generated_at: int  # When tile was generated (ms)
    data_updated_at: Optional[int]  # Latest data timestamp in range
    staleness_ms: int  # How stale the tile is (0 = fresh)
    ui_label: str
    ui_emoji: str

    def to_dict(self) -> dict:
        return {
            "tile_id": self.tile_id,
            "source": self.source.value,
            "cached_at": self.cached_at,
            "generated_at": self.generated_at,
            "data_updated_at": self.data_updated_at,
            "staleness_ms": self.staleness_ms,
            "ui_label": self.ui_label,
            "ui_emoji": self.ui_emoji,
            "is_fresh": self.staleness_ms < 60000,  # < 1 minute
        }


@dataclass
class TileRequestResult:
    """Result of a tile request with metadata"""
    tiles: List[HeatmapTile]
    metadata: List[TileMetadata]
    total_requested: int
    cache_hits: int
    cache_misses: int
    stale_count: int
    generated_count: int
    request_time_ms: int

    def to_dict(self) -> dict:
        return {
            "tile_count": len(self.tiles),
            "total_requested": self.total_requested,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "stale_count": self.stale_count,
            "generated_count": self.generated_count,
            "request_time_ms": self.request_time_ms,
            "hit_rate": self.cache_hits / max(1, self.total_requested),
            "metadata": [m.to_dict() for m in self.metadata],
        }


# UI labels for tile sources
SOURCE_LABELS = {
    TileSource.PRECOMPUTED: ("预热缓存", "🟢"),
    TileSource.ON_DEMAND: ("按需生成", "🟡"),
    TileSource.STALE: ("陈旧数据", "🟠"),
    TileSource.MISS: ("数据缺失", "🔴"),
}

# Staleness thresholds
STALE_THRESHOLD_MS = 60000  # 1 minute - tiles older than this are considered stale


class TileCacheTracker:
    """
    Tracks tile cache performance metrics.

    Provides:
    - Hit/miss/stale counts
    - Per-token statistics
    - Rolling window metrics
    """

    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self._lock = threading.Lock()

        # Global stats
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "stale_hits": 0,
            "on_demand_generated": 0,
        }

        # Per-token stats
        self._token_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"requests": 0, "hits": 0, "misses": 0, "stale": 0}
        )

        # Recent requests for rolling window
        self._recent: List[Tuple[int, str, TileSource]] = []

    def record_request(
        self,
        token_id: str,
        source: TileSource,
        tile_count: int = 1
    ):
        """Record a tile request"""
        now = int(time.time() * 1000)

        with self._lock:
            self.stats["total_requests"] += tile_count

            if source == TileSource.PRECOMPUTED:
                self.stats["cache_hits"] += tile_count
                self._token_stats[token_id]["hits"] += tile_count
            elif source == TileSource.STALE:
                self.stats["stale_hits"] += tile_count
                self._token_stats[token_id]["stale"] += tile_count
            elif source == TileSource.ON_DEMAND:
                self.stats["on_demand_generated"] += tile_count
                self.stats["cache_misses"] += tile_count
                self._token_stats[token_id]["misses"] += tile_count
            else:  # MISS
                self.stats["cache_misses"] += tile_count
                self._token_stats[token_id]["misses"] += tile_count

            self._token_stats[token_id]["requests"] += tile_count

            # Add to recent window
            self._recent.append((now, token_id, source))
            if len(self._recent) > self.window_size:
                self._recent = self._recent[-self.window_size:]

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        with self._lock:
            total = max(1, self.stats["total_requests"])
            return {
                **self.stats,
                "hit_rate": self.stats["cache_hits"] / total,
                "stale_rate": self.stats["stale_hits"] / total,
                "miss_rate": self.stats["cache_misses"] / total,
                "tokens_tracked": len(self._token_stats),
            }

    def get_token_stats(self, token_id: str) -> Dict[str, Any]:
        """Get stats for a specific token"""
        with self._lock:
            stats = self._token_stats.get(token_id, {})
            if not stats:
                return {"requests": 0, "hits": 0, "misses": 0, "stale": 0, "hit_rate": 0}

            total = max(1, stats.get("requests", 0))
            return {
                **stats,
                "hit_rate": stats.get("hits", 0) / total,
            }

    def get_hot_tokens(self, limit: int = 10) -> List[Dict]:
        """Get tokens with most requests"""
        with self._lock:
            sorted_tokens = sorted(
                self._token_stats.items(),
                key=lambda x: x[1].get("requests", 0),
                reverse=True
            )
            return [
                {"token_id": t[0], **t[1]}
                for t in sorted_tokens[:limit]
            ]


class DualTrackTileManager:
    """
    Dual-track tile management system.

    Track 1 (Warm): Pre-computed tiles from cache
    Track 2 (Cold): On-demand tile generation

    Features:
    - Automatic staleness detection
    - Cache performance tracking
    - Priority queuing for precomputation
    """

    def __init__(
        self,
        db_config: Dict[str, Any] = None,
        stale_threshold_ms: int = STALE_THRESHOLD_MS,
        enable_on_demand: bool = True,
    ):
        self.db_config = db_config or {}
        self.stale_threshold_ms = stale_threshold_ms
        self.enable_on_demand = enable_on_demand

        self._generator = HeatmapTileGenerator(db_config=db_config)
        self._cache_tracker = TileCacheTracker()
        self._db_conn = None

        # Priority queue for precomputation (token_id -> priority score)
        self._precompute_queue: Dict[str, float] = {}
        self._queue_lock = threading.Lock()

    def _get_conn(self):
        """Get database connection"""
        if self._db_conn and not self._db_conn.closed:
            return self._db_conn

        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            self._db_conn = psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
            return self._db_conn
        except Exception:
            return None

    def get_tiles_with_metadata(
        self,
        token_id: str,
        from_ts: int,
        to_ts: int,
        lod_ms: int = 250,
        tile_ms: int = 10000,
        band: TileBand = TileBand.FULL,
    ) -> TileRequestResult:
        """
        Get tiles with full source metadata.

        Returns tiles from cache if available, otherwise generates on-demand.
        Includes staleness detection and tracking.
        """
        start_time = time.time()
        now = int(time.time() * 1000)

        tiles: List[HeatmapTile] = []
        metadata: List[TileMetadata] = []
        cache_hits = 0
        cache_misses = 0
        stale_count = 0
        generated_count = 0

        # Calculate expected tile boundaries
        t_start = (from_ts // tile_ms) * tile_ms
        expected_tiles = []
        while t_start < to_ts:
            expected_tiles.append(t_start)
            t_start += tile_ms

        total_requested = len(expected_tiles)

        # Check cache for each expected tile
        conn = self._get_conn()
        cached_tiles = {}

        if conn:
            try:
                with conn.cursor() as cur:
                    # Get cached tiles with creation timestamp
                    cur.execute("""
                        SELECT tile_id, t_start, t_end, created_at,
                               lod_ms, tile_ms, band, tick_size, price_min, price_max,
                               rows, cols, encoding_dtype, encoding_layout, encoding_scale,
                               clip_pctl, clip_value, compression_algo, compression_level,
                               payload, checksum_algo, checksum_value
                        FROM heatmap_tiles
                        WHERE token_id = %s
                        AND lod_ms = %s
                        AND band = %s
                        AND t_start >= %s
                        AND t_end <= %s
                        ORDER BY t_start ASC
                    """, (token_id, lod_ms, band.value, from_ts, to_ts))

                    for row in cur.fetchall():
                        cached_tiles[row['t_start']] = row

                    # Get latest data timestamp in range for staleness check
                    cur.execute("""
                        SELECT MAX(bucket_ts) as latest_data
                        FROM book_bins
                        WHERE token_id = %s
                        AND bucket_ts BETWEEN to_timestamp(%s / 1000.0)
                                          AND to_timestamp(%s / 1000.0)
                    """, (token_id, from_ts, to_ts))
                    latest_row = cur.fetchone()
                    latest_data_ts = int(latest_row['latest_data'].timestamp() * 1000) if latest_row and latest_row['latest_data'] else None

            except Exception as e:
                logger.warning(f"Failed to check tile cache: {e}")

        # Process each expected tile
        for t_start_expected in expected_tiles:
            if t_start_expected in cached_tiles:
                row = cached_tiles[t_start_expected]
                cached_at = int(row['created_at'].timestamp() * 1000) if row['created_at'] else now

                # Check staleness
                staleness_ms = 0
                source = TileSource.PRECOMPUTED

                if latest_data_ts and latest_data_ts > cached_at:
                    staleness_ms = latest_data_ts - cached_at
                    if staleness_ms > self.stale_threshold_ms:
                        source = TileSource.STALE
                        stale_count += 1
                    else:
                        cache_hits += 1
                else:
                    cache_hits += 1

                # Create tile object
                tile = HeatmapTile(
                    tile_id=row['tile_id'],
                    token_id=token_id,
                    lod_ms=row['lod_ms'],
                    tile_ms=row['tile_ms'],
                    band=TileBand(row['band']),
                    t_start=row['t_start'],
                    t_end=row['t_end'],
                    tick_size=float(row['tick_size']),
                    price_min=float(row['price_min']),
                    price_max=float(row['price_max']),
                    rows=row['rows'],
                    cols=row['cols'],
                    encoding_dtype=row['encoding_dtype'],
                    encoding_layout=row['encoding_layout'],
                    encoding_scale=row['encoding_scale'],
                    clip_pctl=float(row['clip_pctl']),
                    clip_value=float(row['clip_value']) if row['clip_value'] else 0,
                    compression_algo=row['compression_algo'],
                    compression_level=row['compression_level'],
                    payload=bytes(row['payload']),
                    checksum_algo=row['checksum_algo'],
                    checksum_value=row['checksum_value'],
                )

                tiles.append(tile)

                label, emoji = SOURCE_LABELS[source]
                metadata.append(TileMetadata(
                    tile_id=tile.tile_id,
                    source=source,
                    cached_at=cached_at,
                    generated_at=cached_at,
                    data_updated_at=latest_data_ts,
                    staleness_ms=staleness_ms,
                    ui_label=label,
                    ui_emoji=emoji,
                ))

                self._cache_tracker.record_request(token_id, source)

            else:
                # Cache miss - generate on demand if enabled
                cache_misses += 1

                if self.enable_on_demand:
                    t_end = t_start_expected + tile_ms
                    generated = self._generator.generate_tile(
                        token_id=token_id,
                        t_start=t_start_expected,
                        t_end=t_end,
                        lod_ms=lod_ms,
                        tile_ms=tile_ms,
                        band=band,
                    )

                    if generated:
                        # Cache it for future
                        self._generator.save_tile(generated)
                        tiles.append(generated)
                        generated_count += 1

                        label, emoji = SOURCE_LABELS[TileSource.ON_DEMAND]
                        metadata.append(TileMetadata(
                            tile_id=generated.tile_id,
                            source=TileSource.ON_DEMAND,
                            cached_at=now,
                            generated_at=now,
                            data_updated_at=latest_data_ts if latest_data_ts else None,
                            staleness_ms=0,
                            ui_label=label,
                            ui_emoji=emoji,
                        ))

                        self._cache_tracker.record_request(token_id, TileSource.ON_DEMAND)
                    else:
                        # No data available
                        label, emoji = SOURCE_LABELS[TileSource.MISS]
                        metadata.append(TileMetadata(
                            tile_id=f"{token_id}:{lod_ms}:{t_start_expected}:{band.value}",
                            source=TileSource.MISS,
                            cached_at=None,
                            generated_at=now,
                            data_updated_at=None,
                            staleness_ms=0,
                            ui_label=label,
                            ui_emoji=emoji,
                        ))
                        self._cache_tracker.record_request(token_id, TileSource.MISS)
                else:
                    self._cache_tracker.record_request(token_id, TileSource.MISS)

        # Queue token for precomputation if many misses
        if cache_misses > total_requested * 0.3:  # >30% miss rate
            self._queue_for_precompute(token_id, priority=cache_misses)

        request_time_ms = int((time.time() - start_time) * 1000)

        return TileRequestResult(
            tiles=tiles,
            metadata=metadata,
            total_requested=total_requested,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            stale_count=stale_count,
            generated_count=generated_count,
            request_time_ms=request_time_ms,
        )

    def _queue_for_precompute(self, token_id: str, priority: float):
        """Queue a token for precomputation"""
        with self._queue_lock:
            current = self._precompute_queue.get(token_id, 0)
            self._precompute_queue[token_id] = max(current, priority)

    def get_precompute_queue(self, limit: int = 20) -> List[Tuple[str, float]]:
        """Get tokens queued for precomputation, sorted by priority"""
        with self._queue_lock:
            sorted_queue = sorted(
                self._precompute_queue.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return sorted_queue[:limit]

    def clear_precompute_queue(self, token_ids: List[str] = None):
        """Clear precomputation queue"""
        with self._queue_lock:
            if token_ids:
                for tid in token_ids:
                    self._precompute_queue.pop(tid, None)
            else:
                self._precompute_queue.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        return self._cache_tracker.get_stats()

    def get_token_stats(self, token_id: str) -> Dict[str, Any]:
        """Get stats for a specific token"""
        return self._cache_tracker.get_token_stats(token_id)

    def get_hot_tokens(self, limit: int = 10) -> List[Dict]:
        """Get most requested tokens"""
        return self._cache_tracker.get_hot_tokens(limit)

    def invalidate_cache(
        self,
        token_id: str,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None
    ) -> int:
        """
        Invalidate cached tiles for a token.

        Args:
            token_id: Token to invalidate
            from_ts: Optional start timestamp
            to_ts: Optional end timestamp

        Returns:
            Number of tiles invalidated
        """
        conn = self._get_conn()
        if not conn:
            return 0

        try:
            with conn.cursor() as cur:
                if from_ts and to_ts:
                    cur.execute("""
                        DELETE FROM heatmap_tiles
                        WHERE token_id = %s
                        AND t_start >= %s AND t_end <= %s
                        RETURNING tile_id
                    """, (token_id, from_ts, to_ts))
                else:
                    cur.execute("""
                        DELETE FROM heatmap_tiles
                        WHERE token_id = %s
                        RETURNING tile_id
                    """, (token_id,))

                deleted = cur.rowcount
                conn.commit()

                logger.info(f"Invalidated {deleted} tiles for {token_id}")
                return deleted

        except Exception as e:
            logger.error(f"Failed to invalidate cache: {e}")
            conn.rollback()
            return 0


# Global singleton
_dual_track_manager: Optional[DualTrackTileManager] = None


def get_dual_track_manager(db_config: Dict[str, Any] = None) -> DualTrackTileManager:
    """Get or create global dual-track manager"""
    global _dual_track_manager
    if _dual_track_manager is None:
        _dual_track_manager = DualTrackTileManager(db_config=db_config)
    return _dual_track_manager
