#!/usr/bin/env python3
"""Test multiple param variations to find best trade frequency."""
import sys, os, random
sys.path.insert(0, os.path.dirname(__file__))
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
m30 = load_tradingview_csv("historical_data/GBPJPY_M30_TV.csv")

base_params = {
    "sl_buffer_pips": 5,
    "min_rr": 2.0,
    "risk_per_trade": 0.01,
    "be_trigger_rr": 1.0,
    "max_daily_trades": 4,
    "max_consecutive_losses": 4,
    "use_structural_tp": False,
}

# Test different parameter combinations
tests = [
    {"name": "SL6_body45_vol50_prox90_timeout35", "swing_lookback": 6, "breakout_body_ratio": 0.45,
     "breakout_size_mult": 0.5, "max_pullback_depth": 1.5, "proximity_factor": 0.9, "stale_timeout": 35,
     "rsi_long_min": 38, "rsi_long_max": 78, "rsi_short_min": 22, "rsi_short_max": 62,
     "min_sl_pips": 5, "max_sl_pips": 90},
    {"name": "SL8_body45_vol50_prox90_timeout35", "swing_lookback": 8, "breakout_body_ratio": 0.45,
     "breakout_size_mult": 0.5, "max_pullback_depth": 1.5, "proximity_factor": 0.9, "stale_timeout": 35,
     "rsi_long_min": 38, "rsi_long_max": 78, "rsi_short_min": 22, "rsi_short_max": 62,
     "min_sl_pips": 5, "max_sl_pips": 90},
    {"name": "SL10_body45_vol50_prox90_timeout35", "swing_lookback": 10, "breakout_body_ratio": 0.45,
     "breakout_size_mult": 0.5, "max_pullback_depth": 1.5, "proximity_factor": 0.9, "stale_timeout": 35,
     "rsi_long_min": 38, "rsi_long_max": 78, "rsi_short_min": 22, "rsi_short_max": 62,
     "min_sl_pips": 5, "max_sl_pips": 90},
    {"name": "SL6_body40_vol40_prox100_timeout40", "swing_lookback": 6, "breakout_body_ratio": 0.40,
     "breakout_size_mult": 0.4, "max_pullback_depth": 1.8, "proximity_factor": 1.0, "stale_timeout": 40,
     "rsi_long_min": 35, "rsi_long_max": 78, "rsi_short_min": 22, "rsi_short_max": 65,
     "min_sl_pips": 5, "max_sl_pips": 100},
    {"name": "SL8_body40_vol40_prox100_timeout40", "swing_lookback": 8, "breakout_body_ratio": 0.40,
     "breakout_size_mult": 0.4, "max_pullback_depth": 1.8, "proximity_factor": 1.0, "stale_timeout": 40,
     "rsi_long_min": 35, "rsi_long_max": 78, "rsi_short_min": 22, "rsi_short_max": 65,
     "min_sl_pips": 5, "max_sl_pips": 100},
    {"name": "SL6_ultra_relaxed", "swing_lookback": 6, "breakout_body_ratio": 0.35,
     "breakout_size_mult": 0.3, "max_pullback_depth": 2.0, "proximity_factor": 1.2, "stale_timeout": 50,
     "rsi_long_min": 30, "rsi_long_max": 80, "rsi_short_min": 20, "rsi_short_max": 70,
     "min_sl_pips": 3, "max_sl_pips": 120},
]

weeks = 60
for t in tests:
    random.seed(42)
    params = {**base_params, **{k: v for k, v in t.items() if k != "name"}}
    bt = GBPJPYBreakoutBacktester(initial_balance=100000)
    r = bt.run(h1, m30, params, base_spread=2.5)
    print(f"{t['name']:45s} | trades={r.total_trades:3d} ({r.total_trades/weeks:.2f}/w) | "
          f"WR={r.win_rate:5.1f}% | ret={r.total_return_pct:+6.2f}% | "
          f"weekly={r.weekly_return_pct:+6.3f}% | PF={r.profit_factor:5.2f} | DD={r.max_drawdown_pct:.2f}%")
