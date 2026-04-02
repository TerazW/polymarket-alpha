"""
Bayesian Kelly Criterion for Prediction Market Position Sizing (v6.2)

DESIGN (v6.2 — category-level learning):

  Per-market posteriors are useless for event markets: each market_id is
  unique, resolves once, and the Beta(2,2) prior never sees an outcome
  before the position closes. The Bayesian machinery was dead code.

  Fix: CATEGORY-LEVEL posteriors. Instead of learning "what's the true
  probability of THIS specific market," we learn "when our system says
  CRACKING with 3% edge, how often do we actually win?"

  This is the right question. Categories are belief state transitions:
    - "CRACKING_YES": trades taken when belief=CRACKING, side=YES
    - "BROKEN_NO": trades taken when belief=BROKEN, side=NO

  The posterior tracks: P(our bet wins | belief_state, side).
  After enough trades, Bayesian Kelly kicks in and naturally sizes
  positions based on our REALIZED win rate per category.

References:
- Kelly (1956) "A New Interpretation of Information Rate"
- Thorp (2006) "The Kelly Criterion in Blackjack, Sports Betting and the Stock Market"
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
    min_outcomes_for_bayesian: int = 10  # Outcomes before trusting Bayesian Kelly


class BetaPosterior:
    """
    Beta posterior for binary outcome probability.

    Prior: p ~ Beta(alpha, beta)
    Only updated with actual trade outcomes.
    """

    def __init__(self, alpha: float = 2.0, beta: float = 2.0):
        self.alpha = alpha
        self.beta = beta

    def update(self, outcome: int, weight: float = 1.0):
        """Update with binary outcome (1=win, 0=loss)."""
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
        return self.alpha + self.beta

    def prob_above(self, threshold: float) -> float:
        from scipy.stats import beta as beta_dist
        return float(1.0 - beta_dist.cdf(threshold, self.alpha, self.beta))

    def credible_interval(self, level: float = 0.9) -> Tuple[float, float]:
        from scipy.stats import beta as beta_dist
        tail = (1 - level) / 2
        lo = float(beta_dist.ppf(tail, self.alpha, self.beta))
        hi = float(beta_dist.ppf(1 - tail, self.alpha, self.beta))
        return lo, hi

    def expected_log_growth(self, fraction: float, market_price: float) -> float:
        """E_p[G(f)] for a YES bet at market price c with fraction f."""
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
    """Plug-in Kelly fraction for binary bet."""
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
    """Bayesian Kelly: maximize E_posterior[log(wealth)] over fraction f."""
    c = market_price

    if side == "YES":
        def neg_growth(f):
            if f <= 0.001:
                return 0.0
            return -posterior.expected_log_growth(f, c)
        result = minimize_scalar(neg_growth, bounds=(0.001, 0.5), method='bounded')
        return float(result.x), float(-result.fun)
    else:
        flipped = BetaPosterior(alpha=posterior.beta, beta=posterior.alpha)
        def neg_growth(f):
            if f <= 0.001:
                return 0.0
            return -flipped.expected_log_growth(f, 1 - c)
        result = minimize_scalar(neg_growth, bounds=(0.001, 0.5), method='bounded')
        return float(result.x), float(-result.fun)


def _category_key(belief_state: str, side: str) -> str:
    """Build category key for posterior grouping."""
    return f"{belief_state}_{side}"


class KellyPositionSizer:
    """
    Kelly position sizing with CATEGORY-LEVEL Bayesian learning.

    Instead of per-market posteriors (dead for event markets), we maintain
    posteriors per (belief_state, side) category:

        "CRACKING_YES": P(we win | belief was CRACKING and we bet YES)
        "BROKEN_NO":    P(we win | belief was BROKEN and we bet NO)

    After enough outcomes accumulate in a category, Bayesian Kelly kicks
    in and sizes positions based on realized win rate — automatically
    implementing fractional Kelly where the fraction is determined by
    how well our signals actually work.
    """

    def __init__(self, config: Optional[KellyConfig] = None):
        self.config = config or KellyConfig()
        # Category-level posteriors: "CRACKING_YES" → BetaPosterior
        self._category_posteriors: Dict[str, BetaPosterior] = {}
        # Map market_id → (category_key, entry_price, side) for outcome routing
        self._active_trades: Dict[str, Tuple[str, float, str]] = {}

    def _get_category_posterior(self, category: str) -> BetaPosterior:
        if category not in self._category_posteriors:
            self._category_posteriors[category] = BetaPosterior(2.0, 2.0)
        return self._category_posteriors[category]

    def size_position(
        self,
        market_id: str,
        p_estimate: float,
        market_price: float,
        bankroll: float,
        belief_state: str = "STABLE",
    ) -> Dict:
        """
        Compute position size for a market.

        Uses plug-in Kelly by default. If the relevant category posterior
        has enough outcome data, switches to Bayesian Kelly which
        naturally adjusts fraction based on realized accuracy.
        """
        # Determine side and edge from plug-in p_estimate
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
                "growth_rate": 0.0, "reason": "insufficient_edge",
            }

        # Category posterior (e.g., "CRACKING_YES")
        category = _category_key(belief_state, side)
        posterior = self._get_category_posterior(category)
        has_enough_data = (posterior.n_observations - 4) >= self.config.min_outcomes_for_bayesian

        if has_enough_data:
            # Bayesian Kelly: use category win rate as P(win)
            # This naturally implements fractional Kelly — if our win rate
            # is only 55%, the Bayesian integral will give a smaller fraction
            # than plug-in Kelly with a 3% edge
            fraction, growth = compute_bayesian_kelly(posterior, market_price, side)
            confidence = posterior.prob_above(market_price) if side == "YES" else (
                1.0 - posterior.prob_above(market_price)
            )
            used_bayesian = True
        else:
            # Plug-in Kelly with fractional multiplier
            fraction = compute_kelly_fraction(p_estimate, market_price, side)
            growth = edge ** 2 / (2 * max(p_estimate * (1 - p_estimate), 0.01))
            # Confidence from edge magnitude
            confidence = 0.5 + min(abs(edge) / 0.10, 0.45)
            used_bayesian = False

        if confidence < self.config.min_confidence:
            return {
                "side": side, "fraction": 0.0, "size_usd": 0.0,
                "edge": edge, "confidence": confidence,
                "growth_rate": 0.0, "reason": "low_confidence",
            }

        # Apply multiplier and cap
        fraction *= self.config.kelly_multiplier
        fraction = min(fraction, self.config.max_fraction)
        size_usd = fraction * bankroll

        # Register trade for outcome routing
        self._active_trades[market_id] = (category, market_price, side)

        return {
            "side": side,
            "fraction": fraction,
            "size_usd": size_usd,
            "edge": edge,
            "confidence": confidence,
            "growth_rate": growth,
            "p_estimate": p_estimate,
            "market_price": market_price,
            "used_bayesian": used_bayesian,
            "category": category,
            "category_win_rate": posterior.mean,
            "category_n": posterior.n_observations - 4,  # Subtract prior
        }

    def update_outcome(self, market_id: str, outcome: int):
        """
        Update category posterior with market resolution.

        Routes the outcome to the correct (belief_state, side) category
        so it accumulates across all markets that triggered under the
        same conditions.
        """
        trade_info = self._active_trades.pop(market_id, None)
        if trade_info is None:
            return

        category, entry_price, side = trade_info

        # Did we win? (outcome=1 means YES won)
        if side == "YES":
            won = 1 if outcome == 1 else 0
        else:
            won = 1 if outcome == 0 else 0

        posterior = self._get_category_posterior(category)
        posterior.update(won)

        logger.info(
            f"Kelly category update: {category} "
            f"{'WIN' if won else 'LOSS'} "
            f"(win_rate={posterior.mean:.1%}, "
            f"n={posterior.n_observations - 4:.0f})"
        )

    def get_category_stats(self) -> Dict[str, dict]:
        """Get performance stats for all categories."""
        result = {}
        for category, posterior in self._category_posteriors.items():
            n = posterior.n_observations - 4  # Subtract prior
            if n > 0:
                result[category] = {
                    "win_rate": posterior.mean,
                    "n_trades": n,
                    "std": posterior.std,
                    "credible_90": posterior.credible_interval(0.9),
                }
        return result


def multi_market_kelly(
    edges: List[float],
    market_prices: List[float],
    kelly_fraction: float = 0.25,
) -> np.ndarray:
    """Multi-market Kelly (independent approximation)."""
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
