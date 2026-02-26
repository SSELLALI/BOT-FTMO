#!/usr/bin/env python3
"""
Runner: Swing Trading Walk-Forward Optimization

Tests BOUNCE, BREAKOUT, COMBINED on GBPJPY, AUDCAD, USDJPY
using D1 (trend) + H4 (signals) + H2 (execution) data from TradingView.

Outputs:
  - Per-pair/strategy JSON results in optimization_results/
  - Summary JSON with all results
  - Human-readable log
"""
import os
import sys
import json
import logging
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from tradingview_loader import load_tradingview_csv
from walkforward_optimizer_swing import walk_forward_optimize_swing

# ── Logging ──
LOG_FILE = "/app/backend/swing_optimization.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

RESULTS_DIR = "/app/backend/optimization_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# ── Configuration ──
PAIRS = [
    {"symbol": "GBPJPY", "base_spread": 2.5},
    {"symbol": "AUDCAD", "base_spread": 1.5},
    {"symbol": "USDJPY", "base_spread": 1.8},
]
STRATEGY_TYPES = ["BOUNCE", "BREAKOUT", "COMBINED"]
DATA_DIR = "/app/backend/historical_data"


def load_pair_data(symbol):
    """Load and validate D1, H4, H2 data for a symbol."""
    d1 = load_tradingview_csv(os.path.join(DATA_DIR, f"{symbol}_D1_TV.csv"))
    h4 = load_tradingview_csv(os.path.join(DATA_DIR, f"{symbol}_H4_TV.csv"))
    h2 = load_tradingview_csv(os.path.join(DATA_DIR, f"{symbol}_H2_TV.csv"))

    if not d1 or not h4:
        logger.error(f"CRITICAL: Missing D1 or H4 data for {symbol}")
        return None, None, None

    # Validate data integrity
    for name, candles in [("D1", d1), ("H4", h4), ("H2", h2)]:
        if not candles:
            continue
        # Check monotonic timestamps
        for i in range(1, len(candles)):
            if candles[i]["datetime"] <= candles[i-1]["datetime"]:
                logger.error(f"NON-MONOTONIC timestamp at index {i} in {symbol}_{name}")
                return None, None, None
        # Check for zero prices
        zeros = sum(1 for c in candles if c["close"] <= 0 or c["high"] <= 0)
        if zeros > 0:
            logger.error(f"ZERO PRICES found in {symbol}_{name}: {zeros} candles")
            return None, None, None

    logger.info(f"[{symbol}] Data loaded: D1={len(d1)} H4={len(h4)} H2={len(h2) if h2 else 0}")
    return d1, h4, h2


def run_optimization():
    """Run full swing optimization across all pairs and strategies."""
    t_start = time.time()
    logger.info("=" * 70)
    logger.info("SWING TRADING WALK-FORWARD OPTIMIZATION")
    logger.info(f"Pairs: {[p['symbol'] for p in PAIRS]}")
    logger.info(f"Strategies: {STRATEGY_TYPES}")
    logger.info(f"Start: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 70)

    all_results = {}
    summary_winners = []

    for pair_cfg in PAIRS:
        symbol = pair_cfg["symbol"]
        base_spread = pair_cfg["base_spread"]

        logger.info(f"\n{'='*50}")
        logger.info(f"PROCESSING: {symbol} (spread={base_spread})")
        logger.info(f"{'='*50}")

        d1, h4, h2 = load_pair_data(symbol)
        if d1 is None or h4 is None:
            logger.error(f"SKIPPING {symbol}: data load failed")
            all_results[symbol] = {"status": "DATA_ERROR"}
            continue

        pair_results = {}

        for strat in STRATEGY_TYPES:
            logger.info(f"\n--- {symbol} / {strat} ---")
            t_strat = time.time()

            result = walk_forward_optimize_swing(
                h4_candles=h4,
                d1_candles=d1,
                h2_candles=h2,
                strategy_type=strat,
                train_pct=0.70,
                min_trades_train=12,
                min_trades_total=20,
                top_n=20,
                initial_balance=100000,
                symbol=symbol,
                base_spread=base_spread,
                progress_key=f"{symbol}_{strat}",
            )

            elapsed = round(time.time() - t_strat, 1)
            logger.info(f"[{symbol}/{strat}] Completed in {elapsed}s — Status: {result['status']}")

            # Save per-strategy result
            result_file = os.path.join(RESULTS_DIR, f"swing_{symbol}_{strat}.json")
            with open(result_file, "w") as f:
                json.dump(result, f, indent=2, default=str)
            logger.info(f"  Saved: {result_file}")

            pair_results[strat] = result

            # Track winners
            if result["status"] == "COMPLETE" and result.get("robust_count", 0) > 0:
                for r in result["results"]:
                    if r["robust"]:
                        summary_winners.append({
                            "symbol": symbol,
                            "strategy": strat,
                            "weekly_return": r["full_period"]["weekly_return_pct"],
                            "total_return": r["full_period"]["total_return_pct"],
                            "trades": r["full_period"]["total_trades"],
                            "win_rate": r["full_period"]["win_rate"],
                            "profit_factor": r["full_period"]["profit_factor"],
                            "max_dd": r["full_period"]["max_drawdown_pct"],
                            "ftmo_compliant": r["full_period"]["ftmo_compliant"],
                            "robustness": r["robustness_rate"],
                            "params": r["params"],
                        })

        all_results[symbol] = pair_results

    # ── Summary ──
    total_elapsed = round(time.time() - t_start, 1)
    summary_winners.sort(key=lambda x: x["weekly_return"], reverse=True)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_elapsed_sec": total_elapsed,
        "pairs_tested": [p["symbol"] for p in PAIRS],
        "strategies_tested": STRATEGY_TYPES,
        "total_robust_winners": len(summary_winners),
        "winners": summary_winners,
        "per_pair_status": {
            sym: {
                strat: {
                    "status": res.get("status", "?"),
                    "grid_size": res.get("total_params_tested", 0),
                    "viable_train": res.get("viable_on_train", 0),
                    "profitable_oos": res.get("profitable_oos", 0),
                    "robust": res.get("robust_count", 0),
                }
                for strat, res in pair_res.items()
            } if isinstance(pair_res, dict) and "status" not in pair_res else {"error": str(pair_res)}
            for sym, pair_res in all_results.items()
        },
    }

    summary_file = os.path.join(RESULTS_DIR, "swing_optimization_summary.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    # ── Final Report ──
    logger.info("\n" + "=" * 70)
    logger.info("OPTIMIZATION COMPLETE")
    logger.info(f"Total time: {total_elapsed}s ({total_elapsed/60:.1f} min)")
    logger.info(f"Total robust winners: {len(summary_winners)}")
    logger.info("=" * 70)

    if summary_winners:
        logger.info("\nTOP WINNERS (sorted by weekly return):")
        for i, w in enumerate(summary_winners[:10]):
            logger.info(
                f"  #{i+1}: {w['symbol']}/{w['strategy']} — "
                f"Weekly: +{w['weekly_return']}% | Total: +{w['total_return']}% | "
                f"Trades: {w['trades']} | WR: {w['win_rate']}% | PF: {w['profit_factor']} | "
                f"DD: {w['max_dd']}% | FTMO: {'OK' if w['ftmo_compliant'] else 'FAIL'} | "
                f"Robust: {w['robustness']*100:.0f}%"
            )
    else:
        logger.info("\nAUCUN GAGNANT ROBUSTE TROUVÉ.")
        logger.info("Analyse des résultats par paire:")
        for sym, pair_res in all_results.items():
            if isinstance(pair_res, dict) and "status" not in pair_res:
                for strat, res in pair_res.items():
                    logger.info(f"  {sym}/{strat}: status={res.get('status')} "
                                f"viable_train={res.get('viable_on_train', 0)} "
                                f"profitable_oos={res.get('profitable_oos', 0)}")

    logger.info(f"\nResults saved to: {summary_file}")
    return summary


if __name__ == "__main__":
    run_optimization()
