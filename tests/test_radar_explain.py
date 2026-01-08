"""
Tests for Radar Explainability Module (v5.20)

Validates:
1. State explanation generation
2. Factor analysis (positive/negative)
3. Trend detection
4. Counterfactual generation
5. Event explanations
6. Bilingual support (EN/CN)

"让每一个判断都有理可循"
"""

import pytest
import time

from backend.radar.explain import (
    Language,
    TrendDirection,
    ExplainFactor,
    Factor,
    CounterfactualCondition,
    StateExplanation,
    generate_explanation,
    explain_single_event,
    generate_radar_tooltip,
    STATE_HEADLINES,
    FACTOR_DESCRIPTIONS,
)


class TestLanguageEnum:
    """Test Language enum"""

    def test_language_values(self):
        """Should have EN and CN"""
        assert Language.EN.value == "EN"
        assert Language.CN.value == "CN"


class TestTrendDirection:
    """Test TrendDirection enum"""

    def test_trend_values(self):
        """Should have all trend directions"""
        assert TrendDirection.IMPROVING.value == "IMPROVING"
        assert TrendDirection.STABLE.value == "STABLE"
        assert TrendDirection.WORSENING.value == "WORSENING"
        assert TrendDirection.VOLATILE.value == "VOLATILE"


class TestExplainFactor:
    """Test ExplainFactor enum"""

    def test_positive_factors_exist(self):
        """Should have positive factors"""
        assert ExplainFactor.HIGH_HOLD_RATIO
        assert ExplainFactor.LOW_FRAGILE_SIGNALS
        assert ExplainFactor.NO_VACUUM
        assert ExplainFactor.QUICK_REFILL

    def test_negative_factors_exist(self):
        """Should have negative factors"""
        assert ExplainFactor.LOW_HOLD_RATIO
        assert ExplainFactor.VACUUM_AT_KEY_LEVEL
        assert ExplainFactor.PULL_AT_KEY_LEVEL
        assert ExplainFactor.DEPTH_COLLAPSE
        assert ExplainFactor.PRE_SHOCK_PULL
        assert ExplainFactor.CANCEL_DOMINATED


class TestFactor:
    """Test Factor dataclass"""

    def test_factor_creation(self):
        """Should create factor with all fields"""
        factor = Factor(
            factor_type=ExplainFactor.HIGH_HOLD_RATIO,
            weight=0.8,
            value="85%",
            threshold=">=70%",
            description_en="Most shocks result in HOLD reactions",
            description_cn="大多数冲击后深度保持稳定",
        )

        assert factor.factor_type == ExplainFactor.HIGH_HOLD_RATIO
        assert factor.weight == 0.8
        assert factor.value == "85%"

    def test_factor_to_dict(self):
        """Should serialize to dict"""
        factor = Factor(
            factor_type=ExplainFactor.VACUUM_AT_KEY_LEVEL,
            weight=-0.9,
            value=2,
            threshold="0",
            description_en="Vacuum at key level",
            description_cn="关键价位出现真空",
        )

        d = factor.to_dict()

        assert d["factor"] == "VACUUM_AT_KEY_LEVEL"
        assert d["weight"] == -0.9
        assert d["value"] == 2
        assert d["description"]["en"] == "Vacuum at key level"
        assert d["description"]["cn"] == "关键价位出现真空"


class TestStateExplanation:
    """Test StateExplanation dataclass"""

    def test_explanation_creation(self):
        """Should create explanation with all fields"""
        explanation = StateExplanation(
            token_id="test-token",
            current_state="FRAGILE",
            confidence=70.0,
            headline_en="Market showing early stress signals",
            headline_cn="市场出现初期压力信号",
            summary_en="Test summary",
            summary_cn="测试摘要",
        )

        assert explanation.token_id == "test-token"
        assert explanation.current_state == "FRAGILE"
        assert explanation.confidence == 70.0

    def test_timestamp_auto_set(self):
        """Should auto-set generated_at timestamp"""
        before = int(time.time() * 1000)
        explanation = StateExplanation(
            token_id="test",
            current_state="STABLE",
            confidence=85.0,
            headline_en="Test",
            headline_cn="测试",
            summary_en="Test",
            summary_cn="测试",
        )
        after = int(time.time() * 1000)

        assert before <= explanation.generated_at <= after

    def test_to_dict_english(self):
        """Should serialize with English preference"""
        explanation = StateExplanation(
            token_id="test-token",
            current_state="STABLE",
            confidence=85.0,
            headline_en="Market depth is holding well",
            headline_cn="市场深度表现稳健",
            summary_en="English summary",
            summary_cn="中文摘要",
            trend=TrendDirection.IMPROVING,
            trend_reason_en="Improved from FRAGILE",
            trend_reason_cn="已从FRAGILE改善",
        )

        d = explanation.to_dict(lang=Language.EN)

        assert d["headline"] == "Market depth is holding well"
        assert d["summary"] == "English summary"
        assert d["trend"] == "IMPROVING"
        assert d["trend_reason"] == "Improved from FRAGILE"

    def test_to_dict_chinese(self):
        """Should serialize with Chinese preference"""
        explanation = StateExplanation(
            token_id="test-token",
            current_state="STABLE",
            confidence=85.0,
            headline_en="Market depth is holding well",
            headline_cn="市场深度表现稳健",
            summary_en="English summary",
            summary_cn="中文摘要",
            trend=TrendDirection.IMPROVING,
            trend_reason_en="Improved from FRAGILE",
            trend_reason_cn="已从FRAGILE改善",
        )

        d = explanation.to_dict(lang=Language.CN)

        assert d["headline"] == "市场深度表现稳健"
        assert d["summary"] == "中文摘要"
        assert d["trend_reason"] == "已从FRAGILE改善"


class TestGenerateExplanation:
    """Test generate_explanation function"""

    def test_stable_state_explanation(self):
        """Should generate explanation for STABLE state"""
        metrics = {
            "hold_ratio": 0.85,
            "fragile_signals": 0,
            "vacuum_count": 0,
            "pull_count": 1,
            "depth_collapse_count": 0,
            "pre_shock_pull_count": 0,
            "fragility_index": 20,
            "cancel_driven_ratio": 0.3,
        }

        explanation = generate_explanation(
            token_id="test-token",
            current_state="STABLE",
            metrics=metrics,
        )

        assert explanation.current_state == "STABLE"
        assert explanation.confidence >= 80
        assert len(explanation.positive_factors) > 0
        assert "STABLE" in explanation.headline_en or "holding" in explanation.headline_en.lower()
        assert "稳健" in explanation.headline_cn

    def test_broken_state_explanation(self):
        """Should generate explanation for BROKEN state"""
        metrics = {
            "hold_ratio": 0.2,
            "fragile_signals": 5,
            "vacuum_count": 3,
            "pull_count": 8,
            "depth_collapse_count": 2,
            "pre_shock_pull_count": 1,
            "fragility_index": 90,
            "cancel_driven_ratio": 0.8,
        }

        explanation = generate_explanation(
            token_id="test-token",
            current_state="BROKEN",
            metrics=metrics,
        )

        assert explanation.current_state == "BROKEN"
        assert len(explanation.negative_factors) > 0
        assert "compromised" in explanation.headline_en.lower() or "BROKEN" in explanation.headline_en
        assert "受损" in explanation.headline_cn

    def test_fragile_state_explanation(self):
        """Should generate explanation for FRAGILE state"""
        metrics = {
            "hold_ratio": 0.55,
            "fragile_signals": 2,
            "vacuum_count": 0,
            "pull_count": 3,
            "depth_collapse_count": 0,
            "pre_shock_pull_count": 1,
            "fragility_index": 45,
            "cancel_driven_ratio": 0.55,
        }

        explanation = generate_explanation(
            token_id="test-token",
            current_state="FRAGILE",
            metrics=metrics,
        )

        assert explanation.current_state == "FRAGILE"
        assert len(explanation.negative_factors) > 0
        assert "stress" in explanation.headline_en.lower() or "FRAGILE" in explanation.headline_en

    def test_cracking_state_explanation(self):
        """Should generate explanation for CRACKING state"""
        metrics = {
            "hold_ratio": 0.35,
            "fragile_signals": 4,
            "vacuum_count": 1,
            "pull_count": 5,
            "depth_collapse_count": 1,
            "pre_shock_pull_count": 0,
            "fragility_index": 75,
            "cancel_driven_ratio": 0.7,
        }

        explanation = generate_explanation(
            token_id="test-token",
            current_state="CRACKING",
            metrics=metrics,
        )

        assert explanation.current_state == "CRACKING"
        assert len(explanation.negative_factors) >= 2


class TestFactorAnalysis:
    """Test factor extraction from metrics"""

    def test_high_hold_ratio_positive(self):
        """High hold ratio should be positive factor"""
        metrics = {
            "hold_ratio": 0.85,
            "fragile_signals": 0,
            "vacuum_count": 0,
            "pull_count": 0,
            "depth_collapse_count": 0,
            "pre_shock_pull_count": 0,
            "fragility_index": 20,
            "cancel_driven_ratio": 0.2,
        }

        explanation = generate_explanation("test", "STABLE", metrics)

        hold_factor = next(
            (f for f in explanation.positive_factors
             if f.factor_type == ExplainFactor.HIGH_HOLD_RATIO),
            None
        )
        assert hold_factor is not None
        assert hold_factor.weight > 0

    def test_vacuum_negative_factor(self):
        """Vacuum should be negative factor"""
        metrics = {
            "hold_ratio": 0.5,
            "fragile_signals": 2,
            "vacuum_count": 2,
            "pull_count": 3,
            "depth_collapse_count": 0,
            "pre_shock_pull_count": 0,
            "fragility_index": 60,
            "cancel_driven_ratio": 0.5,
        }

        explanation = generate_explanation("test", "CRACKING", metrics)

        vacuum_factor = next(
            (f for f in explanation.negative_factors
             if f.factor_type in [ExplainFactor.VACUUM_AT_KEY_LEVEL,
                                   ExplainFactor.MULTIPLE_VACUUM]),
            None
        )
        assert vacuum_factor is not None
        assert vacuum_factor.weight < 0

    def test_pre_shock_pull_negative_factor(self):
        """Pre-shock pull should be high-weight negative factor"""
        metrics = {
            "hold_ratio": 0.5,
            "fragile_signals": 1,
            "vacuum_count": 0,
            "pull_count": 1,
            "depth_collapse_count": 0,
            "pre_shock_pull_count": 2,
            "fragility_index": 50,
            "cancel_driven_ratio": 0.5,
        }

        explanation = generate_explanation("test", "FRAGILE", metrics)

        pre_shock_factor = next(
            (f for f in explanation.negative_factors
             if f.factor_type == ExplainFactor.PRE_SHOCK_PULL),
            None
        )
        assert pre_shock_factor is not None
        assert pre_shock_factor.weight <= -0.8  # High weight


class TestTrendAnalysis:
    """Test trend detection"""

    def test_improving_trend(self):
        """Should detect improving trend"""
        metrics = {"hold_ratio": 0.8, "vacuum_count": 0, "fragile_signals": 0,
                   "pull_count": 0, "depth_collapse_count": 0, "pre_shock_pull_count": 0,
                   "fragility_index": 20, "cancel_driven_ratio": 0.2}

        explanation = generate_explanation(
            "test", "STABLE", metrics, previous_state="FRAGILE"
        )

        assert explanation.trend == TrendDirection.IMPROVING
        assert "Improved" in explanation.trend_reason_en or "improved" in explanation.trend_reason_en.lower()

    def test_worsening_trend(self):
        """Should detect worsening trend"""
        metrics = {"hold_ratio": 0.3, "vacuum_count": 2, "fragile_signals": 3,
                   "pull_count": 5, "depth_collapse_count": 1, "pre_shock_pull_count": 0,
                   "fragility_index": 80, "cancel_driven_ratio": 0.7}

        explanation = generate_explanation(
            "test", "BROKEN", metrics, previous_state="CRACKING"
        )

        assert explanation.trend == TrendDirection.WORSENING
        assert "Declined" in explanation.trend_reason_en or "declined" in explanation.trend_reason_en.lower()

    def test_stable_trend(self):
        """Should detect stable trend"""
        metrics = {"hold_ratio": 0.6, "vacuum_count": 0, "fragile_signals": 1,
                   "pull_count": 2, "depth_collapse_count": 0, "pre_shock_pull_count": 0,
                   "fragility_index": 40, "cancel_driven_ratio": 0.4}

        explanation = generate_explanation(
            "test", "FRAGILE", metrics, previous_state="FRAGILE"
        )

        assert explanation.trend == TrendDirection.STABLE

    def test_volatile_trend(self):
        """Should detect volatile trend from history"""
        metrics = {"hold_ratio": 0.5, "vacuum_count": 0, "fragile_signals": 1,
                   "pull_count": 1, "depth_collapse_count": 0, "pre_shock_pull_count": 0,
                   "fragility_index": 40, "cancel_driven_ratio": 0.4}

        # History with frequent changes
        history = [
            (1000, "STABLE"),
            (2000, "FRAGILE"),
            (3000, "CRACKING"),
            (4000, "FRAGILE"),
            (5000, "STABLE"),
        ]

        explanation = generate_explanation(
            "test", "STABLE", metrics, state_history=history
        )

        assert explanation.trend == TrendDirection.VOLATILE


class TestCounterfactuals:
    """Test counterfactual generation"""

    def test_broken_counterfactuals(self):
        """BROKEN state should have counterfactuals to CRACKING and STABLE"""
        metrics = {
            "hold_ratio": 0.2,
            "vacuum_count": 3,
            "pull_count": 5,
            "fragile_signals": 5,
            "depth_collapse_count": 2,
            "pre_shock_pull_count": 1,
            "fragility_index": 90,
            "cancel_driven_ratio": 0.8,
        }

        explanation = generate_explanation("test", "BROKEN", metrics)

        assert len(explanation.counterfactuals) >= 2

        target_states = [c.target_state for c in explanation.counterfactuals]
        assert "CRACKING" in target_states or "FRAGILE" in target_states
        assert "STABLE" in target_states

    def test_fragile_counterfactuals(self):
        """FRAGILE state should have counterfactual to STABLE"""
        metrics = {
            "hold_ratio": 0.55,
            "vacuum_count": 0,
            "pull_count": 2,
            "fragile_signals": 2,
            "depth_collapse_count": 0,
            "pre_shock_pull_count": 1,
            "fragility_index": 45,
            "cancel_driven_ratio": 0.5,
        }

        explanation = generate_explanation("test", "FRAGILE", metrics)

        stable_cf = next(
            (c for c in explanation.counterfactuals if c.target_state == "STABLE"),
            None
        )
        assert stable_cf is not None
        assert stable_cf.likelihood == "high"  # FRAGILE -> STABLE is achievable

    def test_counterfactual_conditions(self):
        """Counterfactuals should have actionable conditions"""
        metrics = {
            "hold_ratio": 0.4,
            "vacuum_count": 1,
            "pull_count": 3,
            "fragile_signals": 3,
            "depth_collapse_count": 0,
            "pre_shock_pull_count": 0,
            "fragility_index": 65,
            "cancel_driven_ratio": 0.6,
        }

        explanation = generate_explanation("test", "CRACKING", metrics)

        for cf in explanation.counterfactuals:
            assert len(cf.conditions) > 0
            # v5.36: "n/a" added for "why not worse" counterfactuals
            assert cf.likelihood in ["high", "medium", "low", "n/a"]


class TestExplainSingleEvent:
    """Test explain_single_event function"""

    def test_explain_shock_english(self):
        """Should explain shock event in English"""
        event_data = {
            "price": "0.65",
            "trade_volume": 1500,
            "side": "bid",
        }

        explanation = explain_single_event("shock", event_data, Language.EN)

        assert "0.65" in explanation
        assert "1500" in explanation
        assert "bid" in explanation

    def test_explain_shock_chinese(self):
        """Should explain shock event in Chinese"""
        event_data = {
            "price": "0.65",
            "trade_volume": 1500,
            "side": "bid",
        }

        explanation = explain_single_event("shock", event_data, Language.CN)

        assert "0.65" in explanation
        assert "1500" in explanation
        assert "冲击" in explanation

    def test_explain_reaction_english(self):
        """Should explain reaction event in English"""
        event_data = {
            "reaction_type": "VACUUM",
            "price": "0.65",
            "drop_ratio": 0.95,
        }

        explanation = explain_single_event("reaction", event_data, Language.EN)

        assert "VACUUM" in explanation
        assert "0.65" in explanation
        assert "95%" in explanation

    def test_explain_reaction_chinese(self):
        """Should explain reaction event in Chinese"""
        event_data = {
            "reaction_type": "HOLD",
            "price": "0.70",
            "drop_ratio": 0.1,
        }

        explanation = explain_single_event("reaction", event_data, Language.CN)

        assert "保持" in explanation  # HOLD in Chinese
        assert "0.70" in explanation

    def test_explain_leading_event(self):
        """Should explain leading event"""
        event_data = {
            "event_type": "PRE_SHOCK_PULL",
            "price": "0.68",
        }

        explanation = explain_single_event("leading_event", event_data, Language.EN)

        assert "PRE_SHOCK_PULL" in explanation
        assert "0.68" in explanation

    def test_explain_state_change(self):
        """Should explain state change"""
        event_data = {
            "old_state": "STABLE",
            "new_state": "FRAGILE",
            "evidence_refs": ["ev1", "ev2", "ev3"],
        }

        explanation = explain_single_event("state_change", event_data, Language.EN)

        assert "STABLE" in explanation
        assert "FRAGILE" in explanation
        assert "3" in explanation  # evidence count

    def test_explain_unknown_event(self):
        """Should handle unknown event type"""
        explanation = explain_single_event("unknown_type", {}, Language.EN)

        assert "Unknown" in explanation or "unknown" in explanation


class TestRadarTooltip:
    """Test generate_radar_tooltip function"""

    def test_tooltip_english(self):
        """Should generate English tooltip"""
        market_data = {
            "state": "FRAGILE",
            "confidence": 70,
            "leading_rate_10m": 3.5,
            "fragile_index_10m": 45,
            "last_critical_alert": {"type": "VACUUM"},
        }

        tooltip = generate_radar_tooltip(market_data, Language.EN)

        assert "FRAGILE" in tooltip["state"]
        assert "70" in tooltip["state"]
        assert "3.5" in tooltip["metrics"]
        assert "VACUUM" in tooltip["alert"]
        assert "Click" in tooltip["tip"]

    def test_tooltip_chinese(self):
        """Should generate Chinese tooltip"""
        market_data = {
            "state": "CRACKING",
            "confidence": 60,
            "leading_rate_10m": 5.0,
            "fragile_index_10m": 75,
        }

        tooltip = generate_radar_tooltip(market_data, Language.CN)

        assert "信念状态" in tooltip["state"]
        assert "CRACKING" in tooltip["state"]
        assert "领先信号率" in tooltip["metrics"]
        assert "点击" in tooltip["tip"]

    def test_tooltip_without_alert(self):
        """Should handle missing alert"""
        market_data = {
            "state": "STABLE",
            "confidence": 85,
            "leading_rate_10m": 0.5,
            "fragile_index_10m": 15,
        }

        tooltip = generate_radar_tooltip(market_data, Language.EN)

        assert "alert" not in tooltip


class TestStateHeadlines:
    """Test STATE_HEADLINES constant"""

    def test_all_states_have_headlines(self):
        """All states should have headlines"""
        for state in ["STABLE", "FRAGILE", "CRACKING", "BROKEN"]:
            assert state in STATE_HEADLINES
            assert "en" in STATE_HEADLINES[state]
            assert "cn" in STATE_HEADLINES[state]

    def test_headlines_non_empty(self):
        """Headlines should not be empty"""
        for state, headlines in STATE_HEADLINES.items():
            assert len(headlines["en"]) > 0
            assert len(headlines["cn"]) > 0


class TestFactorDescriptions:
    """Test FACTOR_DESCRIPTIONS constant"""

    def test_all_factors_have_descriptions(self):
        """All factors should have descriptions"""
        for factor in ExplainFactor:
            assert factor in FACTOR_DESCRIPTIONS, f"Missing description for {factor}"
            assert "en" in FACTOR_DESCRIPTIONS[factor]
            assert "cn" in FACTOR_DESCRIPTIONS[factor]

    def test_descriptions_non_empty(self):
        """Descriptions should not be empty"""
        for factor, desc in FACTOR_DESCRIPTIONS.items():
            assert len(desc["en"]) > 0, f"Empty EN description for {factor}"
            assert len(desc["cn"]) > 0, f"Empty CN description for {factor}"


class TestCounterfactualCondition:
    """Test CounterfactualCondition dataclass"""

    def test_condition_creation(self):
        """Should create condition"""
        condition = CounterfactualCondition(
            target_state="STABLE",
            conditions=["Increase hold ratio to >70%", "No vacuum events"],
            likelihood="medium",
        )

        assert condition.target_state == "STABLE"
        assert len(condition.conditions) == 2
        assert condition.likelihood == "medium"

    def test_condition_to_dict(self):
        """Should serialize to dict"""
        condition = CounterfactualCondition(
            target_state="FRAGILE",
            conditions=["Reduce vacuum events"],
            likelihood="high",
        )

        d = condition.to_dict()

        assert d["target_state"] == "FRAGILE"
        assert d["conditions"] == ["Reduce vacuum events"]
        assert d["likelihood"] == "high"
