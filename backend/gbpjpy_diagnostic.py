#!/usr/bin/env python3
"""Test matrix: find the best param combo for trade frequency + profitability."""
import sys, os, random
sys.path.insert(0, os.path.dirname(__file__))
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
m30 = load_tradingview_csv("historical_data/GBPJPY_M30_TV.csv")

base = {
    "sl_buffer_pips": 5, "min_rr": 2.0, "risk_per_trade": 0.01,
    "be_trigger_rr": 1.0, "max_daily_trades": 4, "max_consecutive_losses": 4,
    "use_structural_tp": False,
}

tests = [
    # Swing lookback variations with ultra-relaxed
    {"name": "SL4_ultra", "swing_lookback": 4, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": False},
    {"name": "SL5_ultra", "swing_lookback": 5, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": False},
    {"name": "SL6_ultra", "swing_lookback": 6, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": False},
    # With session extension
    {"name": "SL4_ultra_ext", "swing_lookback": 4, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": True},
    {"name": "SL5_ultra_ext", "swing_lookback": 5, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": True},
    {"name": "SL6_ultra_ext", "swing_lookback": 6, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": True},
    # With min_rr=1.5 for more TP hits
    {"name": "SL4_rr15_ext", "swing_lookback": 4, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": True, "min_rr": 1.5},
    {"name": "SL5_rr15_ext", "swing_lookback": 5, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": True, "min_rr": 1.5},
    {"name": "SL6_rr15_ext", "swing_lookback": 6, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": True, "min_rr": 1.5},
    # Without RSI direction requirement (just range)
    {"name": "SL4_noRSIdir_ext", "swing_lookback": 4, "breakout_body_ratio": 0.35, "breakout_size_mult": 0.3,
     "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 25, "rsi_long_max": 85, "rsi_short_min": 15, "rsi_short_max": 75,
     "min_sl_pips": 3, "max_sl_pips": 120, "extend_session": True, "min_rr": 1.5},
]

weeks = 60
print(f"{'Name':45s} | {'Tr':>4s} ({'T/w':>5s}) | {'WR':>6s} | {'RetTot':>7s} | {'Weekly':>7s} | {'PF':>5s} | {'DD':>5s} | {'FTMO':>4s}")
print("-" * 115)
for t in tests:
    random.seed(42)
    params = {**base, **{k: v for k, v in t.items() if k != "name"}}
    bt = GBPJPYBreakoutBacktester(initial_balance=100000)
    r = bt.run(h1, m30, params, base_spread=2.5)
    print(f"{t['name']:45s} | {r.total_trades:4d} ({r.total_trades/weeks:5.2f}) | {r.win_rate:5.1f}% | {r.total_return_pct:+6.2f}% | {r.weekly_return_pct:+6.3f}% | {r.profit_factor:5.2f} | {r.max_drawdown_pct:4.1f}% | {'Y' if r.ftmo_compliant else 'N':>4s}")
