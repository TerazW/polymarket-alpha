# Hawkes Process for Quantitative Trading on Prediction Markets

## 1. Mathematical Formulation

### Univariate Hawkes Process

The Hawkes process is a self-exciting point process where past events increase the probability of future events. The **conditional intensity function** is:

$$\lambda(t) = \mu + \sum_{t_i < t} \alpha \cdot g(t - t_i)$$

where:
- μ > 0 is the background (exogenous) intensity
- α > 0 is the excitation magnitude
- g(·) is the triggering kernel (non-negative and causal)
- {t_i} are the timestamps of past events

### Exponential Kernel

The most common kernel due to analytical tractability:

$$g(t) = \beta \cdot e^{-\beta t}, \quad t \geq 0$$

This gives the intensity:

$$\lambda(t) = \mu + \alpha \beta \sum_{t_i < t} e^{-\beta(t - t_i)}$$

Key parameters:
- **Branching ratio** n = α/β: expected number of child events per parent. Stationarity requires n < 1.
- **Decay rate** β: controls memory length. Half-life = ln(2)/β.
- The intensity admits a **recursive update**: when a new event occurs at t_k, the intensity jumps by αβ and then decays exponentially:

$$R(t_k) = e^{-\beta(t_k - t_{k-1})} \cdot R(t_{k-1}) + 1$$
$$\lambda(t_k) = \mu + \alpha \beta \cdot R(t_k)$$

This makes real-time computation O(1) per event rather than O(n).

### Power-Law Kernel

For long-memory effects (fat-tailed clustering):

$$g(t) = \frac{c}{(1 + t/\tau_0)^{1+\theta}}, \quad \theta > 0$$

The branching ratio is n = c · τ_0 / θ. Better captures empirically observed slow decay in financial event clustering but loses the O(1) recursive trick.

### Multivariate Hawkes Process

For D event types, the intensity of type d is:

$$\lambda_d(t) = \mu_d + \sum_{d'=1}^{D} \sum_{t_i^{d'} < t} \alpha_{dd'} \cdot g_{dd'}(t - t_i^{d'})$$

The **branching matrix** G has entries G_{dd'} = α_{dd'}/β_{dd'} (for exponential kernels). The **stability condition** requires spectral radius ρ(G) < 1.

For a 2D buy/sell model:

$$\mathbf{G} = \begin{pmatrix} \alpha_{bb}/\beta_{bb} & \alpha_{bs}/\beta_{bs} \\ \alpha_{sb}/\beta_{sb} & \alpha_{ss}/\beta_{ss} \end{pmatrix}$$

- Diagonal entries = self-excitation (momentum)
- Off-diagonal entries = cross-excitation (buy triggers sell = mean-reversion)

The **endogeneity ratio** is n = ρ(G), representing the fraction of all events that are endogenously triggered.

---

## 2. Parameter Estimation

### Maximum Likelihood Estimation

For events {t_1, ..., t_N} on [0, T], the log-likelihood of a point process is:

$$\ell = \sum_{i=1}^{N} \ln \lambda(t_i) - \int_0^T \lambda(t) \, dt$$

For the exponential kernel, the compensator (integral) has a closed form:

$$\int_0^T \lambda(t) \, dt = \mu T + \frac{\alpha}{\beta} \sum_{i=1}^{N} \left(1 - e^{-\beta(T - t_i)}\right)$$

The full log-likelihood:

$$\ell(\mu, \alpha, \beta) = \sum_{i=1}^{N} \ln\!\left(\mu + \alpha\beta \sum_{j < i} e^{-\beta(t_i - t_j)}\right) - \mu T - \alpha \sum_{i=1}^{N}\left(1 - e^{-\beta(T - t_i)}\right)$$

Optimization via L-BFGS-B with constraints μ > 0, α > 0, β > 0, α < β.

### EM Algorithm

Treats each observed event as either an "immigrant" (from μ) or "offspring" (triggered by a prior event). The E-step computes responsibilities:

$$p_{ij} = \frac{\alpha \beta e^{-\beta(t_i - t_j)}}{\lambda(t_i)}, \quad p_{i0} = \frac{\mu}{\lambda(t_i)}$$

The M-step updates:

$$\mu^{new} = \frac{\sum_i p_{i0}}{T}, \quad \alpha^{new} = \frac{\sum_i \sum_{j<i} p_{ij}}{N}, \quad \beta^{new} \text{ via numerical optimization}$$

### Online/Recursive Estimation

For streaming data, stochastic gradient ascent on the log-likelihood:

$$\theta_{k+1} = \theta_k + \eta_k \cdot \nabla_\theta \left[\ln \lambda_\theta(t_k) - \int_{t_{k-1}}^{t_k} \lambda_\theta(s)\,ds\right]$$

With exponential kernels, the gradient can be computed recursively. Essential for real-time prediction market applications.

### Method of Moments

The theoretical mean intensity is λ̄ = μ/(1 - n) and the autocovariance can be expressed in terms of (μ, α, β). Matching empirical moments gives fast initial estimates for MLE.

---

## 3. Application to Order Flow and Market Microstructure

### Trade Arrival Modeling

The framework from **Bacry, Mastromatteo & Muzy (2015)** models buy and sell trades as a bivariate Hawkes process. Key empirical findings:

1. **Self-excitation dominates**: α_{bb} and α_{ss} typically larger than cross terms (order-splitting, momentum)
2. **Near-critical branching**: empirical n ≈ 0.6–0.8, meaning 60-80% of trades are endogenously triggered
3. **Fast decay**: typical β corresponds to half-lives of seconds to minutes

### Hawkes-Based Price Impact

$$dP(t) = \sigma \cdot dN_{buy}(t) - \sigma \cdot dN_{sell}(t) + \text{noise}$$

Transient impact from self-excitation decays, while permanent impact comes from the exogenous (informed) component.

### Filimonov & Sornette (2012) — Reflexivity Index

**Endogeneity ratio** n = 1 - μ/λ̄ as a measure of market reflexivity. When n → 1, the market is dominated by self-referential activity (herding, cascades). Found n increased from ~0.3 to ~0.7 in US equity markets from 1998 to 2012 (attributed to HFT).

### Informed vs. Noise Trading Detection

The EM branching structure classifies each trade:
- **High p_{i0}** (immigrant probability) → likely informed trade
- **High Σ_j p_{ij}** (offspring probability) → likely noise/mechanical

---

## 4. Prediction Market Specific Applications

### Shock Propagation

When a large trade moves the price from 0.50 to 0.65, it triggers:
- Limit order cancellations and re-placements
- Follow-on market orders from momentum traders
- Arbitrage trades against correlated markets

A Hawkes model captures this cascade. The **intensity spike after a large trade** and its decay pattern reveal how quickly the market absorbs information.

### Information Cascades vs. Mechanical Reactions

- **Branching ratio n**: high n during a price move suggests cascade/herding; low n suggests exogenous information flow
- **Decay rate β**: fast decay = mechanical (algo reactions); slow decay = genuine cascade
- **Asymmetry in cross-excitation**: if α_{bs} >> α_{sb}, buys strongly trigger sells (mean-reversion regime)

### Real-Time Activity Signal

$$\text{Activity Signal} = \frac{\lambda(t) - \mu}{\mu} = \frac{\text{endogenous intensity}}{\text{baseline}}$$

Uses:
- A **volatility proxy** for position sizing
- A **regime indicator** (calm vs. excited)
- A **trade timing signal** (avoid trading during high self-excitation to reduce slippage)

### Cross-Market Excitation

For correlated prediction markets, a multivariate Hawkes captures information spillover. The cross-excitation kernel parameters reveal the information transmission speed.

---

## 5. Python Implementation

### Core Implementation with `tick` Library

```python
import numpy as np
from tick.hawkes import (
    HawkesExpKern, SimuHawkesExpKernels, HawkesEM
)

# --- Simulation (Ogata thinning) ---
n_nodes = 2  # buy, sell
adjacency = np.array([
    [0.3, 0.1],   # buy->buy=0.3, sell->buy=0.1
    [0.1, 0.3],   # buy->sell=0.1, sell->sell=0.3
])
decays = np.array([
    [5.0, 5.0],
    [5.0, 5.0],
])
baselines = [0.5, 0.5]

sim = SimuHawkesExpKernels(
    adjacency=adjacency, decays=decays,
    baseline=baselines, end_time=1000, seed=42
)
sim.simulate()
timestamps = sim.timestamps

# --- Fitting via MLE ---
learner = HawkesExpKern(decays=5.0, penalty='none', solver='bfgs')
learner.fit(timestamps)
print("Baseline:", learner.baseline)
print("Adjacency:", learner.adjacency)
print("Branching ratio:", np.max(np.abs(
    np.linalg.eigvals(learner.adjacency / 5.0)
)))

# --- Fitting via EM ---
em = HawkesEM(kernel_size=50, n_realizations=1, max_iter=500)
em.fit(timestamps)
```

### Custom MLE Implementation

```python
import numpy as np
from scipy.optimize import minimize

def hawkes_loglik(params, times, T):
    """Negative log-likelihood for univariate exponential Hawkes."""
    mu, alpha, beta = params
    if mu <= 0 or alpha <= 0 or beta <= 0 or alpha >= beta:
        return 1e10
    
    N = len(times)
    R = 0.0
    ll = 0.0
    for i in range(N):
        if i > 0:
            R = np.exp(-beta * (times[i] - times[i-1])) * (1 + R)
        lam_i = mu + alpha * beta * R
        if lam_i <= 0:
            return 1e10
        ll += np.log(lam_i)
    
    compensator = mu * T + alpha * np.sum(
        1 - np.exp(-beta * (T - times))
    )
    return -(ll - compensator)

def fit_hawkes(times, T):
    """Fit univariate Hawkes to event timestamps."""
    avg_rate = len(times) / T
    x0 = [avg_rate * 0.5, 0.5, 2.0]
    res = minimize(
        hawkes_loglik, x0, args=(times, T),
        method='L-BFGS-B',
        bounds=[(1e-6, None), (1e-6, None), (1e-6, None)]
    )
    mu, alpha, beta = res.x
    return {
        'mu': mu, 'alpha': alpha, 'beta': beta,
        'branching_ratio': alpha / beta,
        'endogeneity': 1 - mu / avg_rate,
        'half_life': np.log(2) / beta
    }
```

### Real-Time Intensity Computation

```python
class HawkesIntensityTracker:
    """O(1) per-event real-time intensity for exponential kernel."""
    
    def __init__(self, mu, alpha, beta):
        self.mu = mu
        self.alpha = alpha
        self.beta = beta
        self.R = 0.0
        self.last_time = None
    
    def update(self, t):
        """Call when a new event arrives at time t."""
        if self.last_time is not None:
            self.R = np.exp(-self.beta * (t - self.last_time)) * (1 + self.R)
        self.last_time = t
        return self.intensity(t)
    
    def intensity(self, t):
        """Compute current intensity at arbitrary time t."""
        if self.last_time is None:
            return self.mu
        decay = np.exp(-self.beta * (t - self.last_time))
        return self.mu + self.alpha * self.beta * (1 + self.R) * decay
    
    def endogeneity_ratio(self, t):
        """Fraction of current intensity from self-excitation."""
        lam = self.intensity(t)
        return 1.0 - self.mu / lam if lam > 0 else 0.0
```

### Ogata Thinning Algorithm (Simulation)

```python
def simulate_hawkes(mu, alpha, beta, T):
    """Simulate univariate Hawkes via Ogata thinning."""
    times = []
    lam_bar = mu
    t = 0
    R = 0.0
    
    while t < T:
        u = np.random.exponential(1.0 / lam_bar)
        t += u
        if t >= T:
            break
        R *= np.exp(-beta * u)
        lam_t = mu + alpha * beta * R
        if np.random.uniform() < lam_t / lam_bar:
            times.append(t)
            R += 1
            lam_bar = lam_t + alpha * beta
        else:
            lam_bar = lam_t
    
    return np.array(times)
```

### Fitting to Prediction Market Data

```python
def prepare_trade_timestamps(trades_df):
    """Convert trade DataFrame to Hawkes input format."""
    trades_df = trades_df.sort_values('timestamp')
    t0 = trades_df['timestamp'].min()
    
    buys = (trades_df[trades_df['side'] == 'buy']['timestamp'] - t0
            ).dt.total_seconds().values
    sells = (trades_df[trades_df['side'] == 'sell']['timestamp'] - t0
             ).dt.total_seconds().values
    T = (trades_df['timestamp'].max() - t0).total_seconds()
    
    return [buys, sells], T

def compute_regime_signal(tracker_buy, tracker_sell, t):
    """Regime signal from bivariate Hawkes. Range [-1, 1]."""
    lam_buy = tracker_buy.intensity(t)
    lam_sell = tracker_sell.intensity(t)
    total = lam_buy + lam_sell
    if total < 1e-10:
        return 0.0
    return (lam_buy - lam_sell) / total
```

---

## 6. Key References

1. **Hawkes (1971)** — "Spectra of some self-exciting and mutually exciting point processes." *Biometrika*, 58(1), 83–90. The original formulation.

2. **Bacry, Mastromatteo & Muzy (2015)** — "Hawkes processes in finance." *Market Microstructure and Liquidity*, 1(01), 1550005. Comprehensive review covering trade modeling, price impact, and lead-lag.

3. **Filimonov & Sornette (2012)** — "Quantifying reflexivity in financial markets." *Physical Review E*, 85(5), 056108. Endogeneity ratio as a reflexivity measure.

4. **Rambaldi, Pennesi & Lillo (2015)** — "Modeling FX market activity as a marked multivariate Hawkes process." *Quantitative Finance*, 15(7), 1137–1156. Extended Hawkes to full order book events.

5. **Daley & Vere-Jones (2003)** — *An Introduction to the Theory of Point Processes*. Springer. Standard mathematical reference.

6. **Ogata (1981)** — "On Lewis' simulation method for point processes." The thinning algorithm.

7. **Hardiman, Bercot & Bouchaud (2013)** — "Critical reflexivity in financial markets: a Hawkes process analysis." *EPJ-B*, 86, 442. Near-critical branching in equity markets.

---

## Summary for Prediction Market Application

1. **Collect trade timestamps** segmented by side (buy/sell) from the CLOB.
2. **Fit a bivariate exponential Hawkes** using MLE or the `tick` library.
3. **Track real-time intensity** using the O(1) recursive tracker, publishing: (a) total activity level, (b) directional imbalance.
4. **Monitor the branching ratio** over rolling windows. Spike toward 1.0 signals cascade/herding where prices may overshoot. Low ratio during a price move suggests genuine information.
5. **Use cross-market Hawkes** for correlated prediction markets to detect information propagation before it's reflected in prices.
