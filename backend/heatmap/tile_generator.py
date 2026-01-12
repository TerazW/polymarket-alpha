"""
Heatmap Tile Generator - Generates compressed heatmap tiles from book_bins data

Tile Structure:
- Each tile covers a time window (tile_ms: 5000, 10000, or 15000 ms)
- Each column represents a time bucket (lod_ms: 250, 1000, or 5000 ms)
- Each row represents a price level
- Values are order book sizes encoded as uint16

Encoding:
- log1p scaling: value = log1p(size) / log1p(clip_value) * 65535
- Clipping at 95th percentile to handle outliers
- Row-major layout (prices x time)

Compression:
- zstd level 3 for good compression/speed tradeoff
- xxHash64 checksum for integrity

Usage:
    generator = HeatmapTileGenerator(db_conn)

    # Generate tiles for a time range
    tiles = generator.generate_tiles(
        token_id="abc123",
        from_ts=1704067200000,
        to_ts=1704070800000,
        lod_ms=250,
        tile_ms=10000,
        band=TileBand.FULL
    )

    # Get or generate (with caching)
    tiles = generator.get_or_generate(...)
"""

import numpy as np
import hashlib
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
import json

# Optional imports - graceful degradation if not available
try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
    import zlib

try:
    import xxhash
    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False


class TileBand(str, Enum):
    """Price band selection for tiles"""
    FULL = "FULL"           # All prices
    BEST_5 = "BEST_5"       # Best 5 price levels
    BEST_10 = "BEST_10"     # Best 10 price levels
    BEST_20 = "BEST_20"     # Best 20 price levels


@dataclass
class HeatmapTile:
    """Generated heatmap tile"""
    tile_id: str
    token_id: str
    lod_ms: int
    tile_ms: int
    band: TileBand
    t_start: int
    t_end: int
    tick_size: float
    price_min: float
    price_max: float
    rows: int
    cols: int
    encoding_dtype: str
    encoding_layout: str
    encoding_scale: str
    clip_pctl: float
    clip_value: float
    compression_algo: str
    compression_level: int
    payload: bytes
    checksum_algo: str
    checksum_value: str


class HeatmapTileGenerator:
    """
    Generates heatmap tiles from book_bins data.

    Supports three LOD levels:
    - 250ms: High resolution for detailed analysis
    - 1000ms: Medium resolution for overview
    - 5000ms: Low resolution for long-range view
    """

    # Default configuration
    DEFAULT_CLIP_PCTL = 0.95
    DEFAULT_COMPRESSION_LEVEL = 3

    def __init__(self, db_conn=None, db_config: Dict = None):
        """
        Initialize generator.

        Args:
            db_conn: Existing database connection
            db_config: Database config dict (used if db_conn is None)
        """
        import os
        self._db_conn = db_conn
        self._db_config = db_config or {
            'host': os.getenv('DB_HOST', '127.0.0.1'),
            'port': int(os.getenv('DB_PORT', '5432')),
            'database': os.getenv('DB_NAME', 'belief_reaction'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'postgres')
        }

    def _get_conn(self):
        """Get database connection"""
        if self._db_conn and not self._db_conn.closed:
            return self._db_conn

        import psycopg2
        from psycopg2.extras import RealDictCursor
        self._db_conn = psycopg2.connect(**self._db_config, cursor_factory=RealDictCursor)
        return self._db_conn

    def _fetch_book_data(
        self,
        token_id: str,
        from_ts: int,
        to_ts: int,
        lod_ms: int,
        side: str = None
    ) -> List[Dict]:
        """
        Fetch book_bins data for tile generation.

        Args:
            token_id: Token ID
            from_ts: Start timestamp (ms)
            to_ts: End timestamp (ms)
            lod_ms: Level of detail (250, 1000, 5000)
            side: Optional filter for 'bid' or 'ask'

        Returns:
            List of {bucket_ts, price, size, side} dicts
        """
        print(f"[TILE_DEBUG] _fetch_book_data: token={token_id[:20]}..., from={from_ts}, to={to_ts}, lod={lod_ms}, side={side}")
        conn = self._get_conn()

        # Choose table based on LOD
        if lod_ms <= 250:
            table = "book_bins"
            time_bucket = "bucket_ts"
        elif lod_ms <= 1000:
            table = "book_bins_1s"
            time_bucket = "bucket_ts_1s"
        else:
            table = "book_bins_1m"
            time_bucket = "bucket_ts_1m"

        # Build query
        side_filter = f"AND side = '{side}'" if side else ""

        query = f"""
            SELECT
                EXTRACT(EPOCH FROM {time_bucket}) * 1000 AS bucket_ts_ms,
                price,
                {'avg_size' if table != 'book_bins' else 'size'} AS size,
                side
            FROM {table}
            WHERE token_id = %s
            AND {time_bucket} BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
            {side_filter}
            ORDER BY {time_bucket} ASC, price ASC
        """

        with conn.cursor() as cur:
            cur.execute(query, (token_id, from_ts, to_ts))
            result = cur.fetchall()
            print(f"[TILE_DEBUG] _fetch_book_data: returned {len(result)} rows")
            return result

    def _get_tick_size(self, token_id: str) -> float:
        """Get tick size for a token"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tick_size FROM markets
                WHERE yes_token_id = %s OR no_token_id = %s
                LIMIT 1
            """, (token_id, token_id))
            row = cur.fetchone()
            return float(row['tick_size']) if row else 0.01

    def _build_matrix(
        self,
        data: List[Dict],
        from_ts: int,
        to_ts: int,
        lod_ms: int,
        price_min: float,
        price_max: float,
        tick_size: float,
        side: str = None
    ) -> Tuple[np.ndarray, List[float], List[int]]:
        """
        Build 2D matrix from book data.

        Args:
            data: List of book data points
            from_ts: Start timestamp
            to_ts: End timestamp
            lod_ms: Time resolution
            price_min: Minimum price
            price_max: Maximum price
            tick_size: Price tick size
            side: Filter by side

        Returns:
            (matrix, price_levels, time_buckets)
        """
        # FIX: Align price_min/price_max to tick boundaries
        # This ensures price_to_row keys match the tick-rounded prices from data lookup
        price_min_aligned = round(round(price_min / tick_size) * tick_size, 4)
        price_max_aligned = round(round(price_max / tick_size) * tick_size, 4)

        # Calculate dimensions using aligned prices
        n_cols = max(1, (to_ts - from_ts) // lod_ms)
        n_prices = max(1, int(round((price_max_aligned - price_min_aligned) / tick_size)) + 1)

        print(f"[MATRIX_DEBUG] Building matrix: from_ts={from_ts}, to_ts={to_ts}, lod_ms={lod_ms}")
        print(f"[MATRIX_DEBUG] Raw price range: {price_min}-{price_max}, aligned: {price_min_aligned}-{price_max_aligned}")
        print(f"[MATRIX_DEBUG] Dimensions: n_prices={n_prices}, n_cols={n_cols}, tick={tick_size}")
        print(f"[MATRIX_DEBUG] Data rows received: {len(data)}, side filter: {side}")

        # Initialize matrix
        matrix = np.zeros((n_prices, n_cols), dtype=np.float64)

        # Build price and time indexes using ALIGNED price_min
        price_to_row = {}
        for i in range(n_prices):
            price = round(price_min_aligned + i * tick_size, 4)
            price_to_row[price] = i

        # Fill matrix with debug counters
        skipped_side = 0
        skipped_col = 0
        skipped_price = 0
        filled = 0

        for row in data:
            if side and row['side'] != side:
                skipped_side += 1
                continue

            ts = int(row['bucket_ts_ms'])
            price = float(row['price'])
            size = float(row['size'] or 0)

            # Map to matrix coordinates
            col = (ts - from_ts) // lod_ms
            if col < 0 or col >= n_cols:
                skipped_col += 1
                # Debug: show first few skipped timestamps
                if skipped_col <= 3:
                    print(f"[MATRIX_DEBUG] Skipped col: ts={ts}, from_ts={from_ts}, col={col}, n_cols={n_cols}")
                continue

            # Round price to tick
            price_rounded = round(round(price / tick_size) * tick_size, 4)
            row_idx = price_to_row.get(price_rounded)
            if row_idx is None:
                skipped_price += 1
                if skipped_price <= 3:
                    print(f"[MATRIX_DEBUG] Skipped price: price={price}, rounded={price_rounded}, not in price_to_row")
                continue

            # Accumulate size (in case of multiple entries per bucket)
            matrix[row_idx, col] = max(matrix[row_idx, col], size)
            filled += 1

        # Debug summary
        nonzero = int(np.count_nonzero(matrix))
        max_val = float(np.max(matrix)) if nonzero > 0 else 0
        print(f"[MATRIX_DEBUG] Result: filled={filled}, skipped_side={skipped_side}, skipped_col={skipped_col}, skipped_price={skipped_price}")
        print(f"[MATRIX_DEBUG] Matrix stats: nonzero={nonzero}, max={max_val}")

        price_levels = [round(price_min_aligned + i * tick_size, 4) for i in range(n_prices)]
        time_buckets = [from_ts + i * lod_ms for i in range(n_cols)]

        return matrix, price_levels, time_buckets

    def _encode_matrix(
        self,
        matrix: np.ndarray,
        clip_pctl: float = 0.95
    ) -> Tuple[bytes, float]:
        """
        Encode matrix as uint16 with log1p scaling.

        Args:
            matrix: 2D numpy array of sizes
            clip_pctl: Percentile for clipping

        Returns:
            (encoded_bytes, clip_value)
        """
        # Calculate clip value from non-zero values
        nonzero = matrix[matrix > 0]
        if len(nonzero) == 0:
            clip_value = 1.0
        else:
            clip_value = float(np.percentile(nonzero, clip_pctl * 100))
            clip_value = max(clip_value, 1.0)  # Minimum clip value

        # Apply log1p scaling
        log_matrix = np.log1p(matrix)
        log_clip = np.log1p(clip_value)

        # Normalize to 0-65535 range
        if log_clip > 0:
            normalized = (log_matrix / log_clip) * 65535
        else:
            normalized = np.zeros_like(matrix)

        # Clip and convert to uint16
        normalized = np.clip(normalized, 0, 65535)
        encoded = normalized.astype(np.uint16)

        # Convert to bytes (little-endian)
        return encoded.tobytes(), clip_value

    def _compress(self, data: bytes, level: int = 3) -> bytes:
        """Compress data using zstd or fallback to zlib"""
        if HAS_ZSTD:
            compressor = zstd.ZstdCompressor(level=level)
            return compressor.compress(data)
        else:
            return zlib.compress(data, level=min(level, 9))

    def _compute_checksum(self, data: bytes) -> str:
        """Compute checksum using xxhash or fallback to md5"""
        if HAS_XXHASH:
            return xxhash.xxh64(data).hexdigest()
        else:
            return hashlib.md5(data).hexdigest()

    def _create_tile_id(
        self,
        token_id: str,
        lod_ms: int,
        t_start: int,
        band: TileBand
    ) -> str:
        """Create unique tile ID"""
        return f"{token_id}:{lod_ms}:{t_start}:{band.value}"

    def generate_tile(
        self,
        token_id: str,
        t_start: int,
        t_end: int,
        lod_ms: int = 250,
        tile_ms: int = 10000,
        band: TileBand = TileBand.FULL,
        side: str = None
    ) -> Optional[HeatmapTile]:
        """
        Generate a single heatmap tile.

        Args:
            token_id: Token ID
            t_start: Tile start timestamp (ms)
            t_end: Tile end timestamp (ms)
            lod_ms: Level of detail (250, 1000, 5000)
            tile_ms: Tile duration (usually t_end - t_start)
            band: Price band selection
            side: Optional filter ('bid' or 'ask')

        Returns:
            HeatmapTile or None if no data
        """
        print(f"[TILE_DEBUG] generate_tile: t_start={t_start}, t_end={t_end}, side={side}")
        # Fetch data
        data = self._fetch_book_data(token_id, t_start, t_end, lod_ms, side)

        if not data:
            print(f"[TILE_DEBUG] generate_tile: no data, returning None")
            return None

        # Get tick size
        tick_size = self._get_tick_size(token_id)

        # Determine price range
        prices = [float(d['price']) for d in data]
        if not prices:
            return None

        price_min_raw = min(prices)
        price_max_raw = max(prices)

        # Align prices to tick boundaries (must match _build_matrix alignment)
        price_min = round(round(price_min_raw / tick_size) * tick_size, 4)
        price_max = round(round(price_max_raw / tick_size) * tick_size, 4)

        print(f"[TILE_DEBUG] generate_tile: raw prices={price_min_raw}-{price_max_raw}, aligned={price_min}-{price_max}")

        # Apply band filter
        if band == TileBand.BEST_5:
            # Keep only best 5 levels from each side
            price_range = (price_max - price_min) * 0.1
            price_min = max(0, price_min)
            price_max = min(1, price_min + price_range)
        elif band == TileBand.BEST_10:
            price_range = (price_max - price_min) * 0.2
            price_min = max(0, price_min)
            price_max = min(1, price_min + price_range)
        elif band == TileBand.BEST_20:
            price_range = (price_max - price_min) * 0.4
            price_min = max(0, price_min)
            price_max = min(1, price_min + price_range)

        # Build matrix
        matrix, price_levels, time_buckets = self._build_matrix(
            data, t_start, t_end, lod_ms, price_min, price_max, tick_size, side
        )

        if matrix.size == 0:
            return None

        # Encode
        encoded_bytes, clip_value = self._encode_matrix(matrix, self.DEFAULT_CLIP_PCTL)

        # Compress
        compressed = self._compress(encoded_bytes, self.DEFAULT_COMPRESSION_LEVEL)

        # Checksum
        checksum = self._compute_checksum(compressed)

        # Create tile
        return HeatmapTile(
            tile_id=self._create_tile_id(token_id, lod_ms, t_start, band),
            token_id=token_id,
            lod_ms=lod_ms,
            tile_ms=tile_ms,
            band=band,
            t_start=t_start,
            t_end=t_end,
            tick_size=tick_size,
            price_min=price_min,
            price_max=price_max,
            rows=matrix.shape[0],
            cols=matrix.shape[1],
            encoding_dtype="uint16",
            encoding_layout="row_major",
            encoding_scale="log1p_clip",
            clip_pctl=self.DEFAULT_CLIP_PCTL,
            clip_value=clip_value,
            compression_algo="zstd" if HAS_ZSTD else "zlib",
            compression_level=self.DEFAULT_COMPRESSION_LEVEL,
            payload=compressed,
            checksum_algo="xxh3_64" if HAS_XXHASH else "md5",
            checksum_value=checksum,
        )

    def generate_tiles(
        self,
        token_id: str,
        from_ts: int,
        to_ts: int,
        lod_ms: int = 250,
        tile_ms: int = 10000,
        band: TileBand = TileBand.FULL,
        side: str = None
    ) -> List[HeatmapTile]:
        """
        Generate tiles covering a time range.

        Args:
            token_id: Token ID
            from_ts: Start timestamp (ms)
            to_ts: End timestamp (ms)
            lod_ms: Level of detail
            tile_ms: Tile duration
            band: Price band
            side: Optional side filter

        Returns:
            List of HeatmapTile objects
        """
        print(f"[TILE_DEBUG] generate_tiles: token={token_id[:20]}..., from_ts={from_ts}, to_ts={to_ts}, side={side}")
        tiles = []

        # Align to tile boundaries
        t_start = (from_ts // tile_ms) * tile_ms
        print(f"[TILE_DEBUG] generate_tiles: aligned t_start={t_start}")

        while t_start < to_ts:
            t_end = min(t_start + tile_ms, to_ts)

            tile = self.generate_tile(
                token_id=token_id,
                t_start=t_start,
                t_end=t_end,
                lod_ms=lod_ms,
                tile_ms=tile_ms,
                band=band,
                side=side
            )

            if tile:
                tiles.append(tile)
                print(f"[TILE_DEBUG] generate_tiles: added tile for t_start={t_start}")

            t_start += tile_ms

        print(f"[TILE_DEBUG] generate_tiles: completed, total tiles={len(tiles)}")
        return tiles

    def save_tile(self, tile: HeatmapTile) -> bool:
        """
        Save tile to database cache.

        Args:
            tile: HeatmapTile to save

        Returns:
            True if saved successfully
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO heatmap_tiles (
                        tile_id, token_id, lod_ms, tile_ms, band,
                        t_start, t_end, tick_size, price_min, price_max,
                        rows, cols, encoding_dtype, encoding_layout, encoding_scale,
                        clip_pctl, clip_value, compression_algo, compression_level,
                        payload, checksum_algo, checksum_value
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (tile_id) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        checksum_value = EXCLUDED.checksum_value,
                        created_at = NOW()
                """, (
                    tile.tile_id, tile.token_id, tile.lod_ms, tile.tile_ms, tile.band.value,
                    tile.t_start, tile.t_end, tile.tick_size, tile.price_min, tile.price_max,
                    tile.rows, tile.cols, tile.encoding_dtype, tile.encoding_layout, tile.encoding_scale,
                    tile.clip_pctl, tile.clip_value, tile.compression_algo, tile.compression_level,
                    tile.payload, tile.checksum_algo, tile.checksum_value
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"[TILE ERROR] Failed to save tile: {e}")
            conn.rollback()
            return False

    def get_cached_tile(self, tile_id: str) -> Optional[HeatmapTile]:
        """
        Get tile from cache.

        Args:
            tile_id: Tile ID

        Returns:
            HeatmapTile or None
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM heatmap_tiles WHERE tile_id = %s
            """, (tile_id,))
            row = cur.fetchone()

            if not row:
                return None

            return HeatmapTile(
                tile_id=row['tile_id'],
                token_id=row['token_id'],
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

    def get_or_generate(
        self,
        token_id: str,
        from_ts: int,
        to_ts: int,
        lod_ms: int = 250,
        tile_ms: int = 10000,
        band: TileBand = TileBand.FULL,
        cache: bool = True
    ) -> List[HeatmapTile]:
        """
        Get tiles from cache or generate on demand.

        Args:
            token_id: Token ID
            from_ts: Start timestamp
            to_ts: End timestamp
            lod_ms: Level of detail
            tile_ms: Tile duration
            band: Price band
            cache: Whether to cache generated tiles

        Returns:
            List of HeatmapTile objects
        """
        tiles = []
        t_start = (from_ts // tile_ms) * tile_ms

        while t_start < to_ts:
            t_end = min(t_start + tile_ms, to_ts)
            tile_id = self._create_tile_id(token_id, lod_ms, t_start, band)

            # Try cache first
            tile = self.get_cached_tile(tile_id)

            if not tile:
                # Generate on demand
                tile = self.generate_tile(
                    token_id=token_id,
                    t_start=t_start,
                    t_end=t_end,
                    lod_ms=lod_ms,
                    tile_ms=tile_ms,
                    band=band
                )

                if tile and cache:
                    self.save_tile(tile)

            if tile:
                tiles.append(tile)

            t_start += tile_ms

        return tiles


def tile_to_api_response(tile: HeatmapTile) -> Dict[str, Any]:
    """Convert HeatmapTile to API response format"""
    return {
        'tile_id': tile.tile_id,
        'token_id': tile.token_id,
        'lod_ms': tile.lod_ms,
        'tile_ms': tile.tile_ms,
        'band': tile.band.value,
        't_start': tile.t_start,
        't_end': tile.t_end,
        'tick_size': tile.tick_size,
        'price_min': tile.price_min,
        'price_max': tile.price_max,
        'rows': tile.rows,
        'cols': tile.cols,
        'encoding': {
            'dtype': tile.encoding_dtype,
            'layout': tile.encoding_layout,
            'scale': tile.encoding_scale,
            'clip_pctl': tile.clip_pctl,
            'clip_value': tile.clip_value,
        },
        'compression': {
            'algo': tile.compression_algo,
            'level': tile.compression_level,
        },
        'payload_b64': base64.b64encode(tile.payload).decode('utf-8'),
        'checksum': {
            'algo': tile.checksum_algo,
            'value': tile.checksum_value,
        },
    }
