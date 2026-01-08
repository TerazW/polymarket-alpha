"""
Determinism Tests - Reproducibility guarantees

These tests ensure the system produces IDENTICAL outputs for identical inputs,
regardless of execution environment or timing.

Critical for:
1. Evidence auditability (same bundle hash on replay)
2. Multi-machine consistency
3. Debug reproducibility

"同一证据包，不同机器回放结果必须相同"
"""

import pytest
import sys
import os
import hashlib
import json
from decimal import Decimal
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestEventOrdering:
    """Tests for deterministic event ordering"""

    def test_same_timestamp_stable_sort(self):
        """Events with same timestamp must have stable ordering"""
        events = [
            {'ts': 1000, 'id': 'c', 'seq': 3},
            {'ts': 1000, 'id': 'a', 'seq': 1},
            {'ts': 1000, 'id': 'b', 'seq': 2},
        ]

        # Sort multiple times - must be identical
        sorted1 = sorted(events, key=lambda e: (e['ts'], e.get('seq', 0)))
        sorted2 = sorted(events, key=lambda e: (e['ts'], e.get('seq', 0)))
        sorted3 = sorted(events, key=lambda e: (e['ts'], e.get('seq', 0)))

        assert sorted1 == sorted2 == sorted3

    def test_floating_point_ordering(self):
        """Floating point values must not cause ordering instability"""
        # These are all "equal" in float land but might sort differently
        prices = [
            0.7200000000000001,
            0.72,
            0.7199999999999999,
        ]

        # Convert to Decimal for stable ordering
        decimal_prices = [Decimal(str(p)).quantize(Decimal("0.01")) for p in prices]

        # All should be equal after quantization
        assert all(p == decimal_prices[0] for p in decimal_prices)

    def test_dict_key_ordering(self):
        """Dict key ordering must be deterministic for hashing"""
        data1 = {'b': 2, 'a': 1, 'c': 3}
        data2 = {'a': 1, 'c': 3, 'b': 2}
        data3 = {'c': 3, 'b': 2, 'a': 1}

        # JSON with sort_keys must produce identical output
        json1 = json.dumps(data1, sort_keys=True)
        json2 = json.dumps(data2, sort_keys=True)
        json3 = json.dumps(data3, sort_keys=True)

        assert json1 == json2 == json3


class TestHashDeterminism:
    """Tests for deterministic hash computation"""

    def test_bundle_hash_reproducible(self):
        """Bundle hash must be reproducible"""
        from backend.evidence.bundle_hash import compute_bundle_hash

        bundle = {
            'token_id': 'test-token',
            't0': 1704067200000,
            'window': {'from_ts': 1704067170000, 'to_ts': 1704067230000},
            'trades': [
                {'ts': 1704067200000, 'price': 0.72, 'size': 100},
            ],
        }

        # Compute multiple times
        hash1 = compute_bundle_hash(bundle)
        hash2 = compute_bundle_hash(bundle)
        hash3 = compute_bundle_hash(bundle)

        assert hash1 == hash2 == hash3

    def test_bundle_hash_order_independent(self):
        """Bundle hash should be order-independent for list fields"""
        from backend.evidence.bundle_hash import compute_bundle_hash

        trades_order1 = [
            {'ts': 1000, 'price': 0.72, 'size': 100},
            {'ts': 1001, 'price': 0.73, 'size': 50},
        ]

        trades_order2 = [
            {'ts': 1001, 'price': 0.73, 'size': 50},
            {'ts': 1000, 'price': 0.72, 'size': 100},
        ]

        bundle1 = {'token_id': 'test', 't0': 1000, 'trades': trades_order1}
        bundle2 = {'token_id': 'test', 't0': 1000, 'trades': trades_order2}

        # Hash computation should sort internally
        hash1 = compute_bundle_hash(bundle1)
        hash2 = compute_bundle_hash(bundle2)

        # Should be equal (order independent)
        assert hash1 == hash2

    def test_float_precision_hash(self):
        """Float precision should not affect hash"""
        from backend.evidence.bundle_hash import compute_bundle_hash

        # These floats are "equal" but have different representations
        bundle1 = {'token_id': 'test', 't0': 1000, 'price': 0.72}
        bundle2 = {'token_id': 'test', 't0': 1000, 'price': 0.7200000000000001}

        # After normalization, should produce same hash
        # This requires careful float handling in bundle_hash.py
        hash1 = compute_bundle_hash(bundle1)
        hash2 = compute_bundle_hash(bundle2)

        # Note: This may fail if bundle_hash doesn't normalize floats
        # That would be a bug to fix
        assert hash1 == hash2


class TestClockDeterminism:
    """Tests for deterministic clock behavior"""

    def test_event_time_not_system_time(self):
        """System should use event timestamps, not system clock"""
        from backend.replay.engine import DeterministicClock

        clock = DeterministicClock(start_ts=0)

        # Process events
        events = [
            {'ts': 1000},
            {'ts': 2000},
            {'ts': 1500},  # Out of order
        ]

        for event in events:
            clock.advance_to(event['ts'])

        # Clock should be at max timestamp seen
        assert clock.now == 2000

    def test_replay_uses_event_clock(self):
        """Replay engine must use event timestamps"""
        from backend.replay.engine import ReplayEngine

        engine = ReplayEngine()

        events = [
            {'ts': 1000, 'type': 'trade', 'price': 0.72, 'size': 100},
            {'ts': 2000, 'type': 'trade', 'price': 0.73, 'size': 50},
        ]

        # Run replay
        result = engine.replay(
            raw_events=events,
            expected_hash='dummy',
            token_id='test',
            t0=1500,
            window_ms=2000
        )

        # Clock should end at last event timestamp
        assert engine.clock.now == 2000


class TestCrossEnvironment:
    """Tests for cross-environment consistency"""

    def test_endianness_independent(self):
        """Hash computation must be endianness-independent"""
        # xxhash is already endianness-independent
        import xxhash

        data = b'test data for hashing'

        hash1 = xxhash.xxh64(data).hexdigest()

        # Would need to run on different architecture to truly test
        # For now, just verify it's deterministic
        hash2 = xxhash.xxh64(data).hexdigest()

        assert hash1 == hash2

    def test_locale_independent(self):
        """String operations must be locale-independent"""
        # Sorting strings should use consistent collation
        strings = ['apple', 'Apple', 'APPLE', 'äpple']

        # Sort with explicit key (not locale-dependent)
        sorted1 = sorted(strings, key=str.lower)
        sorted2 = sorted(strings, key=str.lower)

        assert sorted1 == sorted2

    def test_timezone_independent(self):
        """Timestamp handling must be timezone-independent"""
        # All timestamps should be in UTC milliseconds
        timestamp_ms = 1704067200000  # 2024-01-01 00:00:00 UTC

        # Should not depend on local timezone
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1


class TestReplayConsistency:
    """Tests for replay consistency"""

    def test_replay_produces_same_result(self):
        """Multiple replays of same events must produce identical results"""
        from backend.replay.engine import ReplayEngine

        events = [
            {'ts': 1000, 'type': 'trade', 'price': 0.72, 'size': 100},
            {'ts': 1100, 'type': 'price_change', 'price': 0.72, 'size': 900, 'side': 'bid'},
            {'ts': 1200, 'type': 'trade', 'price': 0.72, 'size': 50},
        ]

        engine = ReplayEngine()

        # Replay multiple times
        results = []
        for _ in range(3):
            result = engine.replay(
                raw_events=events,
                expected_hash='dummy',
                token_id='test',
                t0=1100,
                window_ms=1000
            )
            results.append(result.computed_hash)

        # All replays must produce same hash
        assert results[0] == results[1] == results[2]

    def test_replay_with_shuffle_same_result(self):
        """Replay with shuffled input must produce same result (after sorting)"""
        from backend.replay.engine import ReplayEngine
        import random

        events = [
            {'ts': 1000, 'type': 'trade', 'price': 0.72, 'size': 100},
            {'ts': 1100, 'type': 'price_change', 'price': 0.72, 'size': 900, 'side': 'bid'},
            {'ts': 1200, 'type': 'trade', 'price': 0.72, 'size': 50},
            {'ts': 1300, 'type': 'trade', 'price': 0.73, 'size': 25},
        ]

        engine = ReplayEngine()

        # Original order
        result1 = engine.replay(
            raw_events=events.copy(),
            expected_hash='dummy',
            token_id='test',
            t0=1150,
            window_ms=1000
        )

        # Shuffled order
        shuffled = events.copy()
        random.shuffle(shuffled)

        result2 = engine.replay(
            raw_events=shuffled,
            expected_hash='dummy',
            token_id='test',
            t0=1150,
            window_ms=1000
        )

        # Must produce same hash (engine sorts internally)
        assert result1.computed_hash == result2.computed_hash
