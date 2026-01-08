"""
Tests for Dual-Track Heatmap Tile System (v5.18)

Ensures:
1. TileSource enum defines all sources
2. TileCacheTracker tracks hit/miss/stale correctly
3. TileMetadata serializes properly
4. DualTrackTileManager handles warm/cold tracks
5. Precompute queue prioritization works
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock

from backend.heatmap import (
    TileSource,
    TileMetadata,
    TileRequestResult,
    TileCacheTracker,
    DualTrackTileManager,
    SOURCE_LABELS,
    STALE_THRESHOLD_MS,
    get_dual_track_manager,
    TileBand,
)


class TestTileSource:
    """Test TileSource enum"""

    def test_all_sources_defined(self):
        """Should have all required sources"""
        assert TileSource.PRECOMPUTED.value == "PRECOMPUTED"
        assert TileSource.ON_DEMAND.value == "ON_DEMAND"
        assert TileSource.STALE.value == "STALE"
        assert TileSource.MISS.value == "MISS"

    def test_source_labels_defined(self):
        """Each source should have a label"""
        for source in TileSource:
            assert source in SOURCE_LABELS
            label, emoji = SOURCE_LABELS[source]
            assert label  # Non-empty string
            assert emoji  # Non-empty emoji


class TestTileMetadata:
    """Test TileMetadata dataclass"""

    def test_metadata_creation(self):
        """Should create metadata with all fields"""
        now = int(time.time() * 1000)
        metadata = TileMetadata(
            tile_id="test:250:1000:FULL",
            source=TileSource.PRECOMPUTED,
            cached_at=now - 10000,
            generated_at=now - 10000,
            data_updated_at=now - 5000,
            staleness_ms=5000,
            ui_label="预热缓存",
            ui_emoji="🟢",
        )

        assert metadata.tile_id == "test:250:1000:FULL"
        assert metadata.source == TileSource.PRECOMPUTED
        assert metadata.staleness_ms == 5000

    def test_metadata_to_dict(self):
        """Should serialize to dict correctly"""
        now = int(time.time() * 1000)
        metadata = TileMetadata(
            tile_id="test:250:1000:FULL",
            source=TileSource.ON_DEMAND,
            cached_at=now,
            generated_at=now,
            data_updated_at=now,
            staleness_ms=0,
            ui_label="按需生成",
            ui_emoji="🟡",
        )

        d = metadata.to_dict()

        assert d["tile_id"] == "test:250:1000:FULL"
        assert d["source"] == "ON_DEMAND"
        assert d["staleness_ms"] == 0
        assert d["is_fresh"] is True
        assert "ui_label" in d
        assert "ui_emoji" in d

    def test_freshness_calculation(self):
        """is_fresh should be True for staleness < 1 minute"""
        now = int(time.time() * 1000)

        # Fresh tile
        fresh = TileMetadata(
            tile_id="test1",
            source=TileSource.PRECOMPUTED,
            cached_at=now,
            generated_at=now,
            data_updated_at=now,
            staleness_ms=30000,  # 30 seconds
            ui_label="test",
            ui_emoji="🟢",
        )
        assert fresh.to_dict()["is_fresh"] is True

        # Stale tile
        stale = TileMetadata(
            tile_id="test2",
            source=TileSource.STALE,
            cached_at=now - 120000,
            generated_at=now - 120000,
            data_updated_at=now,
            staleness_ms=120000,  # 2 minutes
            ui_label="test",
            ui_emoji="🟠",
        )
        assert stale.to_dict()["is_fresh"] is False


class TestTileRequestResult:
    """Test TileRequestResult dataclass"""

    def test_result_creation(self):
        """Should create result with all fields"""
        result = TileRequestResult(
            tiles=[],
            metadata=[],
            total_requested=10,
            cache_hits=7,
            cache_misses=2,
            stale_count=1,
            generated_count=2,
            request_time_ms=50,
        )

        assert result.total_requested == 10
        assert result.cache_hits == 7
        assert result.cache_misses == 2

    def test_result_to_dict(self):
        """Should serialize to dict with hit rate"""
        result = TileRequestResult(
            tiles=[],
            metadata=[],
            total_requested=10,
            cache_hits=8,
            cache_misses=2,
            stale_count=0,
            generated_count=2,
            request_time_ms=45,
        )

        d = result.to_dict()

        assert d["tile_count"] == 0
        assert d["total_requested"] == 10
        assert d["hit_rate"] == 0.8
        assert d["request_time_ms"] == 45
        assert "metadata" in d


class TestTileCacheTracker:
    """Test TileCacheTracker class"""

    @pytest.fixture
    def tracker(self):
        """Fresh tracker for each test"""
        return TileCacheTracker(window_size=100)

    def test_initial_stats(self, tracker):
        """Initial stats should be zero"""
        stats = tracker.get_stats()
        assert stats["total_requests"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0

    def test_record_cache_hit(self, tracker):
        """Should track cache hits"""
        tracker.record_request("token-1", TileSource.PRECOMPUTED, tile_count=5)

        stats = tracker.get_stats()
        assert stats["total_requests"] == 5
        assert stats["cache_hits"] == 5
        assert stats["hit_rate"] == 1.0

    def test_record_cache_miss(self, tracker):
        """Should track cache misses"""
        tracker.record_request("token-1", TileSource.ON_DEMAND, tile_count=3)

        stats = tracker.get_stats()
        assert stats["total_requests"] == 3
        assert stats["cache_misses"] == 3
        assert stats["on_demand_generated"] == 3

    def test_record_stale_hit(self, tracker):
        """Should track stale hits separately"""
        tracker.record_request("token-1", TileSource.STALE, tile_count=2)

        stats = tracker.get_stats()
        assert stats["total_requests"] == 2
        assert stats["stale_hits"] == 2
        assert stats["stale_rate"] == 1.0

    def test_mixed_requests(self, tracker):
        """Should track mixed request types"""
        tracker.record_request("token-1", TileSource.PRECOMPUTED, tile_count=5)
        tracker.record_request("token-1", TileSource.ON_DEMAND, tile_count=3)
        tracker.record_request("token-1", TileSource.STALE, tile_count=2)

        stats = tracker.get_stats()
        assert stats["total_requests"] == 10
        assert stats["cache_hits"] == 5
        assert stats["cache_misses"] == 3
        assert stats["stale_hits"] == 2
        assert stats["hit_rate"] == 0.5

    def test_per_token_stats(self, tracker):
        """Should track stats per token"""
        tracker.record_request("token-1", TileSource.PRECOMPUTED, tile_count=10)
        tracker.record_request("token-2", TileSource.ON_DEMAND, tile_count=5)

        stats1 = tracker.get_token_stats("token-1")
        assert stats1["requests"] == 10
        assert stats1["hits"] == 10
        assert stats1["hit_rate"] == 1.0

        stats2 = tracker.get_token_stats("token-2")
        assert stats2["requests"] == 5
        assert stats2["misses"] == 5
        assert stats2["hit_rate"] == 0.0

    def test_hot_tokens(self, tracker):
        """Should identify most requested tokens"""
        tracker.record_request("token-1", TileSource.PRECOMPUTED, tile_count=100)
        tracker.record_request("token-2", TileSource.PRECOMPUTED, tile_count=50)
        tracker.record_request("token-3", TileSource.PRECOMPUTED, tile_count=25)

        hot = tracker.get_hot_tokens(limit=2)

        assert len(hot) == 2
        assert hot[0]["token_id"] == "token-1"
        assert hot[0]["requests"] == 100
        assert hot[1]["token_id"] == "token-2"

    def test_unknown_token_stats(self, tracker):
        """Unknown token should return zeroed stats"""
        stats = tracker.get_token_stats("unknown-token")
        assert stats["requests"] == 0
        assert stats["hit_rate"] == 0


class TestDualTrackTileManager:
    """Test DualTrackTileManager class"""

    @pytest.fixture
    def manager(self):
        """Fresh manager without DB"""
        return DualTrackTileManager(
            db_config={},
            enable_on_demand=True
        )

    def test_manager_creation(self, manager):
        """Should create manager"""
        assert manager is not None
        assert manager.enable_on_demand is True
        assert manager.stale_threshold_ms == STALE_THRESHOLD_MS

    def test_cache_stats(self, manager):
        """Should return cache stats"""
        stats = manager.get_cache_stats()
        assert "total_requests" in stats
        assert "hit_rate" in stats

    def test_precompute_queue_empty(self, manager):
        """Empty queue should return empty list"""
        queue = manager.get_precompute_queue()
        assert queue == []

    def test_queue_for_precompute(self, manager):
        """Should queue tokens for precomputation"""
        manager._queue_for_precompute("token-1", priority=10.0)
        manager._queue_for_precompute("token-2", priority=5.0)
        manager._queue_for_precompute("token-3", priority=15.0)

        queue = manager.get_precompute_queue(limit=10)

        assert len(queue) == 3
        # Should be sorted by priority descending
        assert queue[0][0] == "token-3"
        assert queue[0][1] == 15.0
        assert queue[1][0] == "token-1"
        assert queue[2][0] == "token-2"

    def test_priority_update(self, manager):
        """Higher priority should update existing entry"""
        manager._queue_for_precompute("token-1", priority=5.0)
        manager._queue_for_precompute("token-1", priority=10.0)
        manager._queue_for_precompute("token-1", priority=7.0)  # Lower, should not update

        queue = manager.get_precompute_queue()
        assert len(queue) == 1
        assert queue[0][1] == 10.0  # Should be highest priority

    def test_clear_precompute_queue(self, manager):
        """Should clear precomputation queue"""
        manager._queue_for_precompute("token-1", priority=10.0)
        manager._queue_for_precompute("token-2", priority=5.0)

        manager.clear_precompute_queue(["token-1"])
        queue = manager.get_precompute_queue()
        assert len(queue) == 1
        assert queue[0][0] == "token-2"

        manager.clear_precompute_queue()
        assert manager.get_precompute_queue() == []

    def test_get_hot_tokens(self, manager):
        """Should return hot tokens from cache tracker"""
        # Record some requests
        manager._cache_tracker.record_request("token-1", TileSource.PRECOMPUTED, 100)
        manager._cache_tracker.record_request("token-2", TileSource.ON_DEMAND, 50)

        hot = manager.get_hot_tokens(limit=5)
        assert len(hot) == 2


class TestTileRequestResultHitRate:
    """Test hit rate calculations"""

    def test_hit_rate_all_hits(self):
        """100% hit rate"""
        result = TileRequestResult(
            tiles=[],
            metadata=[],
            total_requested=10,
            cache_hits=10,
            cache_misses=0,
            stale_count=0,
            generated_count=0,
            request_time_ms=10,
        )
        assert result.to_dict()["hit_rate"] == 1.0

    def test_hit_rate_all_misses(self):
        """0% hit rate"""
        result = TileRequestResult(
            tiles=[],
            metadata=[],
            total_requested=10,
            cache_hits=0,
            cache_misses=10,
            stale_count=0,
            generated_count=10,
            request_time_ms=10,
        )
        assert result.to_dict()["hit_rate"] == 0.0

    def test_hit_rate_empty_request(self):
        """Empty request should not divide by zero"""
        result = TileRequestResult(
            tiles=[],
            metadata=[],
            total_requested=0,
            cache_hits=0,
            cache_misses=0,
            stale_count=0,
            generated_count=0,
            request_time_ms=0,
        )
        # Should handle division by zero gracefully
        d = result.to_dict()
        assert "hit_rate" in d  # Should not raise


class TestGlobalSingleton:
    """Test global singleton pattern"""

    def test_get_dual_track_manager_returns_same_instance(self):
        """get_dual_track_manager should return same instance"""
        # Reset global
        import backend.heatmap.dual_track as dt_module
        dt_module._dual_track_manager = None

        m1 = get_dual_track_manager()
        m2 = get_dual_track_manager()

        assert m1 is m2


class TestStaleThreshold:
    """Test staleness threshold configuration"""

    def test_default_threshold(self):
        """Default threshold should be 1 minute"""
        assert STALE_THRESHOLD_MS == 60000

    def test_custom_threshold(self):
        """Should accept custom threshold"""
        manager = DualTrackTileManager(
            db_config={},
            stale_threshold_ms=30000  # 30 seconds
        )
        assert manager.stale_threshold_ms == 30000


class TestSourceLabels:
    """Test source label configuration"""

    def test_precomputed_label(self):
        """Precomputed should have Chinese label"""
        label, emoji = SOURCE_LABELS[TileSource.PRECOMPUTED]
        assert "预热" in label or "缓存" in label
        assert emoji == "🟢"

    def test_on_demand_label(self):
        """On-demand should have Chinese label"""
        label, emoji = SOURCE_LABELS[TileSource.ON_DEMAND]
        assert "按需" in label or "生成" in label
        assert emoji == "🟡"

    def test_stale_label(self):
        """Stale should have Chinese label"""
        label, emoji = SOURCE_LABELS[TileSource.STALE]
        assert "陈旧" in label or "数据" in label
        assert emoji == "🟠"

    def test_miss_label(self):
        """Miss should have Chinese label"""
        label, emoji = SOURCE_LABELS[TileSource.MISS]
        assert "缺失" in label or "数据" in label
        assert emoji == "🔴"
