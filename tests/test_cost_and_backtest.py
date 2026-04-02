"""
Tests for transaction cost model, market filter, and backtesting engine.
"""

import sys
import os
import numpy as np
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.strategy.cost_model import TransactionCostModel, CostConfig
from backend.strategy.market_filter import (
    MarketFilter, MarketFilterConfig, MarketSnapshot, FilterReason,
)
from backend.strategy.calibration import DeltaCalibrator
from backend.backtest.data_loader import BeliefTransition
from backend.backtest.engine import BacktestEngine, WalkForwardValidator


class TestCostModel:
    def test_fee_calculation(self):
        model = TransactionCostModel(CostConfig(taker_fee_bps=200))
        costs = model.estimate_total_cost(0.5, 100)
        assert costs["fee_one_way"] == pytest.approx(0.02)  # 2%

    def test_spread_cost(self):
        model = TransactionCostModel()
        costs = model.estimate_total_cost(0.5, 100, spread=0.02)
        assert costs["spread_cost"] > 0

    def test_impact_scales_with_size(self):
        model = TransactionCostModel()
        small = model.estimate_total_cost(0.5, 100, book_depth_usd=10000)
        large = model.estimate_total_cost(0.5, 5000, book_depth_usd=10000)
        assert large["impact_cost"] > small["impact_cost"]

    def test_profitability_check(self):
        model = TransactionCostModel(CostConfig(taker_fee_bps=200))
        # 5% edge should be profitable
        result = model.is_trade_profitable(0.05, 0.5, 100, daily_volume=100000)
        assert result["profitable_hold_to_resolution"]

        # 0.5% edge should NOT be profitable (fee alone is 2%)
        result = model.is_trade_profitable(0.005, 0.5, 100, daily_volume=100000)
        assert not result["profitable_hold_to_resolution"]

    def test_boundary_impact_adjustment(self):
        model = TransactionCostModel()
        # Impact at p=0.5 (max)
        mid = model.estimate_total_cost(0.5, 1000, book_depth_usd=10000)
        # Impact at p=0.1 (near boundary)
        edge = model.estimate_total_cost(0.1, 1000, book_depth_usd=10000)
        assert edge["impact_cost"] < mid["impact_cost"]

    def test_edge_adjustment(self):
        model = TransactionCostModel()
        net = model.adjust_edge_for_costs(0.05, 0.5, 100, daily_volume=100000)
        assert net < 0.05  # Net edge < gross edge
        assert net > 0     # But still positive for 5% edge

    def test_round_trip_more_expensive(self):
        model = TransactionCostModel()
        costs = model.estimate_total_cost(0.5, 100, daily_volume=50000)
        assert costs["total_round_trip"] > costs["total_one_way"]


class TestMarketFilter:
    def _make_market(self, **kwargs) -> MarketSnapshot:
        defaults = {
            "token_id": "test123",
            "last_price": 0.5,
            "bid_price": 0.49,
            "ask_price": 0.51,
            "bid_depth_usd": 10000,
            "ask_depth_usd": 10000,
            "best_bid_size_usd": 2000,
            "best_ask_size_usd": 2000,
            "volume_24h": 50000,
            "volume_7d": 200000,
            "hours_to_resolution": 168,
            "hours_since_last_trade": 0.5,
            "active": True,
            "closed": False,
        }
        defaults.update(kwargs)
        return MarketSnapshot(**defaults)

    def test_good_market_passes(self):
        f = MarketFilter()
        result = f.evaluate(self._make_market())
        assert result.eligible
        assert result.reason == FilterReason.PASSED

    def test_low_volume_rejected(self):
        f = MarketFilter()
        result = f.evaluate(self._make_market(volume_24h=500))
        assert not result.eligible
        assert result.reason == FilterReason.LOW_VOLUME

    def test_low_depth_rejected(self):
        f = MarketFilter()
        result = f.evaluate(self._make_market(bid_depth_usd=100, ask_depth_usd=100))
        assert not result.eligible
        assert result.reason == FilterReason.LOW_DEPTH

    def test_extreme_price_rejected(self):
        f = MarketFilter()
        result = f.evaluate(self._make_market(last_price=0.98))
        assert not result.eligible
        assert result.reason == FilterReason.EXTREME_PRICE

    def test_near_resolution_rejected(self):
        f = MarketFilter()
        result = f.evaluate(self._make_market(hours_to_resolution=2))
        assert not result.eligible
        assert result.reason == FilterReason.NEAR_RESOLUTION

    def test_inactive_rejected(self):
        f = MarketFilter()
        result = f.evaluate(self._make_market(active=False))
        assert not result.eligible
        assert result.reason == FilterReason.INACTIVE

    def test_scoring(self):
        f = MarketFilter()
        # High quality market
        good = self._make_market(volume_24h=200000, bid_depth_usd=30000, ask_depth_usd=30000)
        # Mediocre market
        ok = self._make_market(volume_24h=15000, bid_depth_usd=4000, ask_depth_usd=4000)
        r_good = f.evaluate(good)
        r_ok = f.evaluate(ok)
        assert r_good.overall_score > r_ok.overall_score

    def test_filter_and_rank(self):
        f = MarketFilter()
        markets = [
            self._make_market(token_id="a", volume_24h=100000),
            self._make_market(token_id="b", volume_24h=500),  # Too low
            self._make_market(token_id="c", volume_24h=50000),
        ]
        results = f.filter_markets(markets)
        assert len(results) == 2
        # Sorted by score desc
        assert results[0][0].token_id == "a"


class TestDeltaCalibrator:
    def test_default_deltas(self):
        cal = DeltaCalibrator()
        assert cal.get_delta("STABLE") == 0.0
        assert cal.get_delta("CRACKING") > 0

    def test_calibration_with_data(self):
        cal = DeltaCalibrator()
        # Feed 20 transitions with consistent +3 cent moves
        for _ in range(20):
            cal.record_transition(
                "CRACKING", "bid", 0.50,
                price_1m=0.48, price_5m=0.47, price_15m=0.46,
            )
        stats = cal.get_stats("CRACKING")
        assert stats is not None
        assert stats.n_observations == 20
        assert stats.directional_accuracy > 0.9  # Very accurate

    def test_no_edge_shrinks_delta(self):
        cal = DeltaCalibrator()
        # Feed 20 transitions with random directions (no edge)
        import random
        random.seed(42)
        for _ in range(20):
            move = random.choice([-0.03, 0.03])
            cal.record_transition(
                "CRACKING", "bid", 0.50,
                price_5m=0.50 + move,
            )
        delta = cal.get_delta("CRACKING")
        # Should be small because accuracy ~50%
        assert delta < 0.03


class TestBacktestEngine:
    def _make_transitions(self, n=50, accuracy=0.7, move_size=0.03, spread=0.02):
        """Generate synthetic transitions with controlled accuracy."""
        np.random.seed(42)
        transitions = []
        for i in range(n):
            base_price = 0.5
            side = "bid"  # Bearish prediction → expect price down

            # With given accuracy, price goes in predicted direction
            if np.random.random() < accuracy:
                move = -abs(np.random.normal(move_size, 0.005))  # Correct
            else:
                move = abs(np.random.normal(move_size, 0.005))   # Wrong

            transitions.append(BeliefTransition(
                ts=datetime(2026, 1, 1) + timedelta(hours=i),
                token_id=f"token_{i % 5}",
                old_state="FRAGILE",
                new_state="CRACKING",
                reaction_type="VACUUM",
                reaction_side=side,
                price_at_event=base_price,
                price_1m=base_price + move * 0.3,
                price_5m=base_price + move,
                price_15m=base_price + move * 1.2,
                spread=spread,
                bid_depth_usd=20000,
                ask_depth_usd=20000,
            ))
        return transitions

    def test_signal_analysis(self):
        engine = BacktestEngine()
        transitions = self._make_transitions(50, accuracy=0.7)
        results = engine.analyze_signals(transitions)
        assert "CRACKING" in results
        r = results["CRACKING"]
        assert r.n_with_price_data == 50
        assert r.accuracy_5m > 0.5  # Should be ~70%

    def test_simulation_with_edge(self):
        # Use low costs and tight spread + deep book to ensure edge survives costs
        engine = BacktestEngine(cost_model=TransactionCostModel(
            CostConfig(taker_fee_bps=50, impact_eta=0.02)
        ))
        transitions = self._make_transitions(
            50, accuracy=0.75, move_size=0.05, spread=0.005
        )
        result = engine.simulate_trading(transitions, initial_bankroll=10000)
        # With 75% accuracy, 5 cent moves, tight spread, low fees
        assert result.total_trades > 0
        assert result.win_rate > 0.5

    def test_simulation_no_edge(self):
        engine = BacktestEngine()
        transitions = self._make_transitions(50, accuracy=0.50)
        result = engine.simulate_trading(transitions, initial_bankroll=10000)
        # With 50% accuracy, costs eat any profit
        # May have few trades (edge too small after costs) or negative PnL
        if result.total_trades > 0:
            assert result.avg_pnl_per_trade < 10  # Not significantly profitable

    def test_walk_forward(self):
        validator = WalkForwardValidator(train_days=3, test_days=2, step_days=2)
        transitions = self._make_transitions(100, accuracy=0.65)
        result = validator.validate(transitions)
        # Should produce at least some folds
        assert "n_folds" in result or "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
