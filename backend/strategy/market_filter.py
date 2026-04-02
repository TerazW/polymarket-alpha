"""
Market Selection Filter

Determines which markets are eligible for trading based on
liquidity, depth, volume, and structural criteria.

A market must pass ALL filters to be traded. This prevents the system
from wasting signals on markets where execution is impractical.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class FilterReason(Enum):
    PASSED = "PASSED"
    LOW_VOLUME = "LOW_VOLUME"
    LOW_DEPTH = "LOW_DEPTH"
    WIDE_SPREAD = "WIDE_SPREAD"
    NEAR_RESOLUTION = "NEAR_RESOLUTION"
    EXTREME_PRICE = "EXTREME_PRICE"
    INACTIVE = "INACTIVE"


@dataclass
class MarketFilterConfig:
    """Market selection criteria."""
    # Volume filters
    min_volume_24h: float = 10000.0       # $10K minimum 24h volume
    min_volume_7d: float = 50000.0        # $50K minimum 7d volume

    # Depth filters
    min_book_depth_usd: float = 5000.0    # $5K minimum total depth
    min_best_level_usd: float = 500.0     # $500 minimum at best bid/ask

    # Spread filter
    max_spread_pct: float = 0.04          # 4% maximum bid-ask spread

    # Price filters (avoid extreme markets)
    min_price: float = 0.05               # Don't trade below 5%
    max_price: float = 0.95               # Don't trade above 95%

    # Time filters
    min_hours_to_resolution: float = 24.0  # At least 24h to expiry

    # Activity filters
    min_trades_per_hour: float = 2.0      # At least 2 trades/hour
    max_hours_since_last_trade: float = 4.0  # Activity within 4 hours


@dataclass
class MarketSnapshot:
    """Current state of a market for filtering."""
    token_id: str
    market_id: str = ""
    question: str = ""

    # Price
    last_price: float = 0.5
    bid_price: float = 0.0
    ask_price: float = 1.0

    # Depth
    bid_depth_usd: float = 0.0           # Total bid side depth
    ask_depth_usd: float = 0.0           # Total ask side depth
    best_bid_size_usd: float = 0.0
    best_ask_size_usd: float = 0.0

    # Volume
    volume_24h: float = 0.0
    volume_7d: float = 0.0
    trades_per_hour: float = 0.0

    # Time
    hours_to_resolution: Optional[float] = None
    hours_since_last_trade: float = 0.0

    # Activity
    active: bool = True
    closed: bool = False


@dataclass
class FilterResult:
    """Result of market eligibility check."""
    eligible: bool
    reason: FilterReason
    details: str = ""
    # Scores for ranking eligible markets
    liquidity_score: float = 0.0
    spread_score: float = 0.0
    volume_score: float = 0.0
    overall_score: float = 0.0


class MarketFilter:
    """
    Market eligibility filter.

    Applies all criteria and returns a pass/fail with reason.
    Also scores eligible markets for prioritization.
    """

    def __init__(self, config: Optional[MarketFilterConfig] = None):
        self.config = config or MarketFilterConfig()

    def evaluate(self, market: MarketSnapshot) -> FilterResult:
        """
        Evaluate a single market for trading eligibility.

        Returns FilterResult with pass/fail and scoring.
        """
        # Hard filters (any failure = reject)
        if not market.active or market.closed:
            return FilterResult(False, FilterReason.INACTIVE, "Market inactive or closed")

        if market.volume_24h < self.config.min_volume_24h:
            return FilterResult(
                False, FilterReason.LOW_VOLUME,
                f"24h vol ${market.volume_24h:.0f} < ${self.config.min_volume_24h:.0f}"
            )

        total_depth = market.bid_depth_usd + market.ask_depth_usd
        if total_depth < self.config.min_book_depth_usd:
            return FilterResult(
                False, FilterReason.LOW_DEPTH,
                f"Depth ${total_depth:.0f} < ${self.config.min_book_depth_usd:.0f}"
            )

        if (market.best_bid_size_usd < self.config.min_best_level_usd
                or market.best_ask_size_usd < self.config.min_best_level_usd):
            return FilterResult(
                False, FilterReason.LOW_DEPTH,
                f"Best level too thin: bid=${market.best_bid_size_usd:.0f} ask=${market.best_ask_size_usd:.0f}"
            )

        # Spread check
        spread = market.ask_price - market.bid_price
        if spread > self.config.max_spread_pct and market.bid_price > 0:
            spread_pct = spread / market.last_price if market.last_price > 0 else spread
            if spread_pct > self.config.max_spread_pct:
                return FilterResult(
                    False, FilterReason.WIDE_SPREAD,
                    f"Spread {spread_pct:.1%} > {self.config.max_spread_pct:.1%}"
                )

        # Price bounds
        if market.last_price < self.config.min_price:
            return FilterResult(
                False, FilterReason.EXTREME_PRICE,
                f"Price {market.last_price:.2f} too low"
            )
        if market.last_price > self.config.max_price:
            return FilterResult(
                False, FilterReason.EXTREME_PRICE,
                f"Price {market.last_price:.2f} too high"
            )

        # Time to resolution
        if (market.hours_to_resolution is not None
                and market.hours_to_resolution < self.config.min_hours_to_resolution):
            return FilterResult(
                False, FilterReason.NEAR_RESOLUTION,
                f"{market.hours_to_resolution:.1f}h to resolution < {self.config.min_hours_to_resolution}h"
            )

        # Activity check
        if market.hours_since_last_trade > self.config.max_hours_since_last_trade:
            return FilterResult(
                False, FilterReason.INACTIVE,
                f"Last trade {market.hours_since_last_trade:.1f}h ago"
            )

        # --- Passed all filters, compute scores ---
        spread_val = spread if spread > 0 else 0.01
        liquidity_score = min(1.0, total_depth / 50000.0)
        spread_score = max(0.0, 1.0 - spread_val / 0.05)
        volume_score = min(1.0, market.volume_24h / 100000.0)
        overall_score = (
            liquidity_score * 0.4
            + spread_score * 0.3
            + volume_score * 0.3
        )

        return FilterResult(
            eligible=True,
            reason=FilterReason.PASSED,
            details=f"Score={overall_score:.2f}",
            liquidity_score=liquidity_score,
            spread_score=spread_score,
            volume_score=volume_score,
            overall_score=overall_score,
        )

    def filter_markets(
        self, markets: List[MarketSnapshot]
    ) -> List[tuple]:
        """
        Filter and rank a list of markets.

        Returns list of (market, result) tuples, sorted by overall_score desc.
        Only includes eligible markets.
        """
        results = []
        for market in markets:
            result = self.evaluate(market)
            if result.eligible:
                results.append((market, result))

        # Sort by score descending
        results.sort(key=lambda x: x[1].overall_score, reverse=True)

        n_passed = len(results)
        n_total = len(markets)
        logger.info(
            f"Market filter: {n_passed}/{n_total} eligible "
            f"(top score: {results[0][1].overall_score:.2f})" if results else
            f"Market filter: 0/{n_total} eligible"
        )
        return results
