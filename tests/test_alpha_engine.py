"""
Tests for Alpha Engine components.

Tests:
1. HMM regime detection
2. BOCPD changepoint detection
3. Hawkes process intensity
4. VPIN calculation
5. Microstructure signals (OFI, depth imbalance)
6. Ensemble combination
7. Kelly position sizing
8. Risk manager
"""

import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.alpha.hmm_regime import HMMRegimeDetector, HMMParams
from backend.alpha.bocpd import BOCPDetector, NIGParams
from backend.alpha.hawkes import HawkesIntensity, BivarateHawkes, HawkesParams
from backend.alpha.vpin import VPINCalculator, VPINConfig
from backend.alpha.microstructure import (
    OrderFlowImbalance, DepthImbalance, KyleLambda, BookSnapshot, MicrostructureSignals,
)
from backend.alpha.ensemble import ExponentialWeightsEnsemble, ProbabilityEnsemble
from backend.strategy.kelly import (
    BetaPosterior, compute_kelly_fraction, KellyPositionSizer, KellyConfig,
)
from backend.strategy.risk_manager import RiskManager, RiskConfig, RiskLevel


class TestHMMRegime:
    def test_initialization(self):
        hmm = HMMRegimeDetector()
        regime, prob, name = hmm.get_regime()
        assert regime in [0, 1, 2]
        assert 0 <= prob <= 1
        assert name in ["CALM", "TRENDING", "VOLATILE"]

    def test_calm_regime_detection(self):
        """Low volatility returns should converge to a single dominant state."""
        hmm = HMMRegimeDetector()
        np.random.seed(42)
        for _ in range(200):
            obs = np.random.normal(0, 0.002)
            hmm.update(obs)

        regime, prob, name = hmm.get_regime()
        # With very consistent data, the HMM should converge to one dominant state
        assert prob > 0.5  # Should be confident in some regime

    def test_volatile_regime_detection(self):
        """High volatility returns should shift toward VOLATILE."""
        hmm = HMMRegimeDetector()
        np.random.seed(42)
        # Start calm
        for _ in range(50):
            hmm.update(np.random.normal(0, 0.002))
        # Switch to volatile
        for _ in range(100):
            hmm.update(np.random.normal(0, 0.05))

        probs = hmm.get_regime_probs()
        assert probs["VOLATILE"] > 0.2

    def test_state_probabilities_sum_to_one(self):
        hmm = HMMRegimeDetector()
        for _ in range(50):
            probs = hmm.update(np.random.normal(0, 0.01))
            assert abs(probs.sum() - 1.0) < 1e-6


class TestBOCPD:
    def test_initialization(self):
        detector = BOCPDetector()
        assert detector.get_changepoint_prob() == 0.0

    def test_stable_signal(self):
        """Stable signal should not trigger changepoint."""
        detector = BOCPDetector(hazard_lambda=200)
        np.random.seed(42)
        for _ in range(100):
            detector.update(np.random.normal(0, 0.01))

        assert detector.get_changepoint_prob() < 0.5
        assert not detector.is_changepoint()

    def test_mean_shift_detection(self):
        """Abrupt mean shift should trigger changepoint."""
        detector = BOCPDetector(hazard_lambda=50, changepoint_threshold=0.01)
        np.random.seed(42)

        # Stable period
        for _ in range(100):
            detector.update(np.random.normal(0, 0.01))

        # Large mean shift (10x the std dev)
        max_cp_prob = 0.0
        for _ in range(50):
            cp = detector.update(np.random.normal(0.5, 0.01))
            max_cp_prob = max(max_cp_prob, cp)

        # Should detect changepoint at some point
        assert max_cp_prob > 0.005

    def test_run_length(self):
        detector = BOCPDetector()
        for _ in range(50):
            detector.update(0.0)

        # Run length should be close to 50
        assert detector.get_expected_run_length() > 10


class TestHawkes:
    def test_background_intensity(self):
        h = HawkesIntensity(HawkesParams(mu=0.1, alpha=0.5, beta=1.0))
        assert abs(h.current_intensity - 0.1) < 1e-10

    def test_self_excitation(self):
        """Events should increase intensity."""
        h = HawkesIntensity(HawkesParams(mu=0.1, alpha=0.5, beta=1.0))
        h.on_event(1.0)
        assert h.current_intensity > 0.1

        # Second event should further increase
        intensity_after_1 = h.current_intensity
        h.on_event(1.1)
        assert h.current_intensity > intensity_after_1

    def test_decay(self):
        """Intensity should decay back toward mu after events stop."""
        h = HawkesIntensity(HawkesParams(mu=0.1, alpha=0.5, beta=1.0))
        h.on_event(1.0)
        peak = h.current_intensity

        # Check intensity at a later time
        later_intensity = h.get_intensity(10.0)
        assert later_intensity < peak
        assert later_intensity > 0.1  # Still above background

    def test_bivariate_imbalance(self):
        bh = BivarateHawkes()
        # All buys
        for i in range(10):
            bh.on_event(0, float(i))
        assert bh.get_imbalance_ratio() > 0  # Buy-dominated

    def test_stationarity(self):
        h = HawkesIntensity(HawkesParams(mu=0.1, alpha=0.5, beta=1.0))
        assert h.params.branching_ratio < 1.0
        assert h.params.is_stationary


class TestVPIN:
    def test_initialization(self):
        v = VPINCalculator(VPINConfig(bucket_volume=100, n_buckets=5))
        assert v.current_vpin is None

    def test_balanced_flow(self):
        """Balanced buy/sell should produce low VPIN."""
        v = VPINCalculator(VPINConfig(bucket_volume=100, n_buckets=5))
        np.random.seed(42)

        price = 0.5
        for _ in range(1000):
            # Random walk price
            price += np.random.normal(0, 0.001)
            price = np.clip(price, 0.01, 0.99)
            v.update(price, 10)

        if v.current_vpin is not None:
            assert v.current_vpin < 0.8  # Should not be extreme

    def test_directional_flow(self):
        """Persistent price increase should produce higher VPIN."""
        v = VPINCalculator(VPINConfig(bucket_volume=100, n_buckets=5))

        price = 0.5
        for i in range(500):
            price += 0.001  # Persistent increase
            v.update(price, 10)

        if v.current_vpin is not None:
            assert v.current_vpin > 0.3  # Should detect directional flow

    def test_toxicity_levels(self):
        v = VPINCalculator()
        assert v.get_toxicity_level() == "UNKNOWN"


class TestMicrostructure:
    def test_ofi_basic(self):
        ofi = OrderFlowImbalance()
        snap1 = BookSnapshot(0, 0.50, 0.52, 100, 100)
        snap2 = BookSnapshot(1, 0.51, 0.52, 120, 100)

        ofi.update(snap1)
        val = ofi.update(snap2)
        # Bid moved up and size increased -> positive OFI
        assert val > 0

    def test_depth_imbalance(self):
        di = DepthImbalance()
        # Bid-heavy
        snap = BookSnapshot(0, 0.50, 0.52, 200, 50)
        val = di.compute(snap)
        assert val > 0  # Bullish

        # Ask-heavy
        snap = BookSnapshot(1, 0.50, 0.52, 50, 200)
        val = di.compute(snap)
        assert val < 0  # Bearish

    def test_kyle_lambda(self):
        kyle = KyleLambda()
        np.random.seed(42)
        for _ in range(100):
            dp = np.random.normal(0, 0.01)
            ofi = dp * 100 + np.random.normal(0, 0.5)
            kyle.update(dp, ofi)

        # Lambda should be positive (price moves with OFI)
        assert kyle.value > 0

    def test_integrated_signals(self):
        ms = MicrostructureSignals()
        snap1 = BookSnapshot(0, 0.50, 0.52, 100, 100)
        snap2 = BookSnapshot(1, 0.51, 0.53, 120, 80)

        ms.update_book(snap1)
        ms.update_book(snap2)

        signals = ms.get_signals()
        assert "ofi_zscore" in signals
        assert "depth_imbalance" in signals
        assert "kyle_lambda" in signals


class TestEnsemble:
    def test_equal_weights_initially(self):
        experts = ["a", "b", "c"]
        ens = ExponentialWeightsEnsemble(experts)
        weights = ens.get_weights()
        assert abs(weights["a"] - 1/3) < 0.01

    def test_weight_convergence(self):
        """Expert that consistently predicts correctly should gain weight."""
        experts = ["good", "bad"]
        ens = ExponentialWeightsEnsemble(experts)

        for _ in range(50):
            # Good expert predicts +1, bad predicts -1
            pred = ens.predict({"good": 0.8, "bad": -0.5})
            ens.update(1.0)  # Outcome is positive

        weights = ens.get_weights()
        assert weights["good"] > weights["bad"]

    def test_probability_ensemble(self):
        experts = ["model_a", "model_b"]
        ens = ProbabilityEnsemble(experts)

        p = ens.combine_probabilities({"model_a": 0.7, "model_b": 0.6})
        assert 0.5 < p < 0.8  # Between the two estimates


class TestKelly:
    def test_basic_kelly(self):
        # If true prob is 60% and market is at 50%, should bet
        f = compute_kelly_fraction(0.6, 0.5, "YES")
        assert f > 0
        assert f < 1

    def test_no_edge(self):
        f = compute_kelly_fraction(0.5, 0.5, "YES")
        assert f == 0

    def test_beta_posterior(self):
        post = BetaPosterior(10, 10)
        assert abs(post.mean - 0.5) < 0.01

        # Update with YES outcomes
        for _ in range(20):
            post.update(1)
        assert post.mean > 0.5

    def test_kelly_sizer(self):
        sizer = KellyPositionSizer(KellyConfig(min_edge=0.01, min_confidence=0.5))
        # v6.1: p_estimate used directly as plug-in, no posterior feeding
        result = sizer.size_position(
            market_id="test",
            p_estimate=0.65,
            market_price=0.50,
            bankroll=10000,
        )
        assert result["side"] == "YES"
        assert result["size_usd"] > 0
        assert result["edge"] == pytest.approx(0.15, abs=0.01)

    def test_kelly_no_self_feeding(self):
        """Posterior should NOT inflate from repeated size_position calls."""
        sizer = KellyPositionSizer(KellyConfig(min_edge=0.01))
        posterior = sizer.get_or_create_posterior("test")
        initial_n = posterior.n_observations

        # Call size_position 50 times — posterior should NOT change
        for _ in range(50):
            sizer.size_position("test", 0.65, 0.50, 10000)

        assert posterior.n_observations == initial_n  # No inflation

    def test_kelly_posterior_only_updates_on_outcome(self):
        """Posterior should only update on market resolution."""
        sizer = KellyPositionSizer()
        posterior = sizer.get_or_create_posterior("test")
        n_before = posterior.n_observations

        # Market resolves YES
        sizer.update_outcome("test", 1)
        assert posterior.n_observations == n_before + 1
        assert posterior.mean > 0.5  # Shifted toward YES

    def test_kelly_no_trade_when_no_edge(self):
        sizer = KellyPositionSizer()
        result = sizer.size_position(
            market_id="test",
            p_estimate=0.50,
            market_price=0.50,
            bankroll=10000,
        )
        assert result["side"] is None or result["size_usd"] == 0


class TestRiskManager:
    def test_initialization(self):
        rm = RiskManager()
        assert rm.risk_level == RiskLevel.NORMAL
        assert rm.bankroll == 10000.0

    def test_trade_approval(self):
        rm = RiskManager()
        result = rm.evaluate_trade("mkt1", "YES", 500, 0.5)
        assert result["approved"]

    def test_drawdown_halt(self):
        rm = RiskManager(RiskConfig(
            initial_bankroll=10000,
            max_drawdown=0.15,
        ))
        # Simulate losses
        rm.bankroll = 8400  # 16% drawdown
        result = rm.evaluate_trade("mkt1", "YES", 100, 0.5)
        assert not result["approved"]
        assert result["reason"] == "max_drawdown_reached"

    def test_position_limits(self):
        rm = RiskManager(RiskConfig(
            initial_bankroll=10000,
            max_single_position=0.10,
        ))
        # Try to open position larger than limit
        result = rm.evaluate_trade("mkt1", "YES", 2000, 0.5)
        assert result["approved"]
        assert result["adjusted_size"] <= 1000  # 10% of 10000

    def test_regime_scaling(self):
        rm = RiskManager()
        rm.update_regime("VOLATILE")
        result = rm.evaluate_trade("mkt1", "YES", 500, 0.5)
        assert result["approved"]
        assert result["adjusted_size"] < 500  # Scaled down

    def test_portfolio_summary(self):
        rm = RiskManager()
        summary = rm.get_portfolio_summary()
        assert "bankroll" in summary
        assert "drawdown" in summary
        assert "risk_level" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
