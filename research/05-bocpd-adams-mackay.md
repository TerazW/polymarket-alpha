# Bayesian Online Changepoint Detection (BOCPD)
## Adams & MacKay (2007) — Framework and Application to Prediction Markets

## 1. BOCPD Mathematical Framework

### Core Idea

The key insight of Adams & MacKay (2007) is to introduce a **run length** variable r_t representing the number of time steps since the last changepoint. At each time step, either the run length grows by 1 (no changepoint) or resets to 0 (changepoint occurred). The algorithm maintains a full posterior distribution over r_t and updates it recursively.

### Run Length Variable

r_t ∈ {0, 1, 2, ..., t} denotes the time since the last changepoint. If r_t = 0, a changepoint just occurred. If r_t = t, no changepoint has ever occurred.

### Recursive Message Passing

The joint distribution P(r_t, x_{1:t}) is updated recursively. Let x_t be the new observation.

**Growth probability** (no changepoint, run length increments):

$$P(r_t = r_{t-1}+1,\, x_{1:t}) = P(r_{t-1},\, x_{1:t-1}) \cdot \pi_t^{(r)} \cdot (1 - H(r_{t-1}+1))$$

**Changepoint probability** (run length resets to 0):

$$P(r_t = 0,\, x_{1:t}) = \sum_{r_{t-1}} P(r_{t-1},\, x_{1:t-1}) \cdot \pi_t^{(r)} \cdot H(r_{t-1}+1)$$

where:
- π_t^(r) = P(x_t | x_{t-r:t-1}) is the **predictive probability** under the run-length-r hypothesis
- H(τ) is the **hazard function**, the prior probability of a changepoint at duration τ

### Hazard Function

Most common choice — **constant hazard**:

$$H(\tau) = \frac{1}{\lambda}$$

where λ is the expected run length (mean time between changepoints). This corresponds to a geometric prior on run lengths (memoryless).

More generally, if the prior on run length is P(r_t = τ) = g(τ) with survival function Ḡ(τ) = Σ_{s=τ}^∞ g(s), then:

$$H(\tau) = \frac{g(\tau)}{\bar{G}(\tau)}$$

### Run Length Posterior

$$P(r_t \mid x_{1:t}) = \frac{P(r_t, x_{1:t})}{\sum_{r_t} P(r_t, x_{1:t})}$$

### Changepoint Detection Signal

A changepoint is signaled when:

$$P(r_t = 0 \mid x_{1:t}) > \text{threshold}$$

### Complete Algorithm (One Time Step)

```
Input: Previous joint P(r_{t-1}, x_{1:t-1}), new observation x_t
1. Evaluate predictive probabilities π_t^(r) for each run length r
2. Compute growth probabilities:
     growth_probs(r) = P(r_{t-1}=r, x_{1:t-1}) · π_t^(r) · (1 - H(r+1))
3. Compute changepoint probability:
     cp_prob = Σ_r P(r_{t-1}=r, x_{1:t-1}) · π_t^(r) · H(r+1)
4. Assemble new joint:
     P(r_t=0, x_{1:t}) = cp_prob
     P(r_t=r+1, x_{1:t}) = growth_probs(r)  for each r
5. Update sufficient statistics for each run length hypothesis
6. Normalize to get P(r_t | x_{1:t})
```

---

## 2. Underlying Predictive Models (UPM)

The predictive probability π_t^(r) comes from a Bayesian predictive distribution using conjugate priors.

### Gaussian with Unknown Mean, Known Variance

Prior: μ ~ N(μ_0, σ_0²), known observation variance σ².

Posterior after n observations:
$$\mu_n = \frac{\sigma^2 \mu_0 + n \sigma_0^2 \bar{x}_n}{\sigma^2 + n\sigma_0^2}, \qquad \sigma_n^2 = \frac{\sigma^2 \sigma_0^2}{\sigma^2 + n\sigma_0^2}$$

Predictive: x_{n+1} ~ N(μ_n, σ² + σ_n²)

### Gaussian with Unknown Mean and Variance (Normal-Inverse-Gamma)

This is the **most practical UPM for financial data**. Conjugate prior:

$$\mu, \sigma^2 \sim \text{NIG}(\mu_0, \kappa_0, \alpha_0, \beta_0)$$

Sufficient statistics update (after observing x):
$$\kappa_n = \kappa_0 + n, \quad \mu_n = \frac{\kappa_0 \mu_0 + n\bar{x}}{\kappa_n}$$
$$\alpha_n = \alpha_0 + \frac{n}{2}, \quad \beta_n = \beta_0 + \frac{1}{2}\sum(x_i - \bar{x})^2 + \frac{\kappa_0 n(\bar{x}-\mu_0)^2}{2\kappa_n}$$

**Predictive distribution** is a Student-t:

$$x_{n+1} \sim t_{2\alpha_n}\!\left(\mu_n,\; \frac{\beta_n(\kappa_n+1)}{\alpha_n \kappa_n}\right)$$

**Incremental update** (adding one observation x to existing stats):
```
κ' = κ + 1
μ' = (κ·μ + x) / κ'
α' = α + 0.5
β' = β + κ·(x - μ)² / (2·κ')
```

Only 4 numbers per run length hypothesis — very memory efficient.

---

## 3. Extensions and Improvements

### Run Length Pruning (Essential for Production)

The run length distribution grows by one element per time step. For long-running systems, truncate at max run length R:

$$P(r_t \geq R) \leftarrow \sum_{r=R}^{t} P(r_t = r)$$

Alternatively, prune entries with P(r_t) < ε. In practice, R = 500–2000 is sufficient.

### Hazard Function Learning

Rather than fixing λ, place a prior on it and update online. Treat λ as a hyperparameter with a Gamma prior and use the marginal likelihood for updates (Wilson et al. 2010).

### Robust BOCPD (Heavy-Tailed)

Replace Gaussian UPM with Student-t observation model. The NIG predictive distribution already yields Student-t predictions, providing natural robustness to outliers.

### Multiple UPMs / Model Selection

Run multiple UPMs in parallel (e.g., one for low-vol regimes, one for high-vol). Joint posterior over (r_t, m_t) where m_t indexes the model.

### Connection to Particle Filtering

BOCPD can be viewed as a Rao-Blackwellized particle filter where each particle represents a run length hypothesis. Enables extensions to non-conjugate models via SMC.

---

## 4. Application to Prediction Markets

### Regime Detection in Prediction Market Prices

Key regime changes include:
- **Drift shifts**: Market moving from stable (≈0.60) to trending (→0.80) after news
- **Volatility shifts**: Quiet periods vs. active trading around events
- **Structural breaks**: When the underlying event's probability genuinely changes

**Important**: Use a **logit transform** y_t = logit(p_t) to map prices to (-∞, ∞) before applying BOCPD with Gaussian UPM, or work with price changes Δp_t.

### Order Flow Changepoints

Model order arrival as a Poisson process. A changepoint in the arrival rate λ signals sudden interest. The conjugate UPM is Gamma-Poisson (predictive: Negative binomial).

### Trading Signal Generation

```
Signal strength = P(r_t = 0 | x_{1:t})  # changepoint posterior

if signal_strength > threshold:
    new_mean = μ_{r=small}  # posterior mean under recent short runs
    old_mean = μ_{r=large}  # posterior mean under long run hypothesis
    
    if new_mean > old_mean:
        action = BUY
    else:
        action = SELL
    
    position_size = f(signal_strength, |new_mean - old_mean|)
```

### Multi-Market Correlation

Run independent BOCPD on correlated markets. When multiple related markets show simultaneous changepoints, signal confidence increases.

---

## 5. Python Implementation

### Core BOCPD Algorithm

```python
import numpy as np
from scipy.stats import t as student_t

class BOCPD:
    """Bayesian Online Changepoint Detection with Normal-Inverse-Gamma UPM."""
    
    def __init__(self, hazard_lambda=200, max_run_length=500,
                 mu0=0.0, kappa0=1.0, alpha0=1.0, beta0=1.0):
        self.hazard = 1.0 / hazard_lambda
        self.R = max_run_length
        
        # NIG prior hyperparameters
        self.mu0 = mu0
        self.kappa0 = kappa0
        self.alpha0 = alpha0
        self.beta0 = beta0
        
        # Run length log-probabilities (initialize with r=0)
        self.log_joint = np.array([0.0])
        
        # Sufficient statistics arrays (one per run length)
        self.kappa = np.array([kappa0])
        self.mu = np.array([mu0])
        self.alpha = np.array([alpha0])
        self.beta = np.array([beta0])
        
        self.t = 0
    
    def _predictive_log_prob(self, x):
        """Student-t predictive log probability for each run length."""
        df = 2.0 * self.alpha
        loc = self.mu
        scale2 = self.beta * (self.kappa + 1.0) / (self.alpha * self.kappa)
        scale = np.sqrt(scale2)
        return student_t.logpdf(x, df=df, loc=loc, scale=scale)
    
    def update(self, x):
        """Process one observation. Returns P(r_t | x_{1:t})."""
        self.t += 1
        
        # Step 1: Predictive probabilities under each run length
        log_pred = self._predictive_log_prob(x)
        
        # Step 2: Growth probabilities
        log_growth = self.log_joint + log_pred + np.log(1.0 - self.hazard)
        
        # Step 3: Changepoint probability
        log_cp_terms = self.log_joint + log_pred + np.log(self.hazard)
        log_cp = np.logaddexp.reduce(log_cp_terms)
        
        # Step 4: Assemble new joint
        new_log_joint = np.empty(min(len(log_growth) + 1, self.R + 1))
        new_log_joint[0] = log_cp
        n = min(len(log_growth), self.R)
        new_log_joint[1:n+1] = log_growth[:n]
        
        # Normalize
        log_evidence = np.logaddexp.reduce(new_log_joint)
        new_log_joint -= log_evidence
        self.log_joint = new_log_joint
        
        # Step 5: Update sufficient statistics
        kappa_new = self.kappa + 1.0
        mu_new = (self.kappa * self.mu + x) / kappa_new
        alpha_new = self.alpha + 0.5
        beta_new = self.beta + self.kappa * (x - self.mu)**2 / (2.0 * kappa_new)
        
        # Prepend prior stats for r_t = 0 (fresh start)
        self.kappa = np.concatenate([[self.kappa0], kappa_new[:self.R]])
        self.mu = np.concatenate([[self.mu0], mu_new[:self.R]])
        self.alpha = np.concatenate([[self.alpha0], alpha_new[:self.R]])
        self.beta = np.concatenate([[self.beta0], beta_new[:self.R]])
        
        return np.exp(self.log_joint)
    
    @property
    def changepoint_prob(self):
        """P(r_t = 0 | data) — probability a changepoint just occurred."""
        return np.exp(self.log_joint[0])
    
    @property
    def map_run_length(self):
        """Most probable current run length."""
        return np.argmax(self.log_joint)
```

### Usage for Prediction Market Data

```python
import numpy as np

def detect_regime_changes(prices, hazard_lambda=200):
    """Run BOCPD on prediction market price series.
    
    Args:
        prices: array of market prices in [0, 1]
        hazard_lambda: expected number of ticks between changepoints
    
    Returns:
        cp_probs: changepoint probability at each time step
        run_posteriors: full run length posterior at each step
    """
    # Transform: logit differences
    log_odds = np.log(prices / (1.0 - prices + 1e-10))
    returns = np.diff(log_odds)
    
    detector = BOCPD(
        hazard_lambda=hazard_lambda,
        max_run_length=500,
        mu0=0.0,
        kappa0=0.1,
        alpha0=2.0,
        beta0=np.var(returns[:20]) if len(returns) > 20 else 0.001
    )
    
    cp_probs = []
    run_posteriors = []
    
    for ret in returns:
        posterior = detector.update(ret)
        cp_probs.append(detector.changepoint_prob)
        run_posteriors.append(posterior.copy())
    
    return np.array(cp_probs), run_posteriors


def generate_signals(prices, cp_probs, threshold=0.3, lookback=10):
    """Generate trading signals from BOCPD output."""
    signals = []
    for i in range(len(cp_probs)):
        if cp_probs[i] > threshold and i >= lookback:
            recent = np.mean(prices[i-lookback//2:i+1])
            prior = np.mean(prices[max(0,i-lookback):i-lookback//2])
            direction = 1 if recent > prior else -1
            signals.append({
                'time': i + 1,
                'direction': direction,
                'confidence': float(cp_probs[i]),
                'price': float(prices[i+1])
            })
    return signals
```

### Streaming Integration Pattern

```python
class BOCPDMonitor:
    """Integration wrapper for real-time market monitoring."""
    
    def __init__(self, market_id, hazard_lambda=200, cp_threshold=0.3):
        self.market_id = market_id
        self.detector = BOCPD(hazard_lambda=hazard_lambda)
        self.threshold = cp_threshold
        self.prev_logit = None
        self.history = []
    
    def on_price_update(self, price, timestamp):
        """Call on each new price tick."""
        logit = np.log(price / (1.0 - price + 1e-10))
        
        if self.prev_logit is not None:
            ret = logit - self.prev_logit
            posterior = self.detector.update(ret)
            cp_prob = self.detector.changepoint_prob
            
            self.history.append({
                'timestamp': timestamp,
                'price': price,
                'cp_prob': cp_prob,
                'map_run_length': self.detector.map_run_length
            })
            
            if cp_prob > self.threshold:
                return {
                    'event': 'changepoint_detected',
                    'market_id': self.market_id,
                    'probability': cp_prob,
                    'timestamp': timestamp,
                    'price': price
                }
        
        self.prev_logit = logit
        return None
```

---

## 6. Key References

1. **Adams & MacKay (2007)** — "Bayesian Online Changepoint Detection." arXiv:0710.3742. The foundational paper introducing run length formulation and recursive message passing.

2. **Fearnhead & Liu (2007)** — "On-line inference for multiple changepoint problems." *JRSS-B*, 69(4):589-605. Efficient particle-based changepoint detection.

3. **Turner, Saatci & Rasmussen (2009)** — "Adaptive sequential Bayesian change point detection." *NIPS Temporal Segmentation Workshop*. Extensions including model selection and hazard rate learning.

4. **Saatci, Turner & Rasmussen (2010)** — "Gaussian Process Change Point Models." *ICML*. BOCPD with GP predictive models for temporal correlation structure changes.

5. **Wilson, Nassar & Gold (2010)** — "Bayesian online learning of the hazard rate in change-point problems." *Neural Computation*. Online learning of the hazard function itself.

6. **Knoblauch & Damoulas (2018)** — "Spatio-temporal Bayesian On-line Changepoint Detection." *ICML*. Multivariate/spatial extensions for multi-market monitoring.

---

## Practical Guidance for Prediction Markets

- **Choosing λ**: For prediction markets with updates every few seconds, λ = 200–500. For daily snapshots, λ = 20–50.
- **Prior calibration**: Set β_0 based on typical return variance. Weakly informative priors (κ_0 = 0.1, α_0 = 2) adapt quickly.
- **Threshold tuning**: 0.3–0.5 balances sensitivity and false positives. Combine with minimum magnitude filter.
- **Computational cost**: O(R) per update where R is max run length. With R = 500, processes millions of ticks per second.
- **Logit transform**: Always transform prediction market prices via logit before applying BOCPD. Raw prices in [0,1] violate Gaussian assumptions near boundaries.
