"""
Walk-Forward Optimizer V2 — Multi-Timeframe Support

Runs walk-forward optimization using MTFBacktester (v3).
Splits both H1 and M30 data by the train/test boundary.
"""
import json
import time
import logging
import itertools
from datetime import timedelta

from realistic_backtester_v3 import MTFBacktester

logger = logging.getLogger(__name__)

# Status file for progress tracking
STATUS_FILE = "/app/backend/optimization_status.json"


def _write_status(data):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        pass


def _generate_grid(strategy_type):
    """Generate parameter grid for optimization."""
    if strategy_type == "SCALPING":
        return list(itertools.product(
            [10, 15, 20, 25],       # ema_period
            [2.0, 2.5, 3.0],        # min_rr
            [0.5, 0.75, 1.0],       # atr_multiplier
            [0.002, 0.003, 0.004],   # pullback_pct
            [5, 8, 10, 12, 15],     # min_sl_pips
            [15, 20, 30],           # max_sl_pips
            [0.005, 0.01],          # risk_per_trade
        ))
    else:  # INTRADAY
        return list(itertools.product(
            [15, 20, 25],           # ema_period
            [2.5, 3.0],             # min_rr
            [0.5, 0.75, 1.0],       # atr_multiplier
            [0.003, 0.004, 0.005],   # pullback_pct
            [8, 12, 15],            # min_sl_pips
            [20, 30],               # max_sl_pips
            [0.005, 0.01],          # risk_per_trade
        ))


def _params_from_tuple(t, strategy_type):
    if strategy_type == "SCALPING":
        return {
            "ema_period": t[0], "min_rr": t[1], "atr_multiplier": t[2],
            "pullback_pct": t[3], "min_sl_pips": t[4], "max_sl_pips": t[5],
            "risk_per_trade": t[6],
            "session_start": 7, "session_end": 20,
            "max_daily_trades": 5, "max_consecutive_losses": 3,
        }
    else:
        return {
            "ema_period": t[0], "min_rr": t[1], "atr_multiplier": t[2],
            "pullback_pct": t[3], "min_sl_pips": t[4], "max_sl_pips": t[5],
            "risk_per_trade": t[6],
            "session_start": 7, "session_end": 21,
            "max_daily_trades": 6, "max_consecutive_losses": 3,
        }


def walk_forward_optimize_mtf(
    h1_candles, m30_candles=None,
    strategy_type="SCALPING", train_pct=0.70,
    min_trades_train=60, min_trades_total=200,
    top_n=15, initial_balance=100000,
    progress_key="", symbol="EURUSD", base_spread=None
):
    """
    Walk-forward optimization with multi-timeframe backtester.
    """
    t0 = time.time()

    # ── Split H1 into train/test ──
    split = int(len(h1_candles) * train_pct)
    h1_train = h1_candles[:split]
    h1_test = h1_candles[split:]
    split_time = h1_candles[split]["datetime"]

    logger.info(f"[{strategy_type}] Split: train={len(h1_train)} h1 | test={len(h1_test)} h1 | split_time={split_time}")

    # Split M30 by the same timestamp
    m30_train = None
    m30_test = None
    if m30_candles:
        m30_train = [c for c in m30_candles if c["datetime"] < split_time]
        m30_test = [c for c in m30_candles if c["datetime"] >= split_time]
        logger.info(f"[{strategy_type}] M30: train={len(m30_train)} | test={len(m30_test)}")
        if len(m30_train) == 0:
            m30_train = None
        if len(m30_test) == 0:
            m30_test = None

    # ── Grid ──
    grid = _generate_grid(strategy_type)
    logger.info(f"[{strategy_type}] Grid: {len(grid)} combos | Train: {len(h1_train)} h1 candles")

    # ── Phase 1: Train ──
    train_results = []
    for idx, combo in enumerate(grid):
        if idx % 50 == 0:
            elapsed = time.time() - t0
            _write_status({
                "phase": "train_grid", "strategy": strategy_type,
                "progress": f"{idx}/{len(grid)}", "elapsed_sec": round(elapsed, 1),
                "progress_key": progress_key,
            })
            logger.info(f"  [{strategy_type}] Grid {idx}/{len(grid)} ({elapsed:.0f}s)")

        params = _params_from_tuple(combo, strategy_type)
        bt = MTFBacktester(initial_balance=initial_balance)
        result = bt.run(
            h1_candles=h1_train, strategy_type=strategy_type,
            params=params, symbol=symbol, base_spread=base_spread,
            m30_candles=m30_train,
        )

        if result.total_trades >= min_trades_train and result.total_return_pct > 0 and result.ftmo_compliant:
            train_results.append((params, result))

    train_results.sort(key=lambda x: x[1].weekly_return_pct, reverse=True)
    top = train_results[:top_n]
    logger.info(f"[{strategy_type}] Phase 1 done: {len(train_results)} viable / {len(grid)} tested. Top {len(top)} selected.")

    if not top:
        return {
            "status": "NO_VIABLE_TRAIN",
            "total_params_tested": len(grid),
            "viable_on_train": 0,
        }

    # ── Phase 2: OOS Test ──
    oos_results = []
    for params, train_res in top:
        bt = MTFBacktester(initial_balance=initial_balance)
        test_res = bt.run(
            h1_candles=h1_test, strategy_type=strategy_type,
            params=params, symbol=symbol, base_spread=base_spread,
            m30_candles=m30_test,
        )
        if test_res.total_return_pct > 0:
            oos_results.append((params, train_res, test_res))

    logger.info(f"[{strategy_type}] Phase 2: {len(oos_results)}/{len(top)} profitable OOS")

    if not oos_results:
        # Return best candidate anyway for reporting
        best_p, best_train = top[0]
        bt = MTFBacktester(initial_balance=initial_balance)
        best_test = bt.run(h1_candles=h1_test, strategy_type=strategy_type,
                           params=best_p, symbol=symbol, base_spread=base_spread,
                           m30_candles=m30_test)
        return {
            "status": "NO_OOS_PROFITABLE",
            "total_params_tested": len(grid),
            "viable_on_train": len(train_results),
            "profitable_oos": 0,
            "best_candidate": {
                "params": best_p,
                "train": _result_to_dict(best_train),
                "test": _result_to_dict(best_test),
            }
        }

    # ── Phase 3: Robustness Check ──
    final_results = []
    for params, train_res, test_res in oos_results:
        robust_count = 0
        total_checks = 12
        variations = [0.85, 0.90, 0.95, 1.05, 1.10, 1.15]
        tunable = ["ema_period", "atr_multiplier", "pullback_pct", "min_sl_pips"]

        for var_key in tunable[:3]:
            for mult in [0.85, 1.15]:
                varied = params.copy()
                orig = varied[var_key]
                varied[var_key] = type(orig)(orig * mult) if isinstance(orig, float) else max(1, int(orig * mult))

                bt = MTFBacktester(initial_balance=initial_balance)
                vr = bt.run(h1_candles=h1_train, strategy_type=strategy_type,
                            params=varied, symbol=symbol, base_spread=base_spread,
                            m30_candles=m30_train)
                if vr.total_return_pct > 0:
                    robust_count += 1

        robustness_rate = robust_count / total_checks if total_checks > 0 else 0
        is_robust = robustness_rate >= 0.7

        # Full period run
        bt = MTFBacktester(initial_balance=initial_balance)
        full_res = bt.run(
            h1_candles=h1_candles, strategy_type=strategy_type,
            params=params, symbol=symbol, base_spread=base_spread,
            m30_candles=m30_candles,
        )

        entry = {
            "params": params,
            "train": _result_to_dict(train_res),
            "test": _result_to_dict(test_res),
            "full_period": _result_to_dict(full_res),
            "robust": is_robust,
            "robustness_rate": round(robustness_rate, 2),
        }
        final_results.append(entry)

        if is_robust:
            logger.info(
                f"[{strategy_type}] WINNER: return=+{full_res.total_return_pct}% "
                f"weekly=+{full_res.weekly_return_pct}% trades={full_res.total_trades} "
                f"WR={full_res.win_rate}% PF={full_res.profit_factor} DD={full_res.max_drawdown_pct}% "
                f"robust={is_robust} ({robustness_rate*100:.0f}%)"
            )

    final_results.sort(key=lambda x: (x["robust"], x["full_period"]["weekly_return_pct"]), reverse=True)
    robust_count = sum(1 for r in final_results if r["robust"])

    return {
        "status": "COMPLETE",
        "total_params_tested": len(grid),
        "viable_on_train": len(train_results),
        "profitable_oos": len(oos_results),
        "robust_count": robust_count,
        "results": final_results,
    }


def _result_to_dict(r):
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
        "start_date": r.start_date,
        "end_date": r.end_date,
        "avg_trade_pnl": r.avg_trade_pnl,
    }
