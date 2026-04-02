"""
Bayesian Online Changepoint Detection (BOCPD)

Adams & MacKay (2007) "Bayesian Online Changepoint Detection"

Maintains a posterior distribution over run lengths (time since last
changepoint). When P(r_t=0 | data) spikes, a regime change is detected.

Uses Normal-Inverse-Gamma conjugate prior for unknown mean and variance,
producing Student-t predictive distributions.
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class NIGParams:
    """Normal-Inverse-Gamma sufficient statistics."""
    mu: float = 0.0      # prior mean
    kappa: float = 1.0    # pseudo-observations for mean
    alpha: float = 1.0    # shape (alpha > 0)
    beta: float = 0.01    # scale (beta > 0)


def _student_t_log_pdf(x: float, df: float, loc: float, scale: float) -> float:
    """Log PDF of Student-t distribution."""
    from math import lgamma, log, pi
    if scale < 1e-10:
        scale = 1e-10
    if df < 1e-10:
        df = 1e-10
    z = (x - loc) / scale
    return (
        lgamma((df + 1) / 2) - lgamma(df / 2)
        - 0.5 * log(df * pi) - log(scale)
        - (df + 1) / 2 * log(1 + z * z / df)
    )


class BOCPDetector:
    """
    Online changepoint detector using BOCPD with NIG conjugate prior.

    The run length r_t represents time since last changepoint.
    P(r_t = 0 | data) = probability that a changepoint just occurred.
    """

    def __init__(
        self,
        hazard_lambda: float = 200.0,
        prior: Optional[NIGParams] = None,
        max_run_length: int = 500,
        changepoint_threshold: float = 0.3,
    ):
        """
        Args:
            hazard_lambda: Expected run length (1/H where H is constant hazard)
            prior: NIG prior parameters
            max_run_length: Truncate run length distribution beyond this
            changepoint_threshold: P(r_t=0) threshold to signal changepoint
        """
        self.hazard = 1.0 / hazard_lambda
        self.prior = prior or NIGParams()
        self.max_run = max_run_length
        self.threshold = changepoint_threshold

        # Run length distribution (unnormalized log joint)
        # R[i] = log P(r_t = i, x_{1:t})
        self._log_R = np.array([0.0])  # Start with r_0 = 0
        self._run_length_probs = np.array([1.0])

        # Sufficient statistics for each run length hypothesis
        # Each run length maintains its own NIG posterior
        self._mu = np.array([self.prior.mu])
        self._kappa = np.array([self.prior.kappa])
        self._alpha = np.array([self.prior.alpha])
        self._beta = np.array([self.prior.beta])

        self._t = 0
        self._changepoint_prob = 0.0

    def update(self, x: float) -> float:
        """
        Process one observation.

        Returns:
            changepoint_prob: P(r_t = 0 | data), probability of changepoint
        """
        self._t += 1
        n = len(self._mu)

        # 1. Evaluate predictive probabilities under each run length
        # Predictive is Student-t with 2*alpha degrees of freedom
        log_pred = np.zeros(n)
        for i in range(n):
            df = 2.0 * self._alpha[i]
            loc = self._mu[i]
            scale = np.sqrt(self._beta[i] * (self._kappa[i] + 1) / (self._alpha[i] * self._kappa[i]))
            log_pred[i] = _student_t_log_pdf(x, df, loc, scale)

        # 2. Growth probabilities (run length increments)
        log_growth = self._log_R + log_pred + np.log(1 - self.hazard)

        # 3. Changepoint probability (run length resets to 0)
        log_cp_contributions = self._log_R + log_pred + np.log(self.hazard)
        # log-sum-exp
        max_val = np.max(log_cp_contributions)
        log_cp = max_val + np.log(np.sum(np.exp(log_cp_contributions - max_val)))

        # 4. Assemble new run length distribution
        new_log_R = np.empty(min(n + 1, self.max_run + 1))
        new_log_R[0] = log_cp
        new_log_R[1:len(log_growth)+1] = log_growth[:self.max_run]

        # Normalize
        max_val = np.max(new_log_R)
        log_evidence = max_val + np.log(np.sum(np.exp(new_log_R - max_val)))
        new_log_R -= log_evidence

        self._log_R = new_log_R
        self._run_length_probs = np.exp(new_log_R)

        # 5. Update sufficient statistics
        # New changepoint hypothesis gets prior
        new_mu = np.empty(len(new_log_R))
        new_kappa = np.empty(len(new_log_R))
        new_alpha = np.empty(len(new_log_R))
        new_beta = np.empty(len(new_log_R))

        new_mu[0] = self.prior.mu
        new_kappa[0] = self.prior.kappa
        new_alpha[0] = self.prior.alpha
        new_beta[0] = self.prior.beta

        # Existing hypotheses get updated with new observation
        old_n = min(n, self.max_run)
        kappa_new = self._kappa[:old_n] + 1
        new_mu[1:old_n+1] = (self._kappa[:old_n] * self._mu[:old_n] + x) / kappa_new
        new_kappa[1:old_n+1] = kappa_new
        new_alpha[1:old_n+1] = self._alpha[:old_n] + 0.5
        new_beta[1:old_n+1] = (
            self._beta[:old_n]
            + 0.5 * self._kappa[:old_n] * (x - self._mu[:old_n]) ** 2 / kappa_new
        )

        self._mu = new_mu
        self._kappa = new_kappa
        self._alpha = new_alpha
        self._beta = new_beta

        self._changepoint_prob = float(self._run_length_probs[0])
        return self._changepoint_prob

    def get_changepoint_prob(self) -> float:
        """Current changepoint probability."""
        return self._changepoint_prob

    def is_changepoint(self) -> bool:
        """Whether current observation signals a changepoint."""
        return self._changepoint_prob > self.threshold

    def get_expected_run_length(self) -> float:
        """Expected run length (time since last changepoint)."""
        indices = np.arange(len(self._run_length_probs))
        return float(np.sum(indices * self._run_length_probs))

    def get_map_run_length(self) -> int:
        """Most probable run length."""
        return int(np.argmax(self._run_length_probs))

    def get_posterior_mean_var(self) -> Tuple[float, float]:
        """
        Weighted posterior mean and variance across run lengths.
        Useful for estimating current regime parameters.
        """
        probs = self._run_length_probs
        weighted_mu = float(np.sum(probs * self._mu))
        weighted_var = float(np.sum(probs * self._beta / (self._alpha - 0.5 + 1e-10)))
        return weighted_mu, weighted_var
