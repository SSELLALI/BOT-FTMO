#!/usr/bin/env python3
"""Full cascade diagnostic with M30: trace every breakout's fate."""
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

m30_closes = np.array([c["close"] for c in m30])
m30_rsi = bt._compute_rsi(m30_closes, 14)

# Params
SL = 10; BBO = 0.45; BSM = 0.6; MPD = 1.2; PF = 0.8; ST = 30
RSI_L = (40, 75); RSI_S = (25, 60)

# State
pullback_active = False
last_breakout = None
pullback_low = pullback_high = None
detected = set()

# Counters
breakouts_detected = 0
fate = {"stale": 0, "not_pulled_back": 0, "depth_fail": 0, "proximity_fail": 0, 
        "no_rejection": 0, "rsi_range_fail": 0, "rsi_dir_fail": 0, "sl_fail": 0,
        "structure_broken": 0, "TRADE": 0}
breakout_log = []

for m30_idx in range(2, len(m30)):
    c = m30[m30_idx]
    t = c["datetime"]
    
    h1_idx = bt._find_h1_index(t, h1_times)
    if h1_idx is None or h1_idx < 20:
        continue

    h_min = t.hour * 60 + t.minute
    in_session = (420 <= h_min <= 690) or (810 <= h_min <= 990)
    if not in_session or t.weekday() >= 5:
        # Even outside session, check stale timeout for active pullback
        if pullback_active and last_breakout:
            if h1_idx - last_breakout["h1_idx"] > ST:
                fate["stale"] += 1
                pullback_active = False
                last_breakout = None
        continue

    swings = bt._detect_swings(h1_highs, h1_lows, h1_idx, SL)
    bias = bt._determine_bias(swings)
    if bias is None:
        continue

    key_res = key_sup = None
    for sp in reversed(swings):
        if sp.type in ("HH", "LH") and key_res is None:
            key_res = sp.price
        if sp.type in ("HL", "LL") and key_sup is None:
            key_sup = sp.price
        if key_res and key_sup:
            break

    h1_c = h1[h1_idx]
    prev_close = h1_closes[h1_idx - 1]

    # Breakout detection
    if not pullback_active:
        new_bo = None
        if bias == "BULLISH" and key_res:
            bk = f"B_{key_res:.2f}_{h1_idx}"
            if bk not in detected and h1_c["close"] > key_res and prev_close <= key_res:
                avg_r = float(np.mean(h1_ranges[max(0,h1_idx-10):h1_idx]))
                cr = h1_c["high"] - h1_c["low"]
                cb = abs(h1_c["close"] - h1_c["open"])
                br = cb / cr if cr > 0 else 0
                if cr > avg_r * BSM and br >= BBO:
                    new_bo = {"level": key_res, "direction": "BUY", "h1_idx": h1_idx, "candle_range": cr}
                    detected.add(bk)

        if not new_bo and bias == "BEARISH" and key_sup:
            bk = f"S_{key_sup:.2f}_{h1_idx}"
            if bk not in detected and h1_c["close"] < key_sup and prev_close >= key_sup:
                avg_r = float(np.mean(h1_ranges[max(0,h1_idx-10):h1_idx]))
                cr = h1_c["high"] - h1_c["low"]
                cb = abs(h1_c["close"] - h1_c["open"])
                br = cb / cr if cr > 0 else 0
                if cr > avg_r * BSM and br >= BBO:
                    new_bo = {"level": key_sup, "direction": "SELL", "h1_idx": h1_idx, "candle_range": cr}
                    detected.add(bk)

        if new_bo:
            breakouts_detected += 1
            last_breakout = new_bo
            pullback_active = True
            pullback_low = c["low"]
            pullback_high = c["high"]
            breakout_log.append({"date": str(t), "dir": new_bo["direction"], "level": new_bo["level"], "cr": new_bo["candle_range"]})
            continue

    if not pullback_active or last_breakout is None:
        continue

    # Stale
    if h1_idx - last_breakout["h1_idx"] > ST:
        fate["stale"] += 1
        pullback_active = False
        last_breakout = None
        continue

    level = last_breakout["level"]
    direction = last_breakout["direction"]
    pullback_low = min(pullback_low, c["low"]) if pullback_low else c["low"]
    pullback_high = max(pullback_high, c["high"]) if pullback_high else c["high"]

    # Pullback checks
    if direction == "BUY":
        if c["close"] > level + last_breakout["candle_range"]:
            continue  # Not yet pulled back
        # Structure check
        last_hl = None
        for sp in reversed(swings):
            if sp.type == "HL":
                last_hl = sp.price
                break
        if last_hl and c["low"] < last_hl:
            fate["structure_broken"] += 1
            pullback_active = False
            last_breakout = None
            continue
        pd = (pullback_high - c["low"]) / last_breakout["candle_range"] if last_breakout["candle_range"] > 0 else 999
        if pd > MPD:
            continue
        dist = abs(c["close"] - level)
        if dist > last_breakout["candle_range"] * PF:
            continue
    else:  # SELL
        if c["close"] < level - last_breakout["candle_range"]:
            continue
        last_lh = None
        for sp in reversed(swings):
            if sp.type == "LH":
                last_lh = sp.price
                break
        if last_lh and c["high"] > last_lh:
            fate["structure_broken"] += 1
            pullback_active = False
            last_breakout = None
            continue
        pd = (c["high"] - pullback_low) / last_breakout["candle_range"] if last_breakout["candle_range"] > 0 else 999
        if pd > MPD:
            continue
        dist = abs(c["close"] - level)
        if dist > last_breakout["candle_range"] * PF:
            continue

    # At this point: pullback OK, proximity OK
    # Rejection candle
    patterns = bt._detect_m15_patterns(m30, m30_idx)
    has_rej = False
    if direction == "BUY":
        has_rej = any(p in patterns for p in ("BULLISH_ENGULFING", "BULLISH_PINBAR", "HAMMER", "STRONG_BULLISH"))
        if not (c["close"] > c["open"]):
            has_rej = False
    else:
        has_rej = any(p in patterns for p in ("BEARISH_ENGULFING", "BEARISH_PINBAR", "SHOOTING_STAR", "STRONG_BEARISH"))
        if not (c["close"] < c["open"]):
            has_rej = False

    if not has_rej:
        fate["no_rejection"] += 1  # Count but don't cancel - keep waiting
        continue

    # RSI
    rsi_val = m30_rsi[m30_idx]
    rsi_prev = m30_rsi[m30_idx - 1]
    if direction == "BUY":
        if not (RSI_L[0] <= rsi_val <= RSI_L[1]):
            fate["rsi_range_fail"] += 1
            continue
        if rsi_val <= rsi_prev:
            fate["rsi_dir_fail"] += 1
            continue
    else:
        if not (RSI_S[0] <= rsi_val <= RSI_S[1]):
            fate["rsi_range_fail"] += 1
            continue
        if rsi_val >= rsi_prev:
            fate["rsi_dir_fail"] += 1
            continue

    # SL check
    if direction == "BUY":
        sl_pips = (c["close"] - pullback_low + 7/100) * 100
    else:
        sl_pips = (pullback_high - c["close"] + 7/100) * 100
    if sl_pips < 10 or sl_pips > 70:
        fate["sl_fail"] += 1
        continue

    fate["TRADE"] += 1
    pullback_active = False
    last_breakout = None

print(f"\n{'='*60}")
print(f"FULL CASCADE DIAGNOSTIC (M30 entry)")
print(f"Params: body={BBO}, vol={BSM}, depth={MPD}, prox={PF}, timeout={ST}")
print(f"RSI: long={RSI_L}, short={RSI_S}")
print(f"{'='*60}")
print(f"Breakouts detected:         {breakouts_detected}")
print(f"\nBreakout outcomes:")
for k, v in sorted(fate.items(), key=lambda x: -x[1]):
    pct = v/breakouts_detected*100 if breakouts_detected > 0 else 0
    print(f"  {k:25s}: {v:5d} ({pct:.1f}% of breakouts)")
print(f"\nBreakout log (first 30):")
for bl in breakout_log[:30]:
    print(f"  {bl['date']} | {bl['dir']} | level={bl['level']:.2f} | range={bl['cr']:.3f}")
