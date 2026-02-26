#!/usr/bin/env python3
"""
Full Optimization Runner — Runs walk-forward for SCALPING and INTRADAY independently.

Usage: python run_full_optimization.py
Writes results to /app/backend/optimization_results.json
Progress tracked in /app/backend/optimization_status.json
"""
import json
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from historical_data_loader import download_and_cache, load_candles_from_csv
from walkforward_optimizer import walk_forward_optimize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/backend/optimization.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)

RESULTS_FILE = "/app/backend/optimization_results.json"
STATUS_FILE = "/app/backend/optimization_status.json"


def write_status(data):
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def main():
    t_start = time.time()
    logger.info("=" * 60)
    logger.info("FULL OPTIMIZATION START")
    logger.info("=" * 60)

    write_status({"phase": "loading_data", "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})

    # ── Load data ──
    logger.info("Downloading/loading real EURUSD data...")
    h1_path, m15_path = download_and_cache("EURUSD")
    h1_candles = load_candles_from_csv(h1_path)
    m15_candles = load_candles_from_csv(m15_path)

    logger.info(f"H1 candles: {len(h1_candles)}")
    logger.info(f"M15 candles: {len(m15_candles)}")

    if len(h1_candles) < 2000:
        logger.error("Not enough H1 data for 2-year backtest!")
        write_status({"phase": "error", "message": "Not enough H1 data"})
        return

    h1_start = h1_candles[0]["datetime"].strftime("%Y-%m-%d")
    h1_end = h1_candles[-1]["datetime"].strftime("%Y-%m-%d")
    m15_start = m15_candles[0]["datetime"].strftime("%Y-%m-%d") if m15_candles else "N/A"
    m15_end = m15_candles[-1]["datetime"].strftime("%Y-%m-%d") if m15_candles else "N/A"

    logger.info(f"H1 period: {h1_start} → {h1_end}")
    logger.info(f"M15 period: {m15_start} → {m15_end}")

    results = {}

    # ── 1. SCALPING on H1 data (2 years) ──
    logger.info("=" * 60)
    logger.info("SCALPING OPTIMIZATION (H1, 2 years)")
    logger.info("=" * 60)

    scalp_result = walk_forward_optimize(
        candles=h1_candles,
        strategy_type="SCALPING",
        train_pct=0.70,
        min_trades_train=80,
        min_trades_total=300,
        top_n=15,
        progress_key="scalping_h1",
    )
    results["scalping_h1"] = scalp_result

    # Also run scalping on M15 if available (shorter period)
    if len(m15_candles) > 500:
        logger.info("=" * 60)
        logger.info("SCALPING VALIDATION on M15 data")
        logger.info("=" * 60)

        # If we have a winner from H1, validate it on M15
        if scalp_result.get("results"):
            winner_params = scalp_result["results"][0]["params"]
            from realistic_backtester_v2 import RealisticBacktester
            bt = RealisticBacktester(initial_balance=100000)
            m15_r = bt.run_scalping(m15_candles, winner_params, timeframe="M15")
            results["scalping_m15_validation"] = {
                "params": winner_params,
                "result": {
                    "total_trades": m15_r.total_trades,
                    "win_rate": m15_r.win_rate,
                    "total_return_pct": m15_r.total_return_pct,
                    "weekly_return_pct": m15_r.weekly_return_pct,
                    "profit_factor": m15_r.profit_factor,
                    "max_drawdown_pct": m15_r.max_drawdown_pct,
                    "ftmo_compliant": m15_r.ftmo_compliant,
                },
            }
            logger.info(f"M15 validation: return={m15_r.total_return_pct:+.2f}% "
                        f"weekly={m15_r.weekly_return_pct:+.3f}% trades={m15_r.total_trades}")

    # ── 2. INTRADAY on H1 data (2 years) ──
    logger.info("=" * 60)
    logger.info("INTRADAY OPTIMIZATION (H1, 2 years)")
    logger.info("=" * 60)

    intra_result = walk_forward_optimize(
        candles=h1_candles,
        strategy_type="INTRADAY",
        train_pct=0.70,
        min_trades_train=80,
        min_trades_total=300,
        top_n=15,
        progress_key="intraday_h1",
    )
    results["intraday_h1"] = intra_result

    # ── Summary ──
    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"OPTIMIZATION COMPLETE in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    logger.info("=" * 60)

    for key in ["scalping_h1", "intraday_h1"]:
        r = results.get(key, {})
        status = r.get("status", "?")
        if status == "COMPLETE" and r.get("results"):
            best = r["results"][0]
            fp = best.get("full_period", best.get("test", {}))
            logger.info(
                f"{key}: {fp.get('total_return_pct', '?')}% return, "
                f"{fp.get('weekly_return_pct', '?')}%/week, "
                f"{fp.get('total_trades', '?')} trades, "
                f"WR={fp.get('win_rate', '?')}%, "
                f"PF={fp.get('profit_factor', '?')}, "
                f"DD={fp.get('max_drawdown_pct', '?')}%, "
                f"robust={best.get('robust', '?')} ({best.get('robustness_rate', 0)*100:.0f}%)"
            )
        else:
            logger.info(f"{key}: {status}")

    # Save full results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)

    write_status({
        "phase": "COMPLETE",
        "elapsed_sec": round(elapsed, 1),
        "results_file": RESULTS_FILE,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

    logger.info(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
