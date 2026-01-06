"""
Radar Explainability Module (v5.20)

Generates human-readable explanations for belief states and market conditions.

Key features:
1. Natural language explanations (CN + EN)
2. Factor breakdown for state classifications
3. Trend indicators (improving/worsening)
4. Counterfactual reasoning ("what would make this STABLE?")

"让每一个判断都有理可循"
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import time


class Language(str, Enum):
    """Supported explanation languages"""
    EN = "EN"
    CN = "CN"


class TrendDirection(str, Enum):
    """Belief state trend direction"""
    IMPROVING = "IMPROVING"       # 改善中
    STABLE = "STABLE"             # 持平
    WORSENING = "WORSENING"       # 恶化中
    VOLATILE = "VOLATILE"         # 波动中


class ExplainFactor(str, Enum):
    """Factors that contribute to belief state"""
    # Positive factors (toward STABLE)
    HIGH_HOLD_RATIO = "HIGH_HOLD_RATIO"
    LOW_FRAGILE_SIGNALS = "LOW_FRAGILE_SIGNALS"
    CONSISTENT_DEPTH = "CONSISTENT_DEPTH"
    QUICK_REFILL = "QUICK_REFILL"
    NO_VACUUM = "NO_VACUUM"

    # Negative factors (toward BROKEN)
    LOW_HOLD_RATIO = "LOW_HOLD_RATIO"
    VACUUM_AT_KEY_LEVEL = "VACUUM_AT_KEY_LEVEL"
    PULL_AT_KEY_LEVEL = "PULL_AT_KEY_LEVEL"
    DEPTH_COLLAPSE = "DEPTH_COLLAPSE"
    PRE_SHOCK_PULL = "PRE_SHOCK_PULL"
    MULTIPLE_VACUUM = "MULTIPLE_VACUUM"
    GRADUAL_THINNING = "GRADUAL_THINNING"
    CANCEL_DOMINATED = "CANCEL_DOMINATED"
    HIGH_FRAGILITY_INDEX = "HIGH_FRAGILITY_INDEX"

    # Neutral/Informational
    RECENT_STATE_CHANGE = "RECENT_STATE_CHANGE"
    ACTIVE_ALERTS = "ACTIVE_ALERTS"


@dataclass
class Factor:
    """A single explanatory factor"""
    factor_type: ExplainFactor
    weight: float               # -1.0 (negative) to 1.0 (positive)
    value: Any                  # The actual observed value
    threshold: Any = None       # The threshold for comparison
    description_en: str = ""
    description_cn: str = ""

    def to_dict(self) -> dict:
        return {
            "factor": self.factor_type.value,
            "weight": round(self.weight, 2),
            "value": self.value,
            "threshold": self.threshold,
            "description": {
                "en": self.description_en,
                "cn": self.description_cn,
            }
        }


@dataclass
class CounterfactualCondition:
    """What would need to change to reach a different state"""
    target_state: str           # e.g., "STABLE"
    conditions: List[str]       # Required changes
    likelihood: str             # "high", "medium", "low"

    def to_dict(self) -> dict:
        return {
            "target_state": self.target_state,
            "conditions": self.conditions,
            "likelihood": self.likelihood,
        }


@dataclass
class StateExplanation:
    """Complete explanation for a belief state"""
    token_id: str
    current_state: str
    confidence: float

    # Natural language summary
    headline_en: str
    headline_cn: str
    summary_en: str
    summary_cn: str

    # Factor breakdown
    positive_factors: List[Factor] = field(default_factory=list)
    negative_factors: List[Factor] = field(default_factory=list)

    # Trend
    trend: TrendDirection = TrendDirection.STABLE
    trend_reason_en: str = ""
    trend_reason_cn: str = ""

    # Counterfactuals
    counterfactuals: List[CounterfactualCondition] = field(default_factory=list)

    # Metadata
    generated_at: int = 0
    window_minutes: int = 10

    def __post_init__(self):
        if self.generated_at == 0:
            self.generated_at = int(time.time() * 1000)

    def to_dict(self, lang: Language = Language.EN) -> dict:
        """Serialize with language preference"""
        return {
            "token_id": self.token_id,
            "current_state": self.current_state,
            "confidence": round(self.confidence, 1),
            "headline": self.headline_cn if lang == Language.CN else self.headline_en,
            "summary": self.summary_cn if lang == Language.CN else self.summary_en,
            "positive_factors": [f.to_dict() for f in self.positive_factors],
            "negative_factors": [f.to_dict() for f in self.negative_factors],
            "trend": self.trend.value,
            "trend_reason": self.trend_reason_cn if lang == Language.CN else self.trend_reason_en,
            "counterfactuals": [c.to_dict() for c in self.counterfactuals],
            "generated_at": self.generated_at,
            "window_minutes": self.window_minutes,
        }


# State headlines (natural language)
STATE_HEADLINES = {
    "STABLE": {
        "en": "Market depth is holding well",
        "cn": "市场深度表现稳健",
    },
    "FRAGILE": {
        "en": "Market showing early stress signals",
        "cn": "市场出现初期压力信号",
    },
    "CRACKING": {
        "en": "Market depth under significant stress",
        "cn": "市场深度承受较大压力",
    },
    "BROKEN": {
        "en": "Market depth severely compromised",
        "cn": "市场深度严重受损",
    },
}

# Factor descriptions
FACTOR_DESCRIPTIONS = {
    ExplainFactor.HIGH_HOLD_RATIO: {
        "en": "Most shocks result in HOLD reactions",
        "cn": "大多数冲击后深度保持稳定",
    },
    ExplainFactor.LOW_FRAGILE_SIGNALS: {
        "en": "Few fragility signals detected",
        "cn": "脆弱性信号较少",
    },
    ExplainFactor.CONSISTENT_DEPTH: {
        "en": "Depth remains consistent across levels",
        "cn": "各价位深度保持一致",
    },
    ExplainFactor.QUICK_REFILL: {
        "en": "Liquidity refills quickly after trades",
        "cn": "交易后流动性快速恢复",
    },
    ExplainFactor.NO_VACUUM: {
        "en": "No vacuum events at key levels",
        "cn": "关键价位无真空事件",
    },
    ExplainFactor.LOW_HOLD_RATIO: {
        "en": "Low ratio of HOLD reactions to shocks",
        "cn": "冲击后深度保持率较低",
    },
    ExplainFactor.VACUUM_AT_KEY_LEVEL: {
        "en": "Vacuum detected at key price level",
        "cn": "关键价位出现真空",
    },
    ExplainFactor.PULL_AT_KEY_LEVEL: {
        "en": "Depth pulled at key price level",
        "cn": "关键价位深度被撤走",
    },
    ExplainFactor.DEPTH_COLLAPSE: {
        "en": "Multiple levels collapsed simultaneously",
        "cn": "多个价位同时崩溃",
    },
    ExplainFactor.PRE_SHOCK_PULL: {
        "en": "Depth pulled before shock (potential information leakage)",
        "cn": "冲击前深度被撤走（可能存在信息泄露）",
    },
    ExplainFactor.MULTIPLE_VACUUM: {
        "en": "Multiple vacuum events detected",
        "cn": "检测到多次真空事件",
    },
    ExplainFactor.GRADUAL_THINNING: {
        "en": "Gradual thinning of depth over time",
        "cn": "深度逐渐稀薄",
    },
    ExplainFactor.CANCEL_DOMINATED: {
        "en": "Depth changes dominated by cancellations",
        "cn": "深度变化以撤单为主",
    },
    ExplainFactor.HIGH_FRAGILITY_INDEX: {
        "en": "High fragility index in recent window",
        "cn": "近期脆弱性指数较高",
    },
    ExplainFactor.RECENT_STATE_CHANGE: {
        "en": "State changed recently",
        "cn": "状态近期发生变化",
    },
    ExplainFactor.ACTIVE_ALERTS: {
        "en": "Active alerts on this market",
        "cn": "该市场有未处理警报",
    },
}


def generate_explanation(
    token_id: str,
    current_state: str,
    metrics: Dict[str, Any],
    previous_state: Optional[str] = None,
    state_history: Optional[List[Tuple[int, str]]] = None,
) -> StateExplanation:
    """
    Generate human-readable explanation for a market's belief state.

    Args:
        token_id: Market identifier
        current_state: Current belief state (STABLE, FRAGILE, CRACKING, BROKEN)
        metrics: Dictionary containing:
            - hold_ratio: float (0-1)
            - fragile_signals: int
            - vacuum_count: int
            - pull_count: int
            - depth_collapse_count: int
            - pre_shock_pull_count: int
            - fragility_index: float (0-100)
            - cancel_driven_ratio: float (0-1)
            - avg_refill_time_ms: float (optional)
            - key_level_events: List[dict] (optional)
            - active_alerts: int (optional)
        previous_state: Previous belief state (for trend detection)
        state_history: List of (timestamp_ms, state) tuples for trend analysis

    Returns:
        StateExplanation with full breakdown
    """
    explanation = StateExplanation(
        token_id=token_id,
        current_state=current_state,
        confidence=_compute_confidence(current_state, metrics),
        headline_en=STATE_HEADLINES.get(current_state, {}).get("en", "Unknown state"),
        headline_cn=STATE_HEADLINES.get(current_state, {}).get("cn", "未知状态"),
        summary_en="",
        summary_cn="",
    )

    # Analyze factors
    positive, negative = _analyze_factors(metrics)
    explanation.positive_factors = positive
    explanation.negative_factors = negative

    # Generate summary from factors
    explanation.summary_en = _generate_summary_en(current_state, positive, negative, metrics)
    explanation.summary_cn = _generate_summary_cn(current_state, positive, negative, metrics)

    # Analyze trend
    if state_history or previous_state:
        trend, reason_en, reason_cn = _analyze_trend(
            current_state, previous_state, state_history
        )
        explanation.trend = trend
        explanation.trend_reason_en = reason_en
        explanation.trend_reason_cn = reason_cn

    # Generate counterfactuals
    explanation.counterfactuals = _generate_counterfactuals(current_state, metrics)

    return explanation


def _compute_confidence(state: str, metrics: Dict[str, Any]) -> float:
    """Compute confidence score for the state classification"""
    base_confidence = {
        "STABLE": 85.0,
        "FRAGILE": 70.0,
        "CRACKING": 60.0,
        "BROKEN": 75.0,  # High confidence when broken
    }.get(state, 50.0)

    # Adjust based on metrics clarity
    hold_ratio = metrics.get("hold_ratio", 0.5)
    fragility_index = metrics.get("fragility_index", 50)

    if state == "STABLE":
        # More confident if hold_ratio is very high
        if hold_ratio > 0.8:
            base_confidence += 10
        elif hold_ratio < 0.6:
            base_confidence -= 10
    elif state == "BROKEN":
        # More confident if fragility is very high
        if fragility_index > 80:
            base_confidence += 10

    return max(30.0, min(99.0, base_confidence))


def _analyze_factors(metrics: Dict[str, Any]) -> Tuple[List[Factor], List[Factor]]:
    """Analyze metrics and extract positive/negative factors"""
    positive = []
    negative = []

    hold_ratio = metrics.get("hold_ratio", 0.5)
    fragile_signals = metrics.get("fragile_signals", 0)
    vacuum_count = metrics.get("vacuum_count", 0)
    pull_count = metrics.get("pull_count", 0)
    depth_collapse_count = metrics.get("depth_collapse_count", 0)
    pre_shock_pull_count = metrics.get("pre_shock_pull_count", 0)
    fragility_index = metrics.get("fragility_index", 50)
    cancel_driven_ratio = metrics.get("cancel_driven_ratio", 0.5)
    avg_refill_time_ms = metrics.get("avg_refill_time_ms")
    active_alerts = metrics.get("active_alerts", 0)

    # Positive factors
    if hold_ratio >= 0.7:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.HIGH_HOLD_RATIO]
        positive.append(Factor(
            factor_type=ExplainFactor.HIGH_HOLD_RATIO,
            weight=0.8,
            value=f"{hold_ratio:.0%}",
            threshold="≥70%",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if fragile_signals == 0:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.LOW_FRAGILE_SIGNALS]
        positive.append(Factor(
            factor_type=ExplainFactor.LOW_FRAGILE_SIGNALS,
            weight=0.6,
            value=0,
            threshold="0",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if vacuum_count == 0:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.NO_VACUUM]
        positive.append(Factor(
            factor_type=ExplainFactor.NO_VACUUM,
            weight=0.7,
            value=0,
            threshold="0",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if avg_refill_time_ms and avg_refill_time_ms < 1000:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.QUICK_REFILL]
        positive.append(Factor(
            factor_type=ExplainFactor.QUICK_REFILL,
            weight=0.5,
            value=f"{avg_refill_time_ms:.0f}ms",
            threshold="<1000ms",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    # Negative factors
    if hold_ratio < 0.5:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.LOW_HOLD_RATIO]
        negative.append(Factor(
            factor_type=ExplainFactor.LOW_HOLD_RATIO,
            weight=-0.7,
            value=f"{hold_ratio:.0%}",
            threshold="<50%",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if vacuum_count > 0:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.VACUUM_AT_KEY_LEVEL]
        weight = -0.9 if vacuum_count >= 2 else -0.7
        negative.append(Factor(
            factor_type=ExplainFactor.VACUUM_AT_KEY_LEVEL if vacuum_count == 1
                        else ExplainFactor.MULTIPLE_VACUUM,
            weight=weight,
            value=vacuum_count,
            threshold="0",
            description_en=desc["en"] if vacuum_count == 1
                          else FACTOR_DESCRIPTIONS[ExplainFactor.MULTIPLE_VACUUM]["en"],
            description_cn=desc["cn"] if vacuum_count == 1
                          else FACTOR_DESCRIPTIONS[ExplainFactor.MULTIPLE_VACUUM]["cn"],
        ))

    if pull_count > 2:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.PULL_AT_KEY_LEVEL]
        negative.append(Factor(
            factor_type=ExplainFactor.PULL_AT_KEY_LEVEL,
            weight=-0.6,
            value=pull_count,
            threshold="≤2",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if depth_collapse_count > 0:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.DEPTH_COLLAPSE]
        negative.append(Factor(
            factor_type=ExplainFactor.DEPTH_COLLAPSE,
            weight=-0.8,
            value=depth_collapse_count,
            threshold="0",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if pre_shock_pull_count > 0:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.PRE_SHOCK_PULL]
        negative.append(Factor(
            factor_type=ExplainFactor.PRE_SHOCK_PULL,
            weight=-0.85,
            value=pre_shock_pull_count,
            threshold="0",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if fragility_index > 70:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.HIGH_FRAGILITY_INDEX]
        negative.append(Factor(
            factor_type=ExplainFactor.HIGH_FRAGILITY_INDEX,
            weight=-0.6,
            value=f"{fragility_index:.0f}",
            threshold="≤70",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if cancel_driven_ratio > 0.7:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.CANCEL_DOMINATED]
        negative.append(Factor(
            factor_type=ExplainFactor.CANCEL_DOMINATED,
            weight=-0.5,
            value=f"{cancel_driven_ratio:.0%}",
            threshold="≤70%",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    if active_alerts > 0:
        desc = FACTOR_DESCRIPTIONS[ExplainFactor.ACTIVE_ALERTS]
        negative.append(Factor(
            factor_type=ExplainFactor.ACTIVE_ALERTS,
            weight=-0.3,
            value=active_alerts,
            threshold="0",
            description_en=desc["en"],
            description_cn=desc["cn"],
        ))

    # Sort by weight (most impactful first)
    positive.sort(key=lambda f: abs(f.weight), reverse=True)
    negative.sort(key=lambda f: abs(f.weight), reverse=True)

    return positive, negative


def _generate_summary_en(
    state: str,
    positive: List[Factor],
    negative: List[Factor],
    metrics: Dict[str, Any],
) -> str:
    """Generate English summary paragraph"""
    sentences = []

    if state == "STABLE":
        sentences.append("The market is showing healthy depth dynamics.")
        if positive:
            top_positive = [f.description_en for f in positive[:2]]
            sentences.append("Key strengths: " + "; ".join(top_positive) + ".")
        if negative:
            sentences.append(f"Minor concerns: {len(negative)} factor(s) to monitor.")

    elif state == "FRAGILE":
        sentences.append("The market is showing early signs of stress.")
        if negative:
            top_negative = [f.description_en for f in negative[:2]]
            sentences.append("Warning signs: " + "; ".join(top_negative) + ".")
        if positive:
            sentences.append(f"However, {len(positive)} stabilizing factor(s) present.")

    elif state == "CRACKING":
        sentences.append("The market depth is under significant pressure.")
        if negative:
            top_negative = [f.description_en for f in negative[:3]]
            sentences.append("Critical issues: " + "; ".join(top_negative) + ".")
        sentences.append("Close monitoring recommended.")

    elif state == "BROKEN":
        sentences.append("The market depth has been severely compromised.")
        if negative:
            top_negative = [f.description_en for f in negative[:3]]
            sentences.append("Root causes: " + "; ".join(top_negative) + ".")
        sentences.append("Exercise extreme caution.")

    return " ".join(sentences)


def _generate_summary_cn(
    state: str,
    positive: List[Factor],
    negative: List[Factor],
    metrics: Dict[str, Any],
) -> str:
    """Generate Chinese summary paragraph"""
    sentences = []

    if state == "STABLE":
        sentences.append("市场深度动态表现健康。")
        if positive:
            top_positive = [f.description_cn for f in positive[:2]]
            sentences.append("主要优势：" + "；".join(top_positive) + "。")
        if negative:
            sentences.append(f"需关注：{len(negative)}项次要因素。")

    elif state == "FRAGILE":
        sentences.append("市场出现初期压力信号。")
        if negative:
            top_negative = [f.description_cn for f in negative[:2]]
            sentences.append("预警信号：" + "；".join(top_negative) + "。")
        if positive:
            sentences.append(f"但仍有{len(positive)}项稳定因素存在。")

    elif state == "CRACKING":
        sentences.append("市场深度承受较大压力。")
        if negative:
            top_negative = [f.description_cn for f in negative[:3]]
            sentences.append("关键问题：" + "；".join(top_negative) + "。")
        sentences.append("建议密切监控。")

    elif state == "BROKEN":
        sentences.append("市场深度已严重受损。")
        if negative:
            top_negative = [f.description_cn for f in negative[:3]]
            sentences.append("根本原因：" + "；".join(top_negative) + "。")
        sentences.append("请谨慎操作。")

    return "".join(sentences)


STATE_ORDER = ["STABLE", "FRAGILE", "CRACKING", "BROKEN"]


def _analyze_trend(
    current_state: str,
    previous_state: Optional[str],
    state_history: Optional[List[Tuple[int, str]]],
) -> Tuple[TrendDirection, str, str]:
    """Analyze trend from state history"""

    if not previous_state and not state_history:
        return TrendDirection.STABLE, "Insufficient history", "历史数据不足"

    current_idx = STATE_ORDER.index(current_state) if current_state in STATE_ORDER else -1

    if previous_state:
        prev_idx = STATE_ORDER.index(previous_state) if previous_state in STATE_ORDER else -1

        if current_idx < prev_idx:
            return (
                TrendDirection.IMPROVING,
                f"Improved from {previous_state} to {current_state}",
                f"已从{previous_state}改善至{current_state}",
            )
        elif current_idx > prev_idx:
            return (
                TrendDirection.WORSENING,
                f"Declined from {previous_state} to {current_state}",
                f"已从{previous_state}恶化至{current_state}",
            )

    if state_history and len(state_history) >= 3:
        # Check for oscillation
        recent_states = [s for _, s in state_history[-5:]]
        unique_states = set(recent_states)
        if len(unique_states) >= 3:
            return (
                TrendDirection.VOLATILE,
                "Frequent state changes detected",
                "检测到频繁的状态变化",
            )

    return TrendDirection.STABLE, "State is stable", "状态保持稳定"


def _generate_counterfactuals(
    current_state: str,
    metrics: Dict[str, Any],
) -> List[CounterfactualCondition]:
    """
    Generate counterfactual conditions for state transitions.

    v5.36: Enhanced per expert review - now includes BOTH directions:
    1. What would make this better? (recovery path)
    2. Why wasn't this worse? (anti-misuse, explains untriggered conditions)

    The second direction is critical for preventing misuse:
    "未判为 BROKEN：第二 anchor 未出现 VACUUM"
    """
    counterfactuals = []

    hold_ratio = metrics.get("hold_ratio", 0.5)
    vacuum_count = metrics.get("vacuum_count", 0)
    pull_count = metrics.get("pull_count", 0)
    fragility_index = metrics.get("fragility_index", 50)
    multi_anchor_vacuum = metrics.get("multi_anchor_vacuum", False)
    depth_collapse = metrics.get("depth_collapse", False)
    pre_shock_pull = metrics.get("pre_shock_pull", False)

    # =========================================================================
    # RECOVERY PATH: What would make this better?
    # =========================================================================

    if current_state == "BROKEN":
        conditions = []
        if vacuum_count > 0:
            conditions.append(f"Resolve {vacuum_count} vacuum event(s) at key levels")
        conditions.append("Restore depth at compromised levels")
        conditions.append("Observe sustained HOLD reactions over 10+ minutes")

        counterfactuals.append(CounterfactualCondition(
            target_state="CRACKING",
            conditions=conditions,
            likelihood="medium" if vacuum_count <= 2 else "low",
        ))

    if current_state in ["BROKEN", "CRACKING"]:
        conditions = []
        if hold_ratio < 0.5:
            conditions.append(f"Increase hold ratio from {hold_ratio:.0%} to >60%")
        if pull_count > 2:
            conditions.append(f"Reduce PULL reactions from {pull_count} to ≤2")
        conditions.append("No new vacuum events for 10 minutes")

        counterfactuals.append(CounterfactualCondition(
            target_state="FRAGILE",
            conditions=conditions,
            likelihood="medium",
        ))

    if current_state in ["BROKEN", "CRACKING", "FRAGILE"]:
        conditions = []
        if hold_ratio < 0.7:
            conditions.append(f"Increase hold ratio from {hold_ratio:.0%} to ≥70%")
        conditions.append("Zero vacuum events")
        conditions.append("Zero pre-shock pulls")
        if fragility_index > 30:
            conditions.append(f"Reduce fragility index from {fragility_index:.0f} to <30")

        counterfactuals.append(CounterfactualCondition(
            target_state="STABLE",
            conditions=conditions,
            likelihood="high" if current_state == "FRAGILE" else "low",
        ))

    # =========================================================================
    # ANTI-MISUSE: Why wasn't this worse? (v5.36)
    # =========================================================================

    if current_state == "STABLE":
        # Why not FRAGILE?
        not_fragile_reasons = []
        if hold_ratio >= 0.7:
            not_fragile_reasons.append(f"Hold ratio {hold_ratio:.0%} ≥ 70% threshold")
        if vacuum_count == 0:
            not_fragile_reasons.append("No vacuum events detected")
        if pull_count <= 1:
            not_fragile_reasons.append(f"PULL reactions ({pull_count}) within normal range")
        if fragility_index < 30:
            not_fragile_reasons.append(f"Fragility index {fragility_index:.0f} < 30 threshold")

        if not_fragile_reasons:
            counterfactuals.append(CounterfactualCondition(
                target_state="NOT_FRAGILE",
                conditions=not_fragile_reasons,
                likelihood="n/a",  # This is "why not" not "how to"
            ))

    if current_state in ["STABLE", "FRAGILE"]:
        # Why not CRACKING?
        not_cracking_reasons = []
        if vacuum_count == 0:
            not_cracking_reasons.append("No vacuum events at anchor levels")
        if not depth_collapse:
            not_cracking_reasons.append("No depth collapse detected")
        if hold_ratio >= 0.5:
            not_cracking_reasons.append(f"Hold ratio {hold_ratio:.0%} maintaining depth defense")

        if not_cracking_reasons:
            counterfactuals.append(CounterfactualCondition(
                target_state="NOT_CRACKING",
                conditions=not_cracking_reasons,
                likelihood="n/a",
            ))

    if current_state in ["STABLE", "FRAGILE", "CRACKING"]:
        # Why not BROKEN?
        not_broken_reasons = []
        if not multi_anchor_vacuum:
            not_broken_reasons.append("Second anchor did not show vacuum")
        if vacuum_count < 3:
            not_broken_reasons.append(f"Vacuum count ({vacuum_count}) below BROKEN threshold (≥3)")
        if hold_ratio >= 0.3:
            not_broken_reasons.append(f"Hold ratio {hold_ratio:.0%} shows residual defense")
        if not pre_shock_pull:
            not_broken_reasons.append("No pre-shock pull pattern detected")

        if not_broken_reasons:
            counterfactuals.append(CounterfactualCondition(
                target_state="NOT_BROKEN",
                conditions=not_broken_reasons,
                likelihood="n/a",
            ))

    return counterfactuals


def explain_single_event(
    event_type: str,
    event_data: Dict[str, Any],
    lang: Language = Language.EN,
) -> str:
    """
    Generate natural language explanation for a single event.

    Args:
        event_type: Type of event (shock, reaction, leading_event, state_change)
        event_data: Event data dictionary
        lang: Language for explanation

    Returns:
        Human-readable explanation string
    """
    if event_type == "shock":
        price = event_data.get("price", "?")
        volume = event_data.get("trade_volume", 0)
        side = event_data.get("side", "?")

        if lang == Language.CN:
            return f"在{price}价位检测到{side}方向冲击，交易量{volume:.0f}"
        return f"Shock detected at {price} ({side} side), volume {volume:.0f}"

    elif event_type == "reaction":
        reaction_type = event_data.get("reaction_type", "?")
        price = event_data.get("price", "?")
        drop_ratio = event_data.get("drop_ratio", 0)

        if lang == Language.CN:
            type_cn = {
                "HOLD": "保持",
                "PULL": "撤走",
                "VACUUM": "真空",
                "SWEEP": "扫单",
                "CHASE": "追逐",
                "DELAYED": "延迟",
            }.get(reaction_type, reaction_type)
            return f"反应类型：{type_cn}，价位{price}，下降{drop_ratio:.0%}"
        return f"Reaction: {reaction_type} at {price}, drop {drop_ratio:.0%}"

    elif event_type == "leading_event":
        event_subtype = event_data.get("event_type", "?")
        price = event_data.get("price", "?")

        if lang == Language.CN:
            type_cn = {
                "PRE_SHOCK_PULL": "冲击前撤单",
                "DEPTH_COLLAPSE": "深度崩溃",
                "GRADUAL_THINNING": "逐渐稀薄",
            }.get(event_subtype, event_subtype)
            return f"领先信号：{type_cn}，价位{price}"
        return f"Leading signal: {event_subtype} at {price}"

    elif event_type == "state_change":
        old_state = event_data.get("old_state", "?")
        new_state = event_data.get("new_state", "?")
        evidence_count = len(event_data.get("evidence_refs", []))

        if lang == Language.CN:
            return f"信念状态从{old_state}变为{new_state}（{evidence_count}个证据支持）"
        return f"Belief state changed from {old_state} to {new_state} ({evidence_count} evidence items)"

    return f"Unknown event type: {event_type}"


def generate_radar_tooltip(
    market_data: Dict[str, Any],
    lang: Language = Language.EN,
) -> Dict[str, str]:
    """
    Generate tooltip content for radar/dashboard display.

    Args:
        market_data: RadarMarket-like dictionary
        lang: Language for tooltip

    Returns:
        Dictionary with tooltip sections
    """
    state = market_data.get("state", "UNKNOWN")
    confidence = market_data.get("confidence", 0)
    leading_rate = market_data.get("leading_rate_10m", 0)
    fragile_index = market_data.get("fragile_index_10m", 0)
    last_alert = market_data.get("last_critical_alert")

    tooltip = {}

    # State section
    if lang == Language.CN:
        tooltip["state"] = f"信念状态: {state} ({confidence:.0f}% 置信度)"
        tooltip["metrics"] = f"领先信号率: {leading_rate:.1f}/10分钟 | 脆弱指数: {fragile_index:.0f}"
        if last_alert:
            tooltip["alert"] = f"最近警报: {last_alert.get('type', '?')}"
        tooltip["tip"] = "点击查看详细证据"
    else:
        tooltip["state"] = f"Belief State: {state} ({confidence:.0f}% confidence)"
        tooltip["metrics"] = f"Leading rate: {leading_rate:.1f}/10min | Fragility: {fragile_index:.0f}"
        if last_alert:
            tooltip["alert"] = f"Last alert: {last_alert.get('type', '?')}"
        tooltip["tip"] = "Click for detailed evidence"

    return tooltip
