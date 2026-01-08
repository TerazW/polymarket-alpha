"""
Tests for Unified Attribution System (v5.19)

Validates:
1. Trade-driven vs cancel-driven classification
2. Replenishment detection
3. Multi-level aggregation
4. Volume reconciliation
5. Attribution tracking over time

"不能把撤单当扫单、把扫单当撤单"
"""

import pytest
from decimal import Decimal
import time

from backend.common.attribution import (
    AttributionType,
    DepthChangeAttribution,
    MultiLevelAttribution,
    compute_attribution,
    compute_multi_level_attribution,
    is_trade_driven,
    is_cancel_driven,
    is_replenishment,
    classify_for_reaction,
    reconcile_volume,
    AttributionTracker,
    TRADE_DOMINANT_THRESHOLD,
    CANCEL_DOMINANT_THRESHOLD,
)


class TestAttributionType:
    """Test AttributionType enum"""

    def test_all_types_defined(self):
        """Should have all attribution types"""
        assert AttributionType.TRADE_DRIVEN.value == "TRADE_DRIVEN"
        assert AttributionType.CANCEL_DRIVEN.value == "CANCEL_DRIVEN"
        assert AttributionType.MIXED.value == "MIXED"
        assert AttributionType.REPLENISHMENT.value == "REPLENISHMENT"
        assert AttributionType.NO_CHANGE.value == "NO_CHANGE"

    def test_types_are_strings(self):
        """AttributionType should be string-based for JSON serialization"""
        for t in AttributionType:
            assert isinstance(t.value, str)


class TestDepthChangeAttribution:
    """Test DepthChangeAttribution dataclass"""

    def test_creation(self):
        """Should create attribution with basic fields"""
        attr = DepthChangeAttribution(
            depth_before=1000.0,
            depth_after=500.0,
            trade_volume=300.0,
        )

        assert attr.depth_before == 1000.0
        assert attr.depth_after == 500.0
        assert attr.trade_volume == 300.0

    def test_timestamp_auto_set(self):
        """Should auto-set computed_at timestamp"""
        before = int(time.time() * 1000)
        attr = DepthChangeAttribution(
            depth_before=1000.0,
            depth_after=500.0,
            trade_volume=300.0,
        )
        after = int(time.time() * 1000)

        assert before <= attr.computed_at <= after

    def test_to_dict(self):
        """Should serialize to dict correctly"""
        attr = DepthChangeAttribution(
            depth_before=1000.0,
            depth_after=500.0,
            trade_volume=300.0,
            depth_change=-500.0,
            depth_removed=500.0,
            trade_driven_volume=300.0,
            cancel_driven_volume=200.0,
            trade_driven_ratio=0.6,
            cancel_driven_ratio=0.4,
            attribution_type=AttributionType.MIXED,
            price_level=Decimal("0.65"),
            token_id="test-token",
        )

        d = attr.to_dict()

        assert d["depth_before"] == 1000.0
        assert d["depth_after"] == 500.0
        assert d["trade_volume"] == 300.0
        assert d["depth_removed"] == 500.0
        assert d["trade_driven_ratio"] == 0.6
        assert d["cancel_driven_ratio"] == 0.4
        assert d["attribution_type"] == "MIXED"
        assert d["price_level"] == "0.65"
        assert d["token_id"] == "test-token"


class TestComputeAttribution:
    """Test compute_attribution function"""

    def test_pure_trade_driven(self):
        """100% trade-driven: trade volume equals depth removed"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=0.0,
            trade_volume=1000.0,
        )

        assert attr.depth_removed == 1000.0
        assert attr.trade_driven_volume == 1000.0
        assert attr.cancel_driven_volume == 0.0
        assert attr.trade_driven_ratio == 1.0
        assert attr.cancel_driven_ratio == 0.0
        assert attr.attribution_type == AttributionType.TRADE_DRIVEN

    def test_pure_cancel_driven(self):
        """100% cancel-driven: depth removed with no trades"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=0.0,
            trade_volume=0.0,
        )

        assert attr.depth_removed == 1000.0
        assert attr.trade_driven_volume == 0.0
        assert attr.cancel_driven_volume == 1000.0
        assert attr.trade_driven_ratio == 0.0
        assert attr.cancel_driven_ratio == 1.0
        assert attr.attribution_type == AttributionType.CANCEL_DRIVEN

    def test_mixed_attribution(self):
        """Mixed: 60% trade, 40% cancel"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=0.0,
            trade_volume=600.0,  # 60% of removed depth
        )

        assert attr.depth_removed == 1000.0
        assert attr.trade_driven_volume == 600.0
        assert attr.cancel_driven_volume == 400.0
        assert attr.trade_driven_ratio == 0.6
        assert attr.cancel_driven_ratio == 0.4
        assert attr.attribution_type == AttributionType.MIXED

    def test_trade_dominant_threshold(self):
        """Should be TRADE_DRIVEN when ratio >= 70%"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=0.0,
            trade_volume=700.0,  # Exactly 70%
        )

        assert attr.trade_driven_ratio == 0.7
        assert attr.attribution_type == AttributionType.TRADE_DRIVEN

    def test_cancel_dominant_threshold(self):
        """Should be CANCEL_DRIVEN when ratio >= 70%"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=0.0,
            trade_volume=300.0,  # 30% trade = 70% cancel
        )

        assert attr.cancel_driven_ratio == 0.7
        assert attr.attribution_type == AttributionType.CANCEL_DRIVEN

    def test_replenishment_detected(self):
        """Should detect replenishment when depth increases"""
        attr = compute_attribution(
            depth_before=500.0,
            depth_after=800.0,
            trade_volume=0.0,
        )

        assert attr.depth_change == 300.0
        assert attr.replenishment_volume == 300.0
        assert attr.attribution_type == AttributionType.REPLENISHMENT

    def test_hidden_replenishment(self):
        """Should detect hidden replenishment when trade > depth removed"""
        # 500 removed from book, but 800 traded = 300 replenished during trading
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=500.0,
            trade_volume=800.0,
        )

        assert attr.depth_removed == 500.0
        assert attr.trade_driven_volume == 500.0  # Capped at depth_removed
        assert attr.replenishment_volume == 300.0  # 800 - 500

    def test_no_change_small_delta(self):
        """Should return NO_CHANGE for small depth changes"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=995.0,  # 0.5% change < 5% threshold
            trade_volume=5.0,
        )

        assert attr.attribution_type == AttributionType.NO_CHANGE

    def test_no_initial_depth(self):
        """Should handle zero initial depth"""
        attr = compute_attribution(
            depth_before=0.0,
            depth_after=100.0,
            trade_volume=0.0,
        )

        assert attr.attribution_type == AttributionType.NO_CHANGE

    def test_no_initial_depth_with_trade(self):
        """Should handle zero initial depth with trades"""
        attr = compute_attribution(
            depth_before=0.0,
            depth_after=100.0,
            trade_volume=50.0,
        )

        assert attr.attribution_type == AttributionType.TRADE_DRIVEN

    def test_with_price_level(self):
        """Should include price level in result"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=500.0,
            trade_volume=500.0,
            price_level=Decimal("0.6543"),
        )

        assert attr.price_level == Decimal("0.6543")

    def test_with_token_id(self):
        """Should include token_id in result"""
        attr = compute_attribution(
            depth_before=1000.0,
            depth_after=500.0,
            trade_volume=500.0,
            token_id="test-token-123",
        )

        assert attr.token_id == "test-token-123"


class TestMultiLevelAttribution:
    """Test multi-level attribution aggregation"""

    def test_single_level(self):
        """Single level should work"""
        levels = [
            (Decimal("0.65"), 1000.0, 500.0, 500.0),  # (price, before, after, trade)
        ]

        result = compute_multi_level_attribution(levels)

        assert result.levels_affected == 1
        assert result.total_depth_removed == 500.0
        assert result.total_trade_driven == 500.0
        assert result.attribution_type == AttributionType.TRADE_DRIVEN

    def test_multiple_levels_aggregation(self):
        """Multiple levels should aggregate correctly"""
        levels = [
            (Decimal("0.65"), 1000.0, 500.0, 500.0),   # 100% trade
            (Decimal("0.66"), 800.0, 0.0, 400.0),      # 50% trade, 50% cancel
            (Decimal("0.67"), 600.0, 0.0, 0.0),        # 100% cancel
        ]

        result = compute_multi_level_attribution(levels)

        assert result.levels_affected == 3
        assert result.total_depth_before == 2400.0
        assert result.total_depth_after == 500.0
        assert result.total_trade_volume == 900.0
        assert result.total_depth_removed == 1900.0  # 500 + 800 + 600
        assert result.total_trade_driven == 900.0    # 500 + 400 + 0
        assert result.total_cancel_driven == 1000.0  # 0 + 400 + 600

    def test_overall_classification(self):
        """Overall type should reflect aggregated ratios"""
        # Create scenario where overall is CANCEL_DRIVEN
        levels = [
            (Decimal("0.65"), 1000.0, 500.0, 100.0),  # 20% trade
            (Decimal("0.66"), 1000.0, 500.0, 200.0),  # 40% trade
        ]

        result = compute_multi_level_attribution(levels)

        # Total removed: 1000, total trade: 300 = 30% trade, 70% cancel
        assert result.attribution_type == AttributionType.CANCEL_DRIVEN

    def test_to_dict(self):
        """Should serialize to dict with all levels"""
        levels = [
            (Decimal("0.65"), 1000.0, 500.0, 500.0),
            (Decimal("0.66"), 800.0, 400.0, 400.0),
        ]

        result = compute_multi_level_attribution(levels, token_id="test")
        d = result.to_dict()

        assert d["levels_affected"] == 2
        assert len(d["levels"]) == 2
        assert "total_depth_removed" in d
        assert "trade_driven_ratio" in d
        assert "attribution_type" in d


class TestHelperFunctions:
    """Test helper functions"""

    def test_is_trade_driven(self):
        """is_trade_driven should check attribution type"""
        attr_trade = compute_attribution(1000.0, 0.0, 1000.0)
        attr_cancel = compute_attribution(1000.0, 0.0, 0.0)

        assert is_trade_driven(attr_trade) is True
        assert is_trade_driven(attr_cancel) is False

    def test_is_cancel_driven(self):
        """is_cancel_driven should check attribution type"""
        attr_trade = compute_attribution(1000.0, 0.0, 1000.0)
        attr_cancel = compute_attribution(1000.0, 0.0, 0.0)

        assert is_cancel_driven(attr_trade) is False
        assert is_cancel_driven(attr_cancel) is True

    def test_is_replenishment(self):
        """is_replenishment should check attribution type"""
        attr_replen = compute_attribution(500.0, 800.0, 0.0)
        attr_trade = compute_attribution(1000.0, 0.0, 1000.0)

        assert is_replenishment(attr_replen) is True
        assert is_replenishment(attr_trade) is False


class TestClassifyForReaction:
    """Test classify_for_reaction function"""

    def test_trade_driven_sweep(self):
        """Trade-driven with remaining depth should be SWEEP_CANDIDATE"""
        attr = compute_attribution(1000.0, 100.0, 900.0)
        hint = classify_for_reaction(attr)

        assert hint == "SWEEP_CANDIDATE"

    def test_trade_driven_vacuum(self):
        """Trade-driven with near-zero depth should be VACUUM_CANDIDATE"""
        attr = compute_attribution(1000.0, 10.0, 990.0)  # <5% remaining
        hint = classify_for_reaction(attr)

        assert hint == "VACUUM_CANDIDATE"

    def test_cancel_driven_pull(self):
        """Cancel-driven should be PULL_CANDIDATE"""
        attr = compute_attribution(1000.0, 0.0, 100.0)  # 90% cancel
        hint = classify_for_reaction(attr)

        assert hint == "PULL_CANDIDATE"

    def test_replenishment_hold(self):
        """Replenishment should be HOLD_CANDIDATE"""
        attr = compute_attribution(500.0, 800.0, 0.0)
        hint = classify_for_reaction(attr)

        assert hint == "HOLD_CANDIDATE"

    def test_mixed_signal(self):
        """Mixed attribution should return MIXED"""
        attr = compute_attribution(1000.0, 0.0, 500.0)  # 50/50
        hint = classify_for_reaction(attr)

        assert hint == "MIXED"

    def test_no_change_signal(self):
        """No change should return NO_SIGNAL"""
        attr = compute_attribution(1000.0, 995.0, 5.0)  # Minimal change
        hint = classify_for_reaction(attr)

        assert hint == "NO_SIGNAL"


class TestReconcileVolume:
    """Test volume reconciliation"""

    def test_no_activity(self):
        """Should detect no activity"""
        result = reconcile_volume(0.0, 0.0)

        assert result["status"] == "NO_ACTIVITY"
        assert result["discrepancy"] == 0.0

    def test_matched(self):
        """Should detect matched trade and book change"""
        result = reconcile_volume(500.0, 500.0)

        assert result["status"] == "MATCHED"
        assert result["discrepancy"] == 0.0

    def test_replenishment(self):
        """Should detect replenishment when trade > book change"""
        result = reconcile_volume(500.0, 800.0)

        assert result["status"] == "REPLENISHMENT"
        assert result["replenished"] == 300.0
        assert result["cancelled"] == 0.0

    def test_cancellation(self):
        """Should detect cancellation when book change > trade"""
        result = reconcile_volume(800.0, 500.0)

        assert result["status"] == "CANCELLATION"
        assert result["cancelled"] == 300.0
        assert result["replenished"] == 0.0


class TestAttributionTracker:
    """Test AttributionTracker for rolling statistics"""

    def test_tracker_creation(self):
        """Should create tracker with window size"""
        tracker = AttributionTracker(window_size=100)

        assert tracker.window_size == 100

    def test_record_attribution(self):
        """Should record attributions"""
        tracker = AttributionTracker(window_size=100)
        attr = compute_attribution(1000.0, 0.0, 800.0)

        tracker.record(attr)
        stats = tracker.get_rolling_stats()

        assert stats["count"] == 1

    def test_rolling_window(self):
        """Should maintain rolling window"""
        tracker = AttributionTracker(window_size=5)

        # Add 10 attributions
        for i in range(10):
            attr = compute_attribution(1000.0, 0.0, 500.0)
            tracker.record(attr)

        stats = tracker.get_rolling_stats()
        assert stats["count"] == 5  # Only last 5 kept

    def test_average_ratios(self):
        """Should calculate average ratios correctly"""
        tracker = AttributionTracker(window_size=100)

        # Add 100% trade-driven
        tracker.record(compute_attribution(1000.0, 0.0, 1000.0))
        # Add 100% cancel-driven
        tracker.record(compute_attribution(1000.0, 0.0, 0.0))

        stats = tracker.get_rolling_stats()

        assert stats["avg_trade_driven"] == 0.5
        assert stats["avg_cancel_driven"] == 0.5

    def test_type_counts(self):
        """Should count attribution types"""
        tracker = AttributionTracker(window_size=100)

        # Add various types
        tracker.record(compute_attribution(1000.0, 0.0, 1000.0))  # TRADE
        tracker.record(compute_attribution(1000.0, 0.0, 1000.0))  # TRADE
        tracker.record(compute_attribution(1000.0, 0.0, 0.0))     # CANCEL
        tracker.record(compute_attribution(1000.0, 0.0, 500.0))   # MIXED
        tracker.record(compute_attribution(500.0, 800.0, 0.0))    # REPLENISHMENT

        stats = tracker.get_rolling_stats()

        assert stats["by_type"]["TRADE_DRIVEN"] == 2
        assert stats["by_type"]["CANCEL_DRIVEN"] == 1
        assert stats["by_type"]["MIXED"] == 1
        assert stats["by_type"]["REPLENISHMENT"] == 1

    def test_token_profile(self):
        """Should track per-token statistics"""
        tracker = AttributionTracker(window_size=100)

        # Add attributions for different tokens
        attr1 = compute_attribution(1000.0, 0.0, 1000.0, token_id="token-A")
        attr2 = compute_attribution(1000.0, 0.0, 0.0, token_id="token-A")
        attr3 = compute_attribution(1000.0, 0.0, 500.0, token_id="token-B")

        tracker.record(attr1)
        tracker.record(attr2)
        tracker.record(attr3)

        profile_a = tracker.get_token_profile("token-A")
        profile_b = tracker.get_token_profile("token-B")

        assert profile_a["count"] == 2
        assert profile_a["avg_trade_driven"] == 0.5  # (1.0 + 0.0) / 2
        assert profile_b["count"] == 1

    def test_empty_tracker(self):
        """Empty tracker should return zeros"""
        tracker = AttributionTracker()
        stats = tracker.get_rolling_stats()

        assert stats["count"] == 0
        assert stats["avg_trade_driven"] == 0.0
        assert stats["avg_cancel_driven"] == 0.0

    def test_unknown_token_profile(self):
        """Unknown token should return zeros"""
        tracker = AttributionTracker()
        profile = tracker.get_token_profile("nonexistent")

        assert profile["count"] == 0
        assert profile["avg_trade_driven"] == 0.0


class TestThresholds:
    """Test threshold constants"""

    def test_threshold_values(self):
        """Thresholds should be properly defined"""
        assert TRADE_DOMINANT_THRESHOLD == 0.70
        assert CANCEL_DOMINANT_THRESHOLD == 0.70

    def test_thresholds_sum_logic(self):
        """Thresholds should leave room for MIXED classification"""
        # If trade >= 70% => TRADE_DRIVEN
        # If cancel >= 70% => CANCEL_DRIVEN
        # Else MIXED (between 30-70% each)
        # This ensures 30-70% range for MIXED on each side
        assert TRADE_DOMINANT_THRESHOLD + (1 - CANCEL_DOMINANT_THRESHOLD) <= 1.0


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_very_small_numbers(self):
        """Should handle very small depth values"""
        attr = compute_attribution(0.001, 0.0, 0.001)

        assert attr.attribution_type == AttributionType.TRADE_DRIVEN
        assert attr.trade_driven_ratio == 1.0

    def test_very_large_numbers(self):
        """Should handle very large depth values"""
        attr = compute_attribution(1e12, 5e11, 5e11)

        assert attr.trade_driven_ratio == 1.0
        assert attr.attribution_type == AttributionType.TRADE_DRIVEN

    def test_floating_point_precision(self):
        """Should handle floating point edge cases"""
        # Values that might cause precision issues
        attr = compute_attribution(0.1 + 0.2, 0.0, 0.3)

        # Should still work correctly despite floating point imprecision
        assert 0.99 < attr.trade_driven_ratio <= 1.0

    def test_negative_depth_after(self):
        """Negative depth_after should be treated as removal"""
        # This shouldn't happen in practice, but should not crash
        attr = compute_attribution(1000.0, -100.0, 500.0)

        assert attr.depth_change == -1100.0
        assert attr.depth_removed == 1100.0
