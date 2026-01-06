"""
Tests for Market Eligibility Layer (v5.36)
"""

import pytest
from backend.market.eligibility import (
    MarketEligibilityEvaluator,
    EligibilityStatus,
    EligibilityReason,
    EligibilityScore,
    evaluate_market_eligibility,
    ELIGIBILITY_THRESHOLDS,
)


class TestEligibilityStatus:
    """Test EligibilityStatus enum"""

    def test_status_values(self):
        assert EligibilityStatus.ELIGIBLE.value == "ELIGIBLE"
        assert EligibilityStatus.DEGRADED.value == "DEGRADED"
        assert EligibilityStatus.OBSERVE_ONLY.value == "OBSERVE_ONLY"
        assert EligibilityStatus.EXCLUDED.value == "EXCLUDED"


class TestEligibilityReason:
    """Test EligibilityReason enum"""

    def test_positive_reasons(self):
        assert EligibilityReason.SUFFICIENT_LIQUIDITY.value == "SUFFICIENT_LIQUIDITY"
        assert EligibilityReason.DIVERSE_PARTICIPANTS.value == "DIVERSE_PARTICIPANTS"
        assert EligibilityReason.HUMAN_RHYTHM_DETECTED.value == "HUMAN_RHYTHM_DETECTED"

    def test_negative_reasons(self):
        assert EligibilityReason.THIN_LIQUIDITY.value == "THIN_LIQUIDITY"
        assert EligibilityReason.BOT_DOMINATED.value == "BOT_DOMINATED"
        assert EligibilityReason.HIGH_SPOOFING.value == "HIGH_SPOOFING"


class TestEligibilityScore:
    """Test EligibilityScore dataclass"""

    def test_score_creation(self):
        score = EligibilityScore(
            token_id="test_token",
            status=EligibilityStatus.ELIGIBLE,
            score=0.8,
            liquidity_score=0.9,
            diversity_score=0.7,
        )
        assert score.token_id == "test_token"
        assert score.status == EligibilityStatus.ELIGIBLE
        assert score.score == 0.8

    def test_score_to_dict(self):
        score = EligibilityScore(
            token_id="test_token",
            status=EligibilityStatus.DEGRADED,
            score=0.5,
            positive_reasons=[EligibilityReason.SUFFICIENT_LIQUIDITY],
            negative_reasons=[EligibilityReason.BOT_DOMINATED],
        )
        d = score.to_dict()
        assert d["token_id"] == "test_token"
        assert d["status"] == "DEGRADED"
        assert "SUFFICIENT_LIQUIDITY" in d["positive_reasons"]
        assert "BOT_DOMINATED" in d["negative_reasons"]


class TestMarketEligibilityEvaluator:
    """Test MarketEligibilityEvaluator"""

    @pytest.fixture
    def evaluator(self):
        return MarketEligibilityEvaluator()

    def test_eligible_market(self, evaluator):
        """High quality market should be ELIGIBLE"""
        metrics = {
            "baseline_liquidity": 2000.0,
            "trade_count_24h": 100,
            "unique_traders_24h": 25,
            "cancel_place_ratio": 0.1,
            "top_trader_volume_ratio": 0.3,
            "trade_intervals": [5000, 8000, 3000, 12000, 6000, 9000, 4000, 7000, 11000, 5500],
            "last_activity_ts": int(__import__("time").time() * 1000) - 60000,
            "wash_trade_ratio": 0.05,
        }
        score = evaluator.evaluate("good_market", metrics)

        assert score.status == EligibilityStatus.ELIGIBLE
        assert score.score >= 0.6
        assert EligibilityReason.SUFFICIENT_LIQUIDITY in score.positive_reasons
        assert EligibilityReason.DIVERSE_PARTICIPANTS in score.positive_reasons

    def test_thin_liquidity_market(self, evaluator):
        """Thin liquidity market should be DEGRADED or lower"""
        metrics = {
            "baseline_liquidity": 50.0,  # Very thin
            "trade_count_24h": 20,
            "unique_traders_24h": 8,
            "cancel_place_ratio": 0.15,
            "top_trader_volume_ratio": 0.4,
            "trade_intervals": [10000, 15000, 8000, 12000, 9000, 14000, 11000, 7000, 13000, 10500],
            "last_activity_ts": int(__import__("time").time() * 1000) - 60000,
        }
        score = evaluator.evaluate("thin_market", metrics)

        assert score.status in (EligibilityStatus.DEGRADED, EligibilityStatus.OBSERVE_ONLY, EligibilityStatus.EXCLUDED)
        assert EligibilityReason.THIN_LIQUIDITY in score.negative_reasons

    def test_bot_dominated_market(self, evaluator):
        """Bot-dominated market should be degraded"""
        metrics = {
            "baseline_liquidity": 1000.0,
            "trade_count_24h": 500,
            "unique_traders_24h": 3,  # Few traders
            "cancel_place_ratio": 0.2,
            "top_trader_volume_ratio": 0.95,  # Single dominant trader
            "trade_intervals": [1000, 1001, 999, 1000, 1002, 998, 1001, 999, 1000, 1001],  # Very regular
            "last_activity_ts": int(__import__("time").time() * 1000) - 60000,
        }
        score = evaluator.evaluate("bot_market", metrics)

        assert score.status != EligibilityStatus.ELIGIBLE
        # Should detect single participant or bot pattern
        assert any(r in score.negative_reasons for r in [
            EligibilityReason.SINGLE_PARTICIPANT,
            EligibilityReason.BOT_DOMINATED,
        ])

    def test_high_spoofing_market(self, evaluator):
        """High spoofing market should be OBSERVE_ONLY max"""
        metrics = {
            "baseline_liquidity": 5000.0,
            "trade_count_24h": 200,
            "unique_traders_24h": 30,
            "cancel_place_ratio": 0.8,  # Very high cancel ratio
            "top_trader_volume_ratio": 0.25,
            "trade_intervals": [5000, 8000, 3000, 12000, 6000, 9000, 4000, 7000, 11000, 5500],
            "last_activity_ts": int(__import__("time").time() * 1000) - 60000,
        }
        score = evaluator.evaluate("spoof_market", metrics)

        assert score.status in (EligibilityStatus.OBSERVE_ONLY, EligibilityStatus.EXCLUDED)
        assert EligibilityReason.HIGH_SPOOFING in score.negative_reasons

    def test_wash_trading_market(self, evaluator):
        """Wash trading market should be OBSERVE_ONLY max"""
        metrics = {
            "baseline_liquidity": 3000.0,
            "trade_count_24h": 150,
            "unique_traders_24h": 20,
            "cancel_place_ratio": 0.15,
            "top_trader_volume_ratio": 0.3,
            "trade_intervals": [5000, 8000, 3000, 12000, 6000, 9000, 4000, 7000, 11000, 5500],
            "last_activity_ts": int(__import__("time").time() * 1000) - 60000,
            "wash_trade_ratio": 0.5,  # High wash trading
        }
        score = evaluator.evaluate("wash_market", metrics)

        assert score.status in (EligibilityStatus.OBSERVE_ONLY, EligibilityStatus.EXCLUDED)
        assert EligibilityReason.WASH_TRADING in score.negative_reasons

    def test_inactive_market(self, evaluator):
        """Inactive market should be degraded"""
        metrics = {
            "baseline_liquidity": 1500.0,
            "trade_count_24h": 50,
            "unique_traders_24h": 15,
            "cancel_place_ratio": 0.1,
            "top_trader_volume_ratio": 0.35,
            "trade_intervals": [5000, 8000, 3000, 12000, 6000, 9000, 4000, 7000, 11000, 5500],
            "last_activity_ts": int(__import__("time").time() * 1000) - 50 * 3600000,  # 50 hours ago
        }
        score = evaluator.evaluate("inactive_market", metrics)

        assert EligibilityReason.NO_RECENT_ACTIVITY in score.negative_reasons

    def test_caching(self, evaluator):
        """Evaluator should cache results"""
        metrics = {
            "baseline_liquidity": 2000.0,
            "trade_count_24h": 100,
            "unique_traders_24h": 25,
            "cancel_place_ratio": 0.1,
            "top_trader_volume_ratio": 0.3,
            "trade_intervals": [5000, 8000, 3000, 12000, 6000],
            "last_activity_ts": int(__import__("time").time() * 1000),
        }

        score1 = evaluator.evaluate("cached_market", metrics)
        score2 = evaluator.evaluate("cached_market", metrics)

        # Same object from cache
        assert score1.evaluated_at == score2.evaluated_at

        # Force refresh should create new evaluation
        score3 = evaluator.evaluate("cached_market", metrics, force_refresh=True)
        assert score3.evaluated_at >= score1.evaluated_at

    def test_clear_cache(self, evaluator):
        """Cache clearing should work"""
        metrics = {"baseline_liquidity": 1000.0}
        evaluator.evaluate("market1", metrics)
        evaluator.evaluate("market2", metrics)

        assert "market1" in evaluator._cache
        assert "market2" in evaluator._cache

        evaluator.clear_cache("market1")
        assert "market1" not in evaluator._cache
        assert "market2" in evaluator._cache

        evaluator.clear_cache()
        assert len(evaluator._cache) == 0


class TestEligibilityHelpers:
    """Test helper methods"""

    @pytest.fixture
    def evaluator(self):
        return MarketEligibilityEvaluator()

    def test_alert_severity_cap(self, evaluator):
        """Test alert severity caps by status"""
        assert evaluator.get_alert_severity_cap(EligibilityStatus.ELIGIBLE) is None
        assert evaluator.get_alert_severity_cap(EligibilityStatus.DEGRADED) == "HIGH"
        assert evaluator.get_alert_severity_cap(EligibilityStatus.OBSERVE_ONLY) is None
        assert evaluator.get_alert_severity_cap(EligibilityStatus.EXCLUDED) is None

    def test_should_run_state_machine(self, evaluator):
        """Test state machine eligibility"""
        assert evaluator.should_run_state_machine(EligibilityStatus.ELIGIBLE) is True
        assert evaluator.should_run_state_machine(EligibilityStatus.DEGRADED) is True
        assert evaluator.should_run_state_machine(EligibilityStatus.OBSERVE_ONLY) is False
        assert evaluator.should_run_state_machine(EligibilityStatus.EXCLUDED) is False

    def test_should_generate_tiles(self, evaluator):
        """Test tile generation eligibility"""
        assert evaluator.should_generate_tiles(EligibilityStatus.ELIGIBLE) is True
        assert evaluator.should_generate_tiles(EligibilityStatus.DEGRADED) is True
        assert evaluator.should_generate_tiles(EligibilityStatus.OBSERVE_ONLY) is True
        assert evaluator.should_generate_tiles(EligibilityStatus.EXCLUDED) is False


class TestConvenienceFunction:
    """Test module-level convenience function"""

    def test_evaluate_market_eligibility(self):
        """Test convenience function"""
        metrics = {
            "baseline_liquidity": 2000.0,
            "trade_count_24h": 100,
            "unique_traders_24h": 25,
            "cancel_place_ratio": 0.1,
            "top_trader_volume_ratio": 0.3,
        }
        score = evaluate_market_eligibility("test_token", metrics)
        assert isinstance(score, EligibilityScore)
        assert score.token_id == "test_token"
