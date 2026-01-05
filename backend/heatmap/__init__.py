"""
Heatmap module - Tile generation, caching, and dual-track delivery

v5.18: Add dual-track system for warm/cold tile delivery
"""
from .tile_generator import (
    HeatmapTileGenerator,
    HeatmapTile,
    TileBand,
    tile_to_api_response,
)
from .precompute import precompute_tiles, run_continuous
from .dual_track import (
    DualTrackTileManager,
    TileSource,
    TileMetadata,
    TileRequestResult,
    TileCacheTracker,
    SOURCE_LABELS,
    STALE_THRESHOLD_MS,
    get_dual_track_manager,
)

__all__ = [
    # Core tile generation
    'HeatmapTileGenerator',
    'HeatmapTile',
    'TileBand',
    'tile_to_api_response',
    # Precomputation
    'precompute_tiles',
    'run_continuous',
    # Dual-track system (v5.18)
    'DualTrackTileManager',
    'TileSource',
    'TileMetadata',
    'TileRequestResult',
    'TileCacheTracker',
    'SOURCE_LABELS',
    'STALE_THRESHOLD_MS',
    'get_dual_track_manager',
]
