"""
Backtesting Engine

Replays historical belief state transitions through the trading pipeline
and measures real performance.

Three modes:
1. Signal Analysis — directional accuracy, move distribution (no Kelly/risk)
2. Full Simulation — complete pipeline with sizing, costs, risk
3. Walk-Forward Validation — rolling train/test splits for OOS validation

This answers the ONLY question that matters:
"When the system says CRACKING, does price actually move in the predicted
direction by more than transaction costs?"
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
import logging

from backend.backtest.data_loader import BeliefTransition
from backend.strategy.cost_model import TransactionCostModel, CostConfig
from backend.strategy.calibration import DeltaCalibrator
from backend.strategy.kelly import KellyPositionSizer, KellyConfig, compute_kelly_fraction

logger = logging.getLogger(__name__)


@dataclass
class SignalAnalysisResult:
    """Result of analyzing a set of belief transitions."""
    state: str
    n_total: int = 0
    n_with_price_data: int = 0

    # Directional accuracy at each horizon
    accuracy_1m: float = 0.0
    accuracy_5m: float = 0.0
    accuracy_15m: float = 0.0

    # Move distributions (signed: positive = correct direction)
    moves_1m: List[float] = field(default_factory=list)
    moves_5m: List[float] = field(default_factory=list)
    moves_15m: List[float] = field(default_factory=list)

    # Key stats
    median_move_5m: float = 0.0
    mean_move_5m: float = 0.0
    win_rate_5m: float = 0.0
    false_positive_rate: float = 0.0

    # After costs
    avg_cost: float = 0.0
    profitable_rate_after_costs: float = 0.0
    expected_pnl_per_trade: float = 0.0


@dataclass
class SimulationResult:
    """Result of full trading simulation."""
    total_trades: int = 0
    total_pnl: float = 0.0
    total_cost: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_pnl_per_trade: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    # By state
    by_state: Dict[str, SignalAnalysisResult] = field(default_factory=dict)
    # Equity curve
    equity_curve: List[float] = field(default_factory=list)
    # Trade log
    trades: List[Dict] = field(default_factory=list)


class BacktestEngine:
    """
    Core backtesting engine.

    Processes historical belief transitions and measures performance.
    """

    def __init__(
        self,
        cost_model: Optional[TransactionCostModel] = None,
        kelly_config: Optional[KellyConfig] = None,
    ):
        self.cost = cost_model or TransactionCostModel()
        self.kelly_config = kelly_config or KellyConfig(
            max_fraction=0.25,
            kelly_multiplier=0.5,
            min_edge=0.02,
        )

    def analyze_signals(
        self,
        transitions: List[BeliefTransition],
        horizon_minutes: int = 5,
    ) -> Dict[str, SignalAnalysisResult]:
        """
        Pure signal analysis — no sizing, no costs.

        For each belief state transition, measure:
        - Did price move in the predicted direction?
        - How much did it move?
        - What's the accuracy rate?

        This is the FIRST thing you run. If accuracy < 52%, stop here.
        """
        by_state: Dict[str, SignalAnalysisResult] = {}

        for t in transitions:
            state = t.new_state
            if state not in by_state:
                by_state[state] = SignalAnalysisResult(state=state)
            result = by_state[state]
            result.n_total += 1

            if t.price_at_event is None:
                continue
            result.n_with_price_data += 1

            # Predicted direction from reaction side
            # bid reaction → bearish (expect price DOWN)
            # ask reaction → bullish (expect price UP)
            if t.reaction_side == "bid":
                direction = -1.0
            elif t.reaction_side == "ask":
                direction = 1.0
            else:
                continue  # Can't determine direction

            # Measure moves (signed: positive = correct prediction)
            for horizon, price_field, move_list, acc_field in [
                (1, 'price_1m', result.moves_1m, 'accuracy_1m'),
                (5, 'price_5m', result.moves_5m, 'accuracy_5m'),
                (15, 'price_15m', result.moves_15m, 'accuracy_15m'),
            ]:
                price_future = getattr(t, f'price_{horizon}m', None)
                if price_future is not None:
                    raw_move = price_future - t.price_at_event
                    signed_move = raw_move * direction
                    move_list.append(signed_move)

        # Compute stats
        for state, result in by_state.items():
            for horizon_name in ['1m', '5m', '15m']:
                moves = getattr(result, f'moves_{horizon_name}')
                if moves:
                    correct = sum(1 for m in moves if m > 0)
                    setattr(result, f'accuracy_{horizon_name}', correct / len(moves))

            if result.moves_5m:
                result.median_move_5m = float(np.median(result.moves_5m))
                result.mean_move_5m = float(np.mean(result.moves_5m))
                result.win_rate_5m = sum(1 for m in result.moves_5m if m > 0) / len(result.moves_5m)
                result.false_positive_rate = sum(
                    1 for m in result.moves_5m if abs(m) < 0.005
                ) / len(result.moves_5m)

        return by_state

    def simulate_trading(
        self,
        transitions: List[BeliefTransition],
        initial_bankroll: float = 10000.0,
        min_states: tuple = ("CRACKING", "BROKEN"),
    ) -> SimulationResult:
        """
        Full trading simulation with Kelly sizing and costs.

        For each qualifying transition:
        1. Compute predicted direction + delta
        2. Estimate transaction costs
        3. Compute net edge
        4. Size position via Kelly
        5. Track PnL using realized price at 5-minute horizon
        """
        bankroll = initial_bankroll
        peak = initial_bankroll
        max_dd = 0.0
        equity = [initial_bankroll]
        trades = []
        pnl_series = []
        kelly = KellyPositionSizer(self.kelly_config)
        calibrator = DeltaCalibrator()

        for t in transitions:
            if t.new_state not in min_states:
                continue
            if t.price_at_event is None or t.price_5m is None:
                continue
            if t.reaction_side not in ("bid", "ask"):
                continue

            # Direction
            if t.reaction_side == "bid":
                side = "NO"
                predicted_move = -(calibrator.get_delta(t.new_state))
            else:
                side = "YES"
                predicted_move = calibrator.get_delta(t.new_state)

            # p_estimate
            p_estimate = t.price_at_event + predicted_move
            p_estimate = max(0.01, min(0.99, p_estimate))
            edge = abs(p_estimate - t.price_at_event)

            # Transaction costs
            cost_analysis = self.cost.is_trade_profitable(
                edge=edge,
                price=t.price_at_event,
                size_usd=bankroll * 0.05,  # 5% of bankroll for cost estimation
                spread=t.spread,
                book_depth_usd=(t.bid_depth_usd or 0) + (t.ask_depth_usd or 0),
            )

            if not cost_analysis["profitable_hold_to_resolution"]:
                continue

            # Kelly sizing with net edge
            net_edge = cost_analysis["net_edge_hold"]
            kelly_f = compute_kelly_fraction(
                p_estimate, t.price_at_event, side
            )
            fraction = kelly_f * self.kelly_config.kelly_multiplier
            fraction = min(fraction, self.kelly_config.max_fraction)
            size_usd = fraction * bankroll

            if size_usd < 5.0:
                continue

            # Realized outcome at 5-minute horizon
            actual_move = t.price_5m - t.price_at_event
            if side == "YES":
                pnl_raw = actual_move * (size_usd / t.price_at_event)
            else:
                pnl_raw = -actual_move * (size_usd / (1 - t.price_at_event))

            # Subtract costs
            cost_usd = cost_analysis["cost_breakdown"]["total_one_way"] * size_usd
            pnl_net = pnl_raw - cost_usd

            bankroll += pnl_net
            peak = max(peak, bankroll)
            dd = 1 - bankroll / peak
            max_dd = max(max_dd, dd)
            equity.append(bankroll)
            pnl_series.append(pnl_net)

            # Feed calibrator
            calibrator.record_transition(
                t.new_state, t.reaction_side, t.price_at_event,
                price_1m=t.price_1m, price_5m=t.price_5m, price_15m=t.price_15m,
            )

            trades.append({
                "ts": t.ts.isoformat(),
                "token_id": t.token_id,
                "state": t.new_state,
                "side": side,
                "price": t.price_at_event,
                "price_5m": t.price_5m,
                "size_usd": size_usd,
                "pnl_raw": pnl_raw,
                "cost_usd": cost_usd,
                "pnl_net": pnl_net,
                "bankroll_after": bankroll,
            })

        # Compute summary
        total_trades = len(trades)
        winning = sum(1 for t in trades if t["pnl_net"] > 0)
        total_pnl = bankroll - initial_bankroll
        total_cost = sum(t["cost_usd"] for t in trades)

        sharpe = 0.0
        if pnl_series and len(pnl_series) > 1:
            mean_pnl = np.mean(pnl_series)
            std_pnl = np.std(pnl_series)
            if std_pnl > 0:
                sharpe = mean_pnl / std_pnl * np.sqrt(252)  # Annualized

        return SimulationResult(
            total_trades=total_trades,
            total_pnl=total_pnl,
            total_cost=total_cost,
            winning_trades=winning,
            losing_trades=total_trades - winning,
            win_rate=winning / total_trades if total_trades > 0 else 0,
            avg_pnl_per_trade=total_pnl / total_trades if total_trades > 0 else 0,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            equity_curve=equity,
            trades=trades,
        )


class WalkForwardValidator:
    """
    Walk-forward out-of-sample validation.

    Splits data chronologically into rolling windows:
      [train_1 | test_1] [train_2 | test_2] [train_3 | test_3]

    Each window:
    1. Train: calibrate DeltaCalibrator on train data
    2. Test: simulate trading on test data using trained parameters
    3. Record OOS performance

    If OOS performance degrades vs in-sample, the strategy is overfit.
    """

    def __init__(
        self,
        train_days: int = 14,
        test_days: int = 7,
        step_days: int = 7,
        cost_model: Optional[TransactionCostModel] = None,
    ):
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days
        self.engine = BacktestEngine(cost_model=cost_model)

    def validate(
        self,
        transitions: List[BeliefTransition],
    ) -> Dict:
        """
        Run walk-forward validation across all available data.

        Returns:
            Dict with per-fold and aggregate OOS metrics
        """
        if not transitions:
            return {"error": "No transitions"}

        # Sort by time
        transitions.sort(key=lambda t: t.ts)
        start = transitions[0].ts
        end = transitions[-1].ts
        total_days = (end - start).days

        if total_days < self.train_days + self.test_days:
            return {"error": f"Only {total_days} days of data, need {self.train_days + self.test_days}"}

        folds = []
        current_start = start

        while current_start + timedelta(days=self.train_days + self.test_days) <= end:
            train_end = current_start + timedelta(days=self.train_days)
            test_end = train_end + timedelta(days=self.test_days)

            train_data = [t for t in transitions if current_start <= t.ts < train_end]
            test_data = [t for t in transitions if train_end <= t.ts < test_end]

            if len(train_data) >= 5 and len(test_data) >= 2:
                # Train: analyze signals
                train_analysis = self.engine.analyze_signals(train_data)

                # Test: simulate using trained parameters
                test_sim = self.engine.simulate_trading(test_data)

                fold = {
                    "train_start": current_start.isoformat(),
                    "train_end": train_end.isoformat(),
                    "test_start": train_end.isoformat(),
                    "test_end": test_end.isoformat(),
                    "train_n": len(train_data),
                    "test_n": len(test_data),
                    # In-sample metrics
                    "is_accuracy_5m": {
                        state: r.accuracy_5m for state, r in train_analysis.items()
                    },
                    "is_median_move": {
                        state: r.median_move_5m for state, r in train_analysis.items()
                    },
                    # Out-of-sample metrics
                    "oos_trades": test_sim.total_trades,
                    "oos_win_rate": test_sim.win_rate,
                    "oos_pnl": test_sim.total_pnl,
                    "oos_avg_pnl": test_sim.avg_pnl_per_trade,
                    "oos_max_dd": test_sim.max_drawdown,
                    "oos_sharpe": test_sim.sharpe_ratio,
                }
                folds.append(fold)

            current_start += timedelta(days=self.step_days)

        # Aggregate
        if not folds:
            return {"error": "No valid folds", "folds": []}

        avg_oos_win = np.mean([f["oos_win_rate"] for f in folds if f["oos_trades"] > 0])
        avg_oos_pnl = np.mean([f["oos_pnl"] for f in folds])
        total_oos_trades = sum(f["oos_trades"] for f in folds)
        avg_oos_sharpe = np.mean([f["oos_sharpe"] for f in folds if f["oos_trades"] > 0])

        return {
            "n_folds": len(folds),
            "total_oos_trades": total_oos_trades,
            "avg_oos_win_rate": float(avg_oos_win),
            "avg_oos_pnl": float(avg_oos_pnl),
            "avg_oos_sharpe": float(avg_oos_sharpe),
            "profitable_folds": sum(1 for f in folds if f["oos_pnl"] > 0),
            "folds": folds,
        }


def print_signal_report(results: Dict[str, SignalAnalysisResult]):
    """Pretty-print signal analysis results."""
    print("\n" + "=" * 70)
    print("SIGNAL ANALYSIS REPORT")
    print("=" * 70)

    for state, r in sorted(results.items()):
        print(f"\n--- {state} (n={r.n_with_price_data}/{r.n_total}) ---")
        if r.n_with_price_data == 0:
            print("  No price data available")
            continue

        print(f"  Directional Accuracy:")
        print(f"    1 min:  {r.accuracy_1m:.1%}  (n={len(r.moves_1m)})")
        print(f"    5 min:  {r.accuracy_5m:.1%}  (n={len(r.moves_5m)})")
        print(f"    15 min: {r.accuracy_15m:.1%}  (n={len(r.moves_15m)})")
        print(f"  5-min Move Distribution:")
        print(f"    Median: {r.median_move_5m:+.4f}")
        print(f"    Mean:   {r.mean_move_5m:+.4f}")
        if r.moves_5m:
            print(f"    P25:    {np.percentile(r.moves_5m, 25):+.4f}")
            print(f"    P75:    {np.percentile(r.moves_5m, 75):+.4f}")
        print(f"  Win Rate (5m): {r.win_rate_5m:.1%}")
        print(f"  False Positive Rate: {r.false_positive_rate:.1%}")

    print("\n" + "=" * 70)


def print_simulation_report(result: SimulationResult):
    """Pretty-print simulation results."""
    print("\n" + "=" * 70)
    print("TRADING SIMULATION REPORT")
    print("=" * 70)
    print(f"  Total Trades:      {result.total_trades}")
    print(f"  Win Rate:          {result.win_rate:.1%}")
    print(f"  Total PnL:         ${result.total_pnl:+.2f}")
    print(f"  Total Costs:       ${result.total_cost:.2f}")
    print(f"  Avg PnL/Trade:     ${result.avg_pnl_per_trade:+.2f}")
    print(f"  Max Drawdown:      {result.max_drawdown:.1%}")
    print(f"  Sharpe Ratio:      {result.sharpe_ratio:.2f}")
    print("=" * 70)
