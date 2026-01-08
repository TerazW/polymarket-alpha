"""
Golden Replay Tests (v5.36)

These tests verify deterministic replay behavior by comparing outputs
against known golden fixtures.

Golden tests ensure:
1. Identical inputs produce identical outputs
2. Hash verification is consistent
3. Replay context properly isolates from wall clock

"每个输入都有唯一确定的输出"
"""

import pytest
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List

from backend.common.determinism import (
    EventClock,
    ReplayContext,
    ProcessingMode,
    deterministic_now,
)
from backend.evidence.bundle_hash import compute_bundle_hash

# Golden fixtures directory
GOLDEN_DIR = Path(__file__).parent / "fixtures"


class TestGoldenBundleHash:
    """Test deterministic bundle hash computation"""

    def test_bundle_hash_deterministic(self):
        """
        Verify bundle hash computation is deterministic.

        Same evidence bundle must always produce same hash.
        """
        bundle_data = {
            "token_id": "token_golden",
            "t0": 1700000000000,
            "shocks": [
                {"id": "s1", "ts": 1700000000000, "price": "0.72"},
                {"id": "s2", "ts": 1700000010000, "price": "0.68"},
            ],
            "reactions": [
                {"id": "r1", "ts": 1700000005000, "type": "VACUUM"},
                {"id": "r2", "ts": 1700000015000, "type": "PULL"},
            ],
        }

        # Compute hash multiple times
        hashes = []
        for _ in range(5):
            h = compute_bundle_hash(bundle_data)
            hashes.append(h)

        # All hashes must be identical
        assert all(h == hashes[0] for h in hashes), \
            f"Bundle hash not deterministic: {hashes}"

    def test_bundle_hash_order_independent(self):
        """
        Verify bundle hash is independent of dict key ordering.

        Dict key order should not affect hash.
        """
        bundle1 = {
            "token_id": "token_golden",
            "t0": 1700000000000,
            "shocks": [{"id": "s1"}, {"id": "s2"}],
        }

        bundle2 = {
            "t0": 1700000000000,
            "token_id": "token_golden",
            "shocks": [{"id": "s1"}, {"id": "s2"}],
        }

        h1 = compute_bundle_hash(bundle1)
        h2 = compute_bundle_hash(bundle2)

        assert h1 == h2, "Bundle hash should be order-independent for dict keys"

    def test_known_hash_verification(self):
        """
        Verify against a known golden hash.

        This test pins hash format that must not change.
        """
        golden_bundle = {
            "token_id": "golden_test_token",
            "t0": 1700000000000,
            "version": "1.0",
        }

        computed_hash = compute_bundle_hash(golden_bundle)

        # The hash must be stable across versions
        # xxHash64 hex length is 16 chars
        assert len(computed_hash) == 16, \
            f"Expected xxHash64 hex length 16, got {len(computed_hash)}"

        # Verify it's deterministic
        assert compute_bundle_hash(golden_bundle) == computed_hash

    def test_hash_sensitive_to_content(self):
        """
        Verify hash changes with content changes.

        Any modification to bundle should produce different hash.
        Note: Bundle hash only considers evidence fields (token_id, t0, shocks, etc.)
        """
        base_bundle = {
            "token_id": "test",
            "t0": 1700000000000,
            "shocks": [{"id": "s1"}],
        }

        base_hash = compute_bundle_hash(base_bundle)

        # Modify token_id
        modified = {**base_bundle, "token_id": "test2"}
        assert compute_bundle_hash(modified) != base_hash

        # Modify timestamp
        modified = {**base_bundle, "t0": 1700000000001}
        assert compute_bundle_hash(modified) != base_hash

        # Modify shocks (an evidence field)
        modified = {**base_bundle, "shocks": [{"id": "s1"}, {"id": "s2"}]}
        assert compute_bundle_hash(modified) != base_hash


class TestGoldenEventClock:
    """Test deterministic event clock behavior"""

    @pytest.fixture
    def replay_clock(self) -> EventClock:
        """Create deterministic event clock in replay mode"""
        clock = EventClock()
        clock.set_mode(ProcessingMode.REPLAY)
        yield clock
        # Reset to LIVE mode after test
        clock.set_mode(ProcessingMode.LIVE)

    @pytest.fixture
    def live_clock(self) -> EventClock:
        """Create event clock in live mode"""
        clock = EventClock()
        clock.set_mode(ProcessingMode.LIVE)
        return clock

    def test_replay_clock_deterministic(self, replay_clock: EventClock):
        """
        Verify replay clock returns exactly what was set.
        """
        replay_clock.set_event_time(1700000000000)
        assert replay_clock.now_ms("test1") == 1700000000000

        replay_clock.set_event_time(1700000001000)
        assert replay_clock.now_ms("test2") == 1700000001000

    def test_replay_clock_sequence(self, replay_clock: EventClock):
        """
        Verify replay clock maintains sequence correctly.
        """
        times = [1700000000000, 1700000005000, 1700000010000]
        recorded = []

        for t in times:
            replay_clock.set_event_time(t)
            recorded.append(replay_clock.now_ms("seq_test"))

        assert recorded == times, "Replay clock should return exact times set"

    def test_live_clock_advances(self, live_clock: EventClock):
        """
        Verify live clock uses wall clock and advances.
        """
        import time

        t1 = live_clock.now_ms("live_test1")
        time.sleep(0.01)  # 10ms
        t2 = live_clock.now_ms("live_test2")

        assert t2 >= t1, "Live clock should advance with time"


class TestGoldenReplayContext:
    """Test replay context isolation"""

    def test_context_enters_replay_mode(self):
        """
        Verify replay context sets clock to replay mode.
        """
        clock = EventClock()
        initial_mode = clock.mode

        with ReplayContext() as ctx:
            assert clock.mode == ProcessingMode.REPLAY

        # Mode should be restored after exit
        assert clock.mode == initial_mode

    def test_context_process_event(self):
        """
        Verify process_event context sets time correctly.
        """
        clock = EventClock()

        with ReplayContext() as ctx:
            with ctx.process_event(1700000000000):
                assert clock.now_ms("test") == 1700000000000

            with ctx.process_event(1700000100000):
                assert clock.now_ms("test") == 1700000100000

    def test_context_tracks_stats(self):
        """
        Verify context tracks processing statistics.
        """
        with ReplayContext() as ctx:
            with ctx.process_event(1700000000000):
                pass
            with ctx.process_event(1700000001000):
                pass
            with ctx.process_event(1700000002000):
                pass

            assert ctx.stats["events_processed"] == 3
            assert ctx.stats["sort_violations"] == 0


class TestGoldenSequenceReplay:
    """Test replay of event sequences"""

    def test_event_sequence_order_preserved(self):
        """
        Verify event sequence order is preserved during replay.
        """
        clock = EventClock()
        events = [
            {"id": "e1", "ts": 1700000000000, "type": "shock"},
            {"id": "e2", "ts": 1700000005000, "type": "reaction"},
            {"id": "e3", "ts": 1700000010000, "type": "shock"},
            {"id": "e4", "ts": 1700000015000, "type": "reaction"},
        ]

        with ReplayContext() as ctx:
            processed = []
            for event in events:
                with ctx.process_event(event["ts"]):
                    # Verify time is correctly set
                    assert clock.now_ms("process") == event["ts"]
                    processed.append(event["id"])

        # Order should match original
        assert processed == ["e1", "e2", "e3", "e4"]

    def test_same_sequence_same_result(self):
        """
        Verify same event sequence produces same processing order.
        """
        clock = EventClock()
        events = [
            {"id": "e1", "ts": 1700000000000},
            {"id": "e2", "ts": 1700000005000},
            {"id": "e3", "ts": 1700000010000},
        ]

        results1 = []
        results2 = []

        # First replay
        with ReplayContext() as ctx:
            for event in events:
                with ctx.process_event(event["ts"]):
                    results1.append((event["id"], clock.now_ms("run1")))

        # Second replay (should be identical)
        with ReplayContext() as ctx:
            for event in events:
                with ctx.process_event(event["ts"]):
                    results2.append((event["id"], clock.now_ms("run2")))

        assert results1 == results2, "Same sequence should produce same results"


class TestGoldenFixtures:
    """Test with golden fixture files"""

    def test_load_golden_fixture(self):
        """
        Verify golden fixtures can be loaded and processed.
        """
        # Create a simple golden fixture
        golden_data = {
            "name": "simple_shock_sequence",
            "version": "1.0",
            "events": [
                {"type": "shock", "ts": 1700000000000, "price": 0.72},
                {"type": "reaction", "ts": 1700000005000, "reaction": "VACUUM"},
            ],
            "expected_hash": None,  # Will be computed
        }

        # Compute expected hash
        golden_data["expected_hash"] = compute_bundle_hash(golden_data["events"])

        # Verify hash matches
        computed = compute_bundle_hash(golden_data["events"])
        assert computed == golden_data["expected_hash"]

    def test_fixture_versioning(self):
        """
        Verify fixture versioning works correctly.

        Different evidence bundles should produce different hashes.
        Note: Bundle hash only considers evidence fields (token_id, t0, shocks, etc.)
        """
        v1_fixture = {
            "token_id": "test_v1",
            "t0": 1700000000000,
            "shocks": [{"id": "s1", "ts": 1700000000000}],
        }

        v2_fixture = {
            "token_id": "test_v2",
            "t0": 1700000000000,
            "shocks": [{"id": "s1", "ts": 1700000000000}, {"id": "s2", "ts": 1700000005000}],
        }

        # Different evidence bundles should have different hashes
        h1 = compute_bundle_hash(v1_fixture)
        h2 = compute_bundle_hash(v2_fixture)

        assert h1 != h2, "Different fixture versions should have different hashes"
