"""
Unified Attribution System (v5.19)

Provides standardized attribution for depth changes in the order book:

1. **Trade-driven**: Depth removed by aggressive orders eating liquidity
2. **Cancel-driven**: Depth removed by makers withdrawing orders
3. **Replenishment**: Depth added during observation window

Misattribution leads to wrong signals:
- Treating cancel as trade = overestimate aggression
- Treating trade as cancel = miss actual market activity

"不能把撤单当扫单、把扫单当撤单"

Usage:
    from backend.common.attribution import (
        DepthChangeAttribution,
        compute_attribution,
        AttributionType,
    )

    # Compute attribution
    attribution = compute_attribution(
        depth_before=1000.0,
        depth_after=500.0,
        trade_volume=300.0
    )

    print(f"Trade-driven: {attribution.trade_driven_ratio:.1%}")
    print(f"Cancel-driven: {attribution.cancel_driven_ratio:.1%}")
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import time


class AttributionType(str, Enum):
    """Primary attribution type for a depth change"""
    TRADE_DRIVEN = "TRADE_DRIVEN"       # Mostly trade-driven (>70%)
    CANCEL_DRIVEN = "CANCEL_DRIVEN"     # Mostly cancel-driven (>70%)
    MIXED = "MIXED"                     # Mixed attribution (30-70% each)
    REPLENISHMENT = "REPLENISHMENT"     # Depth increased (trade > book change)
    NO_CHANGE = "NO_CHANGE"             # No significant change


@dataclass
class DepthChangeAttribution:
    """
    Unified attribution for a depth change event.

    Captures how much of a depth change was caused by:
    - Trading activity (aggressive orders)
    - Maker cancellations (order withdrawals)
    - Replenishment (new orders added)
    """
    # Observed values
    depth_before: float
    depth_after: float
    trade_volume: float

    # Computed attribution
    depth_change: float = 0.0           # depth_after - depth_before (negative = removed)
    depth_removed: float = 0.0          # max(0, depth_before - depth_after)

    trade_driven_volume: float = 0.0    # Volume removed by trades
    cancel_driven_volume: float = 0.0   # Volume removed by cancellations
    replenishment_volume: float = 0.0   # Volume added during period

    trade_driven_ratio: float = 0.0     # trade_driven / depth_removed (0-1)
    cancel_driven_ratio: float = 0.0    # cancel_driven / depth_removed (0-1)
    replenishment_ratio: float = 0.0    # replenishment / trade_volume (0+)

    # Primary classification
    attribution_type: AttributionType = AttributionType.NO_CHANGE

    # Metadata
    computed_at: int = 0                # Timestamp ms
    price_level: Optional[Decimal] = None
    token_id: Optional[str] = None

    def __post_init__(self):
        if self.computed_at == 0:
            self.computed_at = int(time.time() * 1000)

    def to_dict(self) -> dict:
        return {
            "depth_before": round(self.depth_before, 2),
            "depth_after": round(self.depth_after, 2),
            "trade_volume": round(self.trade_volume, 2),
            "depth_change": round(self.depth_change, 2),
            "depth_removed": round(self.depth_removed, 2),
            "trade_driven_volume": round(self.trade_driven_volume, 2),
            "cancel_driven_volume": round(self.cancel_driven_volume, 2),
            "replenishment_volume": round(self.replenishment_volume, 2),
            "trade_driven_ratio": round(self.trade_driven_ratio, 4),
            "cancel_driven_ratio": round(self.cancel_driven_ratio, 4),
            "replenishment_ratio": round(self.replenishment_ratio, 4),
            "attribution_type": self.attribution_type.value,
            "computed_at": self.computed_at,
            "price_level": str(self.price_level) if self.price_level else None,
            "token_id": self.token_id,
        }


@dataclass
class MultiLevelAttribution:
    """
    Attribution aggregated across multiple price levels.

    Used for events that span multiple price levels (e.g., SWEEP, DEPTH_COLLAPSE)
    """
    levels: List[DepthChangeAttribution] = field(default_factory=list)

    # Aggregated metrics
    total_depth_before: float = 0.0
    total_depth_after: float = 0.0
    total_trade_volume: float = 0.0
    total_depth_removed: float = 0.0

    total_trade_driven: float = 0.0
    total_cancel_driven: float = 0.0
    total_replenishment: float = 0.0

    # Weighted ratios
    trade_driven_ratio: float = 0.0
    cancel_driven_ratio: float = 0.0

    # Overall classification
    attribution_type: AttributionType = AttributionType.NO_CHANGE

    levels_affected: int = 0
    computed_at: int = 0

    def to_dict(self) -> dict:
        return {
            "levels_affected": self.levels_affected,
            "total_depth_before": round(self.total_depth_before, 2),
            "total_depth_after": round(self.total_depth_after, 2),
            "total_trade_volume": round(self.total_trade_volume, 2),
            "total_depth_removed": round(self.total_depth_removed, 2),
            "total_trade_driven": round(self.total_trade_driven, 2),
            "total_cancel_driven": round(self.total_cancel_driven, 2),
            "trade_driven_ratio": round(self.trade_driven_ratio, 4),
            "cancel_driven_ratio": round(self.cancel_driven_ratio, 4),
            "attribution_type": self.attribution_type.value,
            "computed_at": self.computed_at,
            "levels": [l.to_dict() for l in self.levels],
        }


# Thresholds for attribution classification
TRADE_DOMINANT_THRESHOLD = 0.70     # >70% trade-driven = TRADE_DRIVEN
CANCEL_DOMINANT_THRESHOLD = 0.70    # >70% cancel-driven = CANCEL_DRIVEN
SMALL_CHANGE_THRESHOLD = 0.05       # <5% depth change = NO_CHANGE


def compute_attribution(
    depth_before: float,
    depth_after: float,
    trade_volume: float,
    price_level: Decimal = None,
    token_id: str = None,
) -> DepthChangeAttribution:
    """
    Compute attribution for a single price level depth change.

    Args:
        depth_before: Depth at start of observation window
        depth_after: Depth at end of observation window
        trade_volume: Trade volume at this price level during window
        price_level: Optional price level
        token_id: Optional token ID

    Returns:
        DepthChangeAttribution with computed ratios
    """
    result = DepthChangeAttribution(
        depth_before=depth_before,
        depth_after=depth_after,
        trade_volume=trade_volume,
        price_level=price_level,
        token_id=token_id,
    )

    # Calculate depth change
    result.depth_change = depth_after - depth_before
    result.depth_removed = max(0.0, depth_before - depth_after)

    # Handle edge cases
    if depth_before <= 0:
        # No depth to begin with
        if trade_volume > 0:
            result.attribution_type = AttributionType.TRADE_DRIVEN
        else:
            result.attribution_type = AttributionType.NO_CHANGE
        return result

    # Check for no significant change
    change_ratio = abs(result.depth_change) / depth_before
    if change_ratio < SMALL_CHANGE_THRESHOLD:
        result.attribution_type = AttributionType.NO_CHANGE
        return result

    # Case 1: Depth increased (replenishment scenario)
    if result.depth_change > 0:
        result.replenishment_volume = result.depth_change
        result.replenishment_ratio = result.replenishment_volume / max(1.0, trade_volume) if trade_volume > 0 else 0
        result.attribution_type = AttributionType.REPLENISHMENT
        return result

    # Case 2: Depth decreased
    if result.depth_removed > 0:
        # Trade-driven: min of trade_volume and depth_removed
        result.trade_driven_volume = min(trade_volume, result.depth_removed)

        # Cancel-driven: remaining depth removal not explained by trades
        result.cancel_driven_volume = result.depth_removed - result.trade_driven_volume

        # Ratios
        result.trade_driven_ratio = result.trade_driven_volume / result.depth_removed
        result.cancel_driven_ratio = result.cancel_driven_volume / result.depth_removed

        # If trade > book change, there was replenishment during trading
        if trade_volume > result.depth_removed:
            result.replenishment_volume = trade_volume - result.depth_removed
            result.replenishment_ratio = result.replenishment_volume / result.depth_removed

        # Classify
        if result.trade_driven_ratio >= TRADE_DOMINANT_THRESHOLD:
            result.attribution_type = AttributionType.TRADE_DRIVEN
        elif result.cancel_driven_ratio >= CANCEL_DOMINANT_THRESHOLD:
            result.attribution_type = AttributionType.CANCEL_DRIVEN
        else:
            result.attribution_type = AttributionType.MIXED

    return result


def compute_multi_level_attribution(
    levels: List[Tuple[Decimal, float, float, float]],
    token_id: str = None,
) -> MultiLevelAttribution:
    """
    Compute attribution aggregated across multiple price levels.

    Args:
        levels: List of (price, depth_before, depth_after, trade_volume) tuples
        token_id: Optional token ID

    Returns:
        MultiLevelAttribution with aggregated metrics
    """
    result = MultiLevelAttribution(computed_at=int(time.time() * 1000))

    for price, depth_before, depth_after, trade_volume in levels:
        level_attr = compute_attribution(
            depth_before=depth_before,
            depth_after=depth_after,
            trade_volume=trade_volume,
            price_level=price,
            token_id=token_id,
        )
        result.levels.append(level_attr)

        # Aggregate
        result.total_depth_before += depth_before
        result.total_depth_after += depth_after
        result.total_trade_volume += trade_volume
        result.total_depth_removed += level_attr.depth_removed
        result.total_trade_driven += level_attr.trade_driven_volume
        result.total_cancel_driven += level_attr.cancel_driven_volume
        result.total_replenishment += level_attr.replenishment_volume

    result.levels_affected = len(levels)

    # Calculate overall ratios
    if result.total_depth_removed > 0:
        result.trade_driven_ratio = result.total_trade_driven / result.total_depth_removed
        result.cancel_driven_ratio = result.total_cancel_driven / result.total_depth_removed

        # Classify overall
        if result.trade_driven_ratio >= TRADE_DOMINANT_THRESHOLD:
            result.attribution_type = AttributionType.TRADE_DRIVEN
        elif result.cancel_driven_ratio >= CANCEL_DOMINANT_THRESHOLD:
            result.attribution_type = AttributionType.CANCEL_DRIVEN
        else:
            result.attribution_type = AttributionType.MIXED
    elif result.total_replenishment > 0:
        result.attribution_type = AttributionType.REPLENISHMENT
    else:
        result.attribution_type = AttributionType.NO_CHANGE

    return result


def is_trade_driven(attribution: DepthChangeAttribution) -> bool:
    """Check if depth change is primarily trade-driven"""
    return attribution.attribution_type == AttributionType.TRADE_DRIVEN


def is_cancel_driven(attribution: DepthChangeAttribution) -> bool:
    """Check if depth change is primarily cancel-driven"""
    return attribution.attribution_type == AttributionType.CANCEL_DRIVEN


def is_replenishment(attribution: DepthChangeAttribution) -> bool:
    """Check if there was net replenishment (HOLD signal)"""
    return attribution.attribution_type == AttributionType.REPLENISHMENT


def classify_for_reaction(attribution: DepthChangeAttribution) -> str:
    """
    Map attribution to reaction type hints.

    Returns hint string that can inform reaction classification.
    """
    if attribution.attribution_type == AttributionType.TRADE_DRIVEN:
        # Trade-driven removal = potential SWEEP or VACUUM
        if attribution.depth_after < attribution.depth_before * 0.05:
            return "VACUUM_CANDIDATE"
        return "SWEEP_CANDIDATE"

    elif attribution.attribution_type == AttributionType.CANCEL_DRIVEN:
        # Cancel-driven removal = PULL
        return "PULL_CANDIDATE"

    elif attribution.attribution_type == AttributionType.REPLENISHMENT:
        # Replenishment during trading = HOLD
        return "HOLD_CANDIDATE"

    elif attribution.attribution_type == AttributionType.MIXED:
        return "MIXED"

    return "NO_SIGNAL"


def reconcile_volume(
    book_change: float,
    trade_volume: float,
) -> Dict[str, float]:
    """
    Reconcile trade volume against book depth change.

    Detects:
    - Hidden replenishment (trade > book change)
    - Pure cancellation (book change > trade)
    - Perfect match (equal)

    Args:
        book_change: depth_before - depth_after (positive = removed)
        trade_volume: Trade volume observed

    Returns:
        Dict with reconciliation metrics
    """
    if book_change <= 0 and trade_volume <= 0:
        return {
            "status": "NO_ACTIVITY",
            "discrepancy": 0.0,
            "cancelled": 0.0,
            "replenished": 0.0,
        }

    if book_change >= 0 and trade_volume >= book_change:
        # Trade >= book change => replenishment happened
        replenished = trade_volume - book_change
        return {
            "status": "REPLENISHMENT" if replenished > 0 else "MATCHED",
            "discrepancy": replenished,
            "cancelled": 0.0,
            "replenished": replenished,
        }
    elif book_change > 0 and trade_volume < book_change:
        # Book change > trade => cancellation happened
        cancelled = book_change - trade_volume
        return {
            "status": "CANCELLATION",
            "discrepancy": cancelled,
            "cancelled": cancelled,
            "replenished": 0.0,
        }
    else:
        return {
            "status": "COMPLEX",
            "discrepancy": abs(book_change - trade_volume),
            "cancelled": max(0, book_change - trade_volume),
            "replenished": max(0, trade_volume - book_change),
        }


class AttributionTracker:
    """
    Tracks attribution metrics over time for analysis.

    Provides:
    - Rolling statistics on trade vs cancel attribution
    - Per-token attribution profiles
    - Anomaly detection (unusual attribution patterns)
    """

    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self._attributions: List[DepthChangeAttribution] = []
        self._token_stats: Dict[str, Dict[str, float]] = {}

    def record(self, attribution: DepthChangeAttribution):
        """Record an attribution event"""
        self._attributions.append(attribution)
        if len(self._attributions) > self.window_size:
            self._attributions = self._attributions[-self.window_size:]

        # Update token stats
        if attribution.token_id:
            if attribution.token_id not in self._token_stats:
                self._token_stats[attribution.token_id] = {
                    "count": 0,
                    "trade_driven_sum": 0.0,
                    "cancel_driven_sum": 0.0,
                }
            stats = self._token_stats[attribution.token_id]
            stats["count"] += 1
            stats["trade_driven_sum"] += attribution.trade_driven_ratio
            stats["cancel_driven_sum"] += attribution.cancel_driven_ratio

    def get_rolling_stats(self) -> Dict[str, float]:
        """Get rolling window statistics"""
        if not self._attributions:
            return {
                "count": 0,
                "avg_trade_driven": 0.0,
                "avg_cancel_driven": 0.0,
            }

        count = len(self._attributions)
        avg_trade = sum(a.trade_driven_ratio for a in self._attributions) / count
        avg_cancel = sum(a.cancel_driven_ratio for a in self._attributions) / count

        return {
            "count": count,
            "avg_trade_driven": round(avg_trade, 4),
            "avg_cancel_driven": round(avg_cancel, 4),
            "by_type": {
                "TRADE_DRIVEN": sum(1 for a in self._attributions if a.attribution_type == AttributionType.TRADE_DRIVEN),
                "CANCEL_DRIVEN": sum(1 for a in self._attributions if a.attribution_type == AttributionType.CANCEL_DRIVEN),
                "MIXED": sum(1 for a in self._attributions if a.attribution_type == AttributionType.MIXED),
                "REPLENISHMENT": sum(1 for a in self._attributions if a.attribution_type == AttributionType.REPLENISHMENT),
            }
        }

    def get_token_profile(self, token_id: str) -> Dict[str, float]:
        """Get attribution profile for a token"""
        stats = self._token_stats.get(token_id)
        if not stats or stats["count"] == 0:
            return {"count": 0, "avg_trade_driven": 0.0, "avg_cancel_driven": 0.0}

        return {
            "count": stats["count"],
            "avg_trade_driven": round(stats["trade_driven_sum"] / stats["count"], 4),
            "avg_cancel_driven": round(stats["cancel_driven_sum"] / stats["count"], 4),
        }
