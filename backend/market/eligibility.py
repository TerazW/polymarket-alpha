"""
Market Eligibility Layer (v5.36)

Evaluates market suitability for the Belief Reaction System.

"不是所有市场都适合感知信念变化。"

Markets are classified into:
- ELIGIBLE: Full processing, all alert severities allowed
- DEGRADED: Processing with restrictions, no CRITICAL alerts
- OBSERVE_ONLY: Heatmap only, no state machine
- EXCLUDED: Not processed at all

Eligibility is based on:
1. Liquidity quality (not just size)
2. Participant diversity (trade/cancel patterns)
3. Human rhythm detection (non-bot activity)
4. Spoofing/manipulation ratio

This layer prevents the system from:
- Generating false confidence from thin/manipulated markets
- Treating bot activity as human belief signals
- Over-alerting on markets where the paradigm doesn't apply
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import time
import math


class EligibilityStatus(str, Enum):
    """Market eligibility classification"""
    ELIGIBLE = "ELIGIBLE"           # Full processing
    DEGRADED = "DEGRADED"           # Restricted (no CRITICAL alerts)
    OBSERVE_ONLY = "OBSERVE_ONLY"   # Heatmap only, no state machine
    EXCLUDED = "EXCLUDED"           # Not processed


class EligibilityReason(str, Enum):
    """Reasons for eligibility classification"""
    # Positive
    SUFFICIENT_LIQUIDITY = "SUFFICIENT_LIQUIDITY"
    DIVERSE_PARTICIPANTS = "DIVERSE_PARTICIPANTS"
    HUMAN_RHYTHM_DETECTED = "HUMAN_RHYTHM_DETECTED"
    LOW_MANIPULATION = "LOW_MANIPULATION"

    # Negative
    THIN_LIQUIDITY = "THIN_LIQUIDITY"
    BOT_DOMINATED = "BOT_DOMINATED"
    HIGH_SPOOFING = "HIGH_SPOOFING"
    NO_RECENT_ACTIVITY = "NO_RECENT_ACTIVITY"
    SINGLE_PARTICIPANT = "SINGLE_PARTICIPANT"
    PRICE_MANIPULATION = "PRICE_MANIPULATION"
    WASH_TRADING = "WASH_TRADING"


@dataclass
class EligibilityScore:
    """Detailed eligibility scoring for a market"""
    token_id: str
    status: EligibilityStatus
    score: float  # 0.0 - 1.0

    # Component scores (0.0 - 1.0 each)
    liquidity_score: float = 0.0
    diversity_score: float = 0.0
    rhythm_score: float = 0.0
    manipulation_score: float = 0.0  # Higher = less manipulation

    # Reasons
    positive_reasons: List[EligibilityReason] = field(default_factory=list)
    negative_reasons: List[EligibilityReason] = field(default_factory=list)

    # Metadata
    evaluated_at: int = 0
    valid_until: int = 0  # Re-evaluate after this time
    sample_window_hours: int = 24

    # Raw metrics used for scoring
    metrics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.evaluated_at == 0:
            self.evaluated_at = int(time.time() * 1000)
        if self.valid_until == 0:
            # Default validity: 1 hour
            self.valid_until = self.evaluated_at + 3600000

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "status": self.status.value,
            "score": round(self.score, 3),
            "components": {
                "liquidity": round(self.liquidity_score, 3),
                "diversity": round(self.diversity_score, 3),
                "rhythm": round(self.rhythm_score, 3),
                "manipulation": round(self.manipulation_score, 3),
            },
            "positive_reasons": [r.value for r in self.positive_reasons],
            "negative_reasons": [r.value for r in self.negative_reasons],
            "evaluated_at": self.evaluated_at,
            "valid_until": self.valid_until,
            "metrics": self.metrics,
        }


# Thresholds for eligibility classification
ELIGIBILITY_THRESHOLDS = {
    # Status thresholds (score-based)
    "eligible_min_score": 0.6,
    "degraded_min_score": 0.3,
    "observe_only_min_score": 0.1,

    # Liquidity thresholds
    "min_baseline_liquidity": 500.0,      # Minimum $ at best levels
    "thin_liquidity_threshold": 100.0,    # Below this = THIN_LIQUIDITY

    # Diversity thresholds
    "min_unique_traders_24h": 5,          # Minimum distinct traders
    "single_participant_ratio": 0.9,      # If one trader > 90% volume

    # Rhythm thresholds (human vs bot)
    "human_rhythm_variance": 0.3,         # Time interval variance
    "bot_pattern_threshold": 0.1,         # Too regular = bot

    # Manipulation thresholds
    "max_spoofing_ratio": 0.3,            # Cancel/place ratio
    "max_wash_trading_ratio": 0.2,        # Self-trade detection

    # Activity thresholds
    "min_trades_24h": 10,                 # Minimum trade count
    "max_inactive_hours": 12,             # Hours without activity
}


class MarketEligibilityEvaluator:
    """
    Evaluates market eligibility for belief reaction processing.

    Usage:
        evaluator = MarketEligibilityEvaluator()
        score = evaluator.evaluate(token_id, market_metrics)

        if score.status == EligibilityStatus.ELIGIBLE:
            # Full processing
        elif score.status == EligibilityStatus.DEGRADED:
            # Process but cap alert severity at HIGH
        elif score.status == EligibilityStatus.OBSERVE_ONLY:
            # Heatmap only, skip state machine
        else:
            # Skip entirely
    """

    def __init__(self, thresholds: Dict[str, Any] = None):
        self.thresholds = {**ELIGIBILITY_THRESHOLDS, **(thresholds or {})}
        self._cache: Dict[str, EligibilityScore] = {}

    def evaluate(
        self,
        token_id: str,
        metrics: Dict[str, Any],
        force_refresh: bool = False
    ) -> EligibilityScore:
        """
        Evaluate market eligibility.

        Args:
            token_id: Market token ID
            metrics: Market metrics dict containing:
                - baseline_liquidity: float ($ at best levels)
                - trade_count_24h: int
                - unique_traders_24h: int
                - cancel_place_ratio: float
                - trade_intervals: List[int] (ms between trades)
                - top_trader_volume_ratio: float
                - last_activity_ts: int (ms)
                - wash_trade_ratio: float (optional)
            force_refresh: Bypass cache

        Returns:
            EligibilityScore with status and details
        """
        now_ms = int(time.time() * 1000)

        # Check cache
        if not force_refresh and token_id in self._cache:
            cached = self._cache[token_id]
            if cached.valid_until > now_ms:
                return cached

        # Compute component scores
        liquidity_score, liq_reasons = self._score_liquidity(metrics)
        diversity_score, div_reasons = self._score_diversity(metrics)
        rhythm_score, rhythm_reasons = self._score_rhythm(metrics)
        manipulation_score, manip_reasons = self._score_manipulation(metrics)

        # Aggregate score (weighted average)
        weights = {
            "liquidity": 0.3,
            "diversity": 0.25,
            "rhythm": 0.2,
            "manipulation": 0.25,
        }

        total_score = (
            liquidity_score * weights["liquidity"] +
            diversity_score * weights["diversity"] +
            rhythm_score * weights["rhythm"] +
            manipulation_score * weights["manipulation"]
        )

        # Collect reasons
        positive_reasons = []
        negative_reasons = []

        for reasons, is_positive in [
            (liq_reasons, True), (div_reasons, True),
            (rhythm_reasons, True), (manip_reasons, True)
        ]:
            for reason, positive in reasons:
                if positive:
                    positive_reasons.append(reason)
                else:
                    negative_reasons.append(reason)

        # Determine status
        status = self._determine_status(
            total_score,
            liquidity_score,
            metrics,
            negative_reasons
        )

        # Create score object
        score = EligibilityScore(
            token_id=token_id,
            status=status,
            score=total_score,
            liquidity_score=liquidity_score,
            diversity_score=diversity_score,
            rhythm_score=rhythm_score,
            manipulation_score=manipulation_score,
            positive_reasons=positive_reasons,
            negative_reasons=negative_reasons,
            evaluated_at=now_ms,
            valid_until=now_ms + 3600000,  # 1 hour validity
            metrics=metrics,
        )

        # Cache result
        self._cache[token_id] = score

        return score

    def _score_liquidity(
        self,
        metrics: Dict[str, Any]
    ) -> Tuple[float, List[Tuple[EligibilityReason, bool]]]:
        """Score liquidity quality"""
        reasons = []
        baseline = metrics.get("baseline_liquidity", 0)

        if baseline < self.thresholds["thin_liquidity_threshold"]:
            reasons.append((EligibilityReason.THIN_LIQUIDITY, False))
            return 0.1, reasons

        if baseline >= self.thresholds["min_baseline_liquidity"]:
            reasons.append((EligibilityReason.SUFFICIENT_LIQUIDITY, True))
            # Scale: 500 = 0.6, 2000 = 0.9, 5000+ = 1.0
            score = min(1.0, 0.6 + (baseline - 500) / 10000)
            return score, reasons

        # Between thin and sufficient
        score = 0.3 + 0.3 * (baseline - self.thresholds["thin_liquidity_threshold"]) / (
            self.thresholds["min_baseline_liquidity"] - self.thresholds["thin_liquidity_threshold"]
        )
        return score, reasons

    def _score_diversity(
        self,
        metrics: Dict[str, Any]
    ) -> Tuple[float, List[Tuple[EligibilityReason, bool]]]:
        """Score participant diversity"""
        reasons = []

        unique_traders = metrics.get("unique_traders_24h", 0)
        top_trader_ratio = metrics.get("top_trader_volume_ratio", 1.0)
        trade_count = metrics.get("trade_count_24h", 0)

        # Check for single participant dominance
        if top_trader_ratio > self.thresholds["single_participant_ratio"]:
            reasons.append((EligibilityReason.SINGLE_PARTICIPANT, False))
            return 0.1, reasons

        # Check minimum traders
        if unique_traders < self.thresholds["min_unique_traders_24h"]:
            score = 0.2 + 0.2 * (unique_traders / self.thresholds["min_unique_traders_24h"])
            return score, reasons

        # Good diversity
        reasons.append((EligibilityReason.DIVERSE_PARTICIPANTS, True))

        # Scale by trader count: 5 = 0.6, 20 = 0.9, 50+ = 1.0
        score = min(1.0, 0.6 + (unique_traders - 5) / 100)

        # Adjust by concentration
        score *= (1.0 - top_trader_ratio * 0.3)

        return max(0.0, min(1.0, score)), reasons

    def _score_rhythm(
        self,
        metrics: Dict[str, Any]
    ) -> Tuple[float, List[Tuple[EligibilityReason, bool]]]:
        """Score human rhythm vs bot patterns"""
        reasons = []

        trade_intervals = metrics.get("trade_intervals", [])
        last_activity = metrics.get("last_activity_ts", 0)
        now_ms = int(time.time() * 1000)

        # Check for inactivity
        if last_activity > 0:
            hours_inactive = (now_ms - last_activity) / 3600000
            if hours_inactive > self.thresholds["max_inactive_hours"]:
                reasons.append((EligibilityReason.NO_RECENT_ACTIVITY, False))
                return 0.2, reasons

        # Check interval variance (humans are irregular, bots are regular)
        if len(trade_intervals) >= 10:
            mean_interval = sum(trade_intervals) / len(trade_intervals)
            if mean_interval > 0:
                variance = sum((x - mean_interval) ** 2 for x in trade_intervals) / len(trade_intervals)
                std_dev = math.sqrt(variance)
                cv = std_dev / mean_interval  # Coefficient of variation

                if cv < self.thresholds["bot_pattern_threshold"]:
                    reasons.append((EligibilityReason.BOT_DOMINATED, False))
                    return 0.3, reasons

                if cv > self.thresholds["human_rhythm_variance"]:
                    reasons.append((EligibilityReason.HUMAN_RHYTHM_DETECTED, True))
                    return min(1.0, 0.7 + cv * 0.3), reasons

        # Default: moderate score
        return 0.5, reasons

    def _score_manipulation(
        self,
        metrics: Dict[str, Any]
    ) -> Tuple[float, List[Tuple[EligibilityReason, bool]]]:
        """Score manipulation indicators (higher = less manipulation)"""
        reasons = []

        cancel_place_ratio = metrics.get("cancel_place_ratio", 0)
        wash_trade_ratio = metrics.get("wash_trade_ratio", 0)

        score = 1.0

        # Spoofing detection (high cancel ratio)
        if cancel_place_ratio > self.thresholds["max_spoofing_ratio"]:
            reasons.append((EligibilityReason.HIGH_SPOOFING, False))
            score -= 0.4

        # Wash trading detection
        if wash_trade_ratio > self.thresholds["max_wash_trading_ratio"]:
            reasons.append((EligibilityReason.WASH_TRADING, False))
            score -= 0.4

        if score >= 0.8:
            reasons.append((EligibilityReason.LOW_MANIPULATION, True))

        return max(0.0, score), reasons

    def _determine_status(
        self,
        score: float,
        liquidity_score: float,
        metrics: Dict[str, Any],
        negative_reasons: List[EligibilityReason]
    ) -> EligibilityStatus:
        """Determine final eligibility status"""

        # Hard exclusions (regardless of score)
        critical_negatives = {
            EligibilityReason.WASH_TRADING,
            EligibilityReason.HIGH_SPOOFING,
        }

        if any(r in critical_negatives for r in negative_reasons):
            # If manipulation is detected, max status is OBSERVE_ONLY
            if score >= self.thresholds["observe_only_min_score"]:
                return EligibilityStatus.OBSERVE_ONLY
            return EligibilityStatus.EXCLUDED

        # Score-based classification
        if score >= self.thresholds["eligible_min_score"]:
            return EligibilityStatus.ELIGIBLE

        if score >= self.thresholds["degraded_min_score"]:
            return EligibilityStatus.DEGRADED

        if score >= self.thresholds["observe_only_min_score"]:
            return EligibilityStatus.OBSERVE_ONLY

        return EligibilityStatus.EXCLUDED

    def get_alert_severity_cap(self, status: EligibilityStatus) -> Optional[str]:
        """
        Get maximum alert severity allowed for a status.

        Returns:
            Maximum severity string, or None for no cap
        """
        caps = {
            EligibilityStatus.ELIGIBLE: None,      # No cap
            EligibilityStatus.DEGRADED: "HIGH",    # Cap at HIGH
            EligibilityStatus.OBSERVE_ONLY: None,  # No alerts (no state machine)
            EligibilityStatus.EXCLUDED: None,      # No processing
        }
        return caps.get(status)

    def should_run_state_machine(self, status: EligibilityStatus) -> bool:
        """Check if state machine should run for this status"""
        return status in (EligibilityStatus.ELIGIBLE, EligibilityStatus.DEGRADED)

    def should_generate_tiles(self, status: EligibilityStatus) -> bool:
        """Check if heatmap tiles should be generated for this status"""
        return status in (
            EligibilityStatus.ELIGIBLE,
            EligibilityStatus.DEGRADED,
            EligibilityStatus.OBSERVE_ONLY
        )

    def clear_cache(self, token_id: str = None):
        """Clear eligibility cache"""
        if token_id:
            self._cache.pop(token_id, None)
        else:
            self._cache.clear()


# Singleton instance
_evaluator: Optional[MarketEligibilityEvaluator] = None


def get_eligibility_evaluator() -> MarketEligibilityEvaluator:
    """Get singleton evaluator instance"""
    global _evaluator
    if _evaluator is None:
        _evaluator = MarketEligibilityEvaluator()
    return _evaluator


def evaluate_market_eligibility(
    token_id: str,
    metrics: Dict[str, Any]
) -> EligibilityScore:
    """Convenience function for market evaluation"""
    return get_eligibility_evaluator().evaluate(token_id, metrics)
