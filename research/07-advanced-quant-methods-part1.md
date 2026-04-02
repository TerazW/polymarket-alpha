# Advanced Quantitative Methods for Prediction Markets — Part 1

## 1. Kelly Criterion Extensions

### Binary Kelly (Kelly 1956)

For a binary bet with win probability p, buying at price c that pays $1:

$$f^* = \frac{p - c}{1 - c}$$

This is the fraction of bankroll to risk.

### Multi-Outcome Simultaneous Kelly

For n correlated binary markets, maximize:

$$G(\mathbf{f}) = \sum_{j=1}^{2^n} \pi_j \log\left(1 + \sum_{i=1}^{n} f_i \, r_i(\omega_j)\right)$$

where π_j are joint outcome probabilities (from copula model) and r_i(ω_j) is the return of market i in state j.

Concave optimization solvable via SQP. Key difficulty: specifying the joint distribution over outcome combinations.

### Robust Kelly Under Parameter Uncertainty

**Fractional Kelly** (Thorp 2006): Bet λf* where λ ∈ (0.25, 0.5]. MacLean, Thorp & Ziemba (2011): for typical estimation uncertainty, λ ≈ 0.25 is near-optimal in minimax regret sense.

**Bayesian Kelly**: Prior p ~ Beta(α, β), maximize:

$$E_p[G(f)] = \int_0^1 [p \log(1 + fb) + (1-p)\log(1-f)] \cdot \text{Beta}(p;\alpha,\beta) \, dp$$

Naturally produces smaller bet than plug-in Kelly.

**Growth-Optimality Connection**: Kelly maximizes asymptotic growth rate G = lim_{n→∞} (1/n)log W_n a.s. (Breiman 1961). Equivalent to maximizing expected log utility.

```python
import numpy as np
from scipy.optimize import minimize

def multi_kelly(probs_matrix, prices, lam=0.5):
    """
    probs_matrix: (num_states, num_markets+1) - last col = state probabilities
    prices: market prices (cost of YES contract)
    """
    state_probs = probs_matrix[:, -1]
    outcomes = probs_matrix[:, :-1]
    n_markets = outcomes.shape[1]
    returns = np.where(outcomes == 1, (1 - prices) / prices, -1.0)
    
    def neg_growth(f):
        wealth_changes = 1.0 + returns @ f
        wealth_changes = np.maximum(wealth_changes, 1e-10)
        return -state_probs @ np.log(wealth_changes)
    
    bounds = [(-1, 1)] * n_markets
    result = minimize(neg_growth, np.zeros(n_markets), bounds=bounds)
    return lam * result.x
```

---

## 2. Gaussian Process Regression for Price Prediction

### Framework

GP: f(x) ~ GP(m(x), k(x, x')). Given observations y = f(X) + ε with ε ~ N(0, σ_n²):

$$\mu_* = \mathbf{k}_*^\top (\mathbf{K} + \sigma_n^2 \mathbf{I})^{-1} \mathbf{y}$$

$$\sigma_*^2 = k(\mathbf{x}_*, \mathbf{x}_*) - \mathbf{k}_*^\top (\mathbf{K} + \sigma_n^2 \mathbf{I})^{-1} \mathbf{k}_*$$

### Kernel Selection for Market Time Series

- **Matérn-3/2**: k(r) = σ²(1 + √3r/ℓ)exp(-√3r/ℓ). Less smooth than RBF; better for rough financial paths (Roberts et al. 2013).
- **Periodic × RBF**: k(x,x') = σ² exp(-2sin²(π|x-x'|/T)/ℓ_p²) exp(-|x-x'|²/2ℓ²) for decaying periodicity.
- **Spectral Mixture** (Wilson & Adams 2013): k(τ) = Σ_q w_q exp(-2π²τ²v_q)cos(2πτμ_q). Auto-discovers frequency components.

### Sparse/Online GP Updates

Naive GP is O(n³). For streaming data:
- **FITC** (Snelson & Ghahramani 2006): m inducing points → O(nm²)
- **Online updates**: Incremental Cholesky update in O(m²)

### Prediction Market Application

GP variance σ²_* quantifies uncertainty → integrate with Kelly sizing: high confidence → larger fraction.

```python
import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel

def gp_price_forecast(timestamps, prices, horizon_minutes=30):
    X = np.array(timestamps).reshape(-1, 1)
    y = np.array(prices)
    
    kernel = Matern(length_scale=60, nu=1.5) + WhiteKernel(noise_level=1e-4)
    gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=5)
    gp.fit(X, y)
    
    X_future = np.array([timestamps[-1] + i * 60 
                         for i in range(1, horizon_minutes + 1)]).reshape(-1, 1)
    mu, sigma = gp.predict(X_future, return_std=True)
    
    p_est = np.clip(mu[-1], 0.01, 0.99)
    return {
        'predicted_prices': mu,
        'uncertainty': sigma,
        'p_estimate': p_est,
        'confidence': 1.0 / (1.0 + sigma[-1])
    }
```

---

## 3. Reinforcement Learning for Trading

### MDP Formulation

- **State** s_t: feature vector (price history, OFI, volume, volatility, time to resolution)
- **Action** a_t ∈ {-1, 0, +1} or continuous a_t ∈ [-1, 1]
- **Reward**: Differential Sharpe (Moody & Saffell 2001):

$$r_t = \frac{\Delta W_t}{\sigma_{\Delta W}}$$

### Algorithm Choice

| Algorithm | Strengths | Application |
|-----------|-----------|-------------|
| DQN | Discrete actions, stable | Execution (buy/sell/hold) |
| PPO | Continuous, robust | Portfolio sizing |
| SAC | Entropy-regularized | Multi-modal strategies |

Key papers:
- Jiang, Xu & Liang (2017): EIIE topology with CNN/LSTM for crypto portfolio management
- Deng, Bao, Kong et al. (2017): Deep direct RL for financial signal representation

### Why RL Is Hard for Trading

1. **Non-stationarity**: Market dynamics shift; policies fail across regimes
2. **Sample efficiency**: 5 years daily = ~1250 points (vs millions in Atari)
3. **Overfitting**: Agents memorize historical trajectories
4. **Partial observability**: Other participants' beliefs/inventory hidden
5. **Transaction costs**: Ignored in training, destroy strategies in practice

For prediction markets: each market resolves once (no ergodic repetition). RL better for execution than event probability estimation.

---

## 4. Copula Models for Dependent Prediction Markets

### Sklar's Theorem (1959)

Any joint CDF H(x_1,...,x_d) = C(F_1(x_1),...,F_d(x_d)) where C is the copula.

### Key Copula Families

**Gaussian**: C(u_1,...,u_d) = Φ_Σ(Φ⁻¹(u_1),...,Φ⁻¹(u_d))
- Symmetric dependence, no tail dependence (λ_U = λ_L = 0)

**Clayton**: C(u,v) = (u^{-θ} + v^{-θ} - 1)^{-1/θ}
- Lower tail dependence λ_L = 2^{-1/θ} > 0
- Models joint downside events (correlated political outcomes collapsing)

**Frank**: C(u,v) = -(1/θ)log(1 + (e^{-θu}-1)(e^{-θv}-1)/(e^{-θ}-1))
- Symmetric, no tail dependence

### Vine Copulas (Bedford & Cooke 2002)

For d > 3: decompose d-dimensional copula into C(d,2) bivariate copulas in vine structure. Each pair can use different family.

### Application: Arbitrage Detection

```python
from scipy.stats import norm
import numpy as np

def gaussian_copula_joint_prob(marginal_probs, correlation_matrix, n_sim=100000):
    """Joint outcome probability for correlated binary markets."""
    d = len(marginal_probs)
    thresholds = [norm.ppf(1 - p) for p in marginal_probs]
    
    L = np.linalg.cholesky(correlation_matrix)
    Z = L @ np.random.randn(d, n_sim)
    outcomes = Z < np.array(thresholds).reshape(-1, 1)
    
    joint_prob = np.mean(np.all(outcomes, axis=0))
    
    # All possible outcome states
    all_states = np.array(np.meshgrid(*[[0,1]]*d)).T.reshape(-1, d)
    state_probs = []
    for state in all_states:
        match = np.all(outcomes.T == state, axis=1)
        state_probs.append(np.mean(match))
    
    return joint_prob, all_states, np.array(state_probs)
```

If parlay market priced at c_parlay but copula gives P(joint) ≠ c_parlay → mispricing.

---

## 5. Information Theory in Trading

### Mutual Information: Order Flow → Price

$$I(X; Y) = \int\!\!\int p(x,y) \log\frac{p(x,y)}{p(x)p(y)} \, dx \, dy$$

Estimated via KSG estimator (Kraskov, Stögbauer & Grassberger 2004). High MI = predictive signal in order flow.

### Transfer Entropy for Lead-Lag (Schreiber 2000)

$$T_{X \to Y} = \sum p(y_{t+1}, y_t^{(k)}, x_t^{(l)}) \log \frac{p(y_{t+1} | y_t^{(k)}, x_t^{(l)})}{p(y_{t+1} | y_t^{(k)})}$$

Asymmetry T_{X→Y} - T_{Y→X} > 0 implies X leads Y. Use to find which prediction market incorporates information first.

### Entropy Rate and Efficiency

h = lim_{n→∞} H(X_n | X_{n-1},...,X_1)

- Low h: predictable prices → alpha opportunities
- h ≈ H(X): near-IID → informationally efficient

### KL Divergence for Regime Detection

$$D_{KL}(P \| Q) = \sum_x P(x) \log\frac{P(x)}{Q(x)}$$

Rolling KL divergence between current return distribution and reference. Spike → regime change.

### The Kelly-Information Connection (Kelly 1956, Cover & Thomas 2006)

$$G^* = D_{KL}(\mathbf{p} \| \mathbf{b})$$

Growth rate of Kelly bettor = KL divergence between beliefs p and market prices b.

Binary case: G* = p log(p/c) + (1-p)log((1-p)/(1-c))

**Unified framework**: Information theory quantifies opportunity, GP/copula models estimate edge, Kelly sizing converts edge to optimal bet.

---

## Key References

- Kelly (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*, 35(4), 917-926.
- Breiman (1961). "Optimal Gambling Systems for Favorable Games." *Fourth Berkeley Symposium*.
- Thorp (2006). "The Kelly Criterion in Blackjack, Sports Betting and the Stock Market."
- MacLean, Thorp & Ziemba (2011). *The Kelly Capital Growth Investment Criterion*. World Scientific.
- Cover & Thomas (2006). *Elements of Information Theory*, 2nd ed. Wiley.
- Roberts et al. (2013). "Gaussian Processes for Time-Series Modelling." *Phil. Trans. R. Soc. A*.
- Wilson & Adams (2013). "GP Kernels for Pattern Discovery and Extrapolation." *ICML*.
- Snelson & Ghahramani (2006). "Sparse Gaussian Processes using Pseudo-inputs." *NIPS*.
- Deng et al. (2017). "Deep Direct RL for Financial Signal Representation." *IEEE Trans. Neural Networks*.
- Jiang, Xu & Liang (2017). "A Deep RL Framework for Financial Portfolio Management."
- Moody & Saffell (2001). "Learning to Trade via Direct Reinforcement." *IEEE Trans. Neural Networks*.
- Schreiber (2000). "Measuring Information Transfer." *Physical Review Letters*.
- Kraskov, Stögbauer & Grassberger (2004). "Estimating Mutual Information." *Physical Review E*.
- Bedford & Cooke (2002). "Vines — A New Graphical Model." *Annals of Statistics*.
- Sklar (1959). "Fonctions de répartition à n dimensions et leurs marges."
