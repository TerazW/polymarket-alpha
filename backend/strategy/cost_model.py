"""
Transaction Cost Model for Polymarket

Models all costs of executing a trade:
1. Maker/taker fees (Polymarket fee schedule)
2. Bid-ask spread cost
3. Market impact / slippage (square-root model)

A trade is only profitable if: edge > total_cost

References:
- Polymarket fee docs: per-token basis points, charged to taker
- Almgren & Chriss (2001) for market impact modeling
- Gatheral (2010) for square-root impact calibration
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class CostConfig:
    """Transaction cost configuration."""
    # Polymarket fee structure
    taker_fee_bps: float = 200.0      # 2% taker fee (200 basis points)
    maker_fee_bps: float = 0.0        # 0% maker fee (maker rebate possible)

    # Whether we're placing limit orders (maker) or market orders (taker)
    # In practice, aggressive limit orders that cross the spread are taker
    use_maker_fees: bool = False       # Conservative: assume taker

    # Slippage model parameters
    # Impact = eta * sign(Q) * (|Q| / ADV)^0.5 * p * (1-p)
    # eta = permanent impact coefficient
    impact_eta: float = 0.1           # Calibrate from data
    # Temporary impact (mean-reversion component)
    temp_impact_fraction: float = 0.6  # 60% of impact is temporary

    # Minimum spread assumption when book data unavailable
    default_spread_bps: float = 100.0  # 1% default spread


class TransactionCostModel:
    """
    Full transaction cost model.

    Total cost = fee + half_spread + market_impact

    All costs expressed as a fraction of notional (e.g., 0.02 = 2%).
    """

    def __init__(self, config: Optional[CostConfig] = None):
        self.config = config or CostConfig()

    def estimate_total_cost(
        self,
        price: float,
        size_usd: float,
        spread: Optional[float] = None,
        book_depth_usd: Optional[float] = None,
        daily_volume: Optional[float] = None,
    ) -> Dict:
        """
        Estimate total round-trip cost for a trade.

        Args:
            price: Market price (mid) in [0, 1]
            size_usd: Trade size in USDC
            spread: Current bid-ask spread (absolute, e.g., 0.02)
            book_depth_usd: Total book depth within 2% of mid (USD)
            daily_volume: 24h volume (USD) for impact calibration

        Returns:
            Dict with cost breakdown and total
        """
        # 1. Fee cost (one-way)
        fee_one_way = self._fee_cost()

        # 2. Spread cost (half-spread for immediate execution)
        spread_cost = self._spread_cost(price, spread)

        # 3. Market impact
        impact_cost = self._impact_cost(
            price, size_usd, book_depth_usd, daily_volume
        )

        # Total one-way cost
        one_way = fee_one_way + spread_cost + impact_cost

        # Round-trip (entry + exit)
        round_trip = one_way * 2

        return {
            "fee_one_way": fee_one_way,
            "spread_cost": spread_cost,
            "impact_cost": impact_cost,
            "total_one_way": one_way,
            "total_round_trip": round_trip,
            "min_edge_required": round_trip,  # Edge must exceed this
            # Breakdown in USD
            "cost_usd_one_way": one_way * size_usd,
            "cost_usd_round_trip": round_trip * size_usd,
        }

    def is_trade_profitable(
        self,
        edge: float,
        price: float,
        size_usd: float,
        spread: Optional[float] = None,
        book_depth_usd: Optional[float] = None,
        daily_volume: Optional[float] = None,
    ) -> Dict:
        """
        Check if a trade is profitable after costs.

        Returns:
            Dict with profitability analysis
        """
        costs = self.estimate_total_cost(
            price, size_usd, spread, book_depth_usd, daily_volume
        )

        net_edge = abs(edge) - costs["total_one_way"]
        # For event markets, we typically hold to resolution (no exit spread)
        # So use one-way cost, not round-trip
        # But include impact on entry
        hold_to_resolution_cost = costs["fee_one_way"] + costs["spread_cost"] + costs["impact_cost"]
        net_edge_hold = abs(edge) - hold_to_resolution_cost

        return {
            "profitable_round_trip": net_edge > 0,
            "profitable_hold_to_resolution": net_edge_hold > 0,
            "gross_edge": abs(edge),
            "total_cost_one_way": costs["total_one_way"],
            "total_cost_round_trip": costs["total_round_trip"],
            "net_edge_round_trip": net_edge,
            "net_edge_hold": net_edge_hold,
            "edge_cost_ratio": abs(edge) / costs["total_one_way"] if costs["total_one_way"] > 0 else float('inf'),
            "cost_breakdown": costs,
        }

    def _fee_cost(self) -> float:
        """Fee as fraction of notional."""
        if self.config.use_maker_fees:
            return self.config.maker_fee_bps / 10000.0
        return self.config.taker_fee_bps / 10000.0

    def _spread_cost(self, price: float, spread: Optional[float] = None) -> float:
        """
        Half-spread cost in absolute terms.

        For prediction markets, the spread IS already in probability units.
        If bid=0.49 and ask=0.51, spread=0.02, half-spread=0.01.
        That 0.01 is the cost in the same units as our edge.

        We do NOT divide by price — our edge is also in absolute terms
        (e.g., edge=0.025 means we think true prob is 2.5% away from market).
        """
        if spread is not None:
            return spread / 2.0
        else:
            return (self.config.default_spread_bps / 10000.0) / 2.0

    def _impact_cost(
        self,
        price: float,
        size_usd: float,
        book_depth_usd: Optional[float] = None,
        daily_volume: Optional[float] = None,
    ) -> float:
        """
        Market impact using square-root model adapted for [0,1] prices.

        impact = eta * sqrt(Q / ADV) * p * (1-p)

        The p*(1-p) term captures boundary effects: impact is lower
        near 0 or 1 where there's natural convergence.
        """
        if daily_volume is None and book_depth_usd is None:
            # No liquidity data; use conservative estimate
            return 0.005  # 0.5% default impact

        # Use book depth if available, else daily volume
        if book_depth_usd is not None and book_depth_usd > 0:
            participation_rate = size_usd / book_depth_usd
        elif daily_volume is not None and daily_volume > 0:
            participation_rate = size_usd / daily_volume
        else:
            return 0.005

        # Square-root impact
        raw_impact = self.config.impact_eta * np.sqrt(participation_rate)

        # Boundary adjustment: impact lower near 0 or 1
        boundary_factor = price * (1 - price) / 0.25  # Peaks at 0.5

        impact = raw_impact * boundary_factor

        return float(np.clip(impact, 0, 0.10))  # Cap at 10%

    def adjust_edge_for_costs(
        self,
        edge: float,
        price: float,
        size_usd: float,
        spread: Optional[float] = None,
        book_depth_usd: Optional[float] = None,
        daily_volume: Optional[float] = None,
        hold_to_resolution: bool = True,
    ) -> float:
        """
        Return edge net of transaction costs.

        For Kelly sizing, use this net edge instead of gross edge.
        """
        costs = self.estimate_total_cost(
            price, size_usd, spread, book_depth_usd, daily_volume
        )
        if hold_to_resolution:
            return abs(edge) - costs["total_one_way"]
        else:
            return abs(edge) - costs["total_round_trip"]
