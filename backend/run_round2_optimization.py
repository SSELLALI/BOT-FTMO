#!/usr/bin/env python3
"""
Optimization Round 2: GBPJPY Intraday-adapted + AUDCAD Price Action

GBPJPY: Adapted for high volatility
  - Stricter sessions (London 7-11, NY overlap 13-16)
  - Wider SL (20-50 pips)
  - Lower R:R (2.0-2.5 — smaller targets to account for spread)
  - Max 3 trades/day (more selective)

AUDCAD: Standard PA (totally decorrelated — no JPY, no USD)
  - Spread ~1.8 pips
  - Standard sessions

Both use Price Action (S/R + Candlestick Patterns) + MTF (H1+M30)
All 10 safety rules preserved.
"""
import json
import logging
import time
import sys
import os
import itertools

sys.path.insert(0, os.path.dirname(__file__))

from tradingview_loader import load_tradingview_csv
from price_action_backtester import PriceActionBacktester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/backend/round2_optimization.log"),
    ]
)
logger = logging.getLogger(__name__)

RESULTS_FILE = "/app/backend/round2_optimization_results.json"
DATA_DIR = "/app/backend/historical_data"
STATUS_FILE = "/app/backend/optimization_status.json"


def _write_status(data):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        pass


def _result_to_dict(r):
    return {
        "total_trades": r.total_trades, "wins": r.wins, "losses": r.losses,
        "win_rate": r.win_rate, "total_return_pct": r.total_return_pct,
        "weekly_return_pct": r.weekly_return_pct, "profit_factor": r.profit_factor,
        "max_drawdown_pct": r.max_drawdown_pct, "max_daily_loss_pct": r.max_daily_loss_pct,
        "ftmo_compliant": r.ftmo_compliant, "start_date": r.start_date,
        "end_date": r.end_date, "avg_trade_pnl": r.avg_trade_pnl,
    }


def generate_gbpjpy_grids():
    """GBPJPY: Intraday-adapted grids with wider SL, stricter sessions."""
    bounce = []
    for combo in itertools.product(
        [10, 15, 20],        # swing_lookback (wider for less noise)
        [20, 30],            # sr_cluster_pips (wider for volatile pair)
        [15, 25],            # sr_proximity_pips (wider zone approach)
        [2.0, 2.5],          # min_rr (lower RR — realistic for GBPJPY spread)
        [20, 30, 40],        # min_sl_pips (wider SL for volatility)
        [50, 70],            # max_sl_pips (allow up to 70 pips)
        [0.005, 0.01],       # risk_per_trade
    ):
        bounce.append({
            "swing_lookback": combo[0], "sr_cluster_pips": combo[1],
            "sr_proximity_pips": combo[2], "min_rr": combo[3],
            "min_sl_pips": combo[4], "max_sl_pips": combo[5],
            "risk_per_trade": combo[6], "sr_break_pips": 15,
            "rsi_extreme": 33, "min_zone_strength": 2, "sl_buffer_pips": 8,
            "session_start": 7, "session_end": 17,  # Stricter: London+NY overlap only
            "max_daily_trades": 3, "max_consecutive_losses": 2,  # More selective
            "sr_max_zones": 30,
        })

    breakout = []
    for combo in itertools.product(
        [10, 15, 20],
        [20, 30],
        [15, 25],
        [2.0, 2.5],
        [20, 30, 40],
        [50, 70],
        [0.005, 0.01],
        [12, 20],            # sr_break_pips (wider breakout confirmation)
    ):
        breakout.append({
            "swing_lookback": combo[0], "sr_cluster_pips": combo[1],
            "sr_proximity_pips": combo[2], "min_rr": combo[3],
            "min_sl_pips": combo[4], "max_sl_pips": combo[5],
            "risk_per_trade": combo[6], "sr_break_pips": combo[7],
            "rsi_extreme": 33, "min_zone_strength": 2, "sl_buffer_pips": 8,
            "session_start": 7, "session_end": 17,
            "max_daily_trades": 3, "max_consecutive_losses": 2,
            "sr_max_zones": 30,
        })

    return bounce, breakout


def generate_audcad_grids():
    """AUDCAD: Standard PA grids adapted for low volatility pair."""
    bounce = []
    for combo in itertools.product(
        [10, 15],            # swing_lookback
        [15, 25],            # sr_cluster_pips
        [10, 18],            # sr_proximity_pips
        [2.0, 2.5, 3.0],    # min_rr
        [10, 15, 20],        # min_sl_pips
        [30, 45],            # max_sl_pips
        [0.005, 0.01],       # risk_per_trade
    ):
        bounce.append({
            "swing_lookback": combo[0], "sr_cluster_pips": combo[1],
            "sr_proximity_pips": combo[2], "min_rr": combo[3],
            "min_sl_pips": combo[4], "max_sl_pips": combo[5],
            "risk_per_trade": combo[6], "sr_break_pips": 10,
            "rsi_extreme": 33, "min_zone_strength": 2, "sl_buffer_pips": 5,
            "session_start": 7, "session_end": 20,
            "max_daily_trades": 5, "max_consecutive_losses": 3,
            "sr_max_zones": 30,
        })

    breakout = []
    for combo in itertools.product(
        [10, 15],
        [15, 25],
        [10, 18],
        [2.0, 2.5, 3.0],
        [10, 15, 20],
        [30, 45],
        [0.005, 0.01],
        [8, 12],
    ):
        breakout.append({
            "swing_lookback": combo[0], "sr_cluster_pips": combo[1],
            "sr_proximity_pips": combo[2], "min_rr": combo[3],
            "min_sl_pips": combo[4], "max_sl_pips": combo[5],
            "risk_per_trade": combo[6], "sr_break_pips": combo[7],
            "rsi_extreme": 33, "min_zone_strength": 2, "sl_buffer_pips": 5,
            "session_start": 7, "session_end": 20,
            "max_daily_trades": 5, "max_consecutive_losses": 3,
            "sr_max_zones": 30,
        })

    return bounce, breakout


def run_optimization(h1, m30, grid, strategy_type, symbol, base_spread,
                     progress_key, train_pct=0.70, initial_balance=100000,
                     min_trades_train=40, top_n=15):
    """Run walk-forward optimization for a single strategy."""
    t0 = time.time()

    split = int(len(h1) * train_pct)
    h1_train, h1_test = h1[:split], h1[split:]
    split_time = h1[split]["datetime"]

    m30_train = [c for c in m30 if c["datetime"] < split_time] if m30 else None
    m30_test = [c for c in m30 if c["datetime"] >= split_time] if m30 else None
    if m30_train and len(m30_train) == 0: m30_train = None
    if m30_test and len(m30_test) == 0: m30_test = None

    logger.info(f"[{strategy_type}] Grid: {len(grid)} | H1 train={len(h1_train)} test={len(h1_test)}")

    # Phase 1: Train
    train_results = []
    for idx, params in enumerate(grid):
        if idx % 50 == 0:
            _write_status({"phase": "train", "strategy": strategy_type,
                           "progress": f"{idx}/{len(grid)}", "elapsed_sec": round(time.time()-t0,1),
                           "progress_key": progress_key})
            logger.info(f"  [{strategy_type}] Grid {idx}/{len(grid)} ({time.time()-t0:.0f}s)")

        bt = PriceActionBacktester(initial_balance=initial_balance)
        r = bt.run(h1_train, strategy_type=strategy_type, params=params,
                   symbol=symbol, base_spread=base_spread, m30_candles=m30_train)

        if r.total_trades >= min_trades_train and r.total_return_pct > 0 and r.ftmo_compliant:
            train_results.append((params, r))

    train_results.sort(key=lambda x: x[1].weekly_return_pct, reverse=True)
    top = train_results[:top_n]
    logger.info(f"[{strategy_type}] Phase 1: {len(train_results)} viable / {len(grid)}. Top {len(top)}.")

    if not top:
        return {"status": "NO_VIABLE_TRAIN", "total_params_tested": len(grid), "viable_on_train": 0}

    # Phase 2: OOS
    oos_results = []
    for params, train_res in top:
        bt = PriceActionBacktester(initial_balance=initial_balance)
        test_res = bt.run(h1_test, strategy_type=strategy_type, params=params,
                          symbol=symbol, base_spread=base_spread, m30_candles=m30_test)
        if test_res.total_return_pct > 0:
            oos_results.append((params, train_res, test_res))

    logger.info(f"[{strategy_type}] Phase 2: {len(oos_results)}/{len(top)} OOS profitable")

    if not oos_results:
        best_p, best_train = top[0]
        bt = PriceActionBacktester(initial_balance=initial_balance)
        best_test = bt.run(h1_test, strategy_type=strategy_type, params=best_p,
                           symbol=symbol, base_spread=base_spread, m30_candles=m30_test)
        return {"status": "NO_OOS_PROFITABLE", "total_params_tested": len(grid),
                "viable_on_train": len(train_results), "profitable_oos": 0,
                "best_candidate": {"params": best_p, "train": _result_to_dict(best_train),
                                   "test": _result_to_dict(best_test)}}

    # Phase 3: Robustness
    final_results = []
    for params, train_res, test_res in oos_results:
        robust_count = 0
        tunable = ["swing_lookback", "sr_cluster_pips", "sr_proximity_pips"]
        total_checks = len(tunable) * 2

        for var_key in tunable:
            for mult in [0.85, 1.15]:
                varied = params.copy()
                orig = varied[var_key]
                varied[var_key] = type(orig)(orig * mult) if isinstance(orig, float) else max(1, int(orig * mult))
                bt = PriceActionBacktester(initial_balance=initial_balance)
                vr = bt.run(h1_train, strategy_type=strategy_type, params=varied,
                            symbol=symbol, base_spread=base_spread, m30_candles=m30_train)
                if vr.total_return_pct > 0:
                    robust_count += 1

        robustness_rate = robust_count / total_checks if total_checks > 0 else 0
        is_robust = robustness_rate >= 0.70

        bt = PriceActionBacktester(initial_balance=initial_balance)
        full_res = bt.run(h1, strategy_type=strategy_type, params=params,
                          symbol=symbol, base_spread=base_spread, m30_candles=m30)

        entry = {"params": params, "train": _result_to_dict(train_res),
                 "test": _result_to_dict(test_res), "full_period": _result_to_dict(full_res),
                 "robust": is_robust, "robustness_rate": round(robustness_rate, 2)}
        final_results.append(entry)

        logger.info(f"[{strategy_type}] {'WINNER' if is_robust else 'candidate'}: "
                    f"full={full_res.weekly_return_pct}%/w PF={full_res.profit_factor} "
                    f"DD={full_res.max_drawdown_pct}% robust={is_robust} ({robustness_rate*100:.0f}%)")

    final_results.sort(key=lambda x: (x["robust"], x["full_period"]["weekly_return_pct"]), reverse=True)
    robust_n = sum(1 for r in final_results if r["robust"])

    return {"status": "COMPLETE", "total_params_tested": len(grid),
            "viable_on_train": len(train_results), "profitable_oos": len(oos_results),
            "robust_count": robust_n, "results": final_results}


def main():
    logger.info("=" * 80)
    logger.info("ROUND 2: GBPJPY Intraday + AUDCAD Price Action")
    logger.info("=" * 80)

    results = {"pairs": {}}
    t0 = time.time()

    # ── GBPJPY ──
    logger.info("\n" + "=" * 60)
    logger.info("GBPJPY — Intraday-adapted (wider SL, stricter sessions)")
    logger.info("=" * 60)

    gbpjpy_h1 = load_tradingview_csv(f"{DATA_DIR}/GBPJPY_H1_TV.csv")
    gbpjpy_m30 = load_tradingview_csv(f"{DATA_DIR}/GBPJPY_M30_TV.csv")
    logger.info(f"GBPJPY H1: {len(gbpjpy_h1)} | M30: {len(gbpjpy_m30)}")

    gbpjpy_bounce, gbpjpy_breakout = generate_gbpjpy_grids()
    logger.info(f"GBPJPY grids: BOUNCE={len(gbpjpy_bounce)} | BREAKOUT={len(gbpjpy_breakout)}")

    r = run_optimization(gbpjpy_h1, gbpjpy_m30, gbpjpy_bounce, "BOUNCE", "GBPJPY", 1.8, "GBPJPY_bounce")
    results["pairs"]["GBPJPY_bounce"] = r
    logger.info(f"GBPJPY BOUNCE: {r['status']}")

    r = run_optimization(gbpjpy_h1, gbpjpy_m30, gbpjpy_breakout, "BREAKOUT", "GBPJPY", 1.8, "GBPJPY_breakout")
    results["pairs"]["GBPJPY_breakout"] = r
    logger.info(f"GBPJPY BREAKOUT: {r['status']}")

    # ── AUDCAD ──
    logger.info("\n" + "=" * 60)
    logger.info("AUDCAD — Standard Price Action (totally decorrelated)")
    logger.info("=" * 60)

    audcad_h1 = load_tradingview_csv(f"{DATA_DIR}/AUDCAD_H1_TV.csv")
    audcad_m30 = load_tradingview_csv(f"{DATA_DIR}/AUDCAD_M30_TV.csv")
    logger.info(f"AUDCAD H1: {len(audcad_h1)} | M30: {len(audcad_m30)}")

    audcad_bounce, audcad_breakout = generate_audcad_grids()
    logger.info(f"AUDCAD grids: BOUNCE={len(audcad_bounce)} | BREAKOUT={len(audcad_breakout)}")

    r = run_optimization(audcad_h1, audcad_m30, audcad_bounce, "BOUNCE", "AUDCAD", 1.8, "AUDCAD_bounce")
    results["pairs"]["AUDCAD_bounce"] = r
    logger.info(f"AUDCAD BOUNCE: {r['status']}")

    r = run_optimization(audcad_h1, audcad_m30, audcad_breakout, "BREAKOUT", "AUDCAD", 1.8, "AUDCAD_breakout")
    results["pairs"]["AUDCAD_breakout"] = r
    logger.info(f"AUDCAD BREAKOUT: {r['status']}")

    # ── Summary ──
    elapsed = time.time() - t0
    results["elapsed_sec"] = round(elapsed, 1)

    logger.info("\n" + "=" * 80)
    logger.info("ROUND 2 SUMMARY")
    logger.info("=" * 80)

    for key, res in results["pairs"].items():
        status = res.get("status", "?")
        logger.info(f"  {key}: {status}")
        if status == "COMPLETE" and res.get("results"):
            for r in res["results"][:3]:
                fp = r.get("full_period", {})
                logger.info(f"    weekly={fp.get('weekly_return_pct','?')}% PF={fp.get('profit_factor','?')} "
                           f"DD={fp.get('max_drawdown_pct','?')}% robust={r.get('robust')}")

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nResults: {RESULTS_FILE} | Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
