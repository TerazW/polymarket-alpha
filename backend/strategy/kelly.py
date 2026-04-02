"""
Bayesian Kelly Criterion for Prediction Market Position Sizing (v6.1 fix)

DESIGN FIX (post-review):

  The Beta posterior must ONLY be updated with INDEPENDENT EVIDENCE:
  - Market resolution outcomes (update_outcome) — the only hard signal
  - NOT with the system's own p_estimate every tick (self-feeding loop)

  The previous version called update_with_price_signal() inside size_position(),
  causing the posterior's alpha+beta to inflate on every call. After 100 calls,
  the posterior becomes absurdly overconfident in whatever p_estimate was — but
  that confidence is fake, not backed by independent observations.

  Fixed version:
  - size_position() takes p_estimate as a PLUG-IN value, does NOT feed it
    back into the posterior
  - Posterior only updates via update_outcome() (market resolution)
  - Bayesian Kelly still works: posterior uncertainty naturally implements
    fractional Kelly, but the uncertainty comes from real outcome data

References:
- Kelly (1956) "A New Interpretation of Information Rate"
- Thorp (2006) "The Kelly Criterion in Blackjack, Sports Betting and the Stock Market"
- MacLean, Thorp & Ziemba (2011) "The Kelly Capital Growth Investment Criterion"
"""

import numpy as np
from scipy.optimize import minimize_scalar
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class KellyConfig:
    """Kelly criterion configuration."""
    max_fraction: float = 0.25       # Hard cap on any single bet
    kelly_multiplier: float = 0.5    # Fractional Kelly (conservative)
    min_edge: float = 0.02           # Minimum edge to trade (2%)
    min_confidence: float = 0.55     # Minimum P(edge > 0) to trade


class BetaPosterior:
    """
    Beta posterior for binary outcome probability.

    Prior: p ~ Beta(alpha, beta)
    After observing k successes in n trials:
    Posterior: p ~ Beta(alpha + k, beta + n - k)

    IMPORTANT: Only update with INDEPENDENT observations (market outcomes),
    never with the system's own signal estimates.
    """

    def __init__(self, alpha: float = 2.0, beta: float = 2.0):
        self.alpha = alpha
        self.beta = beta

    def update(self, outcome: int, weight: float = 1.0):
        """
        Update with binary outcome (1=YES, 0=NO).

        This should ONLY be called when a market resolves or when
        there is genuine new independent evidence.
        """
        self.alpha += outcome * weight
        self.beta += (1 - outcome) * weight

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        ab = self.alpha + self.beta
        return (self.alpha * self.beta) / (ab * ab * (ab + 1))

    @property
    def std(self) -> float:
        return np.sqrt(self.variance)

    @property
    def n_observations(self) -> float:
        """Effective number of observations (alpha + beta - prior)."""
        return self.alpha + self.beta

    def prob_above(self, threshold: float) -> float:
        """P(p > threshold) under the posterior."""
        from scipy.stats import beta as beta_dist
        return float(1.0 - beta_dist.cdf(threshold, self.alpha, self.beta))

    def credible_interval(self, level: float = 0.9) -> Tuple[float, float]:
        """Symmetric credible interval."""
        from scipy.stats import beta as beta_dist
        tail = (1 - level) / 2
        lo = float(beta_dist.ppf(tail, self.alpha, self.beta))
        hi = float(beta_dist.ppf(1 - tail, self.alpha, self.beta))
        return lo, hi

    def expected_log_growth(self, fraction: float, market_price: float) -> float:
        """
        E_p[G(f)] = E_p[p * log(1 + f*(1-c)/c) + (1-p) * log(1 - f)]

        For a YES bet at market price c with fraction f of bankroll.
        Expectation taken over Beta posterior.
        """
        from scipy.integrate import quad
        from scipy.stats import beta as beta_dist

        if fraction <= 0 or fraction >= 1:
            return -1e10

        c = market_price
        win_return = (1 - c) / c

        def integrand(p):
            g = p * np.log(1 + fraction * win_return) + (1 - p) * np.log(1 - fraction)
            return g * beta_dist.pdf(p, self.alpha, self.beta)

        result, _ = quad(integrand, 0.001, 0.999)
        return result


def compute_kelly_fraction(
    p_estimate: float,
    market_price: float,
    side: str = "YES",
) -> float:
    """
    Simple (plug-in) Kelly fraction for binary bet.

    For YES bet at price c: f* = (p - c) / (1 - c)
    For NO bet at price c:  f* = (c - p) / c
    """
    if side == "YES":
        edge = p_estimate - market_price
        if edge <= 0:
            return 0.0
        return edge / (1 - market_price)
    else:
        edge = market_price - p_estimate
        if edge <= 0:
            return 0.0
        return edge / market_price


def compute_bayesian_kelly(
    posterior: BetaPosterior,
    market_price: float,
    side: str = "YES",
) -> Tuple[float, float]:
    """
    Bayesian Kelly: maximize E_posterior[log(wealth)] over fraction f.

    Returns:
        (optimal_fraction, expected_growth_rate)
    """
    c = market_price

    if side == "YES":
        def neg_growth(f):
            if f <= 0.001:
                return 0.0
            return -posterior.expected_log_growth(f, c)

        result = minimize_scalar(neg_growth, bounds=(0.001, 0.5), method='bounded')
        return float(result.x), float(-result.fun)
    else:
        flipped_posterior = BetaPosterior(alpha=posterior.beta, beta=posterior.alpha)
        def neg_growth(f):
            if f <= 0.001:
                return 0.0
            return -flipped_posterior.expected_log_growth(f, 1 - c)

        result = minimize_scalar(neg_growth, bounds=(0.001, 0.5), method='bounded')
        return float(result.x), float(-result.fun)


class KellyPositionSizer:
    """
    Kelly position sizing system.

    v6.1 FIX: size_position() uses p_estimate as plug-in value directly.
    Posterior is ONLY updated via update_outcome() when markets resolve.
    No more self-feeding loop.

    When we have enough market resolution data (> 5 outcomes for a market),
    we use Bayesian Kelly which naturally accounts for estimation uncertainty.
    Otherwise, we use plug-in Kelly with the fractional multiplier.
    """

    def __init__(self, config: Optional[KellyConfig] = None):
        self.config = config or KellyConfig()
        self._posteriors: Dict[str, BetaPosterior] = {}

    def get_or_create_posterior(
        self, market_id: str, prior_alpha: float = 2.0, prior_beta: float = 2.0
    ) -> BetaPosterior:
        if market_id not in self._posteriors:
            self._posteriors[market_id] = BetaPosterior(prior_alpha, prior_beta)
        return self._posteriors[market_id]

    def size_position(
        self,
        market_id: str,
        p_estimate: float,
        market_price: float,
        bankroll: float,
    ) -> Dict:
        """
        Compute position size for a market.

        Args:
            market_id: Market identifier
            p_estimate: Estimated P(YES) from signal layer
            market_price: Current market price
            bankroll: Current bankroll

        Returns dict with:
            side, fraction, size_usd, edge, confidence, growth_rate
        """
        # Determine side and edge DIRECTLY from p_estimate (plug-in)
        # NO posterior self-feeding
        edge_yes = p_estimate - market_price
        edge_no = market_price - p_estimate

        if edge_yes > edge_no and edge_yes > self.config.min_edge:
            side = "YES"
            edge = edge_yes
        elif edge_no > self.config.min_edge:
            side = "NO"
            edge = edge_no
        else:
            return {
                "side": None, "fraction": 0.0, "size_usd": 0.0,
                "edge": max(edge_yes, edge_no), "confidence": 0.5,
                "growth_rate": 0.0, "reason": "insufficient_edge"
            }

        # Confidence: simple heuristic based on edge magnitude
        # Larger edge = more confident the signal is real
        # This replaces the fake posterior-based confidence
        confidence = 0.5 + min(abs(edge) / 0.10, 0.45)  # Maps edge to [0.5, 0.95]

        if confidence < self.config.min_confidence:
            return {
                "side": side, "fraction": 0.0, "size_usd": 0.0,
                "edge": edge, "confidence": confidence,
                "growth_rate": 0.0, "reason": "low_confidence"
            }

        # Kelly fraction — use plug-in (most common case)
        # Bayesian Kelly is only used when we have real outcome data
        posterior = self.get_or_create_posterior(market_id)
        has_outcome_data = posterior.n_observations > 6  # More than prior

        if has_outcome_data:
            fraction, growth = compute_bayesian_kelly(posterior, market_price, side)
        else:
            # Plug-in Kelly with fractional multiplier
            fraction = compute_kelly_fraction(p_estimate, market_price, side)
            growth = edge ** 2 / (2 * max(p_estimate * (1 - p_estimate), 0.01))

        # Apply fractional Kelly multiplier and cap
        fraction *= self.config.kelly_multiplier
        fraction = min(fraction, self.config.max_fraction)

        size_usd = fraction * bankroll

        return {
            "side": side,
            "fraction": fraction,
            "size_usd": size_usd,
            "edge": edge,
            "confidence": confidence,
            "growth_rate": growth,
            "p_estimate": p_estimate,
            "market_price": market_price,
            "used_bayesian": has_outcome_data,
        }

    def update_outcome(self, market_id: str, outcome: int):
        """
        Update posterior with realized market outcome.

        THIS is the only valid way to update the posterior.
        Called when a market resolves (1=YES won, 0=NO won).
        """
        posterior = self.get_or_create_posterior(market_id)
        posterior.update(outcome)
        logger.info(
            f"Kelly posterior updated: {market_id[:8]} "
            f"outcome={'YES' if outcome == 1 else 'NO'} "
            f"posterior mean={posterior.mean:.3f} "
            f"n_obs={posterior.n_observations:.0f}"
        )


def multi_market_kelly(
    edges: List[float],
    market_prices: List[float],
    kelly_fraction: float = 0.25,
) -> np.ndarray:
    """
    Multi-market Kelly for correlated binary markets.

    Simplified: treats markets as independent (conservative).
    """
    n = len(edges)
    fractions = np.zeros(n)

    for i in range(n):
        if edges[i] > 0:
            f = edges[i] / (1 - market_prices[i])
        elif edges[i] < 0:
            f = -edges[i] / market_prices[i]
        else:
            f = 0.0

        fractions[i] = np.sign(edges[i]) * min(abs(f), 0.25) * kelly_fraction

    return fractions
