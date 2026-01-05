"""
Tests for Determinism Infrastructure (v5.13)

Ensures:
1. EventClock enforces event-time-only in REPLAY mode
2. ReplayContext validates sort order
3. TokenEventQueue ensures serial processing
4. EventSortKey provides canonical ordering
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
import threading
import time


class TestEventSortKey:
    """Test EventSortKey ordering"""

    def test_same_token_ordered_by_timestamp(self):
        """Events for same token should be ordered by timestamp"""
        from backend.common.determinism import EventSortKey

        k1 = EventSortKey("token_a", 1000, 0)
        k2 = EventSortKey("token_a", 2000, 0)
        k3 = EventSortKey("token_a", 1500, 0)

        assert k1 < k2
        assert k1 < k3
        assert k3 < k2

    def test_same_timestamp_ordered_by_sort_seq(self):
        """Same timestamp should use sort_seq as tiebreaker"""
        from backend.common.determinism import EventSortKey

        k1 = EventSortKey("token_a", 1000, 0)
        k2 = EventSortKey("token_a", 1000, 1)
        k3 = EventSortKey("token_a", 1000, 2)

        assert k1 < k2
        assert k2 < k3

    def test_different_tokens_ordered_by_token_id(self):
        """Different tokens should be ordered by token_id"""
        from backend.common.determinism import EventSortKey

        k1 = EventSortKey("token_a", 1000, 0)
        k2 = EventSortKey("token_b", 1000, 0)

        assert k1 < k2

    def test_equality(self):
        """Test equality comparison"""
        from backend.common.determinism import EventSortKey

        k1 = EventSortKey("token_a", 1000, 0)
        k2 = EventSortKey("token_a", 1000, 0)
        k3 = EventSortKey("token_a", 1000, 1)

        assert k1 == k2
        assert k1 != k3

    def test_to_tuple(self):
        """Test tuple conversion"""
        from backend.common.determinism import EventSortKey

        k = EventSortKey("token_a", 1000, 5)
        assert k.to_tuple() == ("token_a", 1000, 5)


class TestEventClock:
    """Test EventClock singleton"""

    def test_singleton_instance(self):
        """EventClock should be a singleton"""
        from backend.common.determinism import EventClock, get_event_clock

        clock1 = get_event_clock()
        clock2 = get_event_clock()
        clock3 = EventClock()

        assert clock1 is clock2
        assert clock1 is clock3

    def test_event_time_context(self):
        """Test event time context manager"""
        from backend.common.determinism import get_event_clock, ProcessingMode

        clock = get_event_clock()
        clock.set_mode(ProcessingMode.REPLAY)

        with clock.event_context(5000):
            assert clock.now_ms() == 5000

        # After context, event time should be cleared
        with pytest.raises(Exception):  # DeterminismError
            clock.now_ms()

        # Reset to LIVE mode for other tests
        clock.set_mode(ProcessingMode.LIVE)

    def test_replay_mode_requires_event_time(self):
        """In REPLAY mode, now_ms should fail without event time"""
        from backend.common.determinism import get_event_clock, ProcessingMode, DeterminismError

        clock = get_event_clock()
        clock.set_mode(ProcessingMode.REPLAY)
        clock.clear_event_time()

        with pytest.raises(DeterminismError):
            clock.now_ms(context="test")

        # Reset
        clock.set_mode(ProcessingMode.LIVE)

    def test_live_mode_allows_wall_clock(self):
        """In LIVE mode, now_ms should return wall clock with warning"""
        from backend.common.determinism import get_event_clock, ProcessingMode

        clock = get_event_clock()
        clock.set_mode(ProcessingMode.LIVE)
        clock.clear_event_time()

        # Should not raise, but may warn
        ts = clock.now_ms(context="test_live")
        assert ts > 0
        assert ts < int(time.time() * 1000) + 1000  # Within 1 second


class TestReplayContext:
    """Test ReplayContext manager"""

    def test_context_sets_replay_mode(self):
        """ReplayContext should set REPLAY mode"""
        from backend.common.determinism import ReplayContext, get_event_clock, ProcessingMode

        clock = get_event_clock()
        clock.set_mode(ProcessingMode.LIVE)

        with ReplayContext() as ctx:
            assert clock.mode == ProcessingMode.REPLAY

        assert clock.mode == ProcessingMode.LIVE

    def test_process_event_sets_time(self):
        """process_event should set event time"""
        from backend.common.determinism import ReplayContext, get_event_clock

        clock = get_event_clock()

        with ReplayContext() as ctx:
            with ctx.process_event(1000, "token_a"):
                assert clock.now_ms() == 1000

            with ctx.process_event(2000, "token_a"):
                assert clock.now_ms() == 2000

    def test_sort_order_validation(self):
        """ReplayContext should detect sort order violations"""
        from backend.common.determinism import ReplayContext, DeterminismError

        with ReplayContext(strict=True) as ctx:
            with ctx.process_event(1000, "token_a"):
                pass

            # Out of order should raise
            with pytest.raises(DeterminismError):
                with ctx.process_event(500, "token_a"):
                    pass

    def test_non_strict_mode_records_violations(self):
        """Non-strict mode should record but not raise"""
        from backend.common.determinism import ReplayContext

        with ReplayContext(strict=False) as ctx:
            with ctx.process_event(1000, "token_a"):
                pass

            with ctx.process_event(500, "token_a"):
                pass  # Should not raise

            assert ctx.stats['sort_violations'] == 1

    def test_stats_tracking(self):
        """Context should track processing stats"""
        from backend.common.determinism import ReplayContext

        with ReplayContext(strict=False) as ctx:
            for i in range(5):
                with ctx.process_event(i * 100, "token_a"):
                    pass

            assert ctx.stats['events_processed'] == 5


class TestTokenEventQueue:
    """Test TokenEventQueue serial processing"""

    def test_events_processed_in_order(self):
        """Events should be processed in sort key order"""
        from backend.common.determinism import TokenEventQueue

        queue = TokenEventQueue()
        results = []

        # Enqueue out of order
        queue.enqueue("token_a", "event_3", 3000)
        queue.enqueue("token_a", "event_1", 1000)
        queue.enqueue("token_a", "event_2", 2000)

        def handler(event):
            results.append(event)

        queue.process_token("token_a", handler)

        # Should be processed in timestamp order
        assert results == ["event_1", "event_2", "event_3"]

    def test_different_tokens_independent(self):
        """Different tokens should have independent queues"""
        from backend.common.determinism import TokenEventQueue

        queue = TokenEventQueue()
        results_a = []
        results_b = []

        queue.enqueue("token_a", "a1", 1000)
        queue.enqueue("token_b", "b1", 500)
        queue.enqueue("token_a", "a2", 2000)

        queue.process_token("token_a", lambda e: results_a.append(e))
        queue.process_token("token_b", lambda e: results_b.append(e))

        assert results_a == ["a1", "a2"]
        assert results_b == ["b1"]


class TestAsyncTokenEventQueue:
    """Test AsyncTokenEventQueue"""

    @pytest.mark.asyncio
    async def test_async_processing(self):
        """Test async event processing"""
        from backend.common.determinism import AsyncTokenEventQueue

        queue = AsyncTokenEventQueue()
        results = []

        await queue.enqueue("token_a", "event_2", 2000)
        await queue.enqueue("token_a", "event_1", 1000)

        async def handler(event):
            results.append(event)

        await queue.process_token("token_a", handler)

        assert results == ["event_1", "event_2"]


class TestDeterministicNow:
    """Test deterministic_now helper"""

    def test_returns_event_time_when_set(self):
        """Should return event time when set"""
        from backend.common.determinism import deterministic_now, get_event_clock, ProcessingMode

        clock = get_event_clock()
        clock.set_mode(ProcessingMode.LIVE)
        clock.set_event_time(12345)

        assert deterministic_now("test") == 12345

        clock.clear_event_time()


class TestValidateEventOrder:
    """Test validate_event_order utility"""

    def test_valid_order_returns_empty(self):
        """Valid order should return empty violations list"""
        from backend.common.determinism import validate_event_order, EventSortKey

        events = [
            {"token_id": "a", "ts": 1000, "seq": 0},
            {"token_id": "a", "ts": 2000, "seq": 0},
            {"token_id": "a", "ts": 3000, "seq": 0},
        ]

        def key_fn(e):
            return EventSortKey(e["token_id"], e["ts"], e["seq"])

        violations = validate_event_order(events, key_fn)
        assert violations == []

    def test_invalid_order_returns_violations(self):
        """Invalid order should return violation descriptions"""
        from backend.common.determinism import validate_event_order, EventSortKey

        events = [
            {"token_id": "a", "ts": 2000, "seq": 0},
            {"token_id": "a", "ts": 1000, "seq": 0},  # Out of order
            {"token_id": "a", "ts": 3000, "seq": 0},
        ]

        def key_fn(e):
            return EventSortKey(e["token_id"], e["ts"], e["seq"])

        violations = validate_event_order(events, key_fn)
        assert len(violations) == 1
        assert "1000" in violations[0]


class TestSortEvents:
    """Test sort_events utility"""

    def test_sorts_by_key(self):
        """Should sort events by EventSortKey"""
        from backend.common.determinism import sort_events, EventSortKey

        events = [
            {"token_id": "a", "ts": 3000},
            {"token_id": "a", "ts": 1000},
            {"token_id": "a", "ts": 2000},
        ]

        def key_fn(e):
            return EventSortKey(e["token_id"], e["ts"], 0)

        sorted_events = sort_events(events, key_fn)

        assert [e["ts"] for e in sorted_events] == [1000, 2000, 3000]


class TestIntegration:
    """Integration tests for determinism infrastructure"""

    def test_replay_produces_consistent_results(self):
        """Same events replayed should produce same results"""
        from backend.common.determinism import ReplayContext, get_event_clock

        events = [
            {"token_id": "token_a", "ts": 1000, "value": 10},
            {"token_id": "token_a", "ts": 2000, "value": 20},
            {"token_id": "token_a", "ts": 3000, "value": 30},
        ]

        def process_events(events):
            results = []
            with ReplayContext() as ctx:
                for e in events:
                    with ctx.process_event(e["ts"], e["token_id"]):
                        # Simulate processing that uses event time
                        clock = get_event_clock()
                        results.append((clock.now_ms(), e["value"]))
            return results

        # Run twice
        results1 = process_events(events)
        results2 = process_events(events)

        # Should produce identical results
        assert results1 == results2
        assert results1 == [(1000, 10), (2000, 20), (3000, 30)]

    def test_multi_token_replay(self):
        """Replay with multiple tokens should maintain per-token ordering"""
        from backend.common.determinism import ReplayContext, sort_events, EventSortKey

        events = [
            {"token_id": "token_b", "ts": 1500},
            {"token_id": "token_a", "ts": 1000},
            {"token_id": "token_a", "ts": 2000},
            {"token_id": "token_b", "ts": 1000},
        ]

        def key_fn(e):
            return EventSortKey(e["token_id"], e["ts"], 0)

        sorted_events = sort_events(events, key_fn)

        # Check ordering: first by token_id, then by ts
        expected_order = [
            ("token_a", 1000),
            ("token_a", 2000),
            ("token_b", 1000),
            ("token_b", 1500),
        ]

        actual_order = [(e["token_id"], e["ts"]) for e in sorted_events]
        assert actual_order == expected_order
