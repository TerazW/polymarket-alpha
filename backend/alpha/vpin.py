"""
Volume-Synchronized Probability of Informed Trading (VPIN)

Easley, Lopez de Prado & O'Hara (2012)
"Flow Toxicity and Liquidity in a High-frequency World"
Review of Financial Studies, 25(5), 1457-1493.

VPIN measures order flow toxicity (probability that a counterparty is
informed). High VPIN = dangerous to provide liquidity.

Uses Bulk Volume Classification (BVC) to classify trade volume as
buy/sell initiated without tick rule.
"""

import numpy as np
from scipy.stats import norm
from dataclasses import dataclass
from typing import Optional, List
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class VPINConfig:
    """VPIN configuration."""
    bucket_volume: float = 1000.0    # Volume per bucket (in contract units)
    n_buckets: int = 50              # Number of buckets in VPIN window
    sigma_window: int = 100          # Lookback for sigma calibration


class VPINCalculator:
    """
    Real-time VPIN calculator.

    Accumulates volume into fixed-size buckets, classifies buy/sell
    via BVC, and computes rolling VPIN.
    """

    def __init__(self, config: Optional[VPINConfig] = None):
        self.config = config or VPINConfig()
        self.V = self.config.bucket_volume
        self.n = self.config.n_buckets

        # Current bucket accumulation
        self._bucket_buy = 0.0
        self._bucket_sell = 0.0
        self._bucket_vol = 0.0

        # Completed buckets: deque of (buy_vol, sell_vol)
        self._buckets: deque = deque(maxlen=self.n * 2)

        # Price change history for sigma calibration
        self._price_changes: deque = deque(maxlen=self.config.sigma_window)
        self._sigma: float = 0.01  # Initial guess
        self._last_price: Optional[float] = None

        self._vpin: Optional[float] = None

    def update(self, price: float, volume: float) -> Optional[float]:
        """
        Process a trade.

        Args:
            price: Trade price
            volume: Trade volume

        Returns:
            VPIN value if a new bucket completed, else None
        """
        # Track price changes for sigma calibration
        if self._last_price is not None:
            dp = price - self._last_price
            self._price_changes.append(dp)
            if len(self._price_changes) >= 10:
                self._sigma = max(float(np.std(self._price_changes)), 1e-8)
        self._last_price = price

        # BVC: classify volume
        dp = self._price_changes[-1] if self._price_changes else 0.0
        buy_vol, sell_vol = self._classify_volume(volume, dp)

        # Fill buckets
        remaining_vol = volume
        remaining_buy = buy_vol
        remaining_sell = sell_vol
        result = None

        while remaining_vol > 1e-10:
            space = self.V - self._bucket_vol
            fill = min(remaining_vol, space)
            frac = fill / remaining_vol if remaining_vol > 0 else 0

            self._bucket_buy += remaining_buy * frac
            self._bucket_sell += remaining_sell * frac
            self._bucket_vol += fill
            remaining_vol -= fill
            remaining_buy *= (1 - frac)
            remaining_sell *= (1 - frac)

            # Bucket complete?
            if self._bucket_vol >= self.V - 1e-9:
                self._buckets.append((self._bucket_buy, self._bucket_sell))
                self._bucket_buy = 0.0
                self._bucket_sell = 0.0
                self._bucket_vol = 0.0

                # Compute VPIN if we have enough buckets
                if len(self._buckets) >= self.n:
                    window = list(self._buckets)[-self.n:]
                    imbalance_sum = sum(abs(b - s) for b, s in window)
                    result = imbalance_sum / (self.n * self.V)
                    self._vpin = result

        return result

    def _classify_volume(self, volume: float, price_change: float) -> tuple:
        """
        Bulk Volume Classification (BVC).

        V_buy = V * Phi(dp / sigma)
        V_sell = V - V_buy
        """
        if self._sigma < 1e-10:
            if price_change > 0:
                return volume, 0.0
            elif price_change < 0:
                return 0.0, volume
            else:
                return volume / 2, volume / 2

        z = price_change / self._sigma
        buy_pct = float(norm.cdf(z))
        return volume * buy_pct, volume * (1 - buy_pct)

    @property
    def current_vpin(self) -> Optional[float]:
        """Current VPIN value, or None if not enough data."""
        return self._vpin

    def get_toxicity_level(self) -> str:
        """Interpret VPIN level."""
        if self._vpin is None:
            return "UNKNOWN"
        if self._vpin < 0.2:
            return "LOW"
        elif self._vpin < 0.4:
            return "MODERATE"
        elif self._vpin < 0.6:
            return "HIGH"
        else:
            return "EXTREME"

    def get_spread_multiplier(self) -> float:
        """
        Suggested spread multiplier based on VPIN.

        Low toxicity -> tight spreads (1.0x)
        High toxicity -> wide spreads (up to 3.0x)
        """
        if self._vpin is None:
            return 1.5  # Conservative default
        # Piecewise linear mapping
        if self._vpin < 0.2:
            return 1.0
        elif self._vpin < 0.5:
            return 1.0 + 2.0 * (self._vpin - 0.2) / 0.3
        else:
            return 3.0
