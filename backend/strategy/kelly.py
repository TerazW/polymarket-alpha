"""
Bayesian Kelly Criterion for Prediction Market Position Sizing

References:
- Kelly (1956) "A New Interpretation of Information Rate"
- Thorp (2006) "The Kelly Criterion in Blackjack, Sports Betting and the Stock Market"
- MacLean, Thorp & Ziemba (2011) "The Kelly Capital Growth Investment Criterion"
- Cover & Thomas (2006) "Elements of Information Theory"

Key insight: Kelly maximizes asymptotic log-growth rate G* = D_KL(p || b)
where p is true probability and b is market price.

We use Bayesian Kelly with Beta posterior to naturally account for
estimation uncertainty (effectively implements fractional Kelly).
"""

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import betaln
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
    """

    def __init__(self, alpha: float = 2.0, beta: float = 2.0):
        self.alpha = alpha
        self.beta = beta

    def update(self, outcome: int, weight: float = 1.0):
        """Update with binary outcome (1=YES, 0=NO)."""
        self.alpha += outcome * weight
        self.beta += (1 - outcome) * weight

    def update_with_price_signal(self, estimated_prob: float, confidence: float = 1.0):
        """
        Update posterior using a soft probability signal.

        Instead of hard 0/1 outcomes, incorporate a probability estimate
        with a confidence weight.
        """
        # Treat as a pseudo-observation weighted by confidence
        self.alpha += estimated_prob * confidence
        self.beta += (1 - estimated_prob) * confidence

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
        win_return = (1 - c) / c  # Payout per dollar risked

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
    n_grid: int = 100,
) -> Tuple[float, float]:
    """
    Bayesian Kelly: maximize E_posterior[log(wealth)] over fraction f.

    This naturally produces a more conservative bet than plug-in Kelly
    because posterior uncertainty reduces the optimal fraction.

    Returns:
        (optimal_fraction, expected_growth_rate)
    """
    c = market_price

    if side == "YES":
        # Optimize YES fraction
        def neg_growth(f):
            if f <= 0.001:
                return 0.0
            return -posterior.expected_log_growth(f, c)

        result = minimize_scalar(neg_growth, bounds=(0.001, 0.5), method='bounded')
        return float(result.x), float(-result.fun)
    else:
        # For NO bet, flip: bet on NO at price (1-c)
        flipped_posterior = BetaPosterior(alpha=posterior.beta, beta=posterior.alpha)
        def neg_growth(f):
            if f <= 0.001:
                return 0.0
            return -flipped_posterior.expected_log_growth(f, 1 - c)

        result = minimize_scalar(neg_growth, bounds=(0.001, 0.5), method='bounded')
        return float(result.x), float(-result.fun)


class KellyPositionSizer:
    """
    Full Kelly position sizing system with Bayesian estimation,
    fractional Kelly, and risk constraints.
    """

    def __init__(self, config: Optional[KellyConfig] = None):
        self.config = config or KellyConfig()
        # Per-market Beta posteriors
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
        use_bayesian: bool = True,
    ) -> Dict:
        """
        Compute position size for a market.

        Returns dict with:
            side: "YES" or "NO" or None
            fraction: Kelly fraction (after multiplier and caps)
            size_usd: Dollar amount to risk
            edge: Estimated edge
            confidence: P(edge > 0)
            growth_rate: Expected log-growth rate
        """
        posterior = self.get_or_create_posterior(market_id)
        posterior.update_with_price_signal(p_estimate, confidence=0.5)

        # Determine side
        p_est = posterior.mean
        edge_yes = p_est - market_price
        edge_no = market_price - p_est

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

        # Confidence check: P(edge > 0)
        if side == "YES":
            confidence = posterior.prob_above(market_price)
        else:
            confidence = 1.0 - posterior.prob_above(market_price)

        if confidence < self.config.min_confidence:
            return {
                "side": side, "fraction": 0.0, "size_usd": 0.0,
                "edge": edge, "confidence": confidence,
                "growth_rate": 0.0, "reason": "low_confidence"
            }

        # Kelly fraction
        if use_bayesian:
            fraction, growth = compute_bayesian_kelly(posterior, market_price, side)
        else:
            fraction = compute_kelly_fraction(p_est, market_price, side)
            growth = edge ** 2 / (2 * posterior.variance + 1e-10)  # Approximate

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
            "posterior_mean": posterior.mean,
            "posterior_std": posterior.std,
            "credible_interval": posterior.credible_interval(0.9),
        }

    def update_outcome(self, market_id: str, outcome: int):
        """Update posterior with realized outcome (1=YES won, 0=NO won)."""
        if market_id in self._posteriors:
            self._posteriors[market_id].update(outcome)


def multi_market_kelly(
    edges: List[float],
    market_prices: List[float],
    kelly_fraction: float = 0.25,
) -> np.ndarray:
    """
    Multi-market Kelly for correlated binary markets.

    Simplified: treats markets as independent (conservative).
    For correlated markets, use copula-based joint optimization.

    Args:
        edges: Estimated edge per market (p_true - p_market for YES)
        market_prices: Current market prices
        kelly_fraction: Fractional Kelly multiplier

    Returns:
        Optimal fractions per market
    """
    n = len(edges)
    fractions = np.zeros(n)

    for i in range(n):
        if edges[i] > 0:
            # YES bet
            f = edges[i] / (1 - market_prices[i])
        elif edges[i] < 0:
            # NO bet
            f = -edges[i] / market_prices[i]
        else:
            f = 0.0

        fractions[i] = np.sign(edges[i]) * min(abs(f), 0.25) * kelly_fraction

    return fractions
