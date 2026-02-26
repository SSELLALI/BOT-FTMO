#!/usr/bin/env python3
"""
Price Action Walk-Forward Optimization — All Pairs
TradingView Data + MTF (H1 indicators + M30 execution)

Strategies: BOUNCE (S/R rejection) + BREAKOUT (S/R breakout)
Pairs: EURUSD, USDJPY, GBPJPY
"""
import json
import logging
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from tradingview_loader import load_tradingview_csv
from walkforward_optimizer_pa import walk_forward_optimize_pa

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/backend/pa_optimization.log"),
    ]
)
logger = logging.getLogger(__name__)

RESULTS_FILE = "/app/backend/pa_optimization_results.json"
DATA_DIR = "/app/backend/historical_data"

PAIRS = [
    {"symbol": "EURUSD", "h1": f"{DATA_DIR}/EURUSD_H1_TV.csv", "m30": f"{DATA_DIR}/EURUSD_M30_TV.csv", "spread": 0.8},
    {"symbol": "USDJPY", "h1": f"{DATA_DIR}/USDJPY_H1_TV.csv", "m30": f"{DATA_DIR}/USDJPY_M30_TV.csv", "spread": 0.9},
    {"symbol": "GBPJPY", "h1": f"{DATA_DIR}/GBPJPY_H1_TV.csv", "m30": f"{DATA_DIR}/GBPJPY_M30_TV.csv", "spread": 1.8},
]

STRATEGIES = ["BOUNCE", "BREAKOUT"]


def main():
    logger.info("=" * 80)
    logger.info("PRICE ACTION OPTIMIZATION — S/R + Candlestick Patterns + Chartism")
    logger.info("TradingView Data + MTF (H1 indicators + M30 execution)")
    logger.info("=" * 80)

    results = {"pairs": {}, "combined": {}}
    t0 = time.time()

    for pair_cfg in PAIRS:
        symbol = pair_cfg["symbol"]
        base_spread = pair_cfg["spread"]

        logger.info(f"\n{'='*60}")
        logger.info(f"PAIR: {symbol} (spread={base_spread} pips)")
        logger.info(f"{'='*60}")

        h1 = load_tradingview_csv(pair_cfg["h1"])
        m30 = load_tradingview_csv(pair_cfg["m30"])

        if not h1:
            logger.error(f"{symbol}: No H1 data. Skipping.")
            continue

        logger.info(f"{symbol} H1: {len(h1)} | M30: {len(m30) if m30 else 0}")

        for strat in STRATEGIES:
            key = f"{symbol}_{strat.lower()}"
            logger.info(f"\n--- {symbol} {strat} ---")

            result = walk_forward_optimize_pa(
                h1_candles=h1,
                m30_candles=m30,
                strategy_type=strat,
                train_pct=0.70,
                min_trades_train=40,
                min_trades_total=100,
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
                    f"PF={fp.get('profit_factor','?')} DD={fp.get('max_drawdown_pct','?')}% "
                    f"robust={best.get('robust','?')}"
                )

    # Combined Summary
    logger.info("\n" + "=" * 80)
    logger.info("COMBINED PORTFOLIO SUMMARY — PRICE ACTION")
    logger.info("=" * 80)

    total_weekly = 0
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
            total_weekly += w
            total_trades += fp.get("total_trades", 0)
            winners.append({
                "key": key, "weekly_pct": w,
                "total_return_pct": fp.get("total_return_pct", 0),
                "profit_factor": fp.get("profit_factor", 0),
                "max_dd_pct": fp.get("max_drawdown_pct", 0),
                "win_rate": fp.get("win_rate", 0),
                "trades": fp.get("total_trades", 0),
                "params": r["params"],
                "train_weekly": r.get("train", {}).get("weekly_return_pct", 0),
                "test_weekly": r.get("test", {}).get("weekly_return_pct", 0),
            })
            logger.info(
                f"  WINNER {key}: +{w}%/week PF={fp.get('profit_factor',0)} "
                f"DD={fp.get('max_drawdown_pct',0)}% trades={fp.get('total_trades',0)} "
                f"train={r.get('train',{}).get('weekly_return_pct','?')}%/w -> test={r.get('test',{}).get('weekly_return_pct','?')}%/w"
            )

    results["combined"] = {
        "total_weekly_pct": round(total_weekly, 3),
        "total_annual_pct": round(total_weekly * 52, 1),
        "total_trades": total_trades,
        "winners": winners,
        "data_source": "TradingView Pro (FXCM)",
        "method": "Price Action (S/R + Candlestick Patterns) + MTF (H1+M30)",
    }

    elapsed = time.time() - t0
    results["elapsed_sec"] = round(elapsed, 1)

    logger.info(f"\n  TOTAL: +{total_weekly:.3f}%/week | {len(winners)} strategies robustes")
    logger.info(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
