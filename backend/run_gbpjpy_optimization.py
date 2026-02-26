#!/usr/bin/env python3
"""
GBPJPY Breakout-Pullback Optimization Runner

Grid search with walk-forward validation on the user-defined strategy.
Tests parameter variations while respecting core rules.
"""
import os
import sys
import json
import time
import logging
import itertools
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/app/backend/gbpjpy_optimization.log", mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
RESULTS_DIR = "/app/backend/optimization_results"
os.makedirs(RESULTS_DIR, exist_ok=True)


def generate_grid():
    """Focused grid — RSI ranges are the main optimization target."""
    combos = list(itertools.product(
        [10],                  # swing_lookback (fixed)
        [5, 8],                # sl_buffer_pips (2)
        [2.0, 2.5],           # min_rr (2)
        [0.01],                # risk_per_trade (fixed)
        [0.55, 0.60],         # breakout_body_ratio (2)
        [0.85],                # breakout_size_mult (fixed)
        [0.65, 0.85],         # max_pullback_depth (2)
        # RSI long ranges — main optimization axis
        [(45, 68), (48, 68), (50, 65), (52, 65), (45, 70), (48, 72)],  # (6)
        # RSI short ranges
        [(30, 52), (32, 52), (35, 48), (35, 55), (30, 55)],            # (5)
        [False, True],         # use_structural_tp (2)
    ))
    return combos  # 1*2*2*1*2*1*2*6*5*2 = 960


def params_from_tuple(t):
    return {
        "swing_lookback": t[0],
        "sl_buffer_pips": t[1],
        "min_rr": t[2],
        "risk_per_trade": t[3],
        "breakout_body_ratio": t[4],
        "breakout_size_mult": t[5],
        "max_pullback_depth": t[6],
        "rsi_long_min": t[7][0],
        "rsi_long_max": t[7][1],
        "rsi_short_min": t[8][0],
        "rsi_short_max": t[8][1],
        "be_trigger_rr": 1.0,
        "max_daily_trades": 4,
        "max_consecutive_losses": 3,
        "min_sl_pips": 15,
        "max_sl_pips": 60,
    }


def result_to_dict(r):
    return {
        "total_trades": r.total_trades,
        "wins": r.wins,
        "losses": r.losses,
        "win_rate": r.win_rate,
        "total_return_pct": r.total_return_pct,
        "weekly_return_pct": r.weekly_return_pct,
        "profit_factor": r.profit_factor,
        "max_drawdown_pct": r.max_drawdown_pct,
        "max_daily_loss_pct": r.max_daily_loss_pct,
        "ftmo_compliant": r.ftmo_compliant,
        "avg_rr_achieved": r.avg_rr_achieved,
        "start_date": r.start_date,
        "end_date": r.end_date,
    }


def run_optimization():
    t0 = time.time()
    logger.info("=" * 60)
    logger.info("GBPJPY BREAKOUT-PULLBACK OPTIMIZATION")
    logger.info("=" * 60)

    # Load data
    h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
    m15 = load_tradingview_csv("historical_data/GBPJPY_M15_TV.csv")

    if not h1 or not m15:
        logger.error("Data loading failed!")
        return

    # Walk-forward split: 70% train / 30% test on M15 timeline
    m15_split = int(len(m15) * 0.70)
    split_time = m15[m15_split]["datetime"]

    m15_train = m15[:m15_split]
    m15_test = m15[m15_split:]

    logger.info(f"H1: {len(h1)} candles")
    logger.info(f"M15 total: {len(m15)} | train: {len(m15_train)} | test: {len(m15_test)}")
    logger.info(f"Split at: {split_time.date()}")
    logger.info(f"Train: {m15_train[0]['datetime'].date()} -> {m15_train[-1]['datetime'].date()}")
    logger.info(f"Test: {m15_test[0]['datetime'].date()} -> {m15_test[-1]['datetime'].date()}")

    grid = generate_grid()
    logger.info(f"Grid: {len(grid)} parameter combinations")

    # ═══ Phase 1: Train Grid Search ═══
    logger.info("\n=== PHASE 1: TRAIN GRID SEARCH ===")
    train_results = []

    for idx, combo in enumerate(grid):
        if idx % 500 == 0:
            elapsed = time.time() - t0
            logger.info(f"  Grid {idx}/{len(grid)} ({elapsed:.0f}s)")

        params = params_from_tuple(combo)
        bt = GBPJPYBreakoutBacktester(initial_balance=100000)
        r = bt.run(h1, m15_train, params, base_spread=2.5)

        if r.total_trades >= 3 and r.total_return_pct > 0 and r.ftmo_compliant:
            train_results.append((params, r))

    train_results.sort(key=lambda x: x[1].weekly_return_pct, reverse=True)
    logger.info(f"Phase 1 done: {len(train_results)} viable / {len(grid)} tested")

    if not train_results:
        # Relax to min 2 trades
        logger.info("No viable with 3+ trades. Relaxing to 2+ trades...")
        for idx, combo in enumerate(grid):
            params = params_from_tuple(combo)
            bt = GBPJPYBreakoutBacktester(initial_balance=100000)
            r = bt.run(h1, m15_train, params, base_spread=2.5)
            if r.total_trades >= 2 and r.total_return_pct > -1:
                train_results.append((params, r))
        train_results.sort(key=lambda x: x[1].weekly_return_pct, reverse=True)
        logger.info(f"  Relaxed: {len(train_results)} found")

    # ═══ Phase 2: OOS Test (top 30) ═══
    top_n = min(30, len(train_results))
    top = train_results[:top_n]
    logger.info(f"\n=== PHASE 2: OOS TEST (top {top_n}) ===")

    oos_results = []
    for params, train_r in top:
        bt = GBPJPYBreakoutBacktester(initial_balance=100000)
        test_r = bt.run(h1, m15_test, params, base_spread=2.5)

        logger.info(
            f"  Train: +{train_r.total_return_pct}% ({train_r.total_trades}t) | "
            f"Test: +{test_r.total_return_pct}% ({test_r.total_trades}t) | "
            f"RSI_L={params['rsi_long_min']}-{params['rsi_long_max']} RSI_S={params['rsi_short_min']}-{params['rsi_short_max']}"
        )

        oos_results.append({
            "params": params,
            "train": result_to_dict(train_r),
            "test": result_to_dict(test_r),
        })

    # ═══ Phase 3: Full period for top candidates ═══
    logger.info(f"\n=== PHASE 3: FULL PERIOD ===")
    full_results = []
    for entry in oos_results[:15]:
        params = entry["params"]
        bt = GBPJPYBreakoutBacktester(initial_balance=100000)
        full_r = bt.run(h1, m15, params, base_spread=2.5)
        entry["full"] = result_to_dict(full_r)
        full_results.append(entry)

        logger.info(
            f"  Full: +{full_r.total_return_pct}% weekly={full_r.weekly_return_pct}% "
            f"trades={full_r.total_trades} WR={full_r.win_rate}% PF={full_r.profit_factor} "
            f"DD={full_r.max_drawdown_pct}% FTMO={full_r.ftmo_compliant}"
        )

    full_results.sort(key=lambda x: x["full"]["weekly_return_pct"], reverse=True)

    elapsed = round(time.time() - t0, 1)
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": elapsed,
        "total_grid": len(grid),
        "viable_train": len(train_results),
        "oos_tested": len(oos_results),
        "results": full_results,
    }

    out_file = os.path.join(RESULTS_DIR, "gbpjpy_breakout_optimization.json")
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"\n{'='*60}")
    logger.info(f"OPTIMIZATION COMPLETE in {elapsed}s ({elapsed/60:.1f} min)")
    logger.info(f"Results saved to: {out_file}")

    if full_results:
        best = full_results[0]
        bf = best["full"]
        logger.info(f"\nBEST: +{bf['weekly_return_pct']}%/week | {bf['total_trades']} trades | "
                     f"WR={bf['win_rate']}% | PF={bf['profit_factor']} | DD={bf['max_drawdown_pct']}%")
        logger.info(f"  RSI: long={best['params']['rsi_long_min']}-{best['params']['rsi_long_max']} "
                     f"short={best['params']['rsi_short_min']}-{best['params']['rsi_short_max']}")
    else:
        logger.info("\nAUCUN RÉSULTAT VIABLE.")

    return summary


if __name__ == "__main__":
    run_optimization()
