#!/usr/bin/env python3
"""
Multi-Pair Optimization Runner
Runs walk-forward for SCALPING and INTRADAY on EURUSD, GBPUSD, AUDUSD, USDJPY
Then calculates combined performance.
"""
import json
import logging
import sys
import os
import time
import copy

sys.path.insert(0, os.path.dirname(__file__))

from historical_data_loader import load_candles_from_csv
from walkforward_optimizer import walk_forward_optimize
from realistic_backtester_v2 import RealisticBacktester, ExecutionConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/backend/multipair_optimization.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)

RESULTS_FILE = "/app/backend/multipair_results.json"
STATUS_FILE = "/app/backend/optimization_status.json"

# Pair-specific configurations
PAIR_CONFIGS = {
    "EURUSD": {"base_spread": 0.8, "pip_mult": 10000},
    "GBPUSD": {"base_spread": 1.2, "pip_mult": 10000},
    "AUDUSD": {"base_spread": 1.0, "pip_mult": 10000},
    "USDJPY": {"base_spread": 1.0, "pip_mult": 100},
}


def write_status(data):
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def run_pair_optimization(pair, candles, strategy_type, base_spread):
    """Run optimization for a single pair with pair-specific spread."""
    result = walk_forward_optimize(
        candles=candles,
        strategy_type=strategy_type,
        train_pct=0.70,
        min_trades_train=80,
        min_trades_total=300,
        top_n=10,
        progress_key=f"{pair}_{strategy_type.lower()}",
        symbol=pair,
        base_spread=base_spread,
    )
    return result


def validate_on_full_data(pair, candles, params, strategy_type, base_spread):
    """Run a single backtest with optimized params on full data."""
    config = ExecutionConfig()
    config.base_spread_pips = base_spread
    bt = RealisticBacktester(config=config, initial_balance=100000)

    if strategy_type == "SCALPING":
        r = bt.run_scalping(candles, params, symbol=pair)
    else:
        r = bt.run_intraday(candles, params, symbol=pair)

    return {
        "total_trades": r.total_trades,
        "win_rate": r.win_rate,
        "total_return_pct": r.total_return_pct,
        "weekly_return_pct": r.weekly_return_pct,
        "profit_factor": r.profit_factor,
        "max_drawdown_pct": r.max_drawdown_pct,
        "ftmo_compliant": r.ftmo_compliant,
        "sharpe_ratio": r.sharpe_ratio,
        "avg_spread": r.avg_spread,
        "avg_slippage": r.avg_slippage,
    }


def main():
    t_start = time.time()
    logger.info("=" * 60)
    logger.info("MULTI-PAIR OPTIMIZATION START")
    logger.info("=" * 60)

    write_status({"phase": "starting", "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})

    # Load all data
    pairs_data = {}
    for pair in ["EURUSD", "GBPUSD", "AUDUSD", "USDJPY"]:
        path = f"historical_data/{pair}_H1.csv"
        candles = load_candles_from_csv(path)
        if len(candles) > 2000:
            pairs_data[pair] = candles
            logger.info(f"{pair}: {len(candles)} candles loaded")
        else:
            logger.warning(f"{pair}: Only {len(candles)} candles, skipping")

    # Use existing EURUSD results if available
    existing_results = {}
    eurusd_file = "/app/backend/optimization_results.json"
    if os.path.exists(eurusd_file):
        with open(eurusd_file) as f:
            existing_results = json.load(f)
        logger.info("Loaded existing EURUSD optimization results")

    all_results = {}

    for pair in pairs_data:
        candles = pairs_data[pair]
        pair_cfg = PAIR_CONFIGS[pair]
        base_spread = pair_cfg["base_spread"]

        for strategy_type in ["SCALPING", "INTRADAY"]:
            key = f"{pair}_{strategy_type.lower()}"

            # Skip EURUSD if we already have results
            if pair == "EURUSD":
                existing_key = f"{strategy_type.lower()}_h1"
                if existing_key in existing_results:
                    all_results[key] = existing_results[existing_key]
                    logger.info(f"[{key}] Using existing results")
                    continue

            logger.info(f"{'='*60}")
            logger.info(f"[{key}] Optimizing... (spread={base_spread} pip)")
            logger.info(f"{'='*60}")

            write_status({
                "phase": "optimizing",
                "current_pair": pair,
                "current_strategy": strategy_type,
                "spread": base_spread,
            })

            result = run_pair_optimization(pair, candles, strategy_type, base_spread)
            all_results[key] = result

            if result.get("results"):
                best = result["results"][0]
                fp = best.get("full_period", best.get("test", {}))
                logger.info(
                    f"[{key}] RESULT: return={fp.get('total_return_pct', '?')}% "
                    f"weekly={fp.get('weekly_return_pct', '?')}%/w "
                    f"trades={fp.get('total_trades', '?')} "
                    f"robust={best.get('robust', '?')}"
                )

    # ── Calculate combined performance ──
    logger.info("=" * 60)
    logger.info("COMBINED PERFORMANCE ANALYSIS")
    logger.info("=" * 60)

    combined = {"scalping": {}, "intraday": {}, "total": {}}
    total_weekly = 0
    total_trades = 0

    for pair in pairs_data:
        for strategy in ["scalping", "intraday"]:
            key = f"{pair}_{strategy}"
            r = all_results.get(key, {})
            if r.get("results"):
                best = r["results"][0]
                fp = best.get("full_period", best.get("test", {}))
                wk = fp.get("weekly_return_pct", 0)
                tr = fp.get("total_trades", 0)

                combined[strategy][pair] = {
                    "weekly_pct": wk,
                    "total_return_pct": fp.get("total_return_pct", 0),
                    "trades": tr,
                    "win_rate": fp.get("win_rate", 0),
                    "profit_factor": fp.get("profit_factor", 0),
                    "max_dd": fp.get("max_drawdown_pct", 0),
                    "robust": best.get("robust", False),
                    "params": best.get("params"),
                }

                total_weekly += wk
                total_trades += tr

                logger.info(f"  {pair} {strategy}: {wk:+.3f}%/week, {tr} trades")

    combined["total"]["weekly_pct"] = round(total_weekly, 3)
    combined["total"]["annual_pct"] = round(total_weekly * 52, 1)
    combined["total"]["total_trades"] = total_trades

    logger.info(f"\nCOMBINED WEEKLY: {total_weekly:+.3f}%/week ({total_weekly*52:+.1f}%/year)")
    logger.info(f"COMBINED TRADES: {total_trades} over 2+ years")

    # Save
    final = {
        "pairs_tested": list(pairs_data.keys()),
        "pair_results": all_results,
        "combined": combined,
        "elapsed_sec": round(time.time() - t_start, 1),
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(final, f, indent=2, default=str)

    write_status({
        "phase": "COMPLETE",
        "type": "MULTI_PAIR",
        "elapsed_sec": round(time.time() - t_start, 1),
        "combined_weekly": round(total_weekly, 3),
        "combined_annual": round(total_weekly * 52, 1),
        "total_trades": total_trades,
        "pairs": list(pairs_data.keys()),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

    logger.info(f"\nCompleted in {(time.time() - t_start)/60:.1f} min")
    logger.info(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
