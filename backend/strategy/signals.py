"""
Signal Aggregation Layer (v6.1 — Architectural Fix)

DESIGN PHILOSOPHY (post-review):

  The core insight: in prediction markets, microstructure signals (OFI, VPIN,
  Hawkes, Kyle's Lambda) predict SHORT-TERM PRICE DYNAMICS, not event
  probability P(YES). They answer "is the market moving and how toxic is the
  flow" — not "what is the true probability of this outcome."

  Therefore we split signals into two distinct roles:

  1. PROBABILITY ESTIMATION — answers "what is P(YES)?"
     - Market price itself (strongest prior — efficient market baseline)
     - Belief State Machine adjustment (your domain-specific alpha)
     - BOCPD regime shift detection (structural break = price dislocation)

  2. RISK GATING — answers "should we trade RIGHT NOW?"
     - VPIN (flow toxicity → widen spread / don't trade)
     - Hawkes endogeneity (herding → unstable price → wait)
     - OFI zscore (extreme imbalance → adverse selection risk)
     - HMM regime (VOLATILE → reduce size)

  The Belief State Machine (STABLE→FRAGILE→CRACKING→BROKEN) is the PRIMARY
  directional signal. It IS a domain-specific HMM with hand-crafted transitions
  designed for this exact market structure. It should NOT compete with a generic
  HMM in an equal-weight ensemble — it should DRIVE the directional bet.

Signal flow:
  Collector → Reactor (belief states)  → PRIMARY SIGNAL (direction + magnitude)
  Collector → Alpha Engine (quant)     → RISK GATES (trade/don't trade, size scaling)
  Combined  → Kelly (with p_estimate from belief-adjusted market price)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
from collections import deque
from enum import Enum
import time
import logging

from backend.alpha.hmm_regime import HMMRegimeDetector
from backend.alpha.bocpd import BOCPDetector
from backend.alpha.hawkes import HawkesIntensity, BivarateHawkes
from backend.alpha.vpin import VPINCalculator
from backend.alpha.microstructure import MicrostructureSignals, BookSnapshot
from backend.strategy.calibration import DeltaCalibrator, DEFAULT_DELTA_MAP

logger = logging.getLogger(__name__)


class TradeGateVerdict(Enum):
    """Risk gate verdict — should we trade right now?"""
    GO = "GO"                # All clear, full size
    CAUTION = "CAUTION"      # Trade but reduce size
    NO_TRADE = "NO_TRADE"    # Do not trade


@dataclass
class RiskGateResult:
    """Aggregated risk gate output."""
    verdict: TradeGateVerdict = TradeGateVerdict.GO
    size_scale: float = 1.0      # Multiplier on position size [0, 1]
    reasons: List[str] = field(default_factory=list)

    # Individual gate values
    vpin: float = 0.0
    vpin_toxicity: str = "UNKNOWN"
    hawkes_endogeneity: float = 0.0
    ofi_zscore: float = 0.0
    hmm_regime: str = "CALM"
    hmm_regime_prob: float = 0.0


@dataclass
class MarketSignals:
    """All signals for a single market at a point in time."""
    token_id: str
    timestamp: float

    # --- PRIMARY: Probability estimate ---
    p_estimate: float = 0.5           # Belief-adjusted probability estimate
    edge: float = 0.0                 # p_estimate - market_price
    edge_direction: str = "NONE"      # "YES", "NO", or "NONE"

    # --- PRIMARY: Belief state (domain-specific alpha) ---
    belief_state: str = "STABLE"
    belief_state_severity: float = 0.0  # 0 = STABLE, 1 = BROKEN
    belief_state_direction: float = 0.0 # Signed: neg = bearish pressure

    # --- BOCPD structural break ---
    changepoint_prob: float = 0.0
    run_length: float = 0.0
    regime_shift_detected: bool = False

    # --- RISK GATES ---
    gate: RiskGateResult = field(default_factory=RiskGateResult)

    # --- Raw microstructure (for logging/analysis, NOT for direction) ---
    vpin: float = 0.0
    ofi_zscore: float = 0.0
    depth_imbalance: float = 0.0
    kyle_lambda: float = 0.0
    buy_intensity: float = 0.0
    sell_intensity: float = 0.0
    hmm_regime: str = "CALM"


# Belief state severity mapping
# CRACKING/BROKEN = market is dislocated, opportunity exists
BELIEF_STATE_SEVERITY = {
    "STABLE": 0.0,
    "FRAGILE": 0.3,
    "CRACKING": 0.7,
    "BROKEN": 1.0,
}


class MarketSignalProcessor:
    """
    Signal processor for a single market.

    Architecture:
    - Belief State Machine = primary alpha signal (from reactor)
    - BOCPD = structural break detector (supports belief state)
    - VPIN, Hawkes, OFI, HMM = risk gates (timing, not direction)
    """

    def __init__(self, token_id: str, calibrator: Optional[DeltaCalibrator] = None):
        self.token_id = token_id
        self.calibrator = calibrator

        # Risk gate models
        self.hmm = HMMRegimeDetector()
        self.bocpd = BOCPDetector(hazard_lambda=200.0)
        self.hawkes_buy = HawkesIntensity()
        self.hawkes_sell = HawkesIntensity()
        self.hawkes_bivariate = BivarateHawkes()
        self.vpin = VPINCalculator()
        self.microstructure = MicrostructureSignals()

        # State
        self._last_mid: Optional[float] = None
        self._price_buffer: deque = deque(maxlen=500)
        self._return_buffer: deque = deque(maxlen=500)

        # Belief state from reactor (PRIMARY SIGNAL)
        self._belief_state: str = "STABLE"
        self._belief_state_history: deque = deque(maxlen=50)
        self._last_reaction_type: Optional[str] = None
        self._last_reaction_side: Optional[str] = None

        # Price at last belief state change (for measuring dislocation)
        self._price_at_state_change: Optional[float] = None

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
            self.hmm.update(log_return)
            self.bocpd.update(log_return)

        self._price_buffer.append(mid)
        self._last_mid = mid
        self._last_update = timestamp

    def on_trade(self, timestamp: float, price: float, size: float, side: str):
        """Process trade event."""
        if side.upper() in ("BUY", "B"):
            self.hawkes_buy.on_event(timestamp)
            self.hawkes_bivariate.on_event(0, timestamp)
        else:
            self.hawkes_sell.on_event(timestamp)
            self.hawkes_bivariate.on_event(1, timestamp)
        self.vpin.update(price, size)
        self.microstructure.update_trade(price, size)

    def on_belief_state_change(self, new_state: str):
        """
        Receive belief state update from reactor.

        This is the PRIMARY alpha signal. When belief cracks/breaks,
        the market is dislocated and there may be an edge.
        """
        old_state = self._belief_state
        self._belief_state = new_state
        self._belief_state_history.append((time.time(), new_state))
        self._price_at_state_change = self._last_mid

        if new_state != old_state:
            logger.info(
                f"[ALPHA] {self.token_id[:8]}: Belief state {old_state} → {new_state} "
                f"@ price {self._last_mid}"
            )

    def on_reaction(self, reaction_type: str, side: str):
        """
        Receive reaction classification from reactor.

        Reaction types carry directional information:
        - VACUUM/SWEEP/PULL on bid side → selling pressure → price likely down
        - VACUUM/SWEEP/PULL on ask side → buying pressure → price likely up
        - HOLD → no directional information
        """
        self._last_reaction_type = reaction_type
        self._last_reaction_side = side

    def generate_signals(self, market_price: float) -> MarketSignals:
        """
        Generate aggregated signals.

        1. Belief State → directional signal + probability adjustment
        2. Risk gates → should we trade now and at what size?
        """
        now = self._last_update or time.time()

        # ===== PRIMARY: Belief-State-Driven Probability Estimation =====
        belief_severity = BELIEF_STATE_SEVERITY.get(self._belief_state, 0.0)

        # Direction from reaction side:
        # If belief is CRACKING/BROKEN and last reaction was on bid side,
        # that means bid liquidity collapsed → bearish → price will drop → bet NO
        belief_direction = self._compute_belief_direction(market_price)

        # Probability estimate:
        # Start from market price (efficient market prior).
        # Adjust based on belief state severity and direction.
        # CRACKING/BROKEN = market hasn't fully priced in the dislocation yet.
        p_estimate = self._estimate_probability(market_price, belief_severity, belief_direction)

        # Edge and direction
        edge = p_estimate - market_price
        if abs(edge) < 0.005:
            edge_direction = "NONE"
        elif edge > 0:
            edge_direction = "YES"
        else:
            edge_direction = "NO"

        # BOCPD structural break (supports belief state signal)
        cp_prob = self.bocpd.get_changepoint_prob()
        run_length = self.bocpd.get_expected_run_length()
        regime_shift = cp_prob > 0.3

        # ===== RISK GATES: Should we trade? =====
        gate = self._evaluate_risk_gates()

        # ===== Raw values for logging =====
        micro = self.microstructure.get_signals()
        regime_id, regime_prob, regime_name = self.hmm.get_regime()

        return MarketSignals(
            token_id=self.token_id,
            timestamp=now,
            # Primary
            p_estimate=p_estimate,
            edge=edge,
            edge_direction=edge_direction,
            belief_state=self._belief_state,
            belief_state_severity=belief_severity,
            belief_state_direction=belief_direction,
            # BOCPD
            changepoint_prob=cp_prob,
            run_length=run_length,
            regime_shift_detected=regime_shift,
            # Risk gates
            gate=gate,
            # Raw (logging only)
            vpin=self.vpin.current_vpin or 0.0,
            ofi_zscore=micro["ofi_zscore"],
            depth_imbalance=micro["depth_imbalance"],
            kyle_lambda=micro["kyle_lambda"],
            buy_intensity=self.hawkes_buy.current_intensity,
            sell_intensity=self.hawkes_sell.current_intensity,
            hmm_regime=regime_name,
        )

    def _compute_belief_direction(self, market_price: float) -> float:
        """
        Compute directional signal from belief state.

        Returns float in [-1, 1]:
          Negative = bearish (bet NO), Positive = bullish (bet YES)

        Logic:
          - STABLE: 0 (no edge)
          - FRAGILE: small signal based on reaction side
          - CRACKING/BROKEN: strong signal based on reaction side + price move

        The direction comes from WHERE the liquidity reaction happened:
          - Reactions on bid side (bid liquidity collapsing) → bearish
          - Reactions on ask side (ask liquidity collapsing) → bullish
        """
        severity = BELIEF_STATE_SEVERITY.get(self._belief_state, 0.0)

        if severity < 0.1:
            return 0.0  # STABLE: no directional signal

        # Direction from reaction side
        if self._last_reaction_side == "bid":
            raw_direction = -1.0  # Bid collapsing → bearish
        elif self._last_reaction_side == "ask":
            raw_direction = 1.0   # Ask collapsing → bullish
        else:
            # No reaction side info; use price momentum as weak proxy
            if len(self._price_buffer) >= 20:
                recent = list(self._price_buffer)
                short_ma = np.mean(recent[-5:])
                long_ma = np.mean(recent[-20:])
                raw_direction = np.sign(short_ma - long_ma)
            else:
                return 0.0

        # Scale by severity
        return float(np.clip(raw_direction * severity, -1.0, 1.0))

    def _estimate_probability(
        self, market_price: float, severity: float, direction: float
    ) -> float:
        """
        Estimate P(YES) using market price as prior + belief state adjustment.

        The adjustment magnitude scales with belief severity:
          STABLE:   0 adjustment (trust market)
          FRAGILE:  up to ±1% adjustment
          CRACKING: up to ±3% adjustment
          BROKEN:   up to ±5% adjustment

        Why these small numbers? The market is mostly efficient.
        Even a 2-3% edge on a prediction market is enormous. We're not
        claiming we know the true probability — we're claiming the market
        hasn't fully incorporated the liquidity dislocation yet.
        """
        # Use calibrated delta if available, otherwise conservative default
        if self.calibrator:
            max_adjustment = self.calibrator.get_delta(self._belief_state)
        else:
            max_adjustment = DEFAULT_DELTA_MAP.get(self._belief_state, 0.0)

        # BOCPD amplifier: if structural break detected, market may be
        # slower to adjust → increase adjustment
        cp_prob = self.bocpd.get_changepoint_prob()
        if cp_prob > 0.3:
            max_adjustment *= 1.5  # 50% boost during structural breaks

        # Apply directional adjustment
        adjustment = direction * max_adjustment

        # Price dislocation: if price moved significantly since state change,
        # reduce adjustment (market may have already corrected)
        if self._price_at_state_change is not None and self._last_mid is not None:
            price_move = abs(self._last_mid - self._price_at_state_change)
            correction_factor = max(0.0, 1.0 - price_move / 0.05)
            adjustment *= correction_factor

        p_estimate = market_price + adjustment
        return float(np.clip(p_estimate, 0.01, 0.99))

    def _evaluate_risk_gates(self) -> RiskGateResult:
        """
        Evaluate all risk gates to determine if now is safe to trade.

        Each gate can:
          - Block trading entirely (NO_TRADE)
          - Reduce position size (CAUTION + scale factor)
          - Allow full size (GO)
        """
        result = RiskGateResult()
        reasons = []

        # --- VPIN: Flow toxicity ---
        vpin_val = self.vpin.current_vpin or 0.0
        result.vpin = vpin_val
        result.vpin_toxicity = self.vpin.get_toxicity_level()

        if vpin_val > 0.7:
            result.verdict = TradeGateVerdict.NO_TRADE
            reasons.append(f"VPIN extreme ({vpin_val:.2f})")
            result.reasons = reasons
            return result
        elif vpin_val > 0.4:
            result.size_scale *= 0.5
            reasons.append(f"VPIN high ({vpin_val:.2f}), size halved")

        # --- Hawkes endogeneity: herding/cascade risk ---
        endogeneity = self.hawkes_bivariate.endogeneity
        result.hawkes_endogeneity = endogeneity

        if endogeneity > 0.85:
            result.verdict = TradeGateVerdict.NO_TRADE
            reasons.append(f"Hawkes endogeneity critical ({endogeneity:.2f})")
            result.reasons = reasons
            return result
        elif endogeneity > 0.6:
            result.size_scale *= 0.7
            reasons.append(f"Hawkes endogeneity elevated ({endogeneity:.2f})")

        # --- OFI: Extreme imbalance = adverse selection ---
        micro = self.microstructure.get_signals()
        ofi_z = abs(micro["ofi_zscore"])
        result.ofi_zscore = micro["ofi_zscore"]

        if ofi_z > 4.0:
            result.size_scale *= 0.5
            reasons.append(f"OFI extreme (z={ofi_z:.1f})")

        # --- HMM Regime ---
        regime_id, regime_prob, regime_name = self.hmm.get_regime()
        result.hmm_regime = regime_name
        result.hmm_regime_prob = regime_prob

        if regime_name == "VOLATILE":
            result.size_scale *= 0.5
            reasons.append("Volatile regime, size halved")
        elif regime_name == "TRENDING":
            result.size_scale *= 0.8
            reasons.append("Trending regime, slight size reduction")

        # --- Kyle's Lambda: adverse selection level ---
        if abs(micro["kyle_lambda"]) > 0.005:
            result.size_scale *= 0.7
            reasons.append(f"High adverse selection (λ={micro['kyle_lambda']:.4f})")

        # Final verdict
        if result.verdict != TradeGateVerdict.NO_TRADE:
            if result.size_scale < 0.3:
                result.verdict = TradeGateVerdict.CAUTION
            else:
                result.verdict = TradeGateVerdict.GO

        result.reasons = reasons
        return result


class SignalAggregator:
    """
    Multi-market signal aggregator.
    """

    def __init__(self, calibrator: Optional[DeltaCalibrator] = None):
        self._processors: Dict[str, MarketSignalProcessor] = {}
        self.calibrator = calibrator or DeltaCalibrator()

    def get_processor(self, token_id: str) -> MarketSignalProcessor:
        if token_id not in self._processors:
            self._processors[token_id] = MarketSignalProcessor(
                token_id, calibrator=self.calibrator
            )
        return self._processors[token_id]

    def generate_all_signals(
        self, market_prices: Dict[str, float]
    ) -> Dict[str, MarketSignals]:
        results = {}
        for token_id, price in market_prices.items():
            proc = self.get_processor(token_id)
            results[token_id] = proc.generate_signals(price)
        return results

    @property
    def active_markets(self) -> List[str]:
        return list(self._processors.keys())
