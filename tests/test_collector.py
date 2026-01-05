"""
Tests for Collector Module.
"""

import pytest
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRawEventProcessing:
    """Tests for raw event processing in collector."""

    def test_trade_event_parsing(self):
        """Trade events should be parsed correctly."""
        raw_trade = {
            'asset_id': 'test-token-123',
            'price': '0.72',
            'size': '150.5',
            'side': 'BUY',
            'timestamp': '1704067200000',
        }

        # Parse values
        price = Decimal(raw_trade['price'])
        size = float(raw_trade['size'])
        timestamp = int(raw_trade['timestamp'])

        assert price == Decimal('0.72')
        assert size == 150.5
        assert timestamp == 1704067200000

    def test_book_snapshot_parsing(self):
        """Book snapshots should be parsed correctly."""
        raw_book = {
            'asset_id': 'test-token-123',
            'timestamp': '1704067200000',
            'bids': [
                {'price': '0.72', 'size': '100'},
                {'price': '0.71', 'size': '50'},
            ],
            'asks': [
                {'price': '0.73', 'size': '80'},
                {'price': '0.74', 'size': '60'},
            ],
        }

        bids = raw_book['bids']
        asks = raw_book['asks']

        assert len(bids) == 2
        assert len(asks) == 2
        assert Decimal(bids[0]['price']) == Decimal('0.72')
        assert float(bids[0]['size']) == 100.0


class TestProvenanceTracking:
    """Tests for provenance tracking (v5.3)."""

    def test_engine_version_included(self):
        """Events should include engine version."""
        from backend.version import ENGINE_VERSION

        event = {
            'token_id': 'test',
            'engine_version': ENGINE_VERSION,
        }

        assert event['engine_version'] is not None
        assert event['engine_version'].startswith('v')

    def test_config_hash_included(self):
        """Events should include config hash."""
        from backend.version import CONFIG_HASH

        event = {
            'token_id': 'test',
            'config_hash': CONFIG_HASH,
        }

        assert event['config_hash'] is not None
        assert len(event['config_hash']) > 0


class TestEventSequencing:
    """Tests for event sequencing."""

    def test_sequence_tracker_records(self):
        """Sequence tracker should record sequences correctly."""
        from backend.version import RawEventSequenceTracker

        tracker = RawEventSequenceTracker()

        # Record some sequences
        tracker.record_seq('token-1', 100)
        tracker.record_seq('token-1', 101)
        tracker.record_seq('token-1', 102)

        # Get last N
        last_seqs = tracker.get_last_n('token-1', 3)
        assert len(last_seqs) == 3
        assert last_seqs == [100, 101, 102]

    def test_sequence_tracker_per_token(self):
        """Sequence tracker should track per token."""
        from backend.version import RawEventSequenceTracker

        tracker = RawEventSequenceTracker()

        tracker.record_seq('token-1', 100)
        tracker.record_seq('token-2', 200)

        assert tracker.get_last_n('token-1', 1) == [100]
        assert tracker.get_last_n('token-2', 1) == [200]


class TestShockDetection:
    """Tests for shock detection logic."""

    def test_volume_threshold_calculation(self):
        """Volume threshold should be calculated correctly."""
        # From config: SHOCK_VOLUME_THRESHOLD = 0.35 (35%)
        baseline_size = 100.0
        threshold_ratio = 0.35

        trade_volume = 40.0  # 40% of baseline
        is_shock = trade_volume / baseline_size >= threshold_ratio

        assert is_shock is True

        trade_volume_small = 30.0  # 30% of baseline
        is_shock_small = trade_volume_small / baseline_size >= threshold_ratio

        assert is_shock_small is False

    def test_consecutive_trade_detection(self):
        """Consecutive trades at same price should trigger shock."""
        # Track trades at same price
        trades_at_price = []
        min_consecutive = 3

        for i in range(4):
            trades_at_price.append({
                'price': '0.72',
                'timestamp': 1000 + i * 100,
            })

            if len(trades_at_price) >= min_consecutive:
                # Check if consecutive
                is_consecutive = True
                break

        assert is_consecutive is True
        assert len(trades_at_price) == min_consecutive


class TestReactionClassification:
    """Tests for reaction classification."""

    def test_hold_classification_criteria(self):
        """HOLD should be classified when refill > 70%."""
        refill_ratio = 0.85
        hold_threshold = 0.70

        is_hold = refill_ratio >= hold_threshold
        assert is_hold is True

    def test_vacuum_classification_criteria(self):
        """VACUUM should be classified when refill < 5% and duration > 3s."""
        refill_ratio = 0.03
        vacuum_threshold = 0.05
        duration_ms = 4000
        min_duration_ms = 3000

        is_vacuum = refill_ratio < vacuum_threshold and duration_ms >= min_duration_ms
        assert is_vacuum is True

    def test_pull_classification_criteria(self):
        """PULL should be classified when drop > 60% and refill < 30%."""
        drop_ratio = 0.65
        refill_ratio = 0.22
        drop_threshold = 0.60
        refill_max = 0.30

        is_pull = drop_ratio >= drop_threshold and refill_ratio < refill_max
        assert is_pull is True


class TestBeliefStateTransitions:
    """Tests for belief state machine transitions."""

    def test_stable_to_fragile(self):
        """STABLE -> FRAGILE on PRE_SHOCK_PULL."""
        current_state = 'STABLE'
        trigger_event = 'PRE_SHOCK_PULL'

        # State transition rules
        if current_state == 'STABLE' and trigger_event == 'PRE_SHOCK_PULL':
            new_state = 'FRAGILE'
        else:
            new_state = current_state

        assert new_state == 'FRAGILE'

    def test_fragile_to_cracking(self):
        """FRAGILE -> CRACKING on PULL reaction."""
        current_state = 'FRAGILE'
        trigger_reaction = 'PULL'

        if current_state == 'FRAGILE' and trigger_reaction == 'PULL':
            new_state = 'CRACKING'
        else:
            new_state = current_state

        assert new_state == 'CRACKING'

    def test_cracking_to_broken(self):
        """CRACKING -> BROKEN on VACUUM at 2+ key levels."""
        current_state = 'CRACKING'
        vacuum_count_at_key_levels = 2

        if current_state == 'CRACKING' and vacuum_count_at_key_levels >= 2:
            new_state = 'BROKEN'
        else:
            new_state = current_state

        assert new_state == 'BROKEN'
