# Polymarket Trading Engine — Development Notes

## Project State (2026-04)

Standalone autonomous trading system for Polymarket prediction markets.
Forked from the belief reaction monitoring system, stripped of visualization
frontend and API layer, focused purely on trading.

## Architecture

```
poc/                    Core belief reaction engine (ShockDetector, ReactionClassifier, BeliefStateMachine)
backend/
├── alpha/              Quantitative signal models (HMM, BOCPD, Hawkes, VPIN, OFI)
├── strategy/           Trading logic (Kelly, risk manager, cost model, calibration, market filter)
├── execution/          Polymarket CLOB client (paper + live)
├── trading/            Orchestrator (main loop, collector bridge, config)
├── backtest/           Backtesting (data loader, engine, walk-forward, market screening)
├── collector/          Real-time WebSocket data collection
├── reactor/            Production wrapper around POC
├── alerting/           Alert generation
└── common/             Shared config, DB utilities
utils/                  Polymarket API + WebSocket clients
research/               Reference documents
tests/                  Unit tests (60 passing)
```

## Decision Flow (6 steps)

```
1. Belief State    → "Is there a dislocation?"   (CRACKING/BROKEN = yes)
2. Risk Gates      → "Is it safe to trade now?"   (VPIN, Hawkes, OFI, HMM)
3. Cost Check      → "Edge > costs?"              (fee + spread + impact)
4. Kelly Sizing    → "How much?"                  (plug-in or Bayesian by category)
5. Risk Manager    → "Portfolio OK?"              (drawdown, limits, circuit breaker)
6. Execute         → Paper or live order
```

## Key Files

| File | Purpose |
|------|---------|
| `run_trader.py` | Main entry point for trading system |
| `run_collector.py` | Start data collection |
| `backend/strategy/signals.py` | Signal aggregation (belief state → p_estimate) |
| `backend/strategy/kelly.py` | Position sizing with category-level posteriors |
| `backend/strategy/cost_model.py` | Transaction cost model |
| `backend/strategy/calibration.py` | Delta calibrator (learns from data) |
| `backend/trading/trader.py` | Trading orchestrator |
| `backend/backtest/engine.py` | Backtesting engine + walk-forward |
| `backend/backtest/screen_markets.py` | Market screening for collection |
| `poc/belief_state_machine.py` | Core belief state transitions |
| `poc/reaction_classifier.py` | 7-type reaction classification |

## Calibration Status

**DeltaCalibrator**: Using conservative default priors. Needs 5-7 days of
live data collection across 30+ markets to calibrate empirically.

**Category posteriors**: Empty (Beta(2,2) prior). Will populate as trades
resolve. Need ~10 outcomes per category for Bayesian Kelly to activate.

## Running Locally

```bash
# Database
docker compose -f infra/docker-compose.yml up -d timescaledb

# Collector
python run_collector.py

# Paper trading
python run_trader.py

# Backtest calibration
python -m backend.backtest.calibrate --days 7

# Market screening
python -m backend.backtest.screen_markets --markets 30
```

## Environment Variables

### Trading
- `TRADING_PAPER_MODE=true` — Paper trading (default)
- `TRADING_BANKROLL=10000` — Initial bankroll
- `KELLY_MULTIPLIER=0.5` — Fractional Kelly
- `RISK_MAX_DRAWDOWN=0.15` — Max drawdown before halt

### Database
- `DB_HOST=127.0.0.1`
- `DB_PORT=5432`
- `DB_NAME=belief_reaction`
- `DB_USER=postgres`
- `DB_PASSWORD=postgres`

### Polymarket (live trading only)
- `POLY_API_KEY`
- `POLY_API_SECRET`
- `POLY_API_PASSPHRASE`
