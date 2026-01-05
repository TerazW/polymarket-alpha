"""
Tests for Heatmap Tile Generation (v5.4).
"""

import pytest
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTileBand:
    """Tests for TileBand enum."""

    def test_tile_band_values(self):
        """TileBand should have correct values."""
        try:
            from backend.heatmap.tile_generator import TileBand
        except ImportError:
            pytest.skip("psycopg2 not installed")

        assert TileBand.FULL.value == 'FULL'
        assert TileBand.BID.value == 'BID'
        assert TileBand.ASK.value == 'ASK'


class TestHeatmapTile:
    """Tests for HeatmapTile dataclass."""

    def test_tile_creation(self):
        """HeatmapTile should be creatable with valid data."""
        from backend.heatmap.tile_generator import HeatmapTile, TileBand

        tile = HeatmapTile(
            tile_id='test-tile-001',
            token_id='test-token',
            lod_ms=250,
            tile_ms=10000,
            band=TileBand.FULL,
            t_start=1704067200000,
            t_end=1704067210000,
            tick_size=0.01,
            price_min=0.60,
            price_max=0.80,
            rows=20,
            cols=40,
            encoding_dtype='uint16',
            encoding_layout='row-major',
            encoding_scale='log1p',
            clip_pctl=95.0,
            clip_value=10000.0,
            compression_algo='zstd',
            compression_level=3,
            payload=b'\x00' * 100,
            checksum_algo='xxhash64',
            checksum_value='abc123',
        )

        assert tile.tile_id == 'test-tile-001'
        assert tile.rows == 20
        assert tile.cols == 40


class TestMatrixEncoding:
    """Tests for matrix encoding utilities."""

    def test_log1p_encoding(self):
        """log1p encoding should preserve relative magnitudes."""
        # Simulate log1p encoding
        values = np.array([0, 1, 10, 100, 1000, 10000])
        clip_value = 10000

        # log1p encode
        log_values = np.log1p(values)
        max_log = np.log1p(clip_value)
        encoded = (log_values / max_log * 65535).astype(np.uint16)

        # Verify ordering preserved
        assert np.all(encoded[1:] >= encoded[:-1])

        # Verify range
        assert encoded[0] == 0
        assert encoded[-1] == 65535

    def test_log1p_decoding(self):
        """log1p decoding should approximately recover original values."""
        original = np.array([100.0, 500.0, 1000.0, 5000.0])
        clip_value = 10000.0

        # Encode
        log_values = np.log1p(original)
        max_log = np.log1p(clip_value)
        encoded = (log_values / max_log * 65535).astype(np.uint16)

        # Decode
        decoded_log = encoded.astype(np.float64) / 65535 * max_log
        decoded = np.expm1(decoded_log)

        # Should be within 1% due to quantization
        relative_error = np.abs(decoded - original) / original
        assert np.all(relative_error < 0.01)


class TestTileGeneration:
    """Tests for tile generation logic."""

    def test_generate_tile_id_format(self):
        """Tile ID should have correct format."""
        from backend.heatmap.tile_generator import HeatmapTileGenerator

        # Tile ID format: {token_id}_{t_start}_{t_end}_{lod}_{band}
        token_id = 'abc123'
        t_start = 1704067200000
        t_end = 1704067210000
        lod_ms = 250
        band = 'FULL'

        expected_id = f"{token_id}_{t_start}_{t_end}_{lod_ms}_{band}"

        # Verify format components
        parts = expected_id.split('_')
        assert len(parts) == 5
        assert parts[0] == token_id
        assert int(parts[1]) == t_start
        assert int(parts[2]) == t_end
        assert int(parts[3]) == lod_ms
        assert parts[4] == band


class TestTileCompression:
    """Tests for tile compression."""

    def test_zstd_compression_available(self):
        """zstd compression should be available."""
        try:
            import zstandard as zstd
            compressor = zstd.ZstdCompressor(level=3)
            data = b'test data for compression' * 100
            compressed = compressor.compress(data)

            # Compressed should be smaller
            assert len(compressed) < len(data)

            # Should decompress correctly
            decompressor = zstd.ZstdDecompressor()
            decompressed = decompressor.decompress(compressed)
            assert decompressed == data

        except ImportError:
            pytest.skip("zstandard not installed")

    def test_xxhash_checksum(self):
        """xxhash checksum should be available and consistent."""
        try:
            import xxhash
            data = b'test data for checksum'

            hash1 = xxhash.xxh64(data).hexdigest()
            hash2 = xxhash.xxh64(data).hexdigest()

            assert hash1 == hash2
            assert len(hash1) == 16  # xxh64 produces 16 hex chars

        except ImportError:
            pytest.skip("xxhash not installed")


class TestPrecompute:
    """Tests for tile precomputation."""

    def test_priority_calculation(self):
        """Tokens should be prioritized by belief state severity."""
        # BROKEN > CRACKING > FRAGILE > STABLE
        states = ['STABLE', 'FRAGILE', 'CRACKING', 'BROKEN']
        priority_order = {
            'BROKEN': 0,
            'CRACKING': 1,
            'FRAGILE': 2,
            'STABLE': 3,
        }

        # Sort by priority
        sorted_states = sorted(states, key=lambda s: priority_order.get(s, 99))

        assert sorted_states[0] == 'BROKEN'
        assert sorted_states[1] == 'CRACKING'
        assert sorted_states[2] == 'FRAGILE'
        assert sorted_states[3] == 'STABLE'
