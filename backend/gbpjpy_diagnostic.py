#!/usr/bin/env python3
"""Quick diagnostic: run backtester with M30 data and relaxed params to count trades."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
m30 = load_tradingview_csv("historical_data/GBPJPY_M30_TV.csv")
print(f"H1: {len(h1)} | M30: {len(m30)}")

params = {
    "swing_lookback": 10,
    "sl_buffer_pips": 7,
    "min_rr": 2.0,
    "risk_per_trade": 0.01,
    "breakout_body_ratio": 0.50,
    "breakout_size_mult": 0.7,
    "max_pullback_depth": 1.0,
    "rsi_long_min": 42,
    "rsi_long_max": 72,
    "rsi_short_min": 28,
    "rsi_short_max": 58,
    "be_trigger_rr": 1.0,
    "max_daily_trades": 4,
    "max_consecutive_losses": 3,
    "min_sl_pips": 10,
    "max_sl_pips": 70,
    "use_structural_tp": False,
    "proximity_factor": 0.7,
    "stale_timeout": 30,
}

bt = GBPJPYBreakoutBacktester(initial_balance=100000)
r = bt.run(h1, m30, params, base_spread=2.5)
print(f"\nRESULTS:")
print(f"  Trades: {r.total_trades}")
print(f"  Wins: {r.wins} | Losses: {r.losses}")
print(f"  Win Rate: {r.win_rate}%")
print(f"  Total Return: {r.total_return_pct}%")
print(f"  Weekly Return: {r.weekly_return_pct}%")
print(f"  Profit Factor: {r.profit_factor}")
print(f"  Max DD: {r.max_drawdown_pct}%")
print(f"  Max Daily Loss: {r.max_daily_loss_pct}%")
print(f"  FTMO Compliant: {r.ftmo_compliant}")
print(f"  Period: {r.start_date} -> {r.end_date}")
if r.trades:
    for t in r.trades[:20]:
        print(f"    {t}")
