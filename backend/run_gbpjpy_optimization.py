#!/usr/bin/env python3
"""
GBPJPY Breakout-Pullback Walk-Forward Optimization v2 (Performance-Optimized)
Pre-computes breakouts per unique H1 parameter set, then runs M30 entries fast.
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


def generate_entry_params_grid():
    """Entry-only params (fast to iterate)."""
    combos = list(itertools.product(
        [3, 5, 8],                     # sl_buffer_pips (3)
        [1.5, 2.0],                    # min_rr (2)
        [1.2, 1.8],                    # max_pullback_depth (2)
        [0.7, 1.0],                    # proximity_factor (2)
        [25, 40],                      # stale_timeout (2)
        [True],                        # extend_session (1)
        [False, True],                 # use_structural_tp (2)
        [(35, 78), (30, 80)],         # rsi_long (2)
        [(22, 65), (20, 70)],         # rsi_short (2)
    ))
    return combos  # 3*2*2*2*2*1*2*2*2 = 384


def h1_param_combos():
    """H1-level params that affect breakout detection."""
    return list(itertools.product(
        [5, 6],                        # swing_lookback (2)
        [0.35, 0.45],                 # breakout_body_ratio (2)
        [0.3, 0.5],                   # breakout_size_mult (2)
    ))  # 2*2*2 = 8


def make_params(h1_combo, entry_combo):
    return {
        "swing_lookback": h1_combo[0],
        "breakout_body_ratio": h1_combo[1],
        "breakout_size_mult": h1_combo[2],
        "sl_buffer_pips": entry_combo[0],
        "min_rr": entry_combo[1],
        "max_pullback_depth": entry_combo[2],
        "proximity_factor": entry_combo[3],
        "stale_timeout": entry_combo[4],
        "extend_session": entry_combo[5],
        "use_structural_tp": entry_combo[6],
        "rsi_long_min": entry_combo[7][0],
        "rsi_long_max": entry_combo[7][1],
        "rsi_short_min": entry_combo[8][0],
        "rsi_short_max": entry_combo[8][1],
        "risk_per_trade": 0.01,
        "be_trigger_rr": 1.0,
        "max_daily_trades": 4,
        "max_consecutive_losses": 4,
        "min_sl_pips": 5,
        "max_sl_pips": 100,
    }


def result_to_dict(r):
    return {
        "total_trades": r.total_trades, "wins": r.wins, "losses": r.losses,
        "win_rate": r.win_rate, "total_return_pct": r.total_return_pct,
        "weekly_return_pct": r.weekly_return_pct, "profit_factor": r.profit_factor,
        "max_drawdown_pct": r.max_drawdown_pct, "max_daily_loss_pct": r.max_daily_loss_pct,
        "ftmo_compliant": r.ftmo_compliant, "avg_rr_achieved": r.avg_rr_achieved,
        "start_date": r.start_date, "end_date": r.end_date,
    }


def run_optimization():
    t0 = time.time()
    logger.info("=" * 60)
    logger.info("GBPJPY BREAKOUT v2 - OPTIMIZED WALK-FORWARD")
    logger.info("=" * 60)

    h1 = load_tradingview_csv("/app/backend/historical_data/GBPJPY_H1_TV.csv")
    m30 = load_tradingview_csv("/app/backend/historical_data/GBPJPY_M30_TV.csv")

    m30_split = int(len(m30) * 0.65)
    m30_train = m30[:m30_split]
    m30_test = m30[m30_split:]

    logger.info(f"H1: {len(h1)} | M30: {len(m30)} (train={len(m30_train)}, test={len(m30_test)})")
    logger.info(f"Train: {m30_train[0]['datetime'].date()} -> {m30_train[-1]['datetime'].date()}")
    logger.info(f"Test:  {m30_test[0]['datetime'].date()} -> {m30_test[-1]['datetime'].date()}")

    h1_combos = h1_param_combos()
    entry_combos = generate_entry_params_grid()
    total = len(h1_combos) * len(entry_combos)
    logger.info(f"H1 param sets: {len(h1_combos)} | Entry param sets: {len(entry_combos)} | Total: {total}")

    # Phase 1: Train
    logger.info("\n=== PHASE 1: TRAIN ===")
    train_results = []
    tested = 0

    for h1c in h1_combos:
        h1_t0 = time.time()

        # Pre-compute breakouts ONCE for this H1 combo
        bt_prescan = GBPJPYBreakoutBacktester(initial_balance=100000)
        train_time_range = (m30_train[0]["datetime"], m30_train[-1]["datetime"])
        precomputed_train = bt_prescan.pre_scan_breakouts(
            h1, train_time_range, h1c[0], h1c[1], h1c[2])

        logger.info(f"  H1({h1c[0]},{h1c[1]},{h1c[2]}): pre-scanned {len(precomputed_train[0])} breakouts")

        for ec in entry_combos:
            random.seed(42)
            params = make_params(h1c, ec)
            bt = GBPJPYBreakoutBacktester(initial_balance=100000)
            r = bt.run(h1, m30_train, params, base_spread=2.5, precomputed=precomputed_train)
            tested += 1

            if r.total_trades >= 5 and r.total_return_pct > 0 and r.ftmo_compliant and r.profit_factor > 1.0:
                train_results.append((params, r))

        h1_elapsed = time.time() - h1_t0
        elapsed = time.time() - t0
        logger.info(f"  H1({h1c[0]},{h1c[1]},{h1c[2]}): {h1_elapsed:.0f}s | "
                     f"total={tested}/{total} | viable={len(train_results)} | elapsed={elapsed:.0f}s")

    train_results.sort(key=lambda x: (x[1].profit_factor * x[1].total_trades, x[1].weekly_return_pct), reverse=True)
    logger.info(f"Phase 1: {len(train_results)} viable / {tested} tested")

    if not train_results:
        logger.info("Relaxing thresholds...")
        for h1c in h1_combos:
            for ec in entry_combos:
                random.seed(42)
                params = make_params(h1c, ec)
                bt = GBPJPYBreakoutBacktester(initial_balance=100000)
                r = bt.run(h1, m30_train, params, base_spread=2.5)
                if r.total_trades >= 3 and r.total_return_pct > -2:
                    train_results.append((params, r))
        train_results.sort(key=lambda x: x[1].weekly_return_pct, reverse=True)
        logger.info(f"  Relaxed: {len(train_results)} found")

    # Phase 2: OOS
    top_n = min(50, len(train_results))
    top = train_results[:top_n]
    logger.info(f"\n=== PHASE 2: OOS ({top_n} candidates) ===")

    oos_results = []
    for params, train_r in top:
        random.seed(42)
        bt = GBPJPYBreakoutBacktester(initial_balance=100000)
        test_r = bt.run(h1, m30_test, params, base_spread=2.5)
        logger.info(f"  Train: +{train_r.total_return_pct}% ({train_r.total_trades}t PF={train_r.profit_factor}) | "
                     f"Test: +{test_r.total_return_pct}% ({test_r.total_trades}t PF={test_r.profit_factor})")
        oos_results.append({"params": params, "train": result_to_dict(train_r), "test": result_to_dict(test_r)})

    # Phase 3: Full period
    logger.info(f"\n=== PHASE 3: FULL PERIOD ===")
    full_results = []
    for entry in oos_results:
        if entry["test"]["total_return_pct"] > 0 and entry["test"]["total_trades"] >= 2:
            random.seed(42)
            bt = GBPJPYBreakoutBacktester(initial_balance=100000)
            full_r = bt.run(h1, m30, params=entry["params"], base_spread=2.5)
            entry["full"] = result_to_dict(full_r)
            full_results.append(entry)
            logger.info(f"  Full: +{full_r.total_return_pct}% wk={full_r.weekly_return_pct}% "
                         f"trades={full_r.total_trades} WR={full_r.win_rate}% PF={full_r.profit_factor} DD={full_r.max_drawdown_pct}%")

    full_results.sort(key=lambda x: x["full"]["weekly_return_pct"], reverse=True)

    elapsed = round(time.time() - t0, 1)
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": elapsed,
        "total_grid": total,
        "viable_train": len(train_results),
        "oos_tested": len(oos_results),
        "oos_profitable": len(full_results),
        "results": full_results[:20],
    }

    out_file = os.path.join(RESULTS_DIR, "gbpjpy_breakout_v2_optimization.json")
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"\n{'='*60}")
    logger.info(f"DONE in {elapsed}s ({elapsed/60:.1f} min)")
    logger.info(f"Viable: {len(train_results)} | OOS profitable: {len(full_results)}")

    if full_results:
        best = full_results[0]
        bf = best["full"]
        logger.info(f"\nBEST: +{bf['weekly_return_pct']}%/week | {bf['total_trades']} trades | "
                     f"WR={bf['win_rate']}% PF={bf['profit_factor']} DD={bf['max_drawdown_pct']}%")
        p = best["params"]
        logger.info(f"  SL={p['swing_lookback']} body={p['breakout_body_ratio']} vol={p['breakout_size_mult']} "
                     f"RR={p['min_rr']} prox={p['proximity_factor']} timeout={p['stale_timeout']} "
                     f"ext={p['extend_session']} RSI_L=({p['rsi_long_min']},{p['rsi_long_max']}) "
                     f"RSI_S=({p['rsi_short_min']},{p['rsi_short_max']})")
    else:
        logger.info("\nNO PROFITABLE OOS RESULTS")

    return summary


if __name__ == "__main__":
    run_optimization()
