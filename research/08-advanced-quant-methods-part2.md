# Advanced Quantitative Methods for Prediction Markets — Part 2

---

## 1. Optimal Stopping Theory for Trading

### American Option Analogy

A prediction market position paying $1 if event E occurs (price p_t ∈ [0,1]) is analogous to an American binary option:

$$V(p, t) = \sup_{\tau \geq t} \mathbb{E}\left[e^{-r(\tau - t)} g(p_\tau) \mid p_t = p\right]$$

### Dynamic Programming Formulation

$$V_t(p) = \max\left\{g(p),\; \beta \cdot \mathbb{E}[V_{t+1}(p_{t+1}) \mid p_t = p]\right\}$$

**Continuation region**: C = {(p,t) : V_t(p) > g(p)}

For a long position bought at cost c, the free-boundary problem:

$$\frac{\partial V}{\partial t} + \frac{1}{2}\sigma^2 p(1-p)\frac{\partial^2 V}{\partial p^2} + \kappa(\theta - p)\frac{\partial V}{\partial p} - rV = 0 \quad \text{in } \mathcal{C}$$

with smooth-pasting: V(p*) = g(p*) and V'(p*) = g'(p*).

### Shiryaev's Quickest Detection Problem (1963)

Find stopping time τ minimizing Bayes risk:

$$\inf_\tau \left\{P(\tau < \theta) + c\,\mathbb{E}[(\tau - \theta)^+]\right\}$$

Optimal policy: **threshold rule on posterior probability** π_t = P(θ ≤ t | F_t). Stop when π_t ≥ A where A = A(c).

**Connection to BOCPD**: Adams & MacKay (2007) run-length posterior is functionally equivalent to Shiryaev's posterior. P(r_t = 0 | data) maps directly to the "change has occurred" probability.

### Practical Implementation

```python
import numpy as np

def optimal_stop_threshold(pi_t, cost_per_period, false_alarm_cost):
    """Shiryaev-style threshold: exit when regime-change posterior exceeds A."""
    A = 1.0 / (1.0 + cost_per_period / false_alarm_cost)
    return pi_t >= A

def dp_optimal_exit(prices, model, gamma=0.99, cost=0.0):
    """Backward induction for finite-horizon optimal stopping."""
    T = len(prices)
    V = np.zeros(T + 1)
    policy = np.zeros(T, dtype=bool)
    V[T] = prices[-1] - cost
    for t in range(T - 1, -1, -1):
        exercise = prices[t] - cost
        continuation = gamma * model.expected_value(V[t + 1], prices[t])
        policy[t] = exercise >= continuation
        V[t] = max(exercise, continuation)
    return V[0], policy
```

**References**: Shiryaev (1963) *Soviet Math. Doklady*; Peskir & Shiryaev (2006) *Optimal Stopping and Free-Boundary Problems*, Birkhäuser.

---

## 2. Stochastic Calculus for Prediction Markets

### Jacobi (Wright-Fisher) Diffusion

Standard GBM is inappropriate for [0,1]-bounded prices. The Jacobi diffusion:

$$dX_t = \kappa(\theta - X_t)\,dt + \sigma\sqrt{X_t(1 - X_t)}\,dW_t$$

Volatility σ√(x(1-x)) vanishes at boundaries, preventing escape from [0,1].

**Stationary distribution**: Beta(α, β) with α = 2κθ/σ² and β = 2κ(1-θ)/σ².

### Itô's Lemma on Logit Transform

Define Y_t = log(X_t/(1-X_t)) (logit). With f'(x) = 1/(x(1-x)) and f''(x) = (2x-1)/(x²(1-x)²):

$$dY_t = \left[\frac{\kappa(\theta - X_t)}{X_t(1-X_t)} + \frac{\sigma^2(2X_t - 1)}{2}\right]dt + \sigma\,dW_t$$

**Key insight**: Diffusion coefficient becomes **constant σ** in logit space. This simplifies estimation and simulation enormously.

### Stochastic Volatility (Heston-type for [0,1])

$$dX_t = \kappa(\theta - X_t)\,dt + \sqrt{v_t}\sqrt{X_t(1-X_t)}\,dW_t^{(1)}$$
$$dv_t = \kappa_v(\bar{v} - v_t)\,dt + \sigma_v\sqrt{v_t}\,dW_t^{(2)}$$

with Corr(dW^(1), dW^(2)) = ρ. Captures volatility spikes around news events.

### Ornstein-Uhlenbeck for Spread Trading

For spread S_t = p_t^(1) - p_t^(2) between correlated markets:

$$dS_t = \kappa(\mu - S_t)\,dt + \sigma\,dW_t$$

Half-life: h = ln(2)/κ.

### Girsanov Theorem

Under physical measure P: dX_t = μ(X_t)dt + σ(X_t)dW_t^P. Market price of risk: λ_t = (μ(X_t) - r·X_t)/σ(X_t).

Under risk-neutral measure Q:

$$dW_t^{\mathbb{Q}} = dW_t^{\mathbb{P}} + \lambda_t\,dt$$

$$\frac{d\mathbb{Q}}{d\mathbb{P}} = \exp\left(-\int_0^T \lambda_t\,dW_t^{\mathbb{P}} - \frac{1}{2}\int_0^T \lambda_t^2\,dt\right)$$

Fair price: p_t = E^Q[e^{-r(T-t)} 1_E | F_t].

### Fokker-Planck Equation

Transition density of Jacobi diffusion:

$$\frac{\partial f}{\partial t} = -\frac{\partial}{\partial x}[\kappa(\theta - x)f] + \frac{\sigma^2}{2}\frac{\partial^2}{\partial x^2}[x(1-x)f]$$

Governs price density evolution. Solve numerically for option prices, hitting probabilities, expected first-passage times.

**References**: Karlin & Taylor (1981) *A Second Course in Stochastic Processes*; Delbaen & Shirakawa (2002); Forman & Sørensen (2008) *"The Pearson Diffusions"*, Scand. J. Stat.

---

## 3. Ensemble Methods and Model Combination

### Bayesian Model Averaging (BMA)

Given K models producing predictive distributions:

$$p(y_{t+1} \mid \mathcal{D}_t) = \sum_{k=1}^K w_k^{(t)}\, p_k(y_{t+1} \mid \mathcal{D}_t)$$

Posterior weights update via Bayes:

$$w_k^{(t)} \propto w_k^{(t-1)} \cdot p_k(y_t \mid \mathcal{D}_{t-1})$$

For combining HMM (regime), Hawkes (clustering), BOCPD (changepoints): each provides likelihood p_k(y_t | ·).

### Exponential Weights Algorithm (Vovk 1990, Littlestone & Warmuth 1994)

$$w_k^{(t+1)} = w_k^{(t)} \cdot e^{-\eta \ell_k^{(t)}}$$

**Regret bound**:

$$\sum_{t=1}^T \ell_{\text{alg}}^{(t)} - \min_k \sum_{t=1}^T \ell_k^{(t)} \leq \frac{\ln K}{\eta} + \frac{\eta T}{8}$$

Optimal η = √(8 ln K / T) gives regret O(√(T ln K)).

For non-stationary markets: **Fixed Share** (Herbster & Warmuth 1998) mixes in uniform component at each step.

### Implementation

```python
import numpy as np

class ExponentialWeightsEnsemble:
    """Prediction with expert advice (Vovk/Littlestone-Warmuth)."""
    def __init__(self, n_experts, eta=0.1):
        self.weights = np.ones(n_experts) / n_experts
        self.eta = eta

    def predict(self, expert_predictions):
        return self.weights @ expert_predictions

    def update(self, expert_predictions, outcome):
        losses = -outcome * np.log(expert_predictions + 1e-10) \
                 - (1 - outcome) * np.log(1 - expert_predictions + 1e-10)
        self.weights *= np.exp(-self.eta * losses)
        self.weights /= self.weights.sum()

    def fixed_share_update(self, expert_predictions, outcome, alpha=0.01):
        """Fixed Share for non-stationary environments."""
        self.update(expert_predictions, outcome)
        self.weights = (1 - alpha) * self.weights + alpha / len(self.weights)
```

**References**: Vovk (1990) *"Aggregating strategies"*, COLT; Cesa-Bianchi & Lugosi (2006) *Prediction, Learning, and Games*, Cambridge; Herbster & Warmuth (1998) *"Tracking the best expert"*.

---

## 4. Market Microstructure Empirical Methods

### Roll (1984) Implied Spread

$$\text{Cov}(\Delta p_t, \Delta p_{t-1}) = -\frac{s^2}{4}$$

$$\hat{s} = 2\sqrt{-\text{Cov}(\Delta p_t, \Delta p_{t-1})}$$

When covariance is positive (momentum), set ŝ = 0.

**Prediction market adaptation**: Use mid-quote changes from order book rather than trade prices.

### Amihud (2002) Illiquidity Ratio

$$\text{ILLIQ}_t = \frac{|r_t|}{V_t}$$

Higher values = larger price impact per unit volume.

**Adaptation**: Use hourly or per-trade ILLIQ for thin prediction markets.

### Corwin-Schultz (2012) High-Low Spread Estimator

$$\hat{s} = \frac{2(e^\alpha - 1)}{1 + e^\alpha}$$

where:

$$\alpha = \frac{\sqrt{2\beta} - \sqrt{\beta}}{3 - 2\sqrt{2}} - \sqrt{\frac{\gamma}{3 - 2\sqrt{2}}}$$

$$\beta = \sum_{j=0}^{1}\left[\ln\frac{H_{t+j}}{L_{t+j}}\right]^2, \quad \gamma = \left[\ln\frac{H_{t,t+1}}{L_{t,t+1}}\right]^2$$

**Adaptation**: Use high-low of mid-quote, shorter windows (hourly).

### Hasbrouck (2009) Information Share

For price discovery across correlated markets:

$$\text{IS}_j = \frac{(\mathbf{a}'\boldsymbol{\Psi}_j)^2 \sigma_j^2}{\mathbf{a}'\boldsymbol{\Omega}\mathbf{a}}$$

Quantifies which market leads price discovery.

### Implementation

```python
import numpy as np

def roll_spread(price_changes):
    cov = np.cov(price_changes[1:], price_changes[:-1])[0, 1]
    return 2 * np.sqrt(max(-cov, 0))

def amihud_illiq(returns, volumes):
    return np.mean(np.abs(returns) / (volumes + 1e-10))

def corwin_schultz_spread(highs, lows):
    """Two-period high-low spread estimator."""
    beta = np.log(highs[:-1]/lows[:-1])**2 + np.log(highs[1:]/lows[1:])**2
    gamma = np.log(np.maximum(highs[:-1], highs[1:]) /
                   np.minimum(lows[:-1], lows[1:]))**2
    alpha = (np.sqrt(2*beta) - np.sqrt(beta)) / (3 - 2*np.sqrt(2)) \
            - np.sqrt(gamma / (3 - 2*np.sqrt(2)))
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return np.clip(spread, 0, None)
```

**References**: Roll (1984) *J. Finance*; Amihud (2002) *J. Financial Markets*; Hasbrouck (2009) *J. Finance*; Corwin & Schultz (2012) *J. Finance*.

---

## 5. Bayesian Methods Beyond BOCPD

### Thompson Sampling for Market Making

Model true probability as π ~ Beta(α, β). At each round:
1. Sample π̃ ~ Beta(α, β)
2. Set quotes: bid = π̃ - δ, ask = π̃ + δ
3. Observe fill and outcome; update α, β

Achieves asymptotically optimal Bayesian regret O(√(T ln T)) (Agrawal & Goyal, 2012).

### Black-Litterman for Prediction Markets

**Prior**: Market-implied probabilities π_mkt from current prices.

**Views**: Your model's estimates. Express as Pμ = q + ε, ε ~ N(0, Ω).

**Posterior**:

$$\hat{\boldsymbol{\mu}} = [(\tau\boldsymbol{\Sigma})^{-1} + \mathbf{P}'\boldsymbol{\Omega}^{-1}\mathbf{P}]^{-1}[(\tau\boldsymbol{\Sigma})^{-1}\boldsymbol{\pi}_{\text{mkt}} + \mathbf{P}'\boldsymbol{\Omega}^{-1}\mathbf{q}]$$

Elegantly blends your signal with market consensus.

### Bayesian Networks for Event Dependencies

Model conditional event dependencies as DAG. For A = "Fed raises rates", B = "Recession":

P(B|A) ≠ P(B)

Encode CPTs, propagate beliefs via belief propagation or junction tree. Identifies mispricings in conditional markets.

### Probabilistic Programming (PyMC)

```python
import pymc as pm
import numpy as np

def bayesian_prediction_market_model(prices, n_regimes=2):
    """Hierarchical Bayesian model for prediction market inference."""
    with pm.Model() as model:
        p_switch = pm.Beta('p_switch', alpha=1, beta=50)
        kappa = pm.HalfNormal('kappa', sigma=5, shape=n_regimes)
        theta = pm.Beta('theta', alpha=2, beta=2, shape=n_regimes)
        concentration = pm.HalfNormal('concentration', sigma=50, shape=n_regimes)
        regime_weights = pm.Dirichlet('regime_weights', a=np.ones(n_regimes))

        alpha_param = concentration[0] * theta[0]
        beta_param = concentration[0] * (1 - theta[0])
        obs = pm.Beta('obs', alpha=alpha_param, beta=beta_param, observed=prices)

        trace = pm.sample(2000, tune=1000, cores=2)
    return trace
```

### Bayesian Portfolio Optimization

Given posterior π ~ Beta(α, β), the optimal bet maximizes:

$$b^* = \arg\max_b \; \mathbb{E}_\pi\left[\pi \ln(1 + b \cdot g_{\text{win}}) + (1-\pi)\ln(1 + b \cdot g_{\text{lose}})\right]$$

Expectation over posterior naturally yields more conservative bet than point-estimate Kelly — automatically implements "fractional Kelly" with fraction determined by posterior uncertainty.

**References**: Thompson (1933) *Biometrika*; Agrawal & Goyal (2012) *COLT*; Black & Litterman (1992) *Financial Analysts J.*; Salvatier, Wiecki & Fonnesbeck (2016) *"Probabilistic programming in Python using PyMC3"*, PeerJ CS.

---

## Method Synergies

The Jacobi diffusion (§2) provides the generative model; Fokker-Planck solutions feed into the optimal stopping DP (§1); microstructure estimators (§4) calibrate transaction cost parameters; multiple models are combined via exponential weights (§3); and Bayesian methods (§5) propagate uncertainty through to position sizing. Together these form a coherent quantitative stack for prediction market trading.
