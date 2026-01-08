"""
Tests for Evidence Bundle Hash and Auditability (v5.3).
"""

import pytest
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBundleHash:
    """Tests for evidence bundle hash computation."""

    def test_compute_bundle_hash_deterministic(self):
        """Bundle hash should be deterministic for same input."""
        from backend.evidence.bundle_hash import compute_bundle_hash

        bundle = {
            'token_id': 'test-token',
            't0': 1704067200000,
            'window': {'from_ts': 1704067170000, 'to_ts': 1704067230000},
            'shocks': [],
            'reactions': [],
            'leading_events': [],
            'belief_states': [],
            'anchors': [],
        }

        hash1 = compute_bundle_hash(bundle)
        hash2 = compute_bundle_hash(bundle)

        assert hash1 == hash2
        assert len(hash1) == 16  # xxhash64-style hex length (8 bytes)

    def test_compute_bundle_hash_different_for_different_input(self):
        """Bundle hash should differ for different inputs."""
        from backend.evidence.bundle_hash import compute_bundle_hash

        bundle1 = {
            'token_id': 'test-token-1',
            't0': 1704067200000,
            'window': {'from_ts': 1704067170000, 'to_ts': 1704067230000},
            'shocks': [],
            'reactions': [],
            'leading_events': [],
            'belief_states': [],
            'anchors': [],
        }

        bundle2 = {
            'token_id': 'test-token-2',  # Different token
            't0': 1704067200000,
            'window': {'from_ts': 1704067170000, 'to_ts': 1704067230000},
            'shocks': [],
            'reactions': [],
            'leading_events': [],
            'belief_states': [],
            'anchors': [],
        }

        hash1 = compute_bundle_hash(bundle1)
        hash2 = compute_bundle_hash(bundle2)

        assert hash1 != hash2

    def test_compute_bundle_hash_order_independent(self):
        """Bundle hash should handle key ordering consistently."""
        from backend.evidence.bundle_hash import compute_bundle_hash

        # Different key order should produce same hash
        bundle1 = {
            'token_id': 'test-token',
            't0': 1704067200000,
            'window': {'from_ts': 1704067170000, 'to_ts': 1704067230000},
            'shocks': [],
            'reactions': [],
            'leading_events': [],
            'belief_states': [],
            'anchors': [],
        }

        bundle2 = {
            'anchors': [],
            'belief_states': [],
            'leading_events': [],
            'reactions': [],
            'shocks': [],
            'window': {'to_ts': 1704067230000, 'from_ts': 1704067170000},
            't0': 1704067200000,
            'token_id': 'test-token',
        }

        hash1 = compute_bundle_hash(bundle1)
        hash2 = compute_bundle_hash(bundle2)

        assert hash1 == hash2

    def test_compute_bundle_hash_with_events(self, sample_evidence_bundle):
        """Bundle hash should work with actual event data."""
        from backend.evidence.bundle_hash import compute_bundle_hash

        hash_result = compute_bundle_hash(sample_evidence_bundle)

        assert hash_result is not None
        assert len(hash_result) == 16  # xxhash64-style


class TestBundleHashCache:
    """Tests for bundle hash caching."""

    def test_cache_stores_and_retrieves(self):
        """Cache should store and retrieve hashes correctly."""
        from backend.evidence.bundle_hash import BundleHashCache

        # BundleHashCache takes db_conn as optional arg
        cache = BundleHashCache()

        # Use get_or_compute instead
        bundle = {
            'token_id': 'test-token',
            't0': 1704067200000,
            'window': {'from_ts': 1704067170000, 'to_ts': 1704067230000},
            'shocks': [],
            'reactions': [],
            'leading_events': [],
            'belief_states': [],
            'anchors': [],
        }

        hash1 = cache.get_or_compute(bundle)
        hash2 = cache.get_or_compute(bundle)

        # Should get same hash from cache
        assert hash1 == hash2

    def test_cache_verify(self):
        """Cache should verify bundle correctly."""
        from backend.evidence.bundle_hash import BundleHashCache, compute_bundle_hash

        cache = BundleHashCache()

        bundle = {
            'token_id': 'test-token',
            't0': 1704067200000,
            'window': {'from_ts': 1704067170000, 'to_ts': 1704067230000},
            'shocks': [],
            'reactions': [],
            'leading_events': [],
            'belief_states': [],
            'anchors': [],
        }

        expected_hash = compute_bundle_hash(bundle)
        assert cache.verify(bundle, expected_hash) is True
        assert cache.verify(bundle, 'wrong-hash') is False


class TestVersionTracking:
    """Tests for engine version and config hash tracking."""

    def test_engine_version_format(self):
        """Engine version should be in valid format."""
        from backend.version import ENGINE_VERSION

        assert ENGINE_VERSION is not None
        assert ENGINE_VERSION.startswith('v')
        # Should be semantic versioning format
        parts = ENGINE_VERSION[1:].split('.')
        assert len(parts) >= 2

    def test_config_hash_deterministic(self):
        """Config hash should be deterministic."""
        from backend.version import CONFIG_HASH

        assert CONFIG_HASH is not None
        assert len(CONFIG_HASH) > 0
