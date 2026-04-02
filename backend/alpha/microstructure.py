"""
Market Microstructure Alpha Signals

Implements:
1. Order Flow Imbalance (OFI) - Cont, Kukanov & Stoikov (2014)
2. Book Pressure Asymmetry (Depth Imbalance)
3. Kyle's Lambda (price impact per unit order flow) - Kyle (1985)
4. Roll Spread Estimator - Roll (1984)
5. Amihud Illiquidity - Amihud (2002)

These feed into the ensemble signal combiner.
"""

import numpy as np
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class BookSnapshot:
    """Order book snapshot at a point in time."""
    timestamp: float      # seconds
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    # Multi-level depth (optional)
    bid_levels: Optional[List[Tuple[float, float]]] = None  # [(price, size), ...]
    ask_levels: Optional[List[Tuple[float, float]]] = None


class OrderFlowImbalance:
    """
    OFI: Cont, Kukanov & Stoikov (2014)
    "The Price Impact of Order Book Events"
    Journal of Financial Economics, 104(1), 56-72.

    OFI measures the net order flow pressure from book changes.
    Predictive power: R^2 ~40-65% at short horizons.
    """

    def __init__(self, window: int = 100):
        self._prev_snap: Optional[BookSnapshot] = None
        self._ofi_buffer: deque = deque(maxlen=window)
        self._cumulative_ofi = 0.0

    def update(self, snap: BookSnapshot) -> float:
        """
        Compute OFI from consecutive book snapshots.

        Returns:
            ofi: Order flow imbalance value for this update
        """
        if self._prev_snap is None:
            self._prev_snap = snap
            return 0.0

        prev = self._prev_snap

        # Bid contribution
        if snap.bid_price > prev.bid_price:
            bid_contrib = snap.bid_size
        elif snap.bid_price == prev.bid_price:
            bid_contrib = snap.bid_size - prev.bid_size
        else:
            bid_contrib = -prev.bid_size

        # Ask contribution
        if snap.ask_price < prev.ask_price:
            ask_contrib = -snap.ask_size
        elif snap.ask_price == prev.ask_price:
            ask_contrib = -(snap.ask_size - prev.ask_size)
        else:
            ask_contrib = prev.ask_size

        ofi = bid_contrib + ask_contrib
        self._ofi_buffer.append(ofi)
        self._cumulative_ofi += ofi
        self._prev_snap = snap
        return ofi

    @property
    def cumulative(self) -> float:
        return self._cumulative_ofi

    @property
    def rolling_mean(self) -> float:
        if not self._ofi_buffer:
            return 0.0
        return float(np.mean(self._ofi_buffer))

    @property
    def rolling_std(self) -> float:
        if len(self._ofi_buffer) < 2:
            return 0.0
        return float(np.std(self._ofi_buffer))

    def get_zscore(self) -> float:
        """Standardized OFI (z-score of recent OFI)."""
        std = self.rolling_std
        if std < 1e-10:
            return 0.0
        return self.rolling_mean / std


class DepthImbalance:
    """
    Book Pressure Asymmetry: DI = (Q_bid - Q_ask) / (Q_bid + Q_ask)

    With exponential depth weighting (closer levels weighted more).
    """

    def __init__(self, decay: float = 0.5, window: int = 50):
        self.decay = decay
        self._di_buffer: deque = deque(maxlen=window)

    def compute(self, snap: BookSnapshot) -> float:
        """
        Compute depth imbalance from book snapshot.

        Returns:
            di: in [-1, 1], positive = bid-heavy (bullish)
        """
        if snap.bid_levels and snap.ask_levels:
            # Weighted multi-level
            bid_weighted = sum(
                size * np.exp(-self.decay * i)
                for i, (_, size) in enumerate(snap.bid_levels)
            )
            ask_weighted = sum(
                size * np.exp(-self.decay * i)
                for i, (_, size) in enumerate(snap.ask_levels)
            )
        else:
            bid_weighted = snap.bid_size
            ask_weighted = snap.ask_size

        total = bid_weighted + ask_weighted
        if total < 1e-10:
            di = 0.0
        else:
            di = (bid_weighted - ask_weighted) / total

        self._di_buffer.append(di)
        return di

    @property
    def rolling_mean(self) -> float:
        if not self._di_buffer:
            return 0.0
        return float(np.mean(self._di_buffer))


class KyleLambda:
    """
    Kyle's Lambda: price impact per unit of order flow.
    Kyle (1985) "Continuous Auctions and Insider Trading"

    lambda = Cov(dP, OFI) / Var(OFI)

    Higher lambda = more adverse selection, higher information asymmetry.
    """

    def __init__(self, window: int = 100):
        self._dp_buffer: deque = deque(maxlen=window)
        self._ofi_buffer: deque = deque(maxlen=window)
        self._lambda: float = 0.0

    def update(self, price_change: float, order_flow: float):
        """Add observation pair (price change, order flow imbalance)."""
        self._dp_buffer.append(price_change)
        self._ofi_buffer.append(order_flow)

        if len(self._dp_buffer) < 10:
            return

        dp = np.array(self._dp_buffer)
        ofi = np.array(self._ofi_buffer)

        var_ofi = np.var(ofi)
        if var_ofi < 1e-10:
            return

        cov = np.cov(dp, ofi)[0, 1]
        self._lambda = cov / var_ofi

    @property
    def value(self) -> float:
        return self._lambda

    def get_adverse_selection_level(self) -> str:
        """Interpret Kyle's lambda."""
        if abs(self._lambda) < 0.0001:
            return "LOW"
        elif abs(self._lambda) < 0.001:
            return "MODERATE"
        else:
            return "HIGH"


class SpreadEstimator:
    """
    Roll (1984) implied spread estimator.
    s_hat = 2 * sqrt(-Cov(dp_t, dp_{t-1}))

    Also computes Amihud (2002) illiquidity ratio.
    """

    def __init__(self, window: int = 100):
        self._dp_buffer: deque = deque(maxlen=window)
        self._return_buffer: deque = deque(maxlen=window)
        self._volume_buffer: deque = deque(maxlen=window)

    def update(self, price_change: float, ret: float = 0.0, volume: float = 0.0):
        """Add observation."""
        self._dp_buffer.append(price_change)
        self._return_buffer.append(ret)
        self._volume_buffer.append(volume)

    def roll_spread(self) -> float:
        """Roll (1984) implied spread."""
        if len(self._dp_buffer) < 3:
            return 0.0
        dp = np.array(self._dp_buffer)
        cov = np.cov(dp[1:], dp[:-1])[0, 1]
        if cov >= 0:
            return 0.0  # No spread signal (momentum)
        return 2.0 * np.sqrt(-cov)

    def amihud_illiq(self) -> float:
        """Amihud (2002) illiquidity ratio = mean(|r| / V)."""
        if len(self._return_buffer) < 2:
            return 0.0
        rets = np.array(self._return_buffer)
        vols = np.array(self._volume_buffer)
        valid = vols > 0
        if not np.any(valid):
            return 0.0
        return float(np.mean(np.abs(rets[valid]) / vols[valid]))


class MicrostructureSignals:
    """
    Aggregated microstructure signal container.

    Combines OFI, depth imbalance, Kyle's lambda, spread estimators
    into a single update interface.
    """

    def __init__(self, window: int = 100):
        self.ofi = OrderFlowImbalance(window=window)
        self.depth = DepthImbalance(window=window)
        self.kyle = KyleLambda(window=window)
        self.spread = SpreadEstimator(window=window)
        self._last_mid: Optional[float] = None

    def update_book(self, snap: BookSnapshot):
        """Update with new book snapshot."""
        ofi_val = self.ofi.update(snap)
        di_val = self.depth.compute(snap)

        mid = (snap.bid_price + snap.ask_price) / 2
        if self._last_mid is not None:
            dp = mid - self._last_mid
            self.kyle.update(dp, ofi_val)
            ret = dp / self._last_mid if self._last_mid > 0 else 0.0
            self.spread.update(dp, ret)
        self._last_mid = mid

    def update_trade(self, price: float, volume: float):
        """Update spread estimator with trade data."""
        if self._last_mid is not None:
            dp = price - self._last_mid
            ret = dp / self._last_mid if self._last_mid > 0 else 0.0
            self.spread.update(dp, ret, volume)

    def get_signals(self) -> dict:
        """Return all microstructure signals as a dict."""
        return {
            "ofi_zscore": self.ofi.get_zscore(),
            "ofi_cumulative": self.ofi.cumulative,
            "depth_imbalance": self.depth.rolling_mean,
            "kyle_lambda": self.kyle.value,
            "adverse_selection": self.kyle.get_adverse_selection_level(),
            "roll_spread": self.spread.roll_spread(),
            "amihud_illiq": self.spread.amihud_illiq(),
        }
