#!/usr/bin/env python3
"""
Multi-Pair Walk-Forward Optimization — TradingView Data + Multi-Timeframe

Runs full optimization on EURUSD, USDJPY, GBPJPY using:
  - H1 for indicators (full history ~26 months)
  - M30 for execution precision (last ~14 months)

All 10 safety rules applied. TradingView (FXCM) data.
"""
import json
import logging
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from tradingview_loader import load_tradingview_csv
from walkforward_optimizer_v2 import walk_forward_optimize_mtf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/backend/tv_optimization.log"),
    ]
)
logger = logging.getLogger(__name__)

RESULTS_FILE = "/app/backend/tv_optimization_results.json"
DATA_DIR = "/app/backend/historical_data"

PAIRS = [
    {
        "symbol": "EURUSD",
        "h1_file": f"{DATA_DIR}/EURUSD_H1_TV.csv",
        "m30_file": f"{DATA_DIR}/EURUSD_M30_TV.csv",
        "base_spread": 0.8,
    },
    {
        "symbol": "USDJPY",
        "h1_file": f"{DATA_DIR}/USDJPY_H1_TV.csv",
        "m30_file": f"{DATA_DIR}/USDJPY_M30_TV.csv",
        "base_spread": 0.9,
    },
    {
        "symbol": "GBPJPY",
        "h1_file": f"{DATA_DIR}/GBPJPY_H1_TV.csv",
        "m30_file": f"{DATA_DIR}/GBPJPY_M30_TV.csv",
        "base_spread": 1.8,
    },
]

STRATEGIES = ["SCALPING", "INTRADAY"]


def main():
    logger.info("=" * 80)
    logger.info("MULTI-PAIR MTF OPTIMIZATION — TradingView Data")
    logger.info("H1 indicators + M30 execution")
    logger.info("=" * 80)

    results = {"pairs": {}, "combined": {}}
    t0 = time.time()

    for pair_cfg in PAIRS:
        symbol = pair_cfg["symbol"]
        base_spread = pair_cfg["base_spread"]

        logger.info(f"\n{'='*60}")
        logger.info(f"PAIR: {symbol} (spread={base_spread} pips)")
        logger.info(f"{'='*60}")

        h1_candles = load_tradingview_csv(pair_cfg["h1_file"])
        m30_candles = load_tradingview_csv(pair_cfg["m30_file"])

        if not h1_candles:
            logger.error(f"{symbol}: No H1 data. Skipping.")
            continue

        logger.info(f"{symbol} H1: {len(h1_candles)} candles ({h1_candles[0]['datetime']} -> {h1_candles[-1]['datetime']})")
        if m30_candles:
            logger.info(f"{symbol} M30: {len(m30_candles)} candles ({m30_candles[0]['datetime']} -> {m30_candles[-1]['datetime']})")
        else:
            logger.info(f"{symbol} M30: None (H1-only mode)")

        for strat in STRATEGIES:
            key = f"{symbol}_{strat.lower()}"
            logger.info(f"\n--- {symbol} {strat} ---")

            result = walk_forward_optimize_mtf(
                h1_candles=h1_candles,
                m30_candles=m30_candles,
                strategy_type=strat,
                train_pct=0.70,
                min_trades_train=60,
                min_trades_total=200,
                top_n=15,
                initial_balance=100000,
                progress_key=key,
                symbol=symbol,
                base_spread=base_spread,
            )

            results["pairs"][key] = result
            status = result.get("status", "?")
            logger.info(f"{key}: {status}")

            if status == "COMPLETE" and result.get("results"):
                best = result["results"][0]
                fp = best.get("full_period", {})
                logger.info(
                    f"  BEST: return={fp.get('total_return_pct','?')}% "
                    f"weekly={fp.get('weekly_return_pct','?')}% "
                    f"PF={fp.get('profit_factor','?')} "
                    f"DD={fp.get('max_drawdown_pct','?')}% "
                    f"robust={best.get('robust','?')}"
                )

    # ── Combined Summary ──
    logger.info("\n" + "=" * 80)
    logger.info("COMBINED PORTFOLIO SUMMARY")
    logger.info("=" * 80)

    total_weekly = 0
    total_annual = 0
    total_trades = 0
    winners = []

    for key, result in results["pairs"].items():
        if result.get("status") != "COMPLETE":
            logger.info(f"  {key}: ELIMINATED ({result.get('status', '?')})")
            continue

        for r in result.get("results", []):
            if not r.get("robust"):
                continue
            fp = r.get("full_period", {})
            w = fp.get("weekly_return_pct", 0)
            t = fp.get("total_trades", 0)
            total_weekly += w
            total_trades += t
            winners.append({
                "key": key,
                "weekly_pct": w,
                "total_return_pct": fp.get("total_return_pct", 0),
                "profit_factor": fp.get("profit_factor", 0),
                "max_dd_pct": fp.get("max_drawdown_pct", 0),
                "win_rate": fp.get("win_rate", 0),
                "trades": t,
                "params": r["params"],
                "robust": True,
                "robustness_rate": r.get("robustness_rate", 0),
                "train_weekly": r.get("train", {}).get("weekly_return_pct", 0),
                "test_weekly": r.get("test", {}).get("weekly_return_pct", 0),
            })
            logger.info(
                f"  {key}: +{w}%/week | PF={fp.get('profit_factor', 0)} | "
                f"DD={fp.get('max_drawdown_pct', 0)}% | trades={t} | "
                f"train={r.get('train', {}).get('weekly_return_pct', '?')}%/w -> test={r.get('test', {}).get('weekly_return_pct', '?')}%/w"
            )

    total_annual = total_weekly * 52
    results["combined"] = {
        "total_weekly_pct": round(total_weekly, 3),
        "total_annual_pct": round(total_annual, 1),
        "total_trades": total_trades,
        "winners": winners,
        "data_source": "TradingView Pro (FXCM)",
        "method": "Multi-Timeframe (H1 indicators + M30 execution)",
    }

    logger.info(f"\n  TOTAL PORTFOLIO: +{total_weekly:.3f}%/week ({total_annual:.1f}%/year) | {total_trades} trades")
    logger.info(f"  Strategies robustes: {len(winners)}")

    elapsed = time.time() - t0
    results["elapsed_sec"] = round(elapsed, 1)
    results["elapsed_min"] = round(elapsed / 60, 1)

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nResults saved to {RESULTS_FILE}")
    logger.info(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
