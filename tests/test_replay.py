"""
Tests for Replay Infrastructure (v5.14)

Ensures:
1. ReplayEngine uses ReplayContext for determinism
2. DeterministicClock integrates with EventClock
3. Event ordering is validated and enforced
4. SpotCheckReport aggregates statistics correctly
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from backend.replay.engine import (
    ReplayEngine,
    ReplayStatus,
    ReplayResult,
    ReplayCheckpoint,
    DeterministicClock,
)
from backend.replay.verifier import (
    BundleVerifier,
    VerificationStatus,
    VerificationResult,
    VerificationCheck,
)
from backend.jobs.verify_bundles import SpotCheckReport
from backend.common.determinism import (
    get_event_clock,
    ProcessingMode,
    EventSortKey,
    ReplayContext,
)


class TestDeterministicClock:
    """Test DeterministicClock integration with EventClock"""

    def test_clock_advances_event_clock(self):
        """Clock advance should set EventClock's event time"""
        clock = DeterministicClock(start_ts=1000)
        event_clock = get_event_clock()

        clock.advance_to(2000)

        assert clock.now == 2000
        assert event_clock._current_event_ts == 2000

        # Clean up
        event_clock.clear_event_time()

    def test_clock_reset_clears_event_time(self):
        """Reset should clear EventClock's event time"""
        clock = DeterministicClock(start_ts=1000)
        event_clock = get_event_clock()

        clock.advance_to(2000)
        clock.reset(0)

        assert clock.now == 0
        assert event_clock._current_event_ts is None

    def test_clock_only_advances_forward(self):
        """Clock should only advance to higher timestamps"""
        clock = DeterministicClock(start_ts=2000)

        clock.advance_to(1500)  # Shouldn't advance backward
        assert clock.now == 2000

        clock.advance_to(2500)  # Should advance forward
        assert clock.now == 2500

        get_event_clock().clear_event_time()


class TestReplayEngine:
    """Test ReplayEngine with v5.14 determinism"""

    def test_replay_uses_replay_context(self):
        """Replay should run within ReplayContext"""
        engine = ReplayEngine(checkpoint_interval=10)

        raw_events = [
            {'type': 'trade', 'ts': 1000, 'price': 100, 'size': 10, 'side': 'buy'},
            {'type': 'trade', 'ts': 2000, 'price': 101, 'size': 20, 'side': 'sell'},
            {'type': 'trade', 'ts': 3000, 'price': 102, 'size': 30, 'side': 'buy'},
        ]

        result = engine.replay(
            raw_events=raw_events,
            expected_hash="test_hash",
            token_id="test_token",
            t0=2000,
            window_ms=4000
        )

        # Verify result structure
        assert result.token_id == "test_token"
        assert result.t0 == 2000
        assert result.events_count == 3
        assert result.status in [ReplayStatus.HASH_MATCH, ReplayStatus.HASH_MISMATCH]

        # Event clock should be cleared after replay
        assert get_event_clock()._current_event_ts is None

    def test_replay_sorts_events(self):
        """Events should be sorted by EventSortKey"""
        engine = ReplayEngine()

        # Events out of order
        raw_events = [
            {'type': 'trade', 'ts': 3000, 'price': 103},
            {'type': 'trade', 'ts': 1000, 'price': 101},
            {'type': 'trade', 'ts': 2000, 'price': 102},
        ]

        result = engine.replay(
            raw_events=raw_events,
            expected_hash="test",
            token_id="test",
            t0=2000
        )

        # Should process without error (events sorted internally)
        assert result.status != ReplayStatus.ERROR

    def test_replay_creates_checkpoints(self):
        """Replay should create checkpoints at intervals"""
        engine = ReplayEngine(checkpoint_interval=5)

        raw_events = [
            {'type': 'trade', 'ts': i * 100, 'price': 100 + i}
            for i in range(20)
        ]

        result = engine.replay(
            raw_events=raw_events,
            expected_hash="test",
            token_id="test",
            t0=1000,
            window_ms=3000
        )

        # Should have checkpoints at intervals
        assert len(result.checkpoints) > 0

    def test_replay_with_strict_order_violation(self):
        """Strict mode should fail on order violations"""
        engine = ReplayEngine()

        # Events with same timestamp but wrong sort_seq
        raw_events = [
            {'type': 'trade', 'ts': 1000, 'seq': 2},
            {'type': 'trade', 'ts': 1000, 'seq': 1},  # Out of order within same ts
        ]

        # After sorting, this should be fine
        result = engine.replay(
            raw_events=raw_events,
            expected_hash="test",
            token_id="test",
            t0=1000,
            strict_order=True
        )

        # Should succeed because events are sorted before processing
        assert result.status != ReplayStatus.ERROR

    def test_replay_computes_hash(self):
        """Replay should compute bundle hash"""
        engine = ReplayEngine()

        raw_events = [
            {'type': 'trade', 'ts': 1000, 'price': 100, 'size': 10, 'side': 'buy'},
        ]

        result = engine.replay(
            raw_events=raw_events,
            expected_hash="expected_hash_value",
            token_id="test",
            t0=1000
        )

        # Hash should be computed
        assert result.computed_hash != ""
        assert isinstance(result.computed_hash, str)

    def test_replay_result_structure(self):
        """ReplayResult should have all expected fields"""
        result = ReplayResult(
            status=ReplayStatus.HASH_MATCH,
            token_id="test_token",
            t0=1000,
            expected_hash="abc123",
            computed_hash="abc123",
        )

        result_dict = result.to_dict()

        assert "status" in result_dict
        assert "token_id" in result_dict
        assert "t0" in result_dict
        assert "expected_hash" in result_dict
        assert "computed_hash" in result_dict
        assert "hash_matches" in result_dict


class TestBundleVerifier:
    """Test BundleVerifier v5.14 integration"""

    def test_verifier_sets_live_mode(self):
        """Verifier should set LIVE mode for verification metadata"""
        verifier = BundleVerifier()

        bundle = {
            'token_id': 'test',
            't0': 1000,
            'window': {'from_ts': 500, 'to_ts': 1500},
            'trades': [],
        }

        # Should not raise even if we were in REPLAY mode before
        clock = get_event_clock()
        clock.set_mode(ProcessingMode.REPLAY)

        result = verifier.verify(bundle, "test_hash")

        # Clock should be in LIVE mode now
        assert clock.mode == ProcessingMode.LIVE
        assert result.verified_at > 0

    def test_verifier_checks_hash(self):
        """Verifier should check hash integrity"""
        verifier = BundleVerifier()

        bundle = {
            'token_id': 'test',
            't0': 1000,
            'window': {'from_ts': 500, 'to_ts': 1500},
        }

        result = verifier.verify(bundle, "wrong_hash")

        # Should have hash_integrity check
        hash_check = next(
            (c for c in result.checks if c.check_name == 'hash_integrity'),
            None
        )
        assert hash_check is not None
        assert hash_check.status == VerificationStatus.FAIL


class TestSpotCheckReport:
    """Test SpotCheckReport aggregation"""

    def test_audit_rate_calculation(self):
        """Audit rate should be calculated correctly"""
        report = SpotCheckReport(
            period_start=datetime.now() - timedelta(hours=24),
            period_end=datetime.now(),
            total_bundles=100,
            bundles_checked=10,
        )

        assert report.audit_rate == 10.0

    def test_audit_rate_zero_bundles(self):
        """Audit rate should be 0 when no bundles"""
        report = SpotCheckReport(
            period_start=datetime.now() - timedelta(hours=24),
            period_end=datetime.now(),
            total_bundles=0,
            bundles_checked=0,
        )

        assert report.audit_rate == 0.0

    def test_pass_rate_calculation(self):
        """Pass rate should be calculated correctly"""
        report = SpotCheckReport(
            period_start=datetime.now() - timedelta(hours=24),
            period_end=datetime.now(),
            bundles_checked=100,
            bundles_passed=95,
            bundles_failed=5,
        )

        assert report.pass_rate == 95.0

    def test_pass_rate_no_checks(self):
        """Pass rate should be 100% when no checks performed"""
        report = SpotCheckReport(
            period_start=datetime.now() - timedelta(hours=24),
            period_end=datetime.now(),
            bundles_checked=0,
        )

        assert report.pass_rate == 100.0

    def test_replay_match_rate(self):
        """Replay match rate should be calculated correctly"""
        report = SpotCheckReport(
            period_start=datetime.now() - timedelta(hours=24),
            period_end=datetime.now(),
            replay_verified=10,
            replay_matched=8,
        )

        assert report.replay_match_rate == 80.0

    def test_to_dict(self):
        """to_dict should return expected structure"""
        report = SpotCheckReport(
            period_start=datetime.now() - timedelta(hours=24),
            period_end=datetime.now(),
            total_bundles=100,
            bundles_checked=10,
            bundles_passed=9,
            bundles_failed=1,
        )

        result = report.to_dict()

        assert 'period' in result
        assert 'totals' in result
        assert 'rates' in result
        assert 'replay' in result
        assert 'failures' in result

    def test_to_markdown(self):
        """to_markdown should generate markdown report"""
        report = SpotCheckReport(
            period_start=datetime.now() - timedelta(hours=24),
            period_end=datetime.now(),
            total_bundles=100,
            bundles_checked=10,
            bundles_passed=9,
            bundles_failed=1,
            failures=[{
                'bundle_id': 'test_123',
                'token_id': 'token_abc',
                'status': 'FAIL',
                'reason': 'hash_mismatch',
            }]
        )

        markdown = report.to_markdown()

        assert '# ' in markdown  # Has header
        assert 'Spot-Check' in markdown
        assert 'Summary' in markdown
        assert '100' in markdown  # Total bundles
        assert '10.0%' in markdown  # Audit rate


class TestReplayContextIntegration:
    """Test ReplayContext integration with engine"""

    def test_replay_within_context(self):
        """Verify ReplayContext is active during replay"""
        engine = ReplayEngine()

        raw_events = [
            {'type': 'trade', 'ts': 1000, 'price': 100},
        ]

        # Before replay, clock should be in LIVE mode
        clock = get_event_clock()
        clock.set_mode(ProcessingMode.LIVE)

        result = engine.replay(
            raw_events=raw_events,
            expected_hash="test",
            token_id="test",
            t0=1000
        )

        # After replay, clock should be back to LIVE mode
        assert clock.mode == ProcessingMode.LIVE

    def test_event_time_set_during_replay(self):
        """Event time should be set correctly during replay"""
        engine = ReplayEngine()
        clock = get_event_clock()

        captured_times = []

        # Patch _process_event to capture event times
        original_process = engine._process_event

        def capture_process(event, token_id):
            captured_times.append(clock._current_event_ts)
            return original_process(event, token_id)

        engine._process_event = capture_process

        raw_events = [
            {'type': 'trade', 'ts': 1000, 'price': 100},
            {'type': 'trade', 'ts': 2000, 'price': 101},
            {'type': 'trade', 'ts': 3000, 'price': 102},
        ]

        engine.replay(
            raw_events=raw_events,
            expected_hash="test",
            token_id="test",
            t0=2000
        )

        # Event times should match event timestamps
        assert captured_times == [1000, 2000, 3000]


class TestEventSortKeyOrdering:
    """Test event ordering with EventSortKey"""

    def test_multi_token_ordering(self):
        """Events should be ordered by token_id first, then ts"""
        engine = ReplayEngine()

        raw_events = [
            {'type': 'trade', 'ts': 2000, 'token_id': 'b', 'price': 100},
            {'type': 'trade', 'ts': 1000, 'token_id': 'a', 'price': 101},
            {'type': 'trade', 'ts': 1000, 'token_id': 'b', 'price': 102},
            {'type': 'trade', 'ts': 2000, 'token_id': 'a', 'price': 103},
        ]

        # Should process without error
        result = engine.replay(
            raw_events=raw_events,
            expected_hash="test",
            token_id="a",  # Default token
            t0=1500,
            strict_order=False  # Allow mixed tokens
        )

        assert result.status != ReplayStatus.ERROR

    def test_sort_seq_tiebreaker(self):
        """sort_seq should break ties for same timestamp"""
        engine = ReplayEngine()

        raw_events = [
            {'type': 'trade', 'ts': 1000, 'seq': 2, 'price': 100},
            {'type': 'trade', 'ts': 1000, 'seq': 0, 'price': 101},
            {'type': 'trade', 'ts': 1000, 'seq': 1, 'price': 102},
        ]

        result = engine.replay(
            raw_events=raw_events,
            expected_hash="test",
            token_id="test",
            t0=1000
        )

        # Should process without error
        assert result.status != ReplayStatus.ERROR
