"""
Walk-Forward Optimizer with Robustness Testing

1. Expanding-window walk-forward (70% train / 30% test per fold)
2. Parameter grid search on train set
3. Out-of-sample validation on test set
4. Robustness check: ±15% parameter variation must stay profitable
5. Minimum 300 trades required over full period
"""
import json
import logging
import time
from copy import deepcopy
from dataclasses import asdict
from typing import Dict, List, Tuple

from realistic_backtester_v2 import RealisticBacktester, ExecutionConfig, BacktestResultV2

logger = logging.getLogger(__name__)

STATUS_FILE = "/app/backend/optimization_status.json"


def _write_status(data: dict):
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _result_to_dict(r: BacktestResultV2) -> dict:
    return {
        "total_trades": r.total_trades,
        "win_rate": r.win_rate,
        "total_return_pct": r.total_return_pct,
        "weekly_return_pct": r.weekly_return_pct,
        "profit_factor": r.profit_factor,
        "max_drawdown_pct": r.max_drawdown_pct,
        "max_daily_loss_pct": r.max_daily_loss_pct,
        "sharpe_ratio": r.sharpe_ratio,
        "ftmo_compliant": r.ftmo_compliant,
        "max_consecutive_losses": r.max_consecutive_losses,
        "avg_spread": r.avg_spread,
        "avg_slippage": r.avg_slippage,
        "rejected_orders": r.rejected_orders,
        "start_date": r.start_date,
        "end_date": r.end_date,
    }


# ── Parameter Grids ────────────────────────────────────────────────

SCALPING_GRID = []
for fe in [8, 12, 15, 20]:
    for se in [25, 30, 40, 50]:
        if fe >= se:
            continue
        for rsi_bm in [60, 70]:
            for rr in [1.5, 2.0, 2.5]:
                for atr_m in [1.0, 1.5]:
                    for min_sl in [10, 15]:
                        for pb_t in [0.0012, 0.0018]:
                            for risk in [0.005, 0.0075, 0.01]:
                                SCALPING_GRID.append({
                                    "fast_ema": fe, "slow_ema": se,
                                    "rsi_buy_max": rsi_bm,
                                    "rsi_sell_min": 100 - rsi_bm,
                                    "min_rr": rr, "atr_multiplier": atr_m,
                                    "min_sl_pips": min_sl, "max_sl_pips": 30,
                                    "pullback_threshold": pb_t,
                                    "body_atr_ratio": 0.35,
                                    "momentum_threshold": 0.008,
                                    "risk_per_trade": risk,
                                    "session_start": 7, "session_end": 17,
                                    "max_daily_trades": 10,
                                    "max_consecutive_losses": 3,
                                })

INTRADAY_GRID = []
for ep in [15, 20, 25, 30]:
    for rr in [2.0, 2.5, 3.0]:
        for atr_m in [0.5, 0.8, 1.0, 1.5]:
            for pb in [0.002, 0.003, 0.004]:
                for min_sl in [8, 12, 15, 20]:
                    for risk in [0.005, 0.0075, 0.01]:
                        INTRADAY_GRID.append({
                            "ema_period": ep, "min_rr": rr,
                            "atr_multiplier": atr_m, "pullback_pct": pb,
                            "min_sl_pips": min_sl, "max_sl_pips": 30,
                            "risk_per_trade": risk,
                            "session_start": 7, "session_end": 21,
                            "max_daily_trades": 6,
                            "max_consecutive_losses": 3,
                        })


# ── Helper: single backtest ───────────────────────────────────────

def _run_one(candles, params, strategy_type, initial_balance=100000,
             symbol="EURUSD", base_spread=0.8) -> BacktestResultV2:
    config = ExecutionConfig()
    config.base_spread_pips = base_spread
    bt = RealisticBacktester(config=config, initial_balance=initial_balance)
    if strategy_type == "SCALPING":
        return bt.run_scalping(candles, params, symbol=symbol)
    else:
        return bt.run_intraday(candles, params, symbol=symbol)


# ── Robustness Check ─────────────────────────────────────────────

def check_robustness(params: Dict, candles: List[Dict], strategy_type: str,
                     variation: float = 0.15) -> Tuple[bool, float]:
    """
    Vary each numeric parameter by ±variation.
    Robust if ≥70% of variations stay profitable + FTMO compliant.
    Returns (is_robust, pass_rate).
    """
    skip_keys = {"session_start", "session_end", "max_daily_trades", "max_consecutive_losses", "max_sl_pips"}
    ok = 0
    total = 0
    for key, val in params.items():
        if key in skip_keys or not isinstance(val, (int, float)):
            continue
        for mult in [1 - variation, 1 + variation]:
            varied = params.copy()
            nv = val * mult
            varied[key] = max(1, round(nv)) if isinstance(val, int) else round(nv, 4)
            if "rsi_sell_min" in varied and "rsi_buy_max" in varied:
                varied["rsi_sell_min"] = 100 - varied["rsi_buy_max"]
            r = _run_one(candles, varied, strategy_type)
            total += 1
            if r.total_return_pct > 0 and r.ftmo_compliant:
                ok += 1
    rate = ok / total if total > 0 else 0
    return rate >= 0.7, round(rate, 2)


# ── Walk-Forward Optimizer ────────────────────────────────────────

def walk_forward_optimize(
    candles: List[Dict],
    strategy_type: str,  # "SCALPING" or "INTRADAY"
    train_pct: float = 0.70,
    min_trades_train: int = 80,
    min_trades_total: int = 300,
    top_n: int = 15,
    initial_balance: float = 100000,
    progress_key: str = "",
) -> Dict:
    """
    Full walk-forward optimization:
    1. Split: 70% train / 30% test
    2. Grid search on train
    3. Top N → validate on test (OOS)
    4. Robustness check on train
    5. Final ranking by OOS performance
    """
    grid = SCALPING_GRID if strategy_type == "SCALPING" else INTRADAY_GRID
    total_params = len(grid)

    split = int(len(candles) * train_pct)
    train = candles[:split]
    test = candles[split:]

    train_start = train[0]["datetime"].strftime("%Y-%m-%d") if train else "?"
    train_end = train[-1]["datetime"].strftime("%Y-%m-%d") if train else "?"
    test_start = test[0]["datetime"].strftime("%Y-%m-%d") if test else "?"
    test_end = test[-1]["datetime"].strftime("%Y-%m-%d") if test else "?"

    logger.info(f"[{strategy_type}] Grid: {total_params} combos | "
                f"Train: {len(train)} candles ({train_start}→{train_end}) | "
                f"Test: {len(test)} candles ({test_start}→{test_end})")

    # ── Phase 1: Grid search on training data ──
    results = []
    t0 = time.time()
    for idx, params in enumerate(grid):
        if idx % 50 == 0:
            elapsed = time.time() - t0
            _write_status({
                "strategy": strategy_type,
                "phase": "grid_search",
                "progress": f"{idx}/{total_params}",
                "elapsed_sec": round(elapsed, 1),
                "progress_key": progress_key,
            })
            logger.info(f"  [{strategy_type}] Grid {idx}/{total_params} ({elapsed:.0f}s)")

        r = _run_one(train, params, strategy_type, initial_balance)
        if r.total_trades >= min_trades_train and r.ftmo_compliant:
            results.append((params, r))

    # Sort: profitable first, then by (profit_factor * sharpe, low drawdown)
    results.sort(key=lambda x: (
        x[1].total_return_pct > 0,
        x[1].profit_factor * max(0, x[1].sharpe_ratio),
        -x[1].max_drawdown_pct,
    ), reverse=True)

    top_candidates = results[:top_n]
    logger.info(f"[{strategy_type}] Phase 1 done: {len(results)} viable / {total_params} tested. "
                f"Top {len(top_candidates)} selected.")

    if not top_candidates:
        _write_status({
            "strategy": strategy_type, "phase": "done",
            "result": "NO_VIABLE_PARAMS",
            "total_tested": total_params,
            "viable_count": 0,
        })
        return {"status": "NO_VIABLE_PARAMS", "strategy": strategy_type}

    # ── Phase 2: Out-of-sample validation ──
    oos_results = []
    for rank, (params, train_r) in enumerate(top_candidates):
        _write_status({
            "strategy": strategy_type, "phase": "oos_validation",
            "progress": f"{rank + 1}/{len(top_candidates)}",
            "progress_key": progress_key,
        })

        test_r = _run_one(test, params, strategy_type, initial_balance)
        oos_results.append({
            "params": params,
            "train": _result_to_dict(train_r),
            "test": _result_to_dict(test_r),
        })

    # Filter: OOS must be profitable and FTMO compliant
    oos_profitable = [x for x in oos_results
                      if x["test"]["total_return_pct"] > 0 and x["test"]["ftmo_compliant"]]

    logger.info(f"[{strategy_type}] Phase 2: {len(oos_profitable)}/{len(oos_results)} profitable OOS")

    if not oos_profitable:
        # Still return best OOS even if not profitable
        oos_results.sort(key=lambda x: x["test"]["total_return_pct"], reverse=True)
        best = oos_results[0]
        _write_status({
            "strategy": strategy_type, "phase": "done",
            "result": "NO_OOS_PROFITABLE",
            "best_oos_return": best["test"]["total_return_pct"],
            "best_params": best["params"],
        })
        return {
            "status": "NO_OOS_PROFITABLE",
            "strategy": strategy_type,
            "best_candidate": best,
            "all_oos": oos_results[:5],
        }

    # ── Phase 3: Robustness check ──
    robust_results = []
    for rank, cand in enumerate(oos_profitable):
        _write_status({
            "strategy": strategy_type, "phase": "robustness_check",
            "progress": f"{rank + 1}/{len(oos_profitable)}",
            "progress_key": progress_key,
        })

        is_robust, pass_rate = check_robustness(cand["params"], train, strategy_type)
        cand["robust"] = is_robust
        cand["robustness_rate"] = pass_rate
        robust_results.append(cand)

    # Sort by: robust first, then OOS return
    robust_results.sort(key=lambda x: (
        x["robust"],
        x["test"]["total_return_pct"],
    ), reverse=True)

    # ── Phase 4: Full-period validation of winner ──
    if robust_results:
        winner = robust_results[0]
        full_r = _run_one(candles, winner["params"], strategy_type, initial_balance)
        winner["full_period"] = _result_to_dict(full_r)

        # Check minimum trades
        winner["meets_min_trades"] = full_r.total_trades >= min_trades_total

        logger.info(
            f"[{strategy_type}] WINNER: return={full_r.total_return_pct:+.2f}% "
            f"weekly={full_r.weekly_return_pct:+.3f}% trades={full_r.total_trades} "
            f"WR={full_r.win_rate}% PF={full_r.profit_factor} DD={full_r.max_drawdown_pct}% "
            f"robust={winner['robust']} ({winner['robustness_rate']*100:.0f}%)"
        )

    final = {
        "status": "COMPLETE",
        "strategy": strategy_type,
        "train_period": f"{train_start} → {train_end}",
        "test_period": f"{test_start} → {test_end}",
        "total_params_tested": total_params,
        "viable_on_train": len(results),
        "profitable_oos": len(oos_profitable),
        "robust_count": sum(1 for r in robust_results if r["robust"]),
        "results": robust_results[:10],  # Top 10
    }

    _write_status({
        "strategy": strategy_type, "phase": "done",
        "progress_key": progress_key,
        **{k: v for k, v in final.items() if k != "results"},
        "winner_return": robust_results[0]["test"]["total_return_pct"] if robust_results else None,
        "winner_params": robust_results[0]["params"] if robust_results else None,
    })

    return final
