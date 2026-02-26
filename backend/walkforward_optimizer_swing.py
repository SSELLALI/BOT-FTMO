"""
Walk-Forward Optimizer for Swing Trading Strategy (D1 + H4 + H2)

3-phase validation:
  Phase 1: Grid search on TRAIN set (70% H4 timeline)
  Phase 2: Out-of-sample (OOS) test on remaining 30%
  Phase 3: Robustness check (parameter perturbation on train)
  Final: Full-period run for validated strategies

Strict rules:
  - min_rr ALWAYS >= 2.5 (no exceptions)
  - Walk-forward split on H4 timeline, H2/D1 aligned to same date
  - No lookahead: D1 referenced only via completed candles
"""
import json
import time
import logging
import itertools

from swing_backtester import SwingBacktester

logger = logging.getLogger(__name__)
STATUS_FILE = "/app/backend/optimization_status.json"


def _write_status(data):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        pass


def _generate_swing_grid(strategy_type):
    """Generate parameter grid for swing strategies with higher-TF-appropriate ranges.
    
    Grid size per strategy:
      BOUNCE/COMBINED: 384 combos
      BREAKOUT: 768 combos (x2 for sr_break_pips)
    Total per pair: 1536 combos → estimated ~25 min
    """
    base = list(itertools.product(
        [8, 12],              # d1_swing_lookback (2)
        [12, 18],             # h4_swing_lookback (2)
        [40, 65],             # sr_cluster_pips (2)
        [25, 45],             # sr_proximity_pips (2)
        [2.5, 3.0, 3.5],     # min_rr (3) — STRICT >= 2.5
        [25, 40],             # min_sl_pips (2)
        [100, 150],           # max_sl_pips (2)
        [0.005, 0.008],       # risk_per_trade (2)
    ))

    if strategy_type == "BREAKOUT":
        expanded = []
        for combo in base:
            for break_pips in [15, 25]:
                expanded.append(combo + (break_pips,))
        return expanded

    return [combo + (0,) for combo in base]


def _params_from_tuple(t, strategy_type):
    return {
        "d1_swing_lookback": t[0],
        "h4_swing_lookback": t[1],
        "sr_cluster_pips": t[2],
        "sr_proximity_pips": t[3],
        "min_rr": t[4],
        "min_sl_pips": t[5],
        "max_sl_pips": t[6],
        "risk_per_trade": t[7],
        "sr_break_pips": t[8] if strategy_type == "BREAKOUT" else 20,
        "sl_buffer_pips": 10,
        "min_zone_strength": 2,
        "max_hold_bars": 96,       # ~8 days in H2 candles
        "max_daily_trades": 3,
        "max_consecutive_losses": 2,
    }


def _split_candles_by_time(candles, split_time):
    """Split candle list at a given datetime. No lookahead."""
    train = [c for c in candles if c["datetime"] < split_time]
    test = [c for c in candles if c["datetime"] >= split_time]
    return train, test


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


def walk_forward_optimize_swing(
    h4_candles, d1_candles, h2_candles=None,
    strategy_type="BOUNCE", train_pct=0.70,
    min_trades_train=15, min_trades_total=30,
    top_n=20, initial_balance=100000,
    symbol="USDJPY", base_spread=None,
    progress_key="",
):
    """
    Run walk-forward optimization for swing trading strategy.

    Args:
        h4_candles: H4 OHLC candles (primary timeframe for S/R + signals)
        d1_candles: D1 OHLC candles (trend/structure)
        h2_candles: H2 OHLC candles (execution precision, optional)
        strategy_type: BOUNCE, BREAKOUT, or COMBINED
        train_pct: Fraction of H4 data for training
        min_trades_train: Min trades required in train to be viable
        min_trades_total: Min trades across full period
        top_n: Number of top train performers to test OOS
        initial_balance: Starting balance
        symbol: Trading pair
        base_spread: Base spread in pips
        progress_key: Key for status file

    Returns:
        Dict with optimization results
    """
    t0 = time.time()

    # ── Walk-Forward Split (based on H4 timeline) ──
    split_idx = int(len(h4_candles) * train_pct)
    split_time = h4_candles[split_idx]["datetime"]

    h4_train = h4_candles[:split_idx]
    h4_test = h4_candles[split_idx:]

    # Align D1 and H2 to the same split point
    d1_train, d1_test_only = _split_candles_by_time(d1_candles, split_time)
    # For test: D1 needs FULL history before split_time + test period for trend detection
    d1_test = d1_candles  # D1 test uses all D1 data (no lookahead: backtester uses confirmed candles only)

    h2_train, h2_test = None, None
    if h2_candles:
        h2_train, h2_test = _split_candles_by_time(h2_candles, split_time)
        if len(h2_train) < 100:
            h2_train = None
        if h2_test and len(h2_test) < 100:
            h2_test = None

    logger.info(f"[{symbol}/{strategy_type}] WF Split at {split_time.date()}")
    logger.info(f"  H4: train={len(h4_train)} | test={len(h4_test)}")
    logger.info(f"  D1: train={len(d1_train)} | test(full)={len(d1_test)}")
    if h2_candles:
        logger.info(f"  H2: train={len(h2_train) if h2_train else 0} | test={len(h2_test) if h2_test else 0}")

    # ── Parameter Grid ──
    grid = _generate_swing_grid(strategy_type)
    logger.info(f"[{symbol}/{strategy_type}] Grid: {len(grid)} parameter combinations")

    # ═══════════════════════════════════════════════
    # PHASE 1: Train Grid Search
    # ═══════════════════════════════════════════════
    train_results = []
    for idx, combo in enumerate(grid):
        if idx % 100 == 0:
            elapsed = time.time() - t0
            _write_status({
                "phase": "train_grid", "strategy": strategy_type, "symbol": symbol,
                "progress": f"{idx}/{len(grid)}", "elapsed_sec": round(elapsed, 1),
                "progress_key": progress_key,
            })
            logger.info(f"  [{symbol}/{strategy_type}] Grid {idx}/{len(grid)} ({elapsed:.0f}s)")

        params = _params_from_tuple(combo, strategy_type)

        # STRICT: Enforce min_rr >= 2.5
        if params["min_rr"] < 2.5:
            continue

        bt = SwingBacktester(initial_balance=initial_balance)
        result = bt.run(
            h4_candles=h4_train, d1_candles=d1_train,
            strategy_type=strategy_type, params=params,
            symbol=symbol, base_spread=base_spread,
            h2_candles=h2_train,
        )

        if (result.total_trades >= min_trades_train
                and result.total_return_pct > 0
                and result.ftmo_compliant):
            train_results.append((params, result))

    train_results.sort(key=lambda x: x[1].weekly_return_pct, reverse=True)
    top = train_results[:top_n]
    logger.info(f"[{symbol}/{strategy_type}] Phase 1 done: {len(train_results)} viable / {len(grid)} tested. Top {len(top)} selected.")

    if not top:
        return {
            "status": "NO_VIABLE_TRAIN",
            "symbol": symbol,
            "strategy_type": strategy_type,
            "total_params_tested": len(grid),
            "viable_on_train": 0,
            "elapsed_sec": round(time.time() - t0, 1),
        }

    # ═══════════════════════════════════════════════
    # PHASE 2: Out-of-Sample Test
    # ═══════════════════════════════════════════════
    logger.info(f"[{symbol}/{strategy_type}] Phase 2: Testing top {len(top)} on OOS...")
    oos_results = []
    for params, train_res in top:
        bt = SwingBacktester(initial_balance=initial_balance)
        test_res = bt.run(
            h4_candles=h4_test, d1_candles=d1_test,
            strategy_type=strategy_type, params=params,
            symbol=symbol, base_spread=base_spread,
            h2_candles=h2_test,
        )
        # OOS must also be profitable
        if test_res.total_return_pct > 0 and test_res.total_trades >= 5:
            oos_results.append((params, train_res, test_res))

    logger.info(f"[{symbol}/{strategy_type}] Phase 2: {len(oos_results)}/{len(top)} profitable OOS")

    if not oos_results:
        best_p, best_train = top[0]
        bt = SwingBacktester(initial_balance=initial_balance)
        best_test = bt.run(
            h4_candles=h4_test, d1_candles=d1_test,
            strategy_type=strategy_type, params=best_p,
            symbol=symbol, base_spread=base_spread,
            h2_candles=h2_test,
        )
        return {
            "status": "NO_OOS_PROFITABLE",
            "symbol": symbol,
            "strategy_type": strategy_type,
            "total_params_tested": len(grid),
            "viable_on_train": len(train_results),
            "profitable_oos": 0,
            "elapsed_sec": round(time.time() - t0, 1),
            "best_candidate": {
                "params": best_p,
                "train": _result_to_dict(best_train),
                "test": _result_to_dict(best_test),
            }
        }

    # ═══════════════════════════════════════════════
    # PHASE 3: Robustness Check (parameter perturbation)
    # ═══════════════════════════════════════════════
    logger.info(f"[{symbol}/{strategy_type}] Phase 3: Robustness testing {len(oos_results)} candidates...")
    final_results = []

    # Parameters to perturb for robustness
    tunable_keys = ["h4_swing_lookback", "sr_cluster_pips", "sr_proximity_pips", "min_sl_pips"]
    perturbation_factors = [0.80, 1.20]  # +/- 20%
    total_checks = len(tunable_keys) * len(perturbation_factors)

    for params, train_res, test_res in oos_results:
        robust_count = 0

        for var_key in tunable_keys:
            for mult in perturbation_factors:
                varied = params.copy()
                orig = varied[var_key]
                if isinstance(orig, float):
                    varied[var_key] = orig * mult
                else:
                    varied[var_key] = max(1, int(orig * mult))

                bt = SwingBacktester(initial_balance=initial_balance)
                vr = bt.run(
                    h4_candles=h4_train, d1_candles=d1_train,
                    strategy_type=strategy_type, params=varied,
                    symbol=symbol, base_spread=base_spread,
                    h2_candles=h2_train,
                )
                if vr.total_return_pct > 0 and vr.total_trades >= min_trades_train * 0.5:
                    robust_count += 1

        robustness_rate = robust_count / total_checks if total_checks > 0 else 0
        is_robust = robustness_rate >= 0.625  # At least 5/8 perturbations profitable

        # Full period run for final metrics
        bt = SwingBacktester(initial_balance=initial_balance)
        full_res = bt.run(
            h4_candles=h4_candles, d1_candles=d1_candles,
            strategy_type=strategy_type, params=params,
            symbol=symbol, base_spread=base_spread,
            h2_candles=h2_candles,
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

        status = "ROBUST" if is_robust else "FRAGILE"
        logger.info(
            f"  [{symbol}/{strategy_type}] {status}: full_return=+{full_res.total_return_pct}% "
            f"weekly=+{full_res.weekly_return_pct}% trades={full_res.total_trades} "
            f"WR={full_res.win_rate}% PF={full_res.profit_factor} DD={full_res.max_drawdown_pct}% "
            f"robustness={robustness_rate*100:.0f}%"
        )

    # Sort: robust first, then by weekly return
    final_results.sort(key=lambda x: (x["robust"], x["full_period"]["weekly_return_pct"]), reverse=True)
    robust_total = sum(1 for r in final_results if r["robust"])

    elapsed = round(time.time() - t0, 1)
    logger.info(f"[{symbol}/{strategy_type}] COMPLETE: {robust_total} robust / {len(final_results)} tested in {elapsed}s")

    return {
        "status": "COMPLETE",
        "symbol": symbol,
        "strategy_type": strategy_type,
        "total_params_tested": len(grid),
        "viable_on_train": len(train_results),
        "profitable_oos": len(oos_results),
        "robust_count": robust_total,
        "elapsed_sec": elapsed,
        "results": final_results,
    }
