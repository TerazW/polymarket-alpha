"""
Market module - Market eligibility and selection logic.

"不是所有市场都适合感知信念变化。"
"""

from .eligibility import (
    MarketEligibilityEvaluator,
    EligibilityStatus,
    EligibilityReason,
    EligibilityScore,
    get_eligibility_evaluator,
    evaluate_market_eligibility,
    ELIGIBILITY_THRESHOLDS,
)

__all__ = [
    "MarketEligibilityEvaluator",
    "EligibilityStatus",
    "EligibilityReason",
    "EligibilityScore",
    "get_eligibility_evaluator",
    "evaluate_market_eligibility",
    "ELIGIBILITY_THRESHOLDS",
]
