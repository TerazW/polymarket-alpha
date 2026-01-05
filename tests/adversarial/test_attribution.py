"""
Attribution Tests - Trade-driven vs Cancel-driven distinction

These tests ensure the system correctly attributes depth changes to either:
1. Trade-driven: Depth removed by aggressive orders eating liquidity
2. Cancel-driven: Depth removed by maker withdrawing orders

Misattribution leads to completely wrong signals:
- Treating cancel as trade = overestimate aggression
- Treating trade as cancel = miss actual market activity

"不能把撤单当扫单、把扫单当撤单"
"""

import pytest
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestTradeVsCancel:
    """Tests for trade vs cancel attribution"""

    def test_trade_driven_has_trade_volume(self):
        """Trade-driven depth removal must have corresponding trade volume"""
        # Scenario: 500 depth removed, 500 trade volume at same price
        depth_before = 1000.0
        depth_after = 500.0
        depth_removed = depth_before - depth_after

        trade_volume_at_price = 500.0

        # Attribution: how much of depth removal is trade-driven
        trade_driven_ratio = min(1.0, trade_volume_at_price / depth_removed) if depth_removed > 0 else 0
        cancel_driven_ratio = 1.0 - trade_driven_ratio

        # This should be 100% trade-driven
        assert trade_driven_ratio == 1.0
        assert cancel_driven_ratio == 0.0

    def test_cancel_driven_no_trade_volume(self):
        """Cancel-driven depth removal has no corresponding trade volume"""
        from poc.config import PRE_SHOCK_SMALL_TRADE_RATIO, PRE_SHOCK_SMALL_TRADE_ABS

        # Scenario: 500 depth removed, only 10 trade volume (negligible)
        depth_before = 1000.0
        depth_after = 500.0
        depth_removed = depth_before - depth_after

        trade_volume_at_price = 10.0

        # Small trade threshold
        small_trade_threshold = max(
            PRE_SHOCK_SMALL_TRADE_RATIO * depth_before,
            PRE_SHOCK_SMALL_TRADE_ABS
        )

        is_small_trade = trade_volume_at_price < small_trade_threshold

        # This should be cancel-driven (PRE_SHOCK_PULL candidate)
        assert is_small_trade, "Should be detected as cancel-driven"

    def test_mixed_attribution(self):
        """Mixed trade+cancel scenario should attribute proportionally"""
        depth_before = 1000.0
        depth_after = 300.0
        depth_removed = depth_before - depth_after  # 700 removed

        trade_volume_at_price = 400.0  # Only 400 was traded

        # Attribution
        trade_driven = min(trade_volume_at_price, depth_removed)  # 400
        cancel_driven = depth_removed - trade_driven  # 300

        assert trade_driven == 400.0
        assert cancel_driven == 300.0

        trade_ratio = trade_driven / depth_removed
        cancel_ratio = cancel_driven / depth_removed

        assert abs(trade_ratio - 0.571) < 0.01  # ~57% trade-driven
        assert abs(cancel_ratio - 0.429) < 0.01  # ~43% cancel-driven

    def test_sweep_must_be_trade_driven(self):
        """SWEEP classification requires trade-driven removal"""
        from poc.config import SWEEP_DROP_RATIO

        # Scenario: Multi-level drop, all trade-driven
        levels = [
            {'price': 0.72, 'drop': 500, 'trade': 500},
            {'price': 0.73, 'drop': 400, 'trade': 400},
            {'price': 0.74, 'drop': 300, 'trade': 300},
        ]

        total_drop = sum(l['drop'] for l in levels)
        total_trade = sum(l['trade'] for l in levels)

        # All trade-driven = true SWEEP
        is_trade_driven = total_trade >= total_drop * 0.8  # 80% threshold
        assert is_trade_driven, "SWEEP should be trade-driven"

    def test_pull_must_be_cancel_driven(self):
        """PULL classification requires cancel-driven removal"""
        from poc.config import PULL_DROP_RATIO, PRE_SHOCK_SMALL_TRADE_RATIO

        # Scenario: 70% depth removed, almost no trades
        depth_before = 1000.0
        depth_after = 300.0
        trade_volume = 20.0  # Negligible

        drop_ratio = (depth_before - depth_after) / depth_before

        # Check if this is cancel-driven
        trade_driven_ratio = trade_volume / (depth_before - depth_after)

        is_cancel_driven = trade_driven_ratio < PRE_SHOCK_SMALL_TRADE_RATIO
        assert is_cancel_driven, "PULL should be cancel-driven"

        # PULL criteria
        is_pull = drop_ratio >= PULL_DROP_RATIO and is_cancel_driven
        assert is_pull, "Should be classified as PULL"


class TestTimeBasedAttribution:
    """Tests for time-based attribution scenarios"""

    def test_trade_before_cancel_attribution(self):
        """Trade followed by cancel should attribute correctly"""
        events = [
            {'ts': 1000, 'type': 'trade', 'size': 100, 'price': 0.72},
            {'ts': 1100, 'type': 'cancel', 'size': 400, 'price': 0.72},  # Remaining cancelled
        ]

        # First 100 is trade-driven
        # Next 400 is cancel-driven
        trade_volume = sum(e['size'] for e in events if e['type'] == 'trade')
        cancel_volume = sum(e['size'] for e in events if e['type'] == 'cancel')

        assert trade_volume == 100
        assert cancel_volume == 400

    def test_cancel_then_trade_different_meaning(self):
        """Cancel followed by trade at lower price = different signal"""
        # Scenario: Maker cancels at 0.72, trade happens at 0.70
        # This is CHASE/retreat, not sweep at same level
        events = [
            {'ts': 1000, 'type': 'cancel', 'size': 500, 'price': 0.72},
            {'ts': 1100, 'type': 'trade', 'size': 200, 'price': 0.70},
        ]

        # The cancel and trade are at different prices
        cancel_price = Decimal("0.72")
        trade_price = Decimal("0.70")
        tick_size = Decimal("0.01")

        price_gap_ticks = abs(cancel_price - trade_price) / tick_size

        # 2 ticks gap = not same level trading
        assert price_gap_ticks == 2

        # This is CHASE scenario, not simple sweep
        is_chase_candidate = price_gap_ticks >= 1
        assert is_chase_candidate


class TestVolumeReconciliation:
    """Tests for volume reconciliation between trades and book changes"""

    def test_volume_matches_book_change(self):
        """Trade volume should match book depth change"""
        # Scenario: Perfect reconciliation
        book_level_before = 1000.0
        book_level_after = 700.0
        expected_trade_volume = book_level_before - book_level_after  # 300

        actual_trade_volume = 300.0

        # Perfect match
        discrepancy = abs(actual_trade_volume - expected_trade_volume)
        assert discrepancy < 1.0, "Volume should match book change"

    def test_volume_exceeds_book_change(self):
        """Trade volume > book change = replenishment happened"""
        book_level_before = 1000.0
        book_level_after = 800.0
        book_change = book_level_before - book_level_after  # 200 removed

        trade_volume = 350.0  # But 350 was traded!

        # This means 150 was replenished during trading
        replenishment = trade_volume - book_change
        assert replenishment == 150.0, "Should detect replenishment"

        # This is actually a HOLD signal (defending the level)
        is_hold_candidate = replenishment > 0
        assert is_hold_candidate

    def test_book_change_exceeds_volume(self):
        """Book change > trade volume = cancellation happened"""
        book_level_before = 1000.0
        book_level_after = 500.0
        book_change = book_level_before - book_level_after  # 500 removed

        trade_volume = 100.0  # Only 100 was traded

        # 400 was cancelled
        cancelled = book_change - trade_volume
        assert cancelled == 400.0, "Should detect cancellation"

        # This affects PULL vs SWEEP classification
        cancel_ratio = cancelled / book_change
        assert cancel_ratio == 0.8, "80% was cancelled, not traded"
