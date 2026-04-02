"""
Hawkes Process for Trade Event Clustering

Self-exciting point process where past events increase the probability
of future events. Models trade clustering, momentum, and mean-reversion.

References:
- Hawkes (1971) "Spectra of some self-exciting and mutually exciting point processes"
- Bacry, Mastromatteo & Muzy (2015) "Hawkes processes in finance"

Uses exponential kernel for O(1) recursive updates suitable for real-time.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class HawkesParams:
    """Parameters for univariate Hawkes process."""
    mu: float = 0.1       # Background intensity (events per second)
    alpha: float = 0.5    # Excitation magnitude
    beta: float = 1.0     # Decay rate (1/beta = memory half-life in seconds)

    @property
    def branching_ratio(self) -> float:
        """n = alpha/beta, must be < 1 for stationarity."""
        return self.alpha / self.beta if self.beta > 0 else float('inf')

    @property
    def half_life(self) -> float:
        """Memory half-life in seconds."""
        return np.log(2) / self.beta if self.beta > 0 else float('inf')

    @property
    def is_stationary(self) -> bool:
        return self.branching_ratio < 1.0


class HawkesIntensity:
    """
    Real-time Hawkes intensity tracker with O(1) updates.

    Uses the recursive relation:
        R(t_k) = exp(-beta * (t_k - t_{k-1})) * R(t_{k-1}) + 1
        lambda(t_k) = mu + alpha * beta * R(t_k)
    """

    def __init__(self, params: Optional[HawkesParams] = None):
        self.params = params or HawkesParams()
        self._R = 0.0  # Recursive kernel sum
        self._last_event_time: Optional[float] = None
        self._intensity = self.params.mu
        self._event_count = 0

    def on_event(self, timestamp: float) -> float:
        """
        Register a new event and return updated intensity.

        Args:
            timestamp: Event time in seconds (monotonically increasing)

        Returns:
            Current intensity value
        """
        if self._last_event_time is not None:
            dt = timestamp - self._last_event_time
            if dt < 0:
                dt = 0
            self._R = np.exp(-self.params.beta * dt) * self._R + 1
        else:
            self._R = 1.0

        self._last_event_time = timestamp
        self._event_count += 1
        self._intensity = self.params.mu + self.params.alpha * self.params.beta * self._R
        return self._intensity

    def get_intensity(self, timestamp: float) -> float:
        """Get intensity at arbitrary time (between events)."""
        if self._last_event_time is None:
            return self.params.mu

        dt = timestamp - self._last_event_time
        if dt < 0:
            dt = 0
        decayed_R = np.exp(-self.params.beta * dt) * self._R
        return self.params.mu + self.params.alpha * self.params.beta * decayed_R

    @property
    def current_intensity(self) -> float:
        return self._intensity


class BivarateHawkes:
    """
    2D Hawkes process for buy/sell trade flows.

    Models:
    - Self-excitation (buys trigger buys = momentum)
    - Cross-excitation (buys trigger sells = mean-reversion)

    Branching matrix G:
        [[alpha_bb/beta_bb, alpha_bs/beta_bs],
         [alpha_sb/beta_sb, alpha_ss/beta_ss]]
    """

    def __init__(
        self,
        mu: Tuple[float, float] = (0.1, 0.1),
        alpha: np.ndarray = None,
        beta: np.ndarray = None,
    ):
        self.mu = np.array(mu)
        self.alpha = alpha if alpha is not None else np.array([[0.3, 0.1], [0.1, 0.3]])
        self.beta = beta if beta is not None else np.array([[1.0, 1.0], [1.0, 1.0]])

        # Recursive kernel sums R[d, d'] for each (target, source) pair
        self._R = np.zeros((2, 2))
        self._last_event_time = np.array([0.0, 0.0])
        self._has_event = np.array([False, False])
        self._intensity = self.mu.copy()

    def on_event(self, event_type: int, timestamp: float) -> np.ndarray:
        """
        Register event of type 0 (buy) or 1 (sell).

        Returns:
            intensity: array [lambda_buy, lambda_sell]
        """
        # Decay all R values
        for d in range(2):
            for dp in range(2):
                if self._has_event[dp]:
                    dt = timestamp - self._last_event_time[dp]
                    if dt > 0:
                        self._R[d, dp] *= np.exp(-self.beta[d, dp] * dt)

        # Add contribution from new event
        for d in range(2):
            self._R[d, event_type] += 1.0

        self._last_event_time[event_type] = timestamp
        self._has_event[event_type] = True

        # Compute intensities
        for d in range(2):
            self._intensity[d] = self.mu[d]
            for dp in range(2):
                self._intensity[d] += self.alpha[d, dp] * self.beta[d, dp] * self._R[d, dp]

        return self._intensity.copy()

    def get_imbalance_ratio(self) -> float:
        """
        Intensity imbalance: (lambda_buy - lambda_sell) / (lambda_buy + lambda_sell)

        Positive = buy pressure dominates, Negative = sell pressure dominates.
        """
        total = self._intensity[0] + self._intensity[1]
        if total < 1e-10:
            return 0.0
        return float((self._intensity[0] - self._intensity[1]) / total)

    @property
    def branching_matrix(self) -> np.ndarray:
        """G[d,d'] = alpha[d,d'] / beta[d,d']"""
        return self.alpha / (self.beta + 1e-10)

    @property
    def endogeneity(self) -> float:
        """Spectral radius of branching matrix = fraction of endogenous events."""
        G = self.branching_matrix
        return float(np.max(np.abs(np.linalg.eigvals(G))))


class HawkesEstimator:
    """
    Online parameter estimation for Hawkes process via
    stochastic gradient ascent on log-likelihood.

    For streaming prediction market data where batch MLE is impractical.
    """

    def __init__(
        self,
        initial_params: Optional[HawkesParams] = None,
        learning_rate: float = 0.001,
        min_events: int = 20,
    ):
        self.params = initial_params or HawkesParams()
        self.lr = learning_rate
        self.min_events = min_events

        self._events: deque = deque(maxlen=2000)
        self._R = 0.0
        self._dR_dalpha: float = 0.0
        self._dR_dbeta: float = 0.0

    def add_event(self, timestamp: float):
        """Add event and update parameter estimates."""
        self._events.append(timestamp)

        if len(self._events) < 2:
            return

        t_prev = self._events[-2]
        t_curr = timestamp
        dt = t_curr - t_prev

        # Recursive updates for R and gradients
        decay = np.exp(-self.params.beta * dt)
        self._R = decay * self._R + 1
        self._dR_dalpha = decay * self._dR_dalpha
        self._dR_dbeta = decay * self._dR_dbeta - dt * decay * (self._R - 1)

        # Current intensity
        lam = self.params.mu + self.params.alpha * self.params.beta * self._R

        if lam < 1e-10:
            return

        if len(self._events) < self.min_events:
            return

        # Gradient of log-likelihood contribution
        # d/d_mu log(lambda) = 1/lambda
        # d/d_alpha log(lambda) = beta * R / lambda
        # Compensator gradients are approximate (ignore integral term for speed)
        inv_lam = 1.0 / lam

        grad_mu = inv_lam - dt
        grad_alpha = self.params.beta * self._R * inv_lam - self.params.beta * self._R * dt

        # SGD update with projection
        self.params.mu = max(1e-6, self.params.mu + self.lr * grad_mu)
        self.params.alpha = max(1e-6, self.params.alpha + self.lr * grad_alpha)

        # Ensure stationarity: alpha < beta
        if self.params.alpha >= self.params.beta * 0.95:
            self.params.alpha = self.params.beta * 0.95

    def get_params(self) -> HawkesParams:
        return HawkesParams(
            mu=self.params.mu,
            alpha=self.params.alpha,
            beta=self.params.beta,
        )
