#!/usr/bin/env python3
"""
GBPJPY Walk-Forward Optimization

Runs full walk-forward optimization on GBPJPY using TradingView H1 data.
Applies the same 10 strict realism rules as EURUSD/USDJPY.
Adapts spread and pip values for GBPJPY characteristics.
"""
import json
import logging
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from tradingview_loader import load_tradingview_csv
from walkforward_optimizer import walk_forward_optimize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/backend/gbpjpy_optimization.log"),
    ]
)
logger = logging.getLogger(__name__)

RESULTS_FILE = "/app/backend/gbpjpy_optimization_results.json"
DATA_FILE = "/app/backend/historical_data/GBPJPY_H1_TV.csv"

# GBPJPY specific: higher base spread than EURUSD
# Typical GBPJPY spread on cTrader/FTMO: 1.5-2.5 pips
GBPJPY_BASE_SPREAD = 1.8


def main():
    logger.info("=" * 80)
    logger.info("GBPJPY WALK-FORWARD OPTIMIZATION")
    logger.info("Data source: TradingView Pro (FOREXCOM)")
    logger.info(f"Base spread: {GBPJPY_BASE_SPREAD} pips")
    logger.info("=" * 80)

    # Load TradingView H1 data
    candles = load_tradingview_csv(DATA_FILE)
    if not candles:
        logger.error("No data loaded. Aborting.")
        return

    logger.info(f"Loaded {len(candles)} H1 candles")
    logger.info(f"Period: {candles[0]['datetime']} -> {candles[-1]['datetime']}")
    days = (candles[-1]["datetime"] - candles[0]["datetime"]).days
    logger.info(f"Coverage: {days} days ({days/30.44:.1f} months)")

    results = {
        "pair": "GBPJPY",
        "data_source": "TradingView Pro (FOREXCOM)",
        "total_candles": len(candles),
        "period_start": candles[0]["datetime"].isoformat(),
        "period_end": candles[-1]["datetime"].isoformat(),
        "base_spread_pips": GBPJPY_BASE_SPREAD,
        "pair_results": {},
    }

    t0 = time.time()

    # ── SCALPING ──
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 1: SCALPING OPTIMIZATION")
    logger.info("=" * 60)

    scalp_result = walk_forward_optimize(
        candles=candles,
        strategy_type="SCALPING",
        train_pct=0.70,
        min_trades_train=60,
        min_trades_total=200,
        top_n=15,
        initial_balance=100000,
        progress_key="GBPJPY_scalping",
        symbol="GBPJPY",
        base_spread=GBPJPY_BASE_SPREAD,
    )
    results["pair_results"]["GBPJPY_scalping"] = scalp_result
    logger.info(f"Scalping done: {scalp_result.get('status', 'UNKNOWN')}")

    # ── INTRADAY ──
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 2: INTRADAY OPTIMIZATION")
    logger.info("=" * 60)

    intra_result = walk_forward_optimize(
        candles=candles,
        strategy_type="INTRADAY",
        train_pct=0.70,
        min_trades_train=60,
        min_trades_total=200,
        top_n=15,
        initial_balance=100000,
        progress_key="GBPJPY_intraday",
        symbol="GBPJPY",
        base_spread=GBPJPY_BASE_SPREAD,
    )
    results["pair_results"]["GBPJPY_intraday"] = intra_result
    logger.info(f"Intraday done: {intra_result.get('status', 'UNKNOWN')}")

    elapsed = time.time() - t0
    results["elapsed_sec"] = round(elapsed, 1)

    # ── Summary ──
    logger.info("\n" + "=" * 80)
    logger.info("GBPJPY OPTIMIZATION COMPLETE")
    logger.info(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    logger.info("=" * 80)

    for key in ["GBPJPY_scalping", "GBPJPY_intraday"]:
        r = results["pair_results"][key]
        status = r.get("status", "?")
        strat = key.split("_")[1].upper()
        logger.info(f"\n  {strat}: {status}")

        if status == "COMPLETE":
            robust_count = r.get("robust_count", 0)
            logger.info(f"    Params tested: {r.get('total_params_tested', 0)}")
            logger.info(f"    Viable on train: {r.get('viable_on_train', 0)}")
            logger.info(f"    Profitable OOS: {r.get('profitable_oos', 0)}")
            logger.info(f"    Robust: {robust_count}")

            if r.get("results"):
                best = r["results"][0]
                fp = best.get("full_period", best.get("test", {}))
                logger.info(f"    BEST: return={fp.get('total_return_pct', '?')}% "
                           f"weekly={fp.get('weekly_return_pct', '?')}% "
                           f"PF={fp.get('profit_factor', '?')} "
                           f"DD={fp.get('max_drawdown_pct', '?')}% "
                           f"robust={best.get('robust', '?')}")
        elif status == "NO_OOS_PROFITABLE":
            best = r.get("best_candidate", {})
            test = best.get("test", {})
            logger.info(f"    No OOS profitable. Best OOS return: {test.get('total_return_pct', '?')}%")

    # Save results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nResults saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
