"""
Belief State Delta Calibrator

Empirical calibration of the belief_state → price_adjustment mapping.

Instead of hardcoded `severity * 0.05`, we learn the actual price move
distribution after each type of belief state transition from historical data.

This answers: "When the system says CRACKING, how much does price actually
move in the next N minutes?" — the most critical parameter in the system.

Uses the existing `belief_states` and `book_bins` tables to compute:
  For each transition (e.g., STABLE→CRACKING):
    - Median price move at t+1min, t+5min, t+15min, t+30min
    - Directional accuracy (% of time the side prediction was correct)
    - False positive rate (state triggered but price didn't move)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class TransitionStats:
    """Empirical statistics for a specific belief state transition."""
    transition: str           # e.g., "STABLE→CRACKING"
    n_observations: int = 0
    # Signed price moves (positive = same direction as prediction)
    moves_1m: List[float] = field(default_factory=list)
    moves_5m: List[float] = field(default_factory=list)
    moves_15m: List[float] = field(default_factory=list)

    @property
    def median_move_1m(self) -> float:
        return float(np.median(self.moves_1m)) if self.moves_1m else 0.0

    @property
    def median_move_5m(self) -> float:
        return float(np.median(self.moves_5m)) if self.moves_5m else 0.0

    @property
    def median_move_15m(self) -> float:
        return float(np.median(self.moves_15m)) if self.moves_15m else 0.0

    @property
    def directional_accuracy(self) -> float:
        """Fraction of times the direction prediction was correct (at 5m)."""
        if not self.moves_5m:
            return 0.5
        correct = sum(1 for m in self.moves_5m if m > 0)
        return correct / len(self.moves_5m)

    @property
    def false_positive_rate(self) -> float:
        """Fraction of times price didn't move more than 0.5% (at 5m)."""
        if not self.moves_5m:
            return 1.0
        no_move = sum(1 for m in self.moves_5m if abs(m) < 0.005)
        return no_move / len(self.moves_5m)


# Default priors (before any calibration data)
# These are conservative starting points
DEFAULT_DELTA_MAP = {
    "STABLE": 0.0,
    "FRAGILE": 0.01,
    "CRACKING": 0.025,
    "BROKEN": 0.04,
}

# Minimum observations before trusting calibrated values
MIN_CALIBRATION_OBS = 10


class DeltaCalibrator:
    """
    Learns the optimal belief_state → price_delta mapping from data.

    Usage:
        calibrator = DeltaCalibrator()

        # Feed historical data
        calibrator.record_transition("CRACKING", side="bid", price_at_event=0.65,
                                     price_1m=0.63, price_5m=0.61, price_15m=0.60)

        # Get calibrated delta
        delta = calibrator.get_delta("CRACKING")  # Returns ~0.04 based on data
    """

    def __init__(self):
        self._stats: Dict[str, TransitionStats] = {}
        self._calibrated_deltas: Dict[str, float] = dict(DEFAULT_DELTA_MAP)

    def record_transition(
        self,
        new_state: str,
        side: str,
        price_at_event: float,
        price_1m: Optional[float] = None,
        price_5m: Optional[float] = None,
        price_15m: Optional[float] = None,
    ):
        """
        Record a historical belief state transition and its outcome.

        All price moves are recorded as SIGNED values relative to the
        predicted direction:
          - If side="bid" (bearish prediction), positive move = price went DOWN
          - If side="ask" (bullish prediction), positive move = price went UP
        """
        if new_state not in self._stats:
            self._stats[new_state] = TransitionStats(transition=f"→{new_state}")

        stats = self._stats[new_state]
        stats.n_observations += 1

        # Convert to signed moves (positive = prediction was correct)
        sign = -1.0 if side == "bid" else 1.0  # bid reaction → expect price down

        if price_1m is not None:
            move = sign * (price_1m - price_at_event)
            stats.moves_1m.append(move)

        if price_5m is not None:
            move = sign * (price_5m - price_at_event)
            stats.moves_5m.append(move)

        if price_15m is not None:
            move = sign * (price_15m - price_at_event)
            stats.moves_15m.append(move)

        # Re-calibrate if we have enough data
        if stats.n_observations >= MIN_CALIBRATION_OBS:
            self._recalibrate(new_state)

    def get_delta(self, state: str) -> float:
        """
        Get calibrated delta for a belief state.

        Returns the ABSOLUTE adjustment to apply to market_price.
        Direction is determined separately by reaction side.
        """
        return self._calibrated_deltas.get(state, 0.0)

    def get_stats(self, state: str) -> Optional[TransitionStats]:
        return self._stats.get(state)

    def get_all_stats(self) -> Dict[str, dict]:
        """Summary of all calibration data."""
        result = {}
        for state, stats in self._stats.items():
            result[state] = {
                "n_observations": stats.n_observations,
                "median_move_5m": stats.median_move_5m,
                "directional_accuracy": stats.directional_accuracy,
                "false_positive_rate": stats.false_positive_rate,
                "calibrated_delta": self._calibrated_deltas.get(state, 0.0),
            }
        return result

    def _recalibrate(self, state: str):
        """
        Recalibrate delta for a state based on accumulated data.

        We use the median of the 5-minute signed move as the delta,
        BUT only the portion that's directionally correct.

        Effective delta = median_move * directional_accuracy

        This naturally shrinks delta when the signal is noisy
        (accuracy near 50%) and grows it when the signal is reliable.
        """
        stats = self._stats[state]

        if not stats.moves_5m:
            return

        # Use 5-minute horizon as the primary calibration window
        # (1m is too noisy, 15m has too much other stuff mixed in)
        median_move = stats.median_move_5m
        accuracy = stats.directional_accuracy

        # Effective delta: only count the directional component
        # If accuracy = 50%, this goes to 0 (no edge)
        # If accuracy = 70%, delta = median * 0.7
        effective_delta = abs(median_move) * max(0, accuracy - 0.5) * 2

        # Floor at the default (don't go below our conservative prior
        # unless we have LOTS of data showing zero edge)
        default = DEFAULT_DELTA_MAP.get(state, 0.0)
        if stats.n_observations < 50:
            # Blend with prior: weight toward data as n grows
            blend = stats.n_observations / 50
            effective_delta = blend * effective_delta + (1 - blend) * default
        elif effective_delta < 0.005:
            # With 50+ observations showing near-zero edge, respect that
            effective_delta = 0.005  # Minimum to cover spread

        self._calibrated_deltas[state] = effective_delta

        logger.info(
            f"Delta calibrated: {state} → {effective_delta:.4f} "
            f"(n={stats.n_observations}, accuracy={accuracy:.1%}, "
            f"median_5m={median_move:.4f})"
        )
