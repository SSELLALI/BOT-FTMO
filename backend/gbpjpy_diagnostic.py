#!/usr/bin/env python3
"""Quick test of rewritten backtester with M30."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
m30 = load_tradingview_csv("historical_data/GBPJPY_M30_TV.csv")

params = {
    "swing_lookback": 8,
    "sl_buffer_pips": 5,
    "min_rr": 2.0,
    "risk_per_trade": 0.01,
    "breakout_body_ratio": 0.45,
    "breakout_size_mult": 0.6,
    "max_pullback_depth": 1.2,
    "rsi_long_min": 40,
    "rsi_long_max": 75,
    "rsi_short_min": 25,
    "rsi_short_max": 60,
    "be_trigger_rr": 1.0,
    "max_daily_trades": 4,
    "max_consecutive_losses": 3,
    "use_structural_tp": False,
    "min_sl_pips": 8,
    "max_sl_pips": 80,
    "proximity_factor": 0.8,
    "stale_timeout": 30,
}

bt = GBPJPYBreakoutBacktester(initial_balance=100000)
r = bt.run(h1, m30, params, base_spread=2.5)

weeks = 60
print(f"RESULTS (v2, M30, multi-breakout):")
print(f"  Trades: {r.total_trades} ({r.total_trades/weeks:.2f}/week)")
print(f"  W/L: {r.wins}/{r.losses} (WR: {r.win_rate}%)")
print(f"  Total Return: {r.total_return_pct}%")
print(f"  Weekly Return: {r.weekly_return_pct}%")
print(f"  PF: {r.profit_factor} | Avg RR: {r.avg_rr_achieved}")
print(f"  Max DD: {r.max_drawdown_pct}% | Daily Loss: {r.max_daily_loss_pct}%")
print(f"  FTMO: {r.ftmo_compliant}")
print(f"\nAll trades:")
for t in r.trades:
    print(f"  {t}")
