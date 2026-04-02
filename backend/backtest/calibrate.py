"""
Historical Calibration Script

Loads belief transitions from DB, enriches with prices,
and feeds into DeltaCalibrator to produce empirically-calibrated deltas.

Usage:
    # From database
    python -m backend.backtest.calibrate --days 30

    # From CSV export
    python -m backend.backtest.calibrate --csv data/transitions.csv

    # Export enriched data for offline use
    python -m backend.backtest.calibrate --days 30 --export data/transitions.csv
"""

import argparse
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.backtest.data_loader import HistoricalDataLoader
from backend.backtest.engine import BacktestEngine, WalkForwardValidator, print_signal_report, print_simulation_report
from backend.strategy.calibration import DeltaCalibrator
from backend.strategy.cost_model import TransactionCostModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("calibrate")


def run_calibration(transitions, cost_model=None):
    """Run full calibration pipeline on a set of transitions."""
    engine = BacktestEngine(cost_model=cost_model)

    # Step 1: Signal analysis
    print("\n" + "=" * 70)
    print("STEP 1: SIGNAL ANALYSIS (raw accuracy, no costs)")
    print("=" * 70)
    signal_results = engine.analyze_signals(transitions)
    print_signal_report(signal_results)

    # Step 2: Calibrate deltas
    print("\n" + "=" * 70)
    print("STEP 2: DELTA CALIBRATION")
    print("=" * 70)
    calibrator = DeltaCalibrator()
    n_fed = 0
    for t in transitions:
        if t.price_at_event is None or t.reaction_side is None:
            continue
        calibrator.record_transition(
            t.new_state, t.reaction_side, t.price_at_event,
            price_1m=t.price_1m, price_5m=t.price_5m, price_15m=t.price_15m,
        )
        n_fed += 1

    print(f"\nFed {n_fed} transitions into calibrator")
    print("\nCalibrated deltas:")
    for state, stats in calibrator.get_all_stats().items():
        print(f"  {state}: delta={stats['calibrated_delta']:.4f} "
              f"(n={stats['n_observations']}, "
              f"accuracy={stats['directional_accuracy']:.1%}, "
              f"median_5m={stats['median_move_5m']:.4f})")

    # Step 3: Trading simulation
    print("\n" + "=" * 70)
    print("STEP 3: TRADING SIMULATION (with costs)")
    print("=" * 70)
    sim_result = engine.simulate_trading(transitions)
    print_simulation_report(sim_result)

    # Step 4: Walk-forward validation
    print("\n" + "=" * 70)
    print("STEP 4: WALK-FORWARD VALIDATION (out-of-sample)")
    print("=" * 70)
    validator = WalkForwardValidator(
        train_days=14, test_days=7, step_days=7,
        cost_model=cost_model,
    )
    wf_result = validator.validate(transitions)

    if "error" in wf_result:
        print(f"  {wf_result['error']}")
    else:
        print(f"  Folds:              {wf_result['n_folds']}")
        print(f"  Total OOS trades:   {wf_result['total_oos_trades']}")
        print(f"  Avg OOS win rate:   {wf_result['avg_oos_win_rate']:.1%}")
        print(f"  Avg OOS PnL:        ${wf_result['avg_oos_pnl']:+.2f}")
        print(f"  Avg OOS Sharpe:     {wf_result['avg_oos_sharpe']:.2f}")
        print(f"  Profitable folds:   {wf_result['profitable_folds']}/{wf_result['n_folds']}")

        for i, fold in enumerate(wf_result['folds']):
            print(f"\n  Fold {i+1}: "
                  f"train {fold['train_start'][:10]}..{fold['train_end'][:10]} "
                  f"(n={fold['train_n']}), "
                  f"test {fold['test_start'][:10]}..{fold['test_end'][:10]} "
                  f"(n={fold['test_n']})")
            print(f"    OOS trades={fold['oos_trades']}, "
                  f"win={fold['oos_win_rate']:.1%}, "
                  f"PnL=${fold['oos_pnl']:+.2f}, "
                  f"Sharpe={fold['oos_sharpe']:.2f}")

    # Final verdict
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    has_edge = False
    for state, r in signal_results.items():
        if state in ("CRACKING", "BROKEN") and r.accuracy_5m > 0.55 and r.n_with_price_data >= 20:
            print(f"  ✓ {state}: accuracy={r.accuracy_5m:.1%} with n={r.n_with_price_data} — EDGE EXISTS")
            has_edge = True
        elif state in ("CRACKING", "BROKEN") and r.n_with_price_data >= 20:
            print(f"  ✗ {state}: accuracy={r.accuracy_5m:.1%} with n={r.n_with_price_data} — NO EDGE")
        elif state in ("CRACKING", "BROKEN"):
            print(f"  ? {state}: n={r.n_with_price_data} — INSUFFICIENT DATA")

    if sim_result.total_trades > 0 and sim_result.total_pnl > 0:
        print(f"\n  Simulation PnL positive: ${sim_result.total_pnl:+.2f} over {sim_result.total_trades} trades")
    elif sim_result.total_trades > 0:
        print(f"\n  ⚠ Simulation PnL negative: ${sim_result.total_pnl:+.2f} — review parameters")
    else:
        print(f"\n  ⚠ No trades in simulation — edge may not survive costs")

    if not has_edge:
        print("\n  CONCLUSION: No statistically significant edge detected.")
        print("  DO NOT trade with real money until accuracy > 55% with n > 20.")

    return {
        "signal_analysis": {s: {"accuracy_5m": r.accuracy_5m, "n": r.n_with_price_data}
                           for s, r in signal_results.items()},
        "simulation": {
            "total_trades": sim_result.total_trades,
            "total_pnl": sim_result.total_pnl,
            "win_rate": sim_result.win_rate,
            "sharpe": sim_result.sharpe_ratio,
        },
        "walk_forward": wf_result,
        "calibrated_deltas": calibrator.get_all_stats(),
    }


def main():
    parser = argparse.ArgumentParser(description="Calibrate trading system from historical data")
    parser.add_argument("--days", type=int, default=30, help="Days of history to load")
    parser.add_argument("--csv", type=str, help="Load from CSV instead of database")
    parser.add_argument("--export", type=str, help="Export enriched data to CSV")
    parser.add_argument("--token", type=str, help="Filter to specific token_id")
    args = parser.parse_args()

    loader = HistoricalDataLoader()

    if args.csv:
        logger.info(f"Loading from CSV: {args.csv}")
        transitions = loader.load_from_csv(args.csv)
    else:
        logger.info(f"Loading {args.days} days of belief transitions from database")
        transitions = loader.load_belief_transitions(
            days_back=args.days,
            min_severity="FRAGILE",
            token_id=args.token,
        )
        logger.info("Enriching with price data...")
        transitions = loader.enrich_with_prices(transitions)

    if args.export:
        loader.export_to_csv(transitions, args.export)
        logger.info(f"Exported to {args.export}")

    if not transitions:
        logger.error("No transitions loaded. Check database connection or CSV path.")
        return

    logger.info(f"Running calibration on {len(transitions)} transitions")
    cost_model = TransactionCostModel()
    results = run_calibration(transitions, cost_model)

    # Save results
    results_path = "backtest_results.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {results_path}")


if __name__ == "__main__":
    main()
