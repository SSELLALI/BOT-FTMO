#!/usr/bin/env python3
"""Deep diagnostic: trace breakout detection step by step."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
m30 = load_tradingview_csv("historical_data/GBPJPY_M30_TV.csv")

bt = GBPJPYBreakoutBacktester(initial_balance=100000)

h1_times = [c["datetime"] for c in h1]
h1_closes = np.array([c["close"] for c in h1])
h1_highs = np.array([c["high"] for c in h1])
h1_lows = np.array([c["low"] for c in h1])
h1_ranges = h1_highs - h1_lows

swing_lookback = 10
breakout_body_ratio = 0.45
breakout_size_mult = 0.6

# Track breakout stats
breakouts_found = 0
first_close_bull = 0
first_close_bear = 0
vol_pass_bull = 0
vol_pass_bear = 0
body_pass_bull = 0
body_pass_bear = 0
close_above_count = 0
prev_below_count = 0

# Only check at M30 session times to match trading
for m30_idx in range(2, len(m30)):
    m30_c = m30[m30_idx]
    m30_time = m30_c["datetime"]
    
    h = m30_time.hour
    m = m30_time.minute
    t_minutes = h * 60 + m
    in_london = 420 <= t_minutes <= 690
    in_ny = 810 <= t_minutes <= 990
    if not (in_london or in_ny):
        continue
    if m30_time.weekday() >= 5:
        continue

    h1_idx = bt._find_h1_index(m30_time, h1_times)
    if h1_idx is None or h1_idx < swing_lookback + 10:
        continue

    swings = bt._detect_swings(h1_highs, h1_lows, h1_idx, swing_lookback)
    bias = bt._determine_bias(swings)
    if bias is None:
        continue

    key_resistance = key_support = None
    for sp in reversed(swings):
        if sp.type in ("HH", "LH") and key_resistance is None:
            key_resistance = sp.price
        if sp.type in ("HL", "LL") and key_support is None:
            key_support = sp.price
        if key_resistance and key_support:
            break

    h1_c = h1[h1_idx]
    prev_h1_close = h1_closes[h1_idx - 1]

    # Bull analysis
    if bias == "BULLISH" and key_resistance:
        if h1_c["close"] > key_resistance:
            close_above_count += 1
            if prev_h1_close <= key_resistance:
                first_close_bull += 1
                avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx]))
                candle_range = h1_c["high"] - h1_c["low"]
                candle_body = abs(h1_c["close"] - h1_c["open"])
                body_ratio = candle_body / candle_range if candle_range > 0 else 0
                if candle_range > avg_range * breakout_size_mult:
                    vol_pass_bull += 1
                if body_ratio >= breakout_body_ratio:
                    body_pass_bull += 1
                if candle_range > avg_range * breakout_size_mult and body_ratio >= breakout_body_ratio:
                    breakouts_found += 1
            else:
                prev_below_count += 1

    # Bear analysis
    if bias == "BEARISH" and key_support:
        if h1_c["close"] < key_support:
            if prev_h1_close >= key_support:
                first_close_bear += 1
                avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx]))
                candle_range = h1_c["high"] - h1_c["low"]
                candle_body = abs(h1_c["close"] - h1_c["open"])
                body_ratio = candle_body / candle_range if candle_range > 0 else 0
                if candle_range > avg_range * breakout_size_mult:
                    vol_pass_bear += 1
                if body_ratio >= breakout_body_ratio:
                    body_pass_bear += 1
                if candle_range > avg_range * breakout_size_mult and body_ratio >= breakout_body_ratio:
                    breakouts_found += 1

print(f"\n{'='*60}")
print(f"DEEP BREAKOUT DIAGNOSTIC")
print(f"{'='*60}")
print(f"Bull close above resistance: {close_above_count}")
print(f"  But prev H1 was ALREADY above: {prev_below_count}")
print(f"  First close above (bull): {first_close_bull}")
print(f"    Vol pass: {vol_pass_bull} | Body pass: {body_pass_bull}")
print(f"  First close below (bear): {first_close_bear}")
print(f"    Vol pass: {vol_pass_bear} | Body pass: {body_pass_bear}")
print(f"Total breakouts (both): {breakouts_found}")
print(f"{'='*60}")

# Also check: what's the distance between close and key_resistance typically?
print(f"\nSample key levels and prices (first 20 BULLISH with bias):")
count = 0
last_h1_idx = -1
for m30_idx in range(2, min(len(m30), 5000)):
    m30_c = m30[m30_idx]
    m30_time = m30_c["datetime"]
    h = m30_time.hour
    t_minutes = h * 60 + m30_time.minute
    if not (420 <= t_minutes <= 690 or 810 <= t_minutes <= 990):
        continue
    if m30_time.weekday() >= 5:
        continue
    h1_idx = bt._find_h1_index(m30_time, h1_times)
    if h1_idx is None or h1_idx < 20 or h1_idx == last_h1_idx:
        continue
    last_h1_idx = h1_idx
    swings = bt._detect_swings(h1_highs, h1_lows, h1_idx, 10)
    bias = bt._determine_bias(swings)
    if bias != "BULLISH":
        continue
    key_r = None
    for sp in reversed(swings):
        if sp.type in ("HH", "LH"):
            key_r = sp.price
            break
    if not key_r:
        continue
    h1_c = h1[h1_idx]
    dist = h1_c["close"] - key_r
    prev_dist = h1_closes[h1_idx-1] - key_r
    count += 1
    if count <= 20:
        print(f"  {m30_time.date()} h1_idx={h1_idx} | key_R={key_r:.2f} | H1close={h1_c['close']:.2f} (dist={dist:.2f}) | prev={h1_closes[h1_idx-1]:.2f} (dist={prev_dist:.2f})")
