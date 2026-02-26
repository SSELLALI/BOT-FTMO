#!/usr/bin/env python3
"""
GBPJPY Breakout-Pullback Walk-Forward Optimization v2
M30 entry, multi-breakout tracking, relaxed patterns.
"""
import os, sys, json, time, random, logging, itertools
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/app/backend/gbpjpy_opt_v2.log", mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
RESULTS_DIR = "/app/backend/optimization_results"
os.makedirs(RESULTS_DIR, exist_ok=True)


def generate_grid():
    """Focused parameter grid — ~3000 combos based on diagnostic results."""
    combos = list(itertools.product(
        [5, 6],                        # swing_lookback (2) — 5 and 6 best
        [3, 5, 8],                     # sl_buffer_pips (3)
        [1.5, 2.0],                    # min_rr (2) — 1.5 gives more trades
        [0.01],                        # risk_per_trade (fixed)
        [0.35, 0.45],                 # breakout_body_ratio (2)
        [0.3, 0.5],                   # breakout_size_mult (2)
        [1.2, 1.8],                   # max_pullback_depth (2)
        [0.7, 1.0],                   # proximity_factor (2)
        [25, 40],                      # stale_timeout (2)
        [True],                        # extend_session — always True (better)
        [False, True],                 # use_structural_tp (2)
        [(35, 78), (30, 80)],         # rsi_long (2)
        [(22, 65), (20, 70)],         # rsi_short (2)
    ))
    return combos  # 2*3*2*1*2*2*2*2*2*1*2*2*2 = 3072


def params_from_tuple(t):
    return {
        "swing_lookback": t[0],
        "sl_buffer_pips": t[1],
        "min_rr": t[2],
        "risk_per_trade": t[3],
        "breakout_body_ratio": t[4],
        "breakout_size_mult": t[5],
        "max_pullback_depth": t[6],
        "proximity_factor": t[7],
        "stale_timeout": t[8],
        "extend_session": t[9],
        "use_structural_tp": t[10],
        "rsi_long_min": 35,
        "rsi_long_max": 78,
        "rsi_short_min": 22,
        "rsi_short_max": 65,
        "be_trigger_rr": 1.0,
        "max_daily_trades": 4,
        "max_consecutive_losses": 4,
        "min_sl_pips": 5,
        "max_sl_pips": 100,
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
    logger.info("GBPJPY BREAKOUT v2 - WALK-FORWARD OPTIMIZATION")
    logger.info("M30 entry, multi-breakout, enhanced patterns")
    logger.info("=" * 60)

    h1 = load_tradingview_csv("/app/backend/historical_data/GBPJPY_H1_TV.csv")
    m30 = load_tradingview_csv("/app/backend/historical_data/GBPJPY_M30_TV.csv")

    if not h1 or not m30:
        logger.error("Data loading failed!")
        return

    # Walk-forward split: 65% train / 35% test on M30 timeline
    m30_split = int(len(m30) * 0.65)
    split_time = m30[m30_split]["datetime"]

    m30_train = m30[:m30_split]
    m30_test = m30[m30_split:]

    logger.info(f"H1: {len(h1)} candles")
    logger.info(f"M30 total: {len(m30)} | train: {len(m30_train)} | test: {len(m30_test)}")
    logger.info(f"Split at: {split_time.date()}")
    logger.info(f"Train: {m30_train[0]['datetime'].date()} -> {m30_train[-1]['datetime'].date()}")
    logger.info(f"Test:  {m30_test[0]['datetime'].date()} -> {m30_test[-1]['datetime'].date()}")

    grid = generate_grid()
    logger.info(f"Grid: {len(grid)} parameter combinations")

    # Phase 1: Train Grid Search
    logger.info("\n=== PHASE 1: TRAIN GRID SEARCH ===")
    train_results = []

    for idx, combo in enumerate(grid):
        if idx % 2000 == 0:
            elapsed = time.time() - t0
            logger.info(f"  Grid {idx}/{len(grid)} ({elapsed:.0f}s) — {len(train_results)} viable so far")

        random.seed(42)
        params = params_from_tuple(combo)
        bt = GBPJPYBreakoutBacktester(initial_balance=100000)
        r = bt.run(h1, m30_train, params, base_spread=2.5)

        if r.total_trades >= 5 and r.total_return_pct > 0 and r.ftmo_compliant and r.profit_factor > 1.0:
            train_results.append((params, r))

    train_results.sort(key=lambda x: (x[1].profit_factor * x[1].total_trades, x[1].weekly_return_pct), reverse=True)
    logger.info(f"Phase 1 done: {len(train_results)} viable / {len(grid)} tested")

    if not train_results:
        logger.info("Relaxing to 3+ trades...")
        for combo in grid:
            random.seed(42)
            params = params_from_tuple(combo)
            bt = GBPJPYBreakoutBacktester(initial_balance=100000)
            r = bt.run(h1, m30_train, params, base_spread=2.5)
            if r.total_trades >= 3 and r.total_return_pct > -2:
                train_results.append((params, r))
        train_results.sort(key=lambda x: x[1].weekly_return_pct, reverse=True)
        logger.info(f"  Relaxed: {len(train_results)} found")

    # Phase 2: OOS Test (top 50)
    top_n = min(50, len(train_results))
    top = train_results[:top_n]
    logger.info(f"\n=== PHASE 2: OOS TEST (top {top_n}) ===")

    oos_results = []
    for params, train_r in top:
        random.seed(42)
        bt = GBPJPYBreakoutBacktester(initial_balance=100000)
        test_r = bt.run(h1, m30_test, params, base_spread=2.5)

        logger.info(
            f"  Train: +{train_r.total_return_pct}% ({train_r.total_trades}t PF={train_r.profit_factor}) | "
            f"Test: +{test_r.total_return_pct}% ({test_r.total_trades}t PF={test_r.profit_factor})"
        )

        oos_results.append({
            "params": params,
            "train": result_to_dict(train_r),
            "test": result_to_dict(test_r),
        })

    # Phase 3: Full period for profitable OOS results
    logger.info(f"\n=== PHASE 3: FULL PERIOD (profitable OOS only) ===")
    full_results = []
    for entry in oos_results:
        test_ok = entry["test"]["total_return_pct"] > 0 and entry["test"]["total_trades"] >= 2
        if not test_ok:
            continue
        random.seed(42)
        params = entry["params"]
        bt = GBPJPYBreakoutBacktester(initial_balance=100000)
        full_r = bt.run(h1, m30, params, base_spread=2.5)
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
        "oos_profitable": len(full_results),
        "results": full_results[:20],
    }

    out_file = os.path.join(RESULTS_DIR, "gbpjpy_breakout_v2_optimization.json")
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"\n{'='*60}")
    logger.info(f"OPTIMIZATION COMPLETE in {elapsed}s ({elapsed/60:.1f} min)")
    logger.info(f"Viable train: {len(train_results)} | OOS profitable: {len(full_results)}")
    logger.info(f"Results saved to: {out_file}")

    if full_results:
        best = full_results[0]
        bf = best["full"]
        logger.info(f"\nBEST FULL: +{bf['weekly_return_pct']}%/week | {bf['total_trades']} trades | "
                     f"WR={bf['win_rate']}% | PF={bf['profit_factor']} | DD={bf['max_drawdown_pct']}%")
        bt_ = best["train"]
        ts_ = best["test"]
        logger.info(f"  Train: +{bt_['weekly_return_pct']}%/w ({bt_['total_trades']}t) | "
                     f"Test: +{ts_['weekly_return_pct']}%/w ({ts_['total_trades']}t)")
        logger.info(f"  Params: SL={best['params']['swing_lookback']} body={best['params']['breakout_body_ratio']} "
                     f"vol={best['params']['breakout_size_mult']} RR={best['params']['min_rr']} "
                     f"prox={best['params']['proximity_factor']} timeout={best['params']['stale_timeout']} "
                     f"ext={best['params']['extend_session']}")
    else:
        logger.info("\nAUCUN RESULTAT OOS PROFITABLE.")

    return summary


if __name__ == "__main__":
    run_optimization()
