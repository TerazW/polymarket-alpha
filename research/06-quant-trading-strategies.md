# Quantitative Trading Strategies for Prediction Markets

## A Comprehensive Reference for Binary Outcome CLOB Markets

---

# 1. Market Making on Prediction Markets

## 1.1 Avellaneda-Stoikov (2008) Optimal Market Making Framework

The foundational paper "High-frequency trading in a limit order book" by Avellaneda and Stoikov (2008) formulates market making as a stochastic optimal control problem.

### Model Setup

The midprice S_t follows arithmetic Brownian motion:

$$dS_t = \sigma \, dW_t$$

The market maker holds inventory q_t. They post bid price S_t - δ^b and ask price S_t + δ^a. Order arrivals at bid and ask are Poisson processes:

$$\lambda^a(\delta^a) = A e^{-\kappa \delta^a}, \qquad \lambda^b(\delta^b) = A e^{-\kappa \delta^b}$$

where A is baseline arrival rate and κ controls price sensitivity of order flow.

### Objective Function

Maximize expected CARA utility of terminal wealth:

$$\max_{\delta^a, \delta^b} \; \mathbb{E}\left[ -e^{-\gamma (X_T + q_T S_T)} \right]$$

where γ > 0 is absolute risk aversion.

### Key Results: Reservation Price and Optimal Spread

**Reservation price** (market maker's indifference price):

$$r(t, q) = S_t - q \gamma \sigma^2 (T - t)$$

Shifts linearly with inventory: if long (q > 0), reservation price is below mid (want to sell).

**Optimal spread** around reservation price:

$$\delta^a + \delta^b = \frac{2}{\gamma} \ln\left(1 + \frac{\gamma}{\kappa}\right)$$

Total spread is independent of inventory and time. Increases with risk aversion, decreases with κ.

Optimal quotes:

$$\text{ask} = S_t - q\gamma\sigma^2(T-t) + \frac{1}{\gamma}\ln\left(1+\frac{\gamma}{\kappa}\right)$$

$$\text{bid} = S_t - q\gamma\sigma^2(T-t) - \frac{1}{\gamma}\ln\left(1+\frac{\gamma}{\kappa}\right)$$

## 1.2 Guéant, Lehalle & Fernandez-Tapia (2013) Extensions

"Dealing with the inventory risk: a solution to the market making problem," *Mathematics and Financial Economics*.

### Inventory Penalties and Constraints

Running inventory penalty:

$$\max \; \mathbb{E}\left[ X_T + q_T S_T - \ell(q_T) - \int_0^T \phi \, q_t^2 \, dt \right]$$

### Closed-Form Solutions

$$\delta^{a*}(q) = \frac{1}{\kappa} + \left(\frac{1}{2} + q\right)\sqrt{\frac{\phi}{\kappa} + \frac{\sigma^2 \gamma^2}{4\kappa^2}}$$

$$\delta^{b*}(q) = \frac{1}{\kappa} + \left(\frac{1}{2} - q\right)\sqrt{\frac{\phi}{\kappa} + \frac{\sigma^2 \gamma^2}{4\kappa^2}}$$

When q > 0 (long), δ^a decreases (tighter ask) and δ^b increases (wider bid).

## 1.3 Inventory Risk Management: Quote Skewing

### Volatility-Scaled Skew (from Avellaneda-Stoikov)

$$\alpha = \gamma \sigma^2 (T - t)$$

More aggressive when volatility high, time to expiry long, risk aversion high.

### Practical Skewing for Prediction Markets

```python
def compute_skewed_quotes(mid: float, inventory: int, params: dict) -> tuple:
    gamma = params['gamma']
    sigma = params['sigma']
    T = params['T_remaining']
    base_spread = params['base_spread']
    
    skew = gamma * sigma**2 * T * inventory
    reservation_price = max(0.001, min(0.999, mid - skew))
    half_spread = base_spread / 2
    
    bid = max(0.001, reservation_price - half_spread)
    ask = min(0.999, reservation_price + half_spread)
    
    if bid >= ask:
        center = (bid + ask) / 2
        bid = center - 0.005
        ask = center + 0.005
    
    return bid, ask
```

## 1.4 Adverse Selection: Glosten-Milgrom (1985) Model

"Bid, ask and transaction prices in a specialist market with heterogeneously informed traders," *Journal of Financial Economics*.

### Setup

True value V is V_H or V_L. Prior μ = P(V = V_H). Informed traders (fraction π) know true value. Uninformed traders buy/sell with equal probability.

### Equilibrium Bid and Ask

Using Bayes' rule:

$$\mu_{\text{post-buy}} = \frac{\mu(1+\pi)}{\mu(1+\pi) + (1-\mu)(1-\pi)}$$

$$\mu_{\text{post-sell}} = \frac{\mu(1-\pi)}{\mu(1-\pi) + (1-\mu)(1+\pi)}$$

Spread arises entirely from adverse selection:

$$s = (V_H - V_L) \cdot \frac{2\pi \mu(1-\mu)}{[\mu(1+\pi) + (1-\mu)(1-\pi)][\mu(1-\pi) + (1-\mu)(1+\pi)]}$$

## 1.5 Adapting to Bounded [0, 1] Price Range

### Logit Transform Approach

Model price via latent process in logit space:

$$\ell_t = \ln\frac{p_t}{1-p_t}, \qquad d\ell_t = \sigma_\ell \, dW_t$$

Implied volatility in price space:

$$\sigma_p = \sigma_\ell \cdot p(1-p)$$

### Spread Adjustment Near Boundaries

$$s(p) = s_0 \cdot \frac{p(1-p)}{0.25}$$

### Complementary Token Constraint

$$\text{bid}_{\text{YES}} + \text{ask}_{\text{NO}} \leq 1, \qquad \text{ask}_{\text{YES}} + \text{bid}_{\text{NO}} \geq 1$$

Violation creates arbitrage.

## 1.6 PnL Decomposition

$$\text{effective spread} = \underbrace{(M_{t+\Delta} - M_t) \cdot \text{sign}}_{\text{price impact (adverse selection)}} + \underbrace{(P_{\text{trade}} - M_{t+\Delta}) \cdot \text{sign}}_{\text{realized spread (MM profit)}}$$

```python
def decompose_pnl(trades, midprice_history):
    spread_pnl = 0
    adverse_selection = 0
    
    for ts, side, price, qty in trades:
        mid = get_mid_at_time(ts, midprice_history)
        future_mid = get_mid_at_time(ts + timedelta(seconds=30), midprice_history)
        
        if side == 'sell':
            spread_pnl += (price - mid) * qty
            adverse_selection -= (future_mid - mid) * qty
        else:
            spread_pnl += (mid - price) * qty
            adverse_selection += (future_mid - mid) * qty
    
    return {'spread_capture': spread_pnl, 'adverse_selection': adverse_selection}
```

---

# 2. VPIN (Volume-Synchronized Probability of Informed Trading)

## 2.1 The PIN Model Foundation

Easley, Kiefer, O'Hara, and Paperman (1996). The probability of informed trading:

$$\text{PIN} = \frac{\alpha\mu}{\alpha\mu + 2\varepsilon}$$

where α = probability of information event, μ = informed trader arrival rate, ε = uninformed arrival rate.

## 2.2 VPIN: Real-Time Toxicity (Easley, López de Prado & O'Hara, 2012)

"Flow Toxicity and Liquidity in a High-frequency World," *Review of Financial Studies*.

### Bulk Volume Classification (BVC)

$$V_{\text{buy}} = V_{\text{bar}} \cdot \Phi\left(\frac{\Delta P}{\sigma_{\Delta P}}\right)$$

$$V_{\text{sell}} = V_{\text{bar}} - V_{\text{buy}}$$

### VPIN Computation

$$\text{VPIN} = \frac{\sum_{i=1}^{n} |V^B_{\tau-n+i} - V^S_{\tau-n+i}|}{n \cdot V}$$

### Complete Python Implementation

```python
import numpy as np
from scipy.stats import norm

class VPINCalculator:
    def __init__(self, bucket_volume: float, n_buckets: int = 50):
        self.V = bucket_volume
        self.n = n_buckets
        self.buckets = []
        self.current_bucket_buy = 0.0
        self.current_bucket_sell = 0.0
        self.current_bucket_vol = 0.0
        self.sigma_dp = None
        
    def calibrate_sigma(self, recent_price_changes: list):
        self.sigma_dp = np.std(recent_price_changes)
        if self.sigma_dp < 1e-10:
            self.sigma_dp = 1e-10
    
    def _classify_volume(self, volume: float, price_change: float) -> tuple:
        if self.sigma_dp is None or self.sigma_dp < 1e-10:
            if price_change > 0: return volume, 0
            elif price_change < 0: return 0, volume
            else: return volume / 2, volume / 2
        z = price_change / self.sigma_dp
        buy_pct = norm.cdf(z)
        return volume * buy_pct, volume * (1 - buy_pct)
    
    def update(self, volume: float, price_change: float) -> float | None:
        buy_vol, sell_vol = self._classify_volume(volume, price_change)
        remaining = volume
        vpin = None
        
        while remaining > 0:
            space = self.V - self.current_bucket_vol
            fill = min(remaining, space)
            frac = fill / volume if volume > 0 else 0
            
            self.current_bucket_buy += buy_vol * frac
            self.current_bucket_sell += sell_vol * frac
            self.current_bucket_vol += fill
            remaining -= fill
            
            if self.current_bucket_vol >= self.V - 1e-9:
                self.buckets.append((self.current_bucket_buy, self.current_bucket_sell))
                self.current_bucket_buy = 0.0
                self.current_bucket_sell = 0.0
                self.current_bucket_vol = 0.0
                
                if len(self.buckets) >= self.n:
                    window = self.buckets[-self.n:]
                    imbalance_sum = sum(abs(b - s) for b, s in window)
                    vpin = imbalance_sum / (self.n * self.V)
                    if len(self.buckets) > 2 * self.n:
                        self.buckets = self.buckets[-self.n:]
        
        return vpin
```

### Using VPIN for Market Making

- VPIN ≈ 0: balanced flow → tight spreads
- VPIN 0.3-0.5: moderate toxicity → widen spreads
- VPIN > 0.5: high toxicity → widen aggressively or withdraw

---

# 3. Statistical Arbitrage on Prediction Markets

## 3.1 Cross-Market Arbitrage

For mutually exclusive, exhaustive outcomes: Σ p_i = 1

```python
def check_exhaustive_arbitrage(outcomes: list) -> dict | None:
    total_ask = sum(o['best_ask'] for o in outcomes)
    total_bid = sum(o['best_bid'] for o in outcomes)
    
    if total_ask < 1.0:
        return {'type': 'buy_all', 'profit': 1.0 - total_ask}
    if total_bid > 1.0:
        return {'type': 'sell_all', 'profit': total_bid - 1.0}
    return None
```

## 3.2 YES/NO Complementary Token Arbitrage

$$\text{If } \text{ask}_{\text{YES}} + \text{ask}_{\text{NO}} < 1: \text{ buy both (riskless)}$$
$$\text{If } \text{bid}_{\text{YES}} + \text{bid}_{\text{NO}} > 1: \text{ sell both (riskless)}$$

## 3.3 Mean-Reversion: OU Process in Logit Space

$$d\ell_t = \theta(\bar{\ell} - \ell_t) \, dt + \sigma \, dW_t$$

Half-life: t_{1/2} = ln(2)/θ

```python
from scipy import stats

def estimate_ou_params(prices: np.ndarray, dt: float) -> dict:
    logits = np.log(prices / (1 - prices))
    y = logits[1:]
    x = logits[:-1]
    slope, intercept, r_value, _, _ = stats.linregress(x, y)
    
    if slope >= 1.0 or slope <= 0:
        return {'mean_reverting': False, 'half_life': np.inf}
    
    theta = -np.log(slope) / dt
    mu_logit = intercept / (1 - slope)
    half_life = np.log(2) / theta
    sigma_eq = np.std(y - (intercept + slope * x)) / np.sqrt(1 - slope**2)
    z_current = (logits[-1] - mu_logit) / sigma_eq
    
    return {
        'mean_reverting': True, 'theta': theta,
        'mu_price': 1 / (1 + np.exp(-mu_logit)),
        'half_life': half_life, 'z_current': z_current
    }
```

---

# 4. Optimal Execution

## 4.1 Almgren-Chriss (2001) Framework

"Optimal Execution of Portfolio Transactions," *Journal of Risk*.

### Optimal Strategy (Closed-Form)

$$x_k = X \cdot \frac{\sinh[\kappa(T-k\tau)]}{\sinh(\kappa T)}$$

where κ = √(λσ²/(η/τ)), λ = risk aversion, η = temporary impact.

- λ → 0 (risk-neutral): TWAP
- λ → ∞ (risk-averse): immediate execution

### Impact Model for Prediction Markets

Square-root impact with boundary adjustment:

$$\Delta P = c \cdot \text{sign}(Q) \cdot \sqrt{\frac{|Q|}{V}} \cdot p(1-p)$$

---

# 5. Information-Based Trading Models

## 5.1 Kyle (1985) Strategic Trading

"Continuous Auctions and Insider Trading," *Econometrica*.

**Kyle's lambda** (price impact per unit of order flow):

$$\lambda = \frac{1}{2} \cdot \frac{\sqrt{\Sigma_0}}{\sigma_u}$$

Increases with information asymmetry (Σ_0), decreases with noise trading (σ_u).

```python
from sklearn.linear_model import LinearRegression

def estimate_kyle_lambda(price_changes, order_flow_imbalance):
    X = order_flow_imbalance.reshape(-1, 1)
    model = LinearRegression().fit(X, price_changes)
    return {
        'kyle_lambda': model.coef_[0],
        'r_squared': model.score(X, price_changes)
    }
```

## 5.2 Glosten-Milgrom Tracker

```python
class GlostenMilgromTracker:
    def __init__(self, prior: float, pi: float):
        self.mu = prior
        self.pi = pi
    
    def update(self, trade_side: str):
        if trade_side == 'buy':
            p_buy_1 = (1 + self.pi) / 2
            p_buy_0 = (1 - self.pi) / 2
            self.mu = (self.mu * p_buy_1) / (self.mu * p_buy_1 + (1-self.mu) * p_buy_0)
        else:
            p_sell_1 = (1 - self.pi) / 2
            p_sell_0 = (1 + self.pi) / 2
            self.mu = (self.mu * p_sell_1) / (self.mu * p_sell_1 + (1-self.mu) * p_sell_0)
        return self.mu
    
    def get_quotes(self):
        p_buy_1 = (1 + self.pi) / 2
        p_buy_0 = (1 - self.pi) / 2
        ask = (self.mu * p_buy_1) / (self.mu * p_buy_1 + (1-self.mu) * p_buy_0)
        p_sell_1 = (1 - self.pi) / 2
        p_sell_0 = (1 + self.pi) / 2
        bid = (self.mu * p_sell_1) / (self.mu * p_sell_1 + (1-self.mu) * p_sell_0)
        return bid, ask
```

---

# 6. Microstructure Alpha Signals

## 6.1 Order Flow Imbalance (OFI)

Cont, Kukanov, and Stoikov (2014), "The Price Impact of Order Book Events," *Journal of Financial Economics*.

```python
def compute_ofi(book_snapshots: list) -> list:
    ofis = []
    for i in range(1, len(book_snapshots)):
        prev, curr = book_snapshots[i-1], book_snapshots[i]
        
        if curr['bid_price'] > prev['bid_price']:
            bid_contrib = curr['bid_size']
        elif curr['bid_price'] == prev['bid_price']:
            bid_contrib = curr['bid_size'] - prev['bid_size']
        else:
            bid_contrib = -prev['bid_size']
        
        if curr['ask_price'] < prev['ask_price']:
            ask_contrib = -curr['ask_size']
        elif curr['ask_price'] == prev['ask_price']:
            ask_contrib = -(curr['ask_size'] - prev['ask_size'])
        else:
            ask_contrib = prev['ask_size']
        
        ofis.append(bid_contrib + ask_contrib)
    return ofis
```

R² typically 40-65% at short horizons.

## 6.2 Book Pressure Asymmetry

$$\text{DI}_t = \frac{Q_t^b - Q_t^a}{Q_t^b + Q_t^a}$$

Weighted version with exponential decay: w_j = e^{-α·j}

## 6.3 Effective Spread Decomposition

Following Hendershott, Jones, and Menkveld (2011):

$$\text{effective spread} = \text{realized spread (MM profit)} + \text{price impact (adverse selection)}$$

---

# 7. Risk Management for Prediction Market Portfolios

## 7.1 Kelly Criterion for Binary Bets

For a YES bet at market price q with estimated true probability p:

$$f^* = \frac{p - q}{1 - q}$$

For NO bet: f*_NO = (q - p) / q

### Fractional Kelly

$$f_{\text{actual}} = \phi \cdot f^*, \quad \phi \in [0.25, 0.5]$$

**Justification** (MacLean, Thorp, Ziemba 2011): Under parameter uncertainty with estimation error σ_p:

$$f_{\text{optimal}} \approx f^*_{\text{Kelly}} \cdot \left(1 - \frac{\sigma_p^2}{(p - q)^2}\right)$$

### Drawdown Properties

- Full Kelly: P(drawdown ≥ d) ≈ d^{-1}
- Half Kelly: P(drawdown ≥ d) ≈ d^{-2} (much thinner tail)

## 7.2 Multi-Bet Kelly

```python
from scipy.optimize import minimize

def multi_kelly(edges, market_prices, kelly_fraction=0.5):
    n = len(edges)
    p_true = [e + q for e, q in zip(edges, market_prices)]
    
    outcomes = [[(i >> j) & 1 for j in range(n)] for i in range(2**n)]
    probs = []
    for outcome in outcomes:
        prob = 1.0
        for j, o in enumerate(outcome):
            prob *= p_true[j] if o == 1 else (1 - p_true[j])
        probs.append(prob)
    
    def neg_expected_log_wealth(f):
        total = 0
        for k, outcome in enumerate(outcomes):
            ret = sum(
                f[j] * ((1 - market_prices[j]) / market_prices[j] if outcome[j] == 1 else -1)
                if f[j] > 0 else
                abs(f[j]) * (market_prices[j] / (1 - market_prices[j]) if outcome[j] == 0 else -1)
                for j in range(n)
            )
            wealth = 1 + ret
            if wealth <= 0: return 1e10
            total += probs[k] * np.log(wealth)
        return -total
    
    result = minimize(neg_expected_log_wealth, x0=np.zeros(n),
                     bounds=[(-0.3, 0.3)] * n, method='SLSQP')
    return result.x * kelly_fraction
```

## 7.3 Risk Management System

```python
class PredictionMarketRiskManager:
    def __init__(self, bankroll, max_drawdown=0.15, max_single_bet=0.10,
                 max_correlated_exposure=0.30, kelly_fraction=0.25):
        self.bankroll = bankroll
        self.max_drawdown = max_drawdown
        self.max_single_bet = max_single_bet
        self.max_correlated_exposure = max_correlated_exposure
        self.kelly_mult = kelly_fraction
        self.peak_wealth = bankroll
        self.current_wealth = bankroll
        self.positions = {}
    
    def evaluate_trade(self, market_id, side, p_estimate, market_price,
                        correlation_group=None):
        edge = p_estimate - market_price if side == 'YES' else market_price - p_estimate
        if edge <= 0:
            return {'approved': False, 'reason': 'No edge'}
        
        kelly_f = edge / (1 - market_price) if side == 'YES' else edge / market_price
        kelly_size = kelly_f * self.kelly_mult * self.bankroll
        
        # Apply limits
        size = min(kelly_size, self.max_single_bet * self.bankroll)
        
        # Drawdown scaling
        drawdown = 1 - self.current_wealth / self.peak_wealth
        if drawdown >= self.max_drawdown:
            return {'approved': False, 'reason': 'Max drawdown reached'}
        elif drawdown >= self.max_drawdown * 0.5:
            size *= 2 * (1 - drawdown / self.max_drawdown)
        
        if size < 1.0:
            return {'approved': False, 'reason': 'Size too small'}
        
        return {'approved': True, 'size': size, 'edge': edge,
                'kelly_fraction': kelly_f, 'current_drawdown': drawdown}
```

---

# Appendix: Key References

1. **Avellaneda & Stoikov (2008)** — "High-frequency trading in a limit order book." *Quantitative Finance*, 8(3), 217-224.
2. **Guéant, Lehalle & Fernandez-Tapia (2013)** — "Dealing with the inventory risk." *Mathematics and Financial Economics*, 7(4), 477-507.
3. **Glosten & Milgrom (1985)** — "Bid, ask and transaction prices." *Journal of Financial Economics*, 14(1), 71-100.
4. **Easley, López de Prado & O'Hara (2012)** — "Flow Toxicity and Liquidity." *Review of Financial Studies*, 25(5), 1457-1493.
5. **Easley & O'Hara (1987)** — "Price, trade size, and information." *Journal of Financial Economics*, 19(1), 69-90.
6. **Kyle (1985)** — "Continuous Auctions and Insider Trading." *Econometrica*, 53(6), 1315-1335.
7. **Almgren & Chriss (2001)** — "Optimal Execution of Portfolio Transactions." *Journal of Risk*, 3(2), 5-39.
8. **Cont, Kukanov & Stoikov (2014)** — "The Price Impact of Order Book Events." *Journal of Financial Economics*, 104(1), 56-72.
9. **Kelly (1956)** — "A New Interpretation of Information Rate." *Bell System Technical Journal*, 35(4), 917-926.
10. **MacLean, Thorp & Ziemba (2011)** — "The Kelly Capital Growth Investment Criterion." *World Scientific*.
11. **Roll (1984)** — "A Simple Implicit Measure of the Effective Bid-Ask Spread." *Journal of Finance*, 39(4), 1127-1139.
12. **Hendershott, Jones & Menkveld (2011)** — "Does Algorithmic Trading Improve Liquidity?" *Journal of Finance*, 66(1), 1-33.
13. **Andersen & Bondarenko (2014)** — "VPIN and the Flash Crash." *Journal of Financial Markets*, 17, 1-46.

---

# Implementation Priority for Prediction Markets

1. **YES/NO arbitrage** — lowest risk, simplest
2. **Cross-market exhaustive-set arbitrage** — low risk if execution reliable
3. **Market making with inventory management** — moderate risk, needs calibration
4. **VPIN-gated market making** — enhancement to #3
5. **Mean-reversion signals** — requires statistical validation
6. **Kelly-optimized portfolio** — requires reliable edge estimation
7. **Full microstructure alpha** (OFI, book pressure) — highest alpha, hardest
