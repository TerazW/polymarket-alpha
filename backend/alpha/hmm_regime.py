"""
Hidden Markov Model Regime Detection

Implements Gaussian HMM with Baum-Welch (EM) for parameter learning
and online Viterbi for real-time regime inference.

References:
- Rabiner (1989) "A Tutorial on HMMs and Selected Applications"
- Hamilton (1989) "A New Approach to the Economic Analysis of Nonstationary
  Time Series and the Business Cycle"

Regimes:
  0 = CALM      (low vol, mean-reverting)
  1 = TRENDING  (directional momentum)
  2 = VOLATILE  (high vol, uncertainty)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from collections import deque
import logging

logger = logging.getLogger(__name__)

# Default 3-state regime model
N_REGIMES = 3
REGIME_NAMES = {0: "CALM", 1: "TRENDING", 2: "VOLATILE"}


@dataclass
class HMMParams:
    """HMM parameters lambda = (A, mu, sigma, pi)."""
    n_states: int = N_REGIMES
    # Transition matrix A[i,j] = P(state_j | state_i)
    A: np.ndarray = field(default=None)
    # Emission means per state
    mu: np.ndarray = field(default=None)
    # Emission std devs per state
    sigma: np.ndarray = field(default=None)
    # Initial state distribution
    pi: np.ndarray = field(default=None)

    def __post_init__(self):
        n = self.n_states
        if self.A is None:
            # High self-transition probability (sticky regimes)
            self.A = np.full((n, n), 0.02 / (n - 1))
            np.fill_diagonal(self.A, 0.98)
        if self.mu is None:
            # CALM: ~0 return, TRENDING: slight positive, VOLATILE: ~0
            self.mu = np.array([0.0, 0.002, 0.0])
        if self.sigma is None:
            # CALM: low vol, TRENDING: medium, VOLATILE: high
            self.sigma = np.array([0.005, 0.015, 0.04])
        if self.pi is None:
            self.pi = np.array([0.6, 0.2, 0.2])


def _log_gaussian_pdf(x: float, mu: float, sigma: float) -> float:
    """Log of Gaussian PDF, numerically stable."""
    if sigma < 1e-10:
        sigma = 1e-10
    return -0.5 * np.log(2 * np.pi) - np.log(sigma) - 0.5 * ((x - mu) / sigma) ** 2


class HMMRegimeDetector:
    """
    Online HMM regime detection.

    Uses forward algorithm for filtering P(state_t | obs_1:t)
    and periodic Baum-Welch re-estimation on rolling windows.
    """

    def __init__(
        self,
        params: Optional[HMMParams] = None,
        window_size: int = 500,
        refit_every: int = 100,
        min_samples_for_fit: int = 50,
    ):
        self.params = params or HMMParams()
        self.window_size = window_size
        self.refit_every = refit_every
        self.min_samples_for_fit = min_samples_for_fit

        self.n = self.params.n_states
        # Current filtered state probabilities (forward variable, normalized)
        self._alpha = self.params.pi.copy()
        # Observation buffer for Baum-Welch re-estimation
        self._obs_buffer: deque = deque(maxlen=window_size)
        self._step_count = 0

    def update(self, observation: float) -> np.ndarray:
        """
        Process one observation (e.g., log-return).

        Returns:
            state_probs: array of shape (n_states,), filtered regime probabilities
        """
        self._obs_buffer.append(observation)
        self._step_count += 1

        # Forward step: alpha_t(j) = [sum_i alpha_{t-1}(i) * A[i,j]] * b_j(obs)
        log_b = np.array([
            _log_gaussian_pdf(observation, self.params.mu[j], self.params.sigma[j])
            for j in range(self.n)
        ])

        # Prediction step
        predicted = self._alpha @ self.params.A

        # Update step (in log space for stability)
        log_alpha = np.log(predicted + 1e-300) + log_b
        log_alpha -= np.max(log_alpha)  # log-sum-exp normalization
        self._alpha = np.exp(log_alpha)
        self._alpha /= self._alpha.sum()

        # Periodic re-estimation
        if (self._step_count % self.refit_every == 0
                and len(self._obs_buffer) >= self.min_samples_for_fit):
            self._refit()

        return self._alpha.copy()

    def get_regime(self) -> Tuple[int, float, str]:
        """
        Returns:
            (regime_id, probability, regime_name)
        """
        regime = int(np.argmax(self._alpha))
        prob = float(self._alpha[regime])
        return regime, prob, REGIME_NAMES.get(regime, f"STATE_{regime}")

    def get_regime_probs(self) -> dict:
        """Return all regime probabilities as a dict."""
        return {REGIME_NAMES[i]: float(self._alpha[i]) for i in range(self.n)}

    def _refit(self):
        """
        Baum-Welch re-estimation on the observation buffer.

        Full EM with scaled forward-backward (Rabiner 1989).
        """
        obs = np.array(self._obs_buffer)
        T = len(obs)
        n = self.n

        A = self.params.A.copy()
        mu = self.params.mu.copy()
        sigma = self.params.sigma.copy()
        pi = self.params.pi.copy()

        max_iter = 20
        tol = 1e-4
        prev_ll = -np.inf

        for iteration in range(max_iter):
            # --- Forward pass with scaling ---
            alpha = np.zeros((T, n))
            c = np.zeros(T)

            # t=0
            for j in range(n):
                alpha[0, j] = pi[j] * np.exp(_log_gaussian_pdf(obs[0], mu[j], sigma[j]))
            c[0] = 1.0 / (alpha[0].sum() + 1e-300)
            alpha[0] *= c[0]

            # t=1..T-1
            for t in range(1, T):
                for j in range(n):
                    alpha[t, j] = sum(alpha[t-1, i] * A[i, j] for i in range(n))
                    alpha[t, j] *= np.exp(_log_gaussian_pdf(obs[t], mu[j], sigma[j]))
                c[t] = 1.0 / (alpha[t].sum() + 1e-300)
                alpha[t] *= c[t]

            # Log-likelihood
            ll = -np.sum(np.log(c + 1e-300))
            if ll - prev_ll < tol:
                break
            prev_ll = ll

            # --- Backward pass ---
            beta = np.zeros((T, n))
            beta[T-1] = c[T-1]

            for t in range(T-2, -1, -1):
                for i in range(n):
                    beta[t, i] = sum(
                        A[i, j] * np.exp(_log_gaussian_pdf(obs[t+1], mu[j], sigma[j])) * beta[t+1, j]
                        for j in range(n)
                    )
                beta[t] *= c[t]

            # --- E-step: gamma and xi ---
            gamma = np.zeros((T, n))
            xi = np.zeros((T-1, n, n))

            for t in range(T):
                denom = (alpha[t] * beta[t]).sum() + 1e-300
                gamma[t] = (alpha[t] * beta[t]) / denom

            for t in range(T-1):
                denom = 0.0
                for i in range(n):
                    for j in range(n):
                        xi[t, i, j] = (
                            alpha[t, i] * A[i, j]
                            * np.exp(_log_gaussian_pdf(obs[t+1], mu[j], sigma[j]))
                            * beta[t+1, j]
                        )
                        denom += xi[t, i, j]
                xi[t] /= (denom + 1e-300)

            # --- M-step ---
            pi = gamma[0]

            for i in range(n):
                gamma_sum = gamma[:T-1, i].sum() + 1e-300
                for j in range(n):
                    A[i, j] = xi[:, i, j].sum() / gamma_sum

                gamma_full_sum = gamma[:, i].sum() + 1e-300
                mu[i] = (gamma[:, i] * obs).sum() / gamma_full_sum
                sigma[i] = np.sqrt(
                    (gamma[:, i] * (obs - mu[i]) ** 2).sum() / gamma_full_sum
                )
                sigma[i] = max(sigma[i], 1e-6)

        # Sort states by volatility (CALM=lowest, VOLATILE=highest)
        order = np.argsort(sigma)
        self.params.A = A[np.ix_(order, order)]
        self.params.mu = mu[order]
        self.params.sigma = sigma[order]
        self.params.pi = pi[order]

        # Re-initialize filter with new parameters
        self._alpha = gamma[-1][order]
        self._alpha /= self._alpha.sum()

        logger.debug(
            f"HMM refit: mu={self.params.mu}, sigma={self.params.sigma}, "
            f"ll={prev_ll:.2f}"
        )
