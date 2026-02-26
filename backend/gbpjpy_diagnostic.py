#!/usr/bin/env python3
"""
Diagnostic tool: counts how many M30 candles pass each filter stage
to identify the biggest bottleneck in the GBPJPY strategy.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from tradingview_loader import load_tradingview_csv
from gbpjpy_breakout_backtester import GBPJPYBreakoutBacktester

def run_diagnostic():
    h1 = load_tradingview_csv("historical_data/GBPJPY_H1_TV.csv")
    m30 = load_tradingview_csv("historical_data/GBPJPY_M30_TV.csv")
    print(f"H1: {len(h1)} candles | M30: {len(m30)} candles")

    # Use mid-range params
    params = {
        "swing_lookback": 10,
        "sl_buffer_pips": 7,
        "min_rr": 2.0,
        "risk_per_trade": 0.01,
        "breakout_body_ratio": 0.50,
        "breakout_size_mult": 0.8,
        "max_pullback_depth": 1.0,
        "rsi_long_min": 42,
        "rsi_long_max": 72,
        "rsi_short_min": 28,
        "rsi_short_max": 58,
        "be_trigger_rr": 1.0,
        "max_daily_trades": 4,
        "max_consecutive_losses": 3,
        "min_sl_pips": 15,
        "max_sl_pips": 60,
    }

    bt = GBPJPYBreakoutBacktester(initial_balance=100000)

    # Counters
    total_m30 = 0
    pass_session = 0
    pass_weekend = 0
    pass_daily_limit = 0
    pass_consec = 0
    pass_ftmo = 0
    pass_bias = 0
    bias_counts = {"BULLISH": 0, "BEARISH": 0, None: 0}
    pass_key_level = 0
    pass_breakout = 0
    breakout_details = {"bull_close_above": 0, "bull_open_below": 0, "bull_vol_pass": 0, "bull_body_pass": 0,
                        "bear_close_below": 0, "bear_open_above": 0, "bear_vol_pass": 0, "bear_body_pass": 0}
    pass_pullback_active = 0
    pass_pullback_not_stale = 0
    pass_pullback_depth = 0
    pass_pullback_proximity = 0
    pass_rejection = 0
    pass_rsi = 0
    pass_rsi_direction = 0
    pass_sl_range = 0
    final_trades = 0

    h1_times = [c["datetime"] for c in h1]
    h1_closes = np.array([c["close"] for c in h1])
    h1_opens = np.array([c["open"] for c in h1])
    h1_highs = np.array([c["high"] for c in h1])
    h1_lows = np.array([c["low"] for c in h1])
    h1_ranges = h1_highs - h1_lows
    m30_closes = np.array([c["close"] for c in m30])
    m30_rsi = bt._compute_rsi(m30_closes, 14)

    swing_lookback = params["swing_lookback"]
    breakout_body_ratio = params["breakout_body_ratio"]
    breakout_size_mult = params["breakout_size_mult"]
    max_pullback_depth = params["max_pullback_depth"]

    last_breakout = None
    pullback_active = False
    pullback_low = None
    pullback_high = None
    detected_h1_breakouts = set()
    open_trade = False

    for m30_idx in range(2, len(m30)):
        m30_c = m30[m30_idx]
        m30_time = m30_c["datetime"]
        total_m30 += 1

        h1_idx = bt._find_h1_index(m30_time, h1_times)
        if h1_idx is None or h1_idx < swing_lookback + 10:
            continue

        if open_trade:
            continue

        # Session filter
        h = m30_time.hour
        m = m30_time.minute
        t_minutes = h * 60 + m
        in_london = 420 <= t_minutes <= 690
        in_ny = 810 <= t_minutes <= 990
        if not (in_london or in_ny):
            continue
        pass_session += 1

        if m30_time.weekday() >= 5:
            continue
        pass_weekend += 1
        pass_daily_limit += 1
        pass_consec += 1
        pass_ftmo += 1

        # Bias
        swings = bt._detect_swings(h1_highs, h1_lows, h1_idx, swing_lookback)
        bias = bt._determine_bias(swings)
        bias_counts[bias] = bias_counts.get(bias, 0) + 1
        if bias is None:
            continue
        pass_bias += 1

        # Key levels
        key_resistance = key_support = None
        for sp in reversed(swings):
            if sp.type in ("HH", "LH") and key_resistance is None:
                key_resistance = sp.price
            if sp.type in ("HL", "LL") and key_support is None:
                key_support = sp.price
            if key_resistance and key_support:
                break
        if key_resistance or key_support:
            pass_key_level += 1

        # Breakout detection
        h1_c = h1[h1_idx]
        new_breakout = None
        if not pullback_active:
            if bias == "BULLISH" and key_resistance and h1_idx not in detected_h1_breakouts:
                if h1_c["close"] > key_resistance:
                    breakout_details["bull_close_above"] += 1
                    if h1_c["open"] <= key_resistance:
                        breakout_details["bull_open_below"] += 1
                        avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx]))
                        candle_range = h1_c["high"] - h1_c["low"]
                        candle_body = abs(h1_c["close"] - h1_c["open"])
                        body_ratio = candle_body / candle_range if candle_range > 0 else 0
                        if candle_range > avg_range * breakout_size_mult:
                            breakout_details["bull_vol_pass"] += 1
                        if body_ratio >= breakout_body_ratio:
                            breakout_details["bull_body_pass"] += 1
                        if candle_range > avg_range * breakout_size_mult and body_ratio >= breakout_body_ratio:
                            new_breakout = {"level": key_resistance, "direction": "BUY", "h1_idx": h1_idx, "candle_range": candle_range}
                            detected_h1_breakouts.add(h1_idx)

            if not new_breakout and bias == "BEARISH" and key_support and h1_idx not in detected_h1_breakouts:
                if h1_c["close"] < key_support:
                    breakout_details["bear_close_below"] += 1
                    if h1_c["open"] >= key_support:
                        breakout_details["bear_open_above"] += 1
                        avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx]))
                        candle_range = h1_c["high"] - h1_c["low"]
                        candle_body = abs(h1_c["close"] - h1_c["open"])
                        body_ratio = candle_body / candle_range if candle_range > 0 else 0
                        if candle_range > avg_range * breakout_size_mult:
                            breakout_details["bear_vol_pass"] += 1
                        if body_ratio >= breakout_body_ratio:
                            breakout_details["bear_body_pass"] += 1
                        if candle_range > avg_range * breakout_size_mult and body_ratio >= breakout_body_ratio:
                            new_breakout = {"level": key_support, "direction": "SELL", "h1_idx": h1_idx, "candle_range": candle_range}
                            detected_h1_breakouts.add(h1_idx)

        if new_breakout:
            pass_breakout += 1
            last_breakout = new_breakout
            pullback_active = True
            pullback_low = m30_c["low"]
            pullback_high = m30_c["high"]
            continue

        if not pullback_active or last_breakout is None:
            continue
        pass_pullback_active += 1

        # Stale check
        if h1_idx - last_breakout["h1_idx"] > 20:
            last_breakout = None
            pullback_active = False
            continue
        pass_pullback_not_stale += 1

        level = last_breakout["level"]
        direction = last_breakout["direction"]
        pullback_low = min(pullback_low, m30_c["low"]) if pullback_low else m30_c["low"]
        pullback_high = max(pullback_high, m30_c["high"]) if pullback_high else m30_c["high"]

        # Pullback depth + proximity
        if direction == "BUY":
            if m30_c["close"] > level + last_breakout["candle_range"]:
                continue
            pullback_depth_val = (pullback_high - m30_c["low"]) / last_breakout["candle_range"] if last_breakout["candle_range"] > 0 else 999
            if pullback_depth_val > max_pullback_depth:
                continue
            pass_pullback_depth += 1
            dist_to_level = abs(m30_c["close"] - level)
            if dist_to_level > last_breakout["candle_range"] * 0.5:
                continue
        elif direction == "SELL":
            if m30_c["close"] < level - last_breakout["candle_range"]:
                continue
            pullback_depth_val = (m30_c["high"] - pullback_low) / last_breakout["candle_range"] if last_breakout["candle_range"] > 0 else 999
            if pullback_depth_val > max_pullback_depth:
                continue
            pass_pullback_depth += 1
            dist_to_level = abs(m30_c["close"] - level)
            if dist_to_level > last_breakout["candle_range"] * 0.5:
                continue
        pass_pullback_proximity += 1

        # Rejection
        patterns = bt._detect_m15_patterns(m30, m30_idx)  # Works on M30 too
        has_rejection = False
        if direction == "BUY":
            has_rejection = any(p in patterns for p in ("BULLISH_ENGULFING", "BULLISH_PINBAR", "HAMMER", "STRONG_BULLISH"))
            if not (m30_c["close"] > m30_c["open"]):
                has_rejection = False
        elif direction == "SELL":
            has_rejection = any(p in patterns for p in ("BEARISH_ENGULFING", "BEARISH_PINBAR", "SHOOTING_STAR", "STRONG_BEARISH"))
            if not (m30_c["close"] < m30_c["open"]):
                has_rejection = False
        if not has_rejection:
            continue
        pass_rejection += 1

        # RSI
        rsi_val = m30_rsi[m30_idx]
        rsi_prev = m30_rsi[m30_idx - 1]
        if direction == "BUY":
            if not (params["rsi_long_min"] <= rsi_val <= params["rsi_long_max"]):
                continue
            pass_rsi += 1
            if rsi_val <= rsi_prev:
                continue
        elif direction == "SELL":
            if not (params["rsi_short_min"] <= rsi_val <= params["rsi_short_max"]):
                continue
            pass_rsi += 1
            if rsi_val >= rsi_prev:
                continue
        pass_rsi_direction += 1

        # SL range
        if direction == "BUY":
            sl_pips = (m30_c["close"] - pullback_low + params["sl_buffer_pips"]/100) * 100
        else:
            sl_pips = (pullback_high - m30_c["close"] + params["sl_buffer_pips"]/100) * 100
        if sl_pips < params["min_sl_pips"] or sl_pips > params["max_sl_pips"]:
            continue
        pass_sl_range += 1
        final_trades += 1

    print(f"\n{'='*60}")
    print(f"DIAGNOSTIC GBPJPY BREAKOUT-PULLBACK (M30 entry)")
    print(f"{'='*60}")
    print(f"Total M30 candles processed:    {total_m30}")
    print(f"After session filter:           {pass_session} ({pass_session/total_m30*100:.1f}%)")
    print(f"After weekend filter:           {pass_weekend}")
    print(f"After bias detection:           {pass_bias} ({pass_bias/pass_session*100:.1f}% of session)")
    print(f"  Bias counts: {bias_counts}")
    print(f"With key level identified:      {pass_key_level}")
    print(f"Breakouts detected:             {pass_breakout}")
    print(f"  Breakout details: {breakout_details}")
    print(f"Pullback active candles:        {pass_pullback_active}")
    print(f"Pullback not stale:             {pass_pullback_not_stale}")
    print(f"Pullback depth OK:              {pass_pullback_depth}")
    print(f"Pullback proximity OK:          {pass_pullback_proximity}")
    print(f"Rejection candle found:         {pass_rejection}")
    print(f"RSI in range:                   {pass_rsi}")
    print(f"RSI direction OK:               {pass_rsi_direction}")
    print(f"SL range OK:                    {pass_sl_range}")
    print(f"FINAL POTENTIAL TRADES:         {final_trades}")
    print(f"{'='*60}")

if __name__ == "__main__":
    run_diagnostic()
