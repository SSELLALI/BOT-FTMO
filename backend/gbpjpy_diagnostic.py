#!/usr/bin/env python3
"""Run actual backtester with relaxed params on M30 data."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
m30 = load_tradingview_csv("historical_data/GBPJPY_M30_TV.csv")

params = {
    "swing_lookback": 10,
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

print(f"RESULTS (M30 entry, relaxed params):")
print(f"  Trades: {r.total_trades}")
print(f"  Wins/Losses: {r.wins}/{r.losses} (WR: {r.win_rate}%)")
print(f"  Total Return: {r.total_return_pct}%")
print(f"  Weekly Return: {r.weekly_return_pct}%")
print(f"  Profit Factor: {r.profit_factor}")
print(f"  Max DD: {r.max_drawdown_pct}%")
print(f"  Max Daily Loss: {r.max_daily_loss_pct}%")
print(f"  FTMO: {r.ftmo_compliant}")
print(f"  Avg RR: {r.avg_rr_achieved}")
print(f"  Period: {r.start_date} -> {r.end_date}")
days = 420
weeks = days / 7
print(f"  Trades/week: {r.total_trades/weeks:.2f}")
print(f"\nAll trades:")
for t in r.trades:
    print(f"  {t}")
