# Hidden Markov Models for Quantitative Trading

## 1. Mathematical Formulation

An HMM is defined by the tuple λ = (A, B, π) over:

- **Hidden states** S = {s_1, s_2, ..., s_N} — e.g., N=3 for bull/bear/sideways regimes
- **Observations** O = {o_1, o_2, ..., o_T} — e.g., daily returns, realized volatility, volume

**Transition matrix** A ∈ ℝ^{N×N}:

$$a_{ij} = P(q_{t+1} = s_j \mid q_t = s_i), \quad \sum_j a_{ij} = 1$$

**Emission (observation) model** B: For continuous financial data, typically Gaussian:

$$b_j(o_t) = P(o_t \mid q_t = s_j) = \mathcal{N}(o_t; \mu_j, \Sigma_j)$$

For multivariate observations (returns + volume + spread), use multivariate Gaussian with mean vector μ_j ∈ ℝ^d and covariance Σ_j ∈ ℝ^{d×d}.

**Initial state distribution** π:

$$\pi_i = P(q_1 = s_i), \quad \sum_i \pi_i = 1$$

The **three canonical problems**:
1. **Evaluation**: P(O | λ) — solved by Forward algorithm
2. **Decoding**: argmax_Q P(Q | O, λ) — solved by Viterbi
3. **Learning**: argmax_λ P(O | λ) — solved by Baum-Welch

---

## 2. Baum-Welch Algorithm (EM for HMMs)

### Forward Variable

$$\alpha_t(i) = P(o_1, o_2, \dots, o_t, q_t = s_i \mid \lambda)$$

**Initialization**: α_1(i) = π_i · b_i(o_1)

**Induction**: α_{t+1}(j) = [Σ_{i=1}^{N} α_t(i) · a_{ij}] · b_j(o_{t+1})

**Termination**: P(O | λ) = Σ_{i=1}^{N} α_T(i)

### Backward Variable

$$\beta_t(i) = P(o_{t+1}, o_{t+2}, \dots, o_T \mid q_t = s_i, \lambda)$$

**Initialization**: β_T(i) = 1

**Induction**: β_t(i) = Σ_{j=1}^{N} a_{ij} · b_j(o_{t+1}) · β_{t+1}(j)

### E-Step: Compute ξ and γ

**Gamma** (posterior state probability):

$$\gamma_t(i) = P(q_t = s_i \mid O, \lambda) = \frac{\alpha_t(i) \cdot \beta_t(i)}{\sum_{j=1}^{N} \alpha_t(j) \cdot \beta_t(j)}$$

**Xi** (posterior transition probability):

$$\xi_t(i, j) = P(q_t = s_i, q_{t+1} = s_j \mid O, \lambda) = \frac{\alpha_t(i) \cdot a_{ij} \cdot b_j(o_{t+1}) \cdot \beta_{t+1}(j)}{\sum_{i}\sum_{j} \alpha_t(i) \cdot a_{ij} \cdot b_j(o_{t+1}) \cdot \beta_{t+1}(j)}$$

### M-Step: Re-estimation

$$\hat{\pi}_i = \gamma_1(i)$$

$$\hat{a}_{ij} = \frac{\sum_{t=1}^{T-1} \xi_t(i,j)}{\sum_{t=1}^{T-1} \gamma_t(i)}$$

For Gaussian emissions:

$$\hat{\mu}_j = \frac{\sum_{t=1}^{T} \gamma_t(j) \cdot o_t}{\sum_{t=1}^{T} \gamma_t(j)}$$

$$\hat{\Sigma}_j = \frac{\sum_{t=1}^{T} \gamma_t(j) \cdot (o_t - \hat{\mu}_j)(o_t - \hat{\mu}_j)^\top}{\sum_{t=1}^{T} \gamma_t(j)}$$

### Scaling Factors (Numerical Stability)

Raw alpha values underflow exponentially. The Rabiner (1989) solution uses scaling coefficients:

$$c_t = \frac{1}{\sum_{i} \hat{\alpha}_t(i)}, \quad \tilde{\alpha}_t(i) = c_t \cdot \hat{\alpha}_t(i)$$

Then log P(O | λ) = -Σ_{t=1}^{T} log c_t. The beta pass uses the same c_t values. An alternative (used in practice) is to work entirely in log-space with the log-sum-exp trick: log(Σ_i exp(x_i)) = x_max + log(Σ_i exp(x_i - x_max)).

---

## 3. Viterbi Algorithm

Finds the single best state sequence Q* = argmax_Q P(Q | O, λ) via dynamic programming.

**In log-space** (standard practice to avoid underflow):

**Initialization**:

$$\delta_1(i) = \log \pi_i + \log b_i(o_1), \quad \psi_1(i) = 0$$

**Recursion** (for t = 2, ..., T):

$$\delta_t(j) = \max_{1 \le i \le N} \left[\delta_{t-1}(i) + \log a_{ij}\right] + \log b_j(o_t)$$

$$\psi_t(j) = \arg\max_{1 \le i \le N} \left[\delta_{t-1}(i) + \log a_{ij}\right]$$

**Termination**:

$$q_T^* = \arg\max_{1 \le i \le N} \delta_T(i)$$

**Backtracking** (for t = T-1, ..., 1):

$$q_t^* = \psi_{t+1}(q_{t+1}^*)$$

Complexity: O(T · N²) time, O(T · N) space.

---

## 4. Application to Financial Regime Detection

### Regime Definitions (typical 2-3 state model)

| State | Interpretation | μ (return) | σ (volatility) |
|-------|---------------|------------|-----------------|
| s_1 | Bull / Risk-on | Positive, moderate | Low |
| s_2 | Bear / Risk-off | Negative | High |
| s_3 | Sideways / Mean-reverting | ~Zero | Medium |

### Observable Features

Typical multivariate observation vector at time t:

$$o_t = [\text{log-return}_t, \; \text{realized\_vol}_t, \; \text{volume\_ratio}_t, \; \text{spread}_t]$$

Where:
- Log-return: r_t = ln(P_t / P_{t-1})
- Realized vol: rolling std of returns (e.g., 5-day)
- Volume ratio: V_t / V̄_{20} (current vs 20-day average)
- Spread: bid-ask spread as a liquidity proxy

### Trading Strategy Pattern

1. Fit HMM on rolling window of historical data
2. At each new observation, compute γ_T(i) — the filtered posterior probability of each regime
3. Adjust portfolio: high P(bull) => long; high P(bear) => hedge/short; high P(sideways) => mean-reversion
4. Use transition matrix to estimate regime persistence: expected duration in state i is 1/(1 - a_{ii})

### Key insight from Hamilton (1989)

Hamilton's seminal paper modeled US GDP growth as a 2-state Markov-switching autoregressive process, showing that recessions and expansions have distinct, persistent dynamics. The transition probabilities capture that regimes are "sticky" — a_{ii} is typically 0.95+ for both bull and bear states, meaning average regime duration of 20+ periods.

---

## 5. Online/Incremental HMM Updating

For streaming financial data, full Baum-Welch re-estimation on the entire history is impractical. Approaches:

### Approach A: Rolling Window
Re-fit the HMM on the most recent W observations (e.g., W=252 for one trading year). Simple but discards long-term structure.

### Approach B: Stochastic/Online EM
Update sufficient statistics incrementally. At time t, after observing o_t:

1. Run forward pass to get α_t(i) (only need previous step, O(N²))
2. Compute filtered state probabilities: γ_t(i) = α_t(i) / Σ_j α_t(j)
3. Update sufficient statistics with exponential decay η:

$$\bar{\mu}_j \leftarrow (1 - \eta \cdot \gamma_t(j)) \cdot \bar{\mu}_j + \eta \cdot \gamma_t(j) \cdot o_t$$

$$\bar{a}_{ij} \leftarrow (1 - \eta) \cdot \bar{a}_{ij} + \eta \cdot \xi_t(i,j)$$

The learning rate η (or equivalently a decay factor) controls adaptation speed. This is derived from the online EM framework of Cappé (2011).

### Approach C: Bayesian HMM with Particle Filtering
Use sequential Monte Carlo to maintain a posterior over both states and parameters. More principled but computationally heavier.

---

## 6. Python Implementation with hmmlearn

```python
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

# --- Data Preparation ---
# Assume df has columns: ['close', 'volume']
df['log_return'] = np.log(df['close'] / df['close'].shift(1))
df['realized_vol'] = df['log_return'].rolling(5).std()
df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
df = df.dropna()

features = ['log_return', 'realized_vol', 'volume_ratio']
X = df[features].values

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# --- Model Fitting ---
n_regimes = 3
model = GaussianHMM(
    n_components=n_regimes,
    covariance_type='full',       # full covariance per state
    n_iter=200,
    tol=1e-4,
    random_state=42,
    init_params='stmc',           # initialize all params
    verbose=False,
)

model.fit(X_scaled)

# --- Regime Decoding ---
# Viterbi (most likely state sequence)
hidden_states = model.predict(X_scaled)

# Filtered probabilities (forward algorithm)
state_probs = model.predict_proba(X_scaled)  # T x N matrix of gamma_t(i)

# Log-likelihood
log_likelihood = model.score(X_scaled)

# --- Inspect Learned Parameters ---
print("Transition matrix A:")
print(model.transmat_.round(3))

print("\nState means (scaled):")
for i in range(n_regimes):
    print(f"  State {i}: mu={model.means_[i].round(3)}, "
          f"expected duration={1/(1-model.transmat_[i,i]):.1f} periods")

# --- Online Filtering for New Data ---
def online_filter(model, new_obs_scaled):
    """
    Get regime probabilities for a single new observation.
    Uses the forward algorithm incrementally.
    """
    probs = model.predict_proba(new_obs_scaled.reshape(1, -1))
    return probs[0]  # shape (n_regimes,)

# --- Trading Signal Generation ---
df['regime'] = hidden_states
df['bull_prob'] = state_probs[:, 0]  # adjust index based on learned ordering

# Identify which state is "bull" by highest mean return
mean_returns = model.means_[:, 0]  # first feature is log_return
bull_state = np.argmax(mean_returns)
bear_state = np.argmin(mean_returns)

df['position'] = 0.0
df.loc[df['regime'] == bull_state, 'position'] = 1.0   # long
df.loc[df['regime'] == bear_state, 'position'] = -0.5  # short/hedge

# Strategy returns
df['strategy_return'] = df['position'].shift(1) * df['log_return']
sharpe = df['strategy_return'].mean() / df['strategy_return'].std() * np.sqrt(252)
print(f"\nStrategy Sharpe Ratio: {sharpe:.2f}")
```

### Model Selection and Validation

```python
# Select number of states via BIC
for n in [2, 3, 4, 5]:
    m = GaussianHMM(n_components=n, covariance_type='full',
                    n_iter=200, random_state=42)
    m.fit(X_scaled)
    bic = -2 * m.score(X_scaled) * len(X_scaled) + \
          n * (n - 1 + 2 * X_scaled.shape[1] + 
               X_scaled.shape[1] * (X_scaled.shape[1] + 1) // 2) * np.log(len(X_scaled))
    print(f"n_states={n}: log_likelihood={m.score(X_scaled)*len(X_scaled):.0f}, BIC={bic:.0f}")

# Walk-forward validation (critical for finance)
train_size = 252  # 1 year
results = []
for t in range(train_size, len(X_scaled) - 1):
    X_train = X_scaled[t - train_size:t]
    model = GaussianHMM(n_components=3, covariance_type='full',
                        n_iter=100, random_state=42)
    model.fit(X_train)
    
    # Predict regime for next period
    probs = model.predict_proba(X_scaled[t:t+1])
    bull_idx = np.argmax(model.means_[:, 0])
    results.append({
        'date': df.index[t],
        'bull_prob': probs[0, bull_idx],
        'next_return': X_scaled[t + 1, 0]
    })
```

### Practical Pitfalls

- **Label switching**: Regime indices are arbitrary across re-fits. Always identify regimes by their learned parameters (mean, variance), not index.
- **Local optima**: Baum-Welch is EM and converges to local maxima. Run multiple random initializations and pick best log-likelihood.
- **Covariance degeneracy**: A state can collapse onto a single point. Use `covariance_type='diag'` or add regularization: `model.min_covar = 1e-3`.
- **Look-ahead bias**: Never use future data for fitting. Always walk-forward.
- **Regime persistence assumption**: HMMs assume geometric regime duration distribution. If real regime durations are more complex, consider Hidden Semi-Markov Models (HSMMs) which model duration explicitly.

---

## 7. Key References

- **Rabiner (1989)** — "A Tutorial on Hidden Markov Models and Selected Applications in Speech Recognition," *Proceedings of the IEEE*, 77(2), 257-286. The foundational tutorial that formalized the forward-backward, Viterbi, and Baum-Welch algorithms with scaling.

- **Hamilton (1989)** — "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle," *Econometrica*, 57(2), 357-384. Introduced regime-switching models to economics/finance.

- **Rydén, Teräsvirta & Åsbrink (1998)** — HMMs for financial returns stylized facts.

- **Bulla & Bulla (2006)** — HSMMs for financial data (explicit duration modeling).

- **Cappé (2011)** — Online EM for HMMs (streaming data adaptation).

---

## 8. Prediction Market Specific Considerations

### Price Bounded [0, 1]
Prediction market prices are bounded between 0 and 1 (representing probabilities). Standard Gaussian HMM assumes unbounded observations. Solutions:
- Use logit-transformed prices: x_t = log(p_t / (1 - p_t))
- Use Beta distribution emissions instead of Gaussian
- Use returns (Δp or log-odds changes) which are approximately unbounded

### Complementary Token Pairs
YES + NO tokens always sum to $1. This creates a natural hedge and means:
- Only need to model one side (YES token)
- Spread between YES ask and (1 - NO bid) reveals market efficiency
- Cross-token arbitrage is a separate signal

### Event-Driven Regime Changes
Unlike equity markets where regimes are gradual, prediction markets can have sudden jumps:
- News events → instant probability updates
- Deadline effects → increasing volatility near resolution
- Consider non-stationary transition probabilities (time-varying A matrix)

### Thin Order Books
Prediction markets typically have much thinner order books than equity markets:
- Volume and spread features are noisier
- Consider using order book depth features rather than just trade-based features
- Tick size changes at extreme prices (near 0 or 1) affect feature computation
