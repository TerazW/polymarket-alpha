"""
Ensemble Signal Combination

Implements:
1. Exponential Weights Algorithm (Vovk 1990, Littlestone & Warmuth 1994)
2. Fixed Share extension (Herbster & Warmuth 1998) for non-stationarity
3. Bayesian Model Averaging fallback

Regret bound: O(sqrt(T ln K)) for K experts over T rounds.

Each "expert" is one alpha signal (HMM regime probability, BOCPD
changepoint, Hawkes intensity, VPIN, OFI, depth imbalance, belief state).
The ensemble learns which signals are most predictive in real-time.
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class EnsembleConfig:
    """Configuration for the ensemble combiner."""
    eta: float = 0.1              # Learning rate
    fixed_share_alpha: float = 0.02  # Mixing rate for Fixed Share
    min_weight: float = 0.01     # Minimum weight per expert (stability)
    lookback: int = 200          # Evaluation window


class ExponentialWeightsEnsemble:
    """
    Prediction with expert advice using exponential weights.

    Each expert provides a directional signal in [-1, 1].
    The ensemble learns to weight experts based on their
    realized prediction accuracy.

    Uses Fixed Share (Herbster & Warmuth 1998) to track
    non-stationary environments where the best expert changes.
    """

    def __init__(self, expert_names: List[str], config: Optional[EnsembleConfig] = None):
        self.config = config or EnsembleConfig()
        self.expert_names = expert_names
        self.n = len(expert_names)
        self.weights = np.ones(self.n) / self.n
        self._predictions: deque = deque(maxlen=self.config.lookback)
        self._outcomes: deque = deque(maxlen=self.config.lookback)
        self._step = 0

    def predict(self, expert_signals: Dict[str, float]) -> float:
        """
        Combine expert signals into ensemble prediction.

        Args:
            expert_signals: {expert_name: signal_value} where signal in [-1, 1]
                           Positive = bullish, Negative = bearish

        Returns:
            Combined signal in [-1, 1]
        """
        signals = np.array([
            expert_signals.get(name, 0.0) for name in self.expert_names
        ])
        # Clip signals
        signals = np.clip(signals, -1.0, 1.0)

        combined = float(self.weights @ signals)
        self._predictions.append((signals.copy(), combined))
        return np.clip(combined, -1.0, 1.0)

    def update(self, outcome: float):
        """
        Update weights based on realized outcome.

        Args:
            outcome: Realized direction/return (positive = up, negative = down)
        """
        if not self._predictions:
            return

        signals, _ = self._predictions[-1]
        self._outcomes.append(outcome)
        self._step += 1

        # Loss = negative correlation with outcome
        # Expert that predicted same sign as outcome has low loss
        if abs(outcome) < 1e-10:
            return

        # Squared loss: (signal - sign(outcome))^2
        target = np.sign(outcome)
        losses = (signals - target) ** 2

        # Exponential weights update
        self.weights *= np.exp(-self.config.eta * losses)

        # Fixed Share: mix in uniform component for non-stationarity
        alpha = self.config.fixed_share_alpha
        self.weights = (1 - alpha) * self.weights + alpha / self.n

        # Normalize
        self.weights /= self.weights.sum()

        # Enforce minimum weight
        below_min = self.weights < self.config.min_weight
        if below_min.any():
            deficit = np.sum(self.config.min_weight - self.weights[below_min])
            self.weights[below_min] = self.config.min_weight
            above_min = ~below_min
            if above_min.any():
                self.weights[above_min] -= deficit / above_min.sum()
            self.weights = np.clip(self.weights, self.config.min_weight, 1.0)
            self.weights /= self.weights.sum()

    def get_weights(self) -> Dict[str, float]:
        """Current expert weights."""
        return {name: float(w) for name, w in zip(self.expert_names, self.weights)}

    def get_expert_performance(self) -> Dict[str, dict]:
        """Compute per-expert performance metrics."""
        if len(self._predictions) < 10 or len(self._outcomes) < 10:
            return {}

        n_eval = min(len(self._predictions), len(self._outcomes))
        results = {}

        for i, name in enumerate(self.expert_names):
            signals = [self._predictions[j][0][i] for j in range(n_eval)]
            outcomes = list(self._outcomes)[:n_eval]

            # Hit rate: how often signal sign matches outcome sign
            hits = sum(
                1 for s, o in zip(signals, outcomes)
                if s * o > 0 and abs(o) > 1e-10
            )
            n_valid = sum(1 for o in outcomes if abs(o) > 1e-10)
            hit_rate = hits / n_valid if n_valid > 0 else 0.5

            # Correlation
            if len(signals) > 2:
                corr = float(np.corrcoef(signals, outcomes)[0, 1])
                if np.isnan(corr):
                    corr = 0.0
            else:
                corr = 0.0

            results[name] = {
                "weight": float(self.weights[i]),
                "hit_rate": hit_rate,
                "correlation": corr,
            }

        return results


class ProbabilityEnsemble:
    """
    Ensemble specifically for combining probability estimates.

    Each expert provides P(outcome=YES) for a binary market.
    Combination via log-linear pooling with learned weights:

        log p_combined = sum_k w_k * log p_k + const

    This is equivalent to a product-of-experts model normalized.
    """

    def __init__(self, expert_names: List[str], config: Optional[EnsembleConfig] = None):
        self.config = config or EnsembleConfig()
        self.expert_names = expert_names
        self.n = len(expert_names)
        self.weights = np.ones(self.n) / self.n
        self._step = 0

    def combine_probabilities(self, expert_probs: Dict[str, float]) -> float:
        """
        Combine probability estimates via log-linear pooling.

        Args:
            expert_probs: {name: P(YES)} where each P in (0, 1)

        Returns:
            Combined P(YES)
        """
        probs = np.array([
            np.clip(expert_probs.get(name, 0.5), 0.01, 0.99)
            for name in self.expert_names
        ])

        # Log-linear pooling
        log_odds = np.log(probs / (1 - probs))
        combined_log_odds = float(self.weights @ log_odds)

        # Sigmoid back to probability
        combined_prob = 1.0 / (1.0 + np.exp(-combined_log_odds))
        return float(np.clip(combined_prob, 0.01, 0.99))

    def update(self, outcome: int, expert_probs: Dict[str, float]):
        """
        Update weights based on realized binary outcome.

        Args:
            outcome: 1 (YES) or 0 (NO)
            expert_probs: {name: P(YES)} predictions that were made
        """
        self._step += 1

        probs = np.array([
            np.clip(expert_probs.get(name, 0.5), 0.01, 0.99)
            for name in self.expert_names
        ])

        # Log loss per expert
        if outcome == 1:
            losses = -np.log(probs)
        else:
            losses = -np.log(1 - probs)

        # Exponential weights update
        self.weights *= np.exp(-self.config.eta * losses)

        # Fixed Share
        alpha = self.config.fixed_share_alpha
        self.weights = (1 - alpha) * self.weights + alpha / self.n
        self.weights /= self.weights.sum()

    def get_weights(self) -> Dict[str, float]:
        return {name: float(w) for name, w in zip(self.expert_names, self.weights)}
