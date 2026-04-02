"""
Signal Aggregation Layer

Bridges the alpha engine (raw signals) with the strategy engine (trading decisions).
Converts reactor belief states + alpha signals into probability estimates and
directional signals.

Signal flow:
  Collector → Reactor (belief states) ─┐
  Collector → Alpha Engine (quant)   ──┤→ SignalAggregator → Kelly → RiskManager → Execution
  Market Data → Microstructure        ─┘
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from collections import deque
import time
import logging

from backend.alpha.hmm_regime import HMMRegimeDetector
from backend.alpha.bocpd import BOCPDetector
from backend.alpha.hawkes import HawkesIntensity, BivarateHawkes
from backend.alpha.vpin import VPINCalculator
from backend.alpha.microstructure import MicrostructureSignals, BookSnapshot
from backend.alpha.ensemble import ExponentialWeightsEnsemble, ProbabilityEnsemble

logger = logging.getLogger(__name__)

# Expert names for ensemble
DIRECTIONAL_EXPERTS = [
    "ofi_zscore",           # Order flow imbalance
    "depth_imbalance",      # Book pressure
    "hawkes_imbalance",     # Trade flow clustering
    "bocpd_signal",         # Changepoint direction
    "belief_state_signal",  # From existing reactor
    "mean_reversion",       # Price mean-reversion
]

PROBABILITY_EXPERTS = [
    "market_price",         # Current market price as prior
    "bayesian_update",      # Bayesian update from trade flow
    "regime_adjusted",      # Regime-adjusted probability
]


@dataclass
class MarketSignals:
    """All signals for a single market at a point in time."""
    token_id: str
    timestamp: float

    # Probability estimates
    p_estimate: float = 0.5           # Combined probability estimate
    p_confidence: float = 0.0         # Confidence in estimate

    # Directional signal [-1, 1]
    direction: float = 0.0
    direction_strength: float = 0.0

    # Regime
    regime: str = "CALM"
    regime_prob: float = 0.0

    # Changepoint
    changepoint_prob: float = 0.0
    run_length: float = 0.0

    # Flow toxicity
    vpin: float = 0.0
    toxicity_level: str = "UNKNOWN"

    # Microstructure
    ofi_zscore: float = 0.0
    depth_imbalance: float = 0.0
    kyle_lambda: float = 0.0

    # Hawkes intensity
    buy_intensity: float = 0.0
    sell_intensity: float = 0.0

    # From reactor
    belief_state: str = "STABLE"

    # Raw expert signals
    expert_weights: Dict[str, float] = field(default_factory=dict)


class MarketSignalProcessor:
    """
    Signal processor for a single market.

    Maintains all alpha models and produces aggregated signals.
    """

    def __init__(self, token_id: str):
        self.token_id = token_id

        # Alpha models
        self.hmm = HMMRegimeDetector()
        self.bocpd = BOCPDetector(hazard_lambda=200.0)
        self.hawkes_buy = HawkesIntensity()
        self.hawkes_sell = HawkesIntensity()
        self.hawkes_bivariate = BivarateHawkes()
        self.vpin = VPINCalculator()
        self.microstructure = MicrostructureSignals()

        # Ensembles
        self.direction_ensemble = ExponentialWeightsEnsemble(DIRECTIONAL_EXPERTS)
        self.prob_ensemble = ProbabilityEnsemble(PROBABILITY_EXPERTS)

        # State
        self._last_mid: Optional[float] = None
        self._price_buffer: deque = deque(maxlen=500)
        self._return_buffer: deque = deque(maxlen=500)
        self._belief_state: str = "STABLE"
        self._last_update: float = 0.0

    def on_book_update(
        self,
        timestamp: float,
        bid_price: float,
        ask_price: float,
        bid_size: float,
        ask_size: float,
        bid_levels: Optional[list] = None,
        ask_levels: Optional[list] = None,
    ):
        """Process order book update."""
        snap = BookSnapshot(
            timestamp=timestamp,
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            bid_levels=bid_levels,
            ask_levels=ask_levels,
        )
        self.microstructure.update_book(snap)

        mid = (bid_price + ask_price) / 2.0
        if self._last_mid is not None and self._last_mid > 0:
            log_return = np.log(mid / self._last_mid)
            self._return_buffer.append(log_return)

            # Update HMM with log-return
            self.hmm.update(log_return)

            # Update BOCPD with log-return
            self.bocpd.update(log_return)

        self._price_buffer.append(mid)
        self._last_mid = mid
        self._last_update = timestamp

    def on_trade(self, timestamp: float, price: float, size: float, side: str):
        """Process trade event."""
        # Hawkes
        if side.upper() in ("BUY", "B"):
            self.hawkes_buy.on_event(timestamp)
            self.hawkes_bivariate.on_event(0, timestamp)
        else:
            self.hawkes_sell.on_event(timestamp)
            self.hawkes_bivariate.on_event(1, timestamp)

        # VPIN
        self.vpin.update(price, size)

        # Microstructure trade update
        self.microstructure.update_trade(price, size)

    def on_belief_state_change(self, new_state: str):
        """Receive belief state update from reactor."""
        self._belief_state = new_state

    def generate_signals(self, market_price: float) -> MarketSignals:
        """
        Generate aggregated signals for the current moment.

        Args:
            market_price: Current market last trade price

        Returns:
            MarketSignals with all computed signals
        """
        now = self._last_update or time.time()

        # --- Collect raw signals ---
        # HMM regime
        regime_id, regime_prob, regime_name = self.hmm.get_regime()

        # BOCPD
        cp_prob = self.bocpd.get_changepoint_prob()
        run_length = self.bocpd.get_expected_run_length()

        # VPIN
        vpin_val = self.vpin.current_vpin or 0.0
        toxicity = self.vpin.get_toxicity_level()

        # Microstructure
        micro = self.microstructure.get_signals()

        # Hawkes
        buy_intensity = self.hawkes_buy.current_intensity
        sell_intensity = self.hawkes_sell.current_intensity
        hawkes_imbalance = self.hawkes_bivariate.get_imbalance_ratio()

        # --- Build directional expert signals ---
        # Convert each signal to [-1, 1] range
        expert_signals = {}

        # OFI z-score (already normalized-ish)
        expert_signals["ofi_zscore"] = np.clip(micro["ofi_zscore"] / 3.0, -1, 1)

        # Depth imbalance (already in [-1, 1])
        expert_signals["depth_imbalance"] = np.clip(micro["depth_imbalance"], -1, 1)

        # Hawkes imbalance (already in [-1, 1])
        expert_signals["hawkes_imbalance"] = np.clip(hawkes_imbalance, -1, 1)

        # BOCPD signal: direction of change at changepoint
        if cp_prob > 0.2 and len(self._return_buffer) >= 5:
            recent_return = np.mean(list(self._return_buffer)[-5:])
            expert_signals["bocpd_signal"] = np.clip(
                np.sign(recent_return) * cp_prob * 2, -1, 1
            )
        else:
            expert_signals["bocpd_signal"] = 0.0

        # Belief state signal (from reactor)
        belief_signal = {
            "STABLE": 0.0,
            "FRAGILE": -0.3,
            "CRACKING": -0.6,
            "BROKEN": -0.9,
        }.get(self._belief_state, 0.0)
        expert_signals["belief_state_signal"] = belief_signal

        # Mean reversion signal
        if len(self._price_buffer) >= 50:
            prices = np.array(list(self._price_buffer))
            mean_price = np.mean(prices[-50:])
            std_price = np.std(prices[-50:])
            if std_price > 1e-6:
                z = (prices[-1] - mean_price) / std_price
                # Negative z = price below mean = buy signal
                expert_signals["mean_reversion"] = np.clip(-z / 3.0, -1, 1)
            else:
                expert_signals["mean_reversion"] = 0.0
        else:
            expert_signals["mean_reversion"] = 0.0

        # --- Ensemble combination ---
        direction = self.direction_ensemble.predict(expert_signals)

        # --- Probability estimation ---
        # Convert directional signal + market price into probability estimate
        prob_experts = {
            "market_price": market_price,
            "bayesian_update": np.clip(market_price + direction * 0.05, 0.01, 0.99),
            "regime_adjusted": self._regime_adjust_prob(
                market_price, regime_name, cp_prob
            ),
        }
        p_estimate = self.prob_ensemble.combine_probabilities(prob_experts)

        # Confidence: higher when signals agree and regime is calm
        direction_strength = abs(direction)
        vpin_confidence = 1.0 - min(vpin_val, 1.0)  # High VPIN = low confidence
        regime_confidence = 1.0 if regime_name == "CALM" else 0.7 if regime_name == "TRENDING" else 0.4
        p_confidence = direction_strength * vpin_confidence * regime_confidence

        return MarketSignals(
            token_id=self.token_id,
            timestamp=now,
            p_estimate=p_estimate,
            p_confidence=p_confidence,
            direction=direction,
            direction_strength=direction_strength,
            regime=regime_name,
            regime_prob=regime_prob,
            changepoint_prob=cp_prob,
            run_length=run_length,
            vpin=vpin_val,
            toxicity_level=toxicity,
            ofi_zscore=micro["ofi_zscore"],
            depth_imbalance=micro["depth_imbalance"],
            kyle_lambda=micro["kyle_lambda"],
            buy_intensity=buy_intensity,
            sell_intensity=sell_intensity,
            belief_state=self._belief_state,
            expert_weights=self.direction_ensemble.get_weights(),
        )

    def feedback(self, outcome_direction: float):
        """
        Provide feedback to ensemble after observing price move.

        Args:
            outcome_direction: Positive = price went up, negative = down
        """
        self.direction_ensemble.update(outcome_direction)

    def _regime_adjust_prob(
        self, market_price: float, regime: str, cp_prob: float
    ) -> float:
        """Adjust probability based on regime and changepoint."""
        # In volatile regime, shrink toward 0.5 (less confident)
        if regime == "VOLATILE":
            return 0.5 + (market_price - 0.5) * 0.7
        # At changepoint, recent direction may reverse
        if cp_prob > 0.5:
            return 0.5 + (market_price - 0.5) * 0.5
        return market_price


class SignalAggregator:
    """
    Multi-market signal aggregator.

    Manages per-market signal processors and provides a unified interface.
    """

    def __init__(self):
        self._processors: Dict[str, MarketSignalProcessor] = {}

    def get_processor(self, token_id: str) -> MarketSignalProcessor:
        """Get or create signal processor for a market."""
        if token_id not in self._processors:
            self._processors[token_id] = MarketSignalProcessor(token_id)
        return self._processors[token_id]

    def generate_all_signals(
        self, market_prices: Dict[str, float]
    ) -> Dict[str, MarketSignals]:
        """Generate signals for all tracked markets."""
        results = {}
        for token_id, price in market_prices.items():
            proc = self.get_processor(token_id)
            results[token_id] = proc.generate_signals(price)
        return results

    @property
    def active_markets(self) -> List[str]:
        return list(self._processors.keys())
