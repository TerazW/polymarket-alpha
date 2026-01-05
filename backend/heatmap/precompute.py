"""
Heatmap Tile Pre-computation Task

Runs periodically to pre-generate heatmap tiles for active markets.
This improves API response time by having tiles ready in cache.

Usage:
    # Run as standalone script
    python -m backend.heatmap.precompute

    # Or import and run
    from backend.heatmap.precompute import precompute_tiles
    precompute_tiles(lookback_hours=1)
"""

import time
from datetime import datetime, timedelta
from typing import List, Optional

from .tile_generator import HeatmapTileGenerator, TileBand

# Optional psycopg2 import
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    psycopg2 = None
    RealDictCursor = None


# Database config
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 5433,
    'database': 'belief_reaction',
    'user': 'postgres',
    'password': 'postgres'
}

# Pre-computation settings
DEFAULT_LOOKBACK_HOURS = 1  # Pre-compute last 1 hour
DEFAULT_LOD_LEVELS = [250, 1000]  # Generate 250ms and 1s tiles
DEFAULT_TILE_MS = 10000  # 10 second tiles
DEFAULT_BANDS = [TileBand.FULL]  # Generate full band only


def get_active_tokens(db_config: dict, limit: int = 50) -> List[str]:
    """
    Get list of active token IDs to pre-compute tiles for.

    Prioritizes tokens with:
    1. Recent trading activity
    2. Recent shock/reaction events
    3. Non-STABLE belief state
    """
    if not HAS_PSYCOPG2:
        raise ImportError("psycopg2 is required for precompute functionality")

    conn = psycopg2.connect(**db_config, cursor_factory=RealDictCursor)

    try:
        with conn.cursor() as cur:
            # Get tokens with recent activity, prioritized by belief state
            cur.execute("""
                WITH recent_activity AS (
                    SELECT DISTINCT token_id
                    FROM book_bins
                    WHERE bucket_ts > NOW() - INTERVAL '1 hour'
                ),
                token_states AS (
                    SELECT DISTINCT ON (token_id)
                        token_id,
                        new_state,
                        ts
                    FROM belief_states
                    ORDER BY token_id, ts DESC
                )
                SELECT ra.token_id,
                       COALESCE(ts.new_state, 'STABLE') as state
                FROM recent_activity ra
                LEFT JOIN token_states ts ON ts.token_id = ra.token_id
                ORDER BY
                    CASE COALESCE(ts.new_state, 'STABLE')
                        WHEN 'BROKEN' THEN 0
                        WHEN 'CRACKING' THEN 1
                        WHEN 'FRAGILE' THEN 2
                        ELSE 3
                    END ASC,
                    ts.ts DESC NULLS LAST
                LIMIT %s
            """, (limit,))

            return [row['token_id'] for row in cur.fetchall()]
    finally:
        conn.close()


def precompute_tiles(
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    lod_levels: List[int] = None,
    tile_ms: int = DEFAULT_TILE_MS,
    bands: List[TileBand] = None,
    token_limit: int = 50,
    verbose: bool = True
) -> dict:
    """
    Pre-compute heatmap tiles for active markets.

    Args:
        lookback_hours: Hours of history to generate tiles for
        lod_levels: List of LOD levels to generate (default: [250, 1000])
        tile_ms: Tile duration in ms
        bands: List of price bands to generate
        token_limit: Maximum number of tokens to process
        verbose: Print progress

    Returns:
        Stats dict with counts
    """
    lod_levels = lod_levels or DEFAULT_LOD_LEVELS
    bands = bands or DEFAULT_BANDS

    stats = {
        'tokens_processed': 0,
        'tiles_generated': 0,
        'tiles_cached': 0,
        'errors': 0,
        'duration_ms': 0,
    }

    start_time = time.time()

    # Calculate time range
    now_ms = int(datetime.now().timestamp() * 1000)
    from_ts = now_ms - int(lookback_hours * 3600 * 1000)
    to_ts = now_ms

    # Align to tile boundaries
    from_ts = (from_ts // tile_ms) * tile_ms
    to_ts = ((to_ts // tile_ms) + 1) * tile_ms

    if verbose:
        print(f"[PRECOMPUTE] Starting tile pre-computation")
        print(f"  Time range: {datetime.fromtimestamp(from_ts/1000)} - {datetime.fromtimestamp(to_ts/1000)}")
        print(f"  LOD levels: {lod_levels}")
        print(f"  Tile duration: {tile_ms}ms")

    # Get active tokens
    tokens = get_active_tokens(DB_CONFIG, limit=token_limit)

    if verbose:
        print(f"  Active tokens: {len(tokens)}")

    if not tokens:
        if verbose:
            print("  No active tokens found, skipping")
        return stats

    # Initialize generator
    generator = HeatmapTileGenerator(db_config=DB_CONFIG)

    # Process each token
    for token_id in tokens:
        try:
            for lod in lod_levels:
                for band in bands:
                    tiles = generator.get_or_generate(
                        token_id=token_id,
                        from_ts=from_ts,
                        to_ts=to_ts,
                        lod_ms=lod,
                        tile_ms=tile_ms,
                        band=band,
                        cache=True
                    )

                    stats['tiles_generated'] += len(tiles)

            stats['tokens_processed'] += 1

            if verbose and stats['tokens_processed'] % 10 == 0:
                print(f"  Processed {stats['tokens_processed']}/{len(tokens)} tokens...")

        except Exception as e:
            stats['errors'] += 1
            if verbose:
                print(f"  Error processing {token_id[:8]}...: {e}")

    stats['duration_ms'] = int((time.time() - start_time) * 1000)

    if verbose:
        print(f"[PRECOMPUTE] Complete:")
        print(f"  Tokens: {stats['tokens_processed']}")
        print(f"  Tiles: {stats['tiles_generated']}")
        print(f"  Errors: {stats['errors']}")
        print(f"  Duration: {stats['duration_ms']}ms")

    return stats


def run_continuous(
    interval_seconds: int = 60,
    lookback_hours: float = 0.5,
    **kwargs
):
    """
    Run pre-computation continuously.

    Args:
        interval_seconds: Seconds between runs
        lookback_hours: Hours of history to compute
        **kwargs: Additional args passed to precompute_tiles
    """
    print(f"[PRECOMPUTE] Starting continuous pre-computation")
    print(f"  Interval: {interval_seconds}s")
    print(f"  Lookback: {lookback_hours}h")

    while True:
        try:
            precompute_tiles(
                lookback_hours=lookback_hours,
                verbose=True,
                **kwargs
            )
        except Exception as e:
            print(f"[PRECOMPUTE ERROR] {e}")

        print(f"[PRECOMPUTE] Sleeping {interval_seconds}s...")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pre-compute heatmap tiles")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=60, help="Interval between runs (seconds)")
    parser.add_argument("--lookback", type=float, default=1.0, help="Hours of history to compute")
    parser.add_argument("--tokens", type=int, default=50, help="Max tokens to process")

    args = parser.parse_args()

    if args.continuous:
        run_continuous(
            interval_seconds=args.interval,
            lookback_hours=args.lookback,
            token_limit=args.tokens
        )
    else:
        precompute_tiles(
            lookback_hours=args.lookback,
            token_limit=args.tokens,
            verbose=True
        )
