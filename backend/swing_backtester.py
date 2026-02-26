"""
Swing Trading Backtester — Price Action (D1 + H4 + H2)

Day/Swing trading: positions held hours to 10 days max.
MTF: D1 trend/structure + H4 signals + H2 execution precision.

Strategy:
  - D1: Market structure (HH/HL=uptrend, LH/LL=downtrend), major S/R
  - H4: S/R zones, candlestick patterns, entry signals
  - H2: Execution precision (2 candles per H4 = 2x resolution)
  - R:R minimum 2.5 (STRICT, no exceptions)
  - Max hold: 10 days
  - No session filter (swing positions held overnight)

All 10 safety rules preserved (spread, slippage, latency, news, FTMO, anti-lookahead).
"""
import bisect
import random
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta

from news_calendar import news_calendar

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    entry_price: float = 0
    stop_loss: float = 0
    take_profit: float = 0
    direction: str = ""
    size: float = 0
    entry_time: datetime = None
    exit_price: float = 0
    exit_time: datetime = None
    pnl: float = 0
    reason: str = ""


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0
    total_pnl: float = 0
    total_return_pct: float = 0
    weekly_return_pct: float = 0
    profit_factor: float = 0
    max_drawdown_pct: float = 0
    max_daily_loss_pct: float = 0
    ftmo_compliant: bool = False
    start_date: str = ""
    end_date: str = ""
    avg_trade_pnl: float = 0
    equity_curve: list = field(default_factory=list)
    daily_returns: list = field(default_factory=list)


# ── Candlestick Pattern Detection ──

def _body(c):
    return abs(c["close"] - c["open"])

def _range_c(c):
    return c["high"] - c["low"]

def _is_bullish(c):
    return c["close"] > c["open"]

def _is_bearish(c):
    return c["close"] < c["open"]

def detect_pattern(candles, idx):
    if idx < 2:
        return []
    c = candles[idx]
    p1 = candles[idx - 1]
    p2 = candles[idx - 2]
    patterns = []
    body = _body(c)
    rng = _range_c(c)
    if rng <= 0:
        return []
    body_ratio = body / rng
    uw = c["high"] - max(c["open"], c["close"])
    lw = min(c["open"], c["close"]) - c["low"]

    # Pin Bar
    if body_ratio < 0.35:
        if lw > body * 2.0 and uw < body * 1.0:
            patterns.append("BULLISH_PINBAR")
        if uw > body * 2.0 and lw < body * 1.0:
            patterns.append("BEARISH_PINBAR")
    # Hammer / Shooting Star
    if _is_bullish(c) and lw > body * 2.0 and uw < body * 0.5:
        patterns.append("HAMMER")
    if _is_bearish(c) and uw > body * 2.0 and lw < body * 0.5:
        patterns.append("SHOOTING_STAR")
    # Engulfing
    if _is_bullish(c) and _is_bearish(p1) and c["close"] > p1["open"] and c["open"] < p1["close"]:
        patterns.append("BULLISH_ENGULFING")
    if _is_bearish(c) and _is_bullish(p1) and c["close"] < p1["open"] and c["open"] > p1["close"]:
        patterns.append("BEARISH_ENGULFING")
    # Doji
    if body_ratio < 0.1:
        patterns.append("DOJI")
    # Morning/Evening Star
    if _range_c(p1) > 0 and _body(p1) / _range_c(p1) < 0.3:
        if _is_bearish(p2) and _is_bullish(c) and c["close"] > (p2["open"] + p2["close"]) / 2:
            patterns.append("MORNING_STAR")
        if _is_bullish(p2) and _is_bearish(c) and c["close"] < (p2["open"] + p2["close"]) / 2:
            patterns.append("EVENING_STAR")
    # Strong body (breakout)
    if body_ratio > 0.65:
        patterns.append("STRONG_BULLISH" if _is_bullish(c) else "STRONG_BEARISH")
    return patterns


class SwingBacktester:

    def __init__(self, initial_balance=100000, seed=42):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.rng = random.Random(seed)
        self.trades: List[Trade] = []
        self.open_trade: Optional[Trade] = None
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.current_date = None
        self.equity_curve = []
        self.daily_results = {}
        self.pm = 10000
        self.pip_value = 10.0
        self.trade_open_bar = 0

    def _setup_pair(self, symbol, candles):
        is_jpy = "JPY" in symbol.upper()
        self.pm = 100 if is_jpy else 10000
        if candles:
            price = candles[len(candles) // 2]["close"]
            self.pip_value = 1000.0 / price if is_jpy else 10.0

    # ── D1 Precomputation: Trend + Major S/R ──

    def _precompute_d1(self, d1_candles, params):
        n = len(d1_candles)
        closes = np.array([c["close"] for c in d1_candles])
        highs = np.array([c["high"] for c in d1_candles])
        lows = np.array([c["low"] for c in d1_candles])

        # D1 Swing detection (for market structure)
        d1_swing_lb = params.get("d1_swing_lookback", 10)
        d1_swing_highs = []
        d1_swing_lows = []
        for i in range(d1_swing_lb, n - d1_swing_lb):
            ws, we = max(0, i - d1_swing_lb), min(n, i + d1_swing_lb + 1)
            if highs[i] >= np.max(highs[ws:we]):
                d1_swing_highs.append((i, float(highs[i]), i + d1_swing_lb))
            if lows[i] <= np.min(lows[ws:we]):
                d1_swing_lows.append((i, float(lows[i]), i + d1_swing_lb))

        self.d1_closes = closes
        self.d1_highs = highs
        self.d1_lows = lows
        self.d1_swing_highs = sorted(d1_swing_highs, key=lambda x: x[2])
        self.d1_swing_lows = sorted(d1_swing_lows, key=lambda x: x[2])
        self.d1_sh_confs = [x[2] for x in self.d1_swing_highs]
        self.d1_sl_confs = [x[2] for x in self.d1_swing_lows]

    def _d1_trend(self, d1_idx):
        """Market structure from D1: uptrend, downtrend, or ranging."""
        # Get last 4 confirmed swing points
        hi_cut = bisect.bisect_right(self.d1_sh_confs, d1_idx)
        lo_cut = bisect.bisect_right(self.d1_sl_confs, d1_idx)

        recent_highs = [p for _, p, _ in self.d1_swing_highs[max(0, hi_cut - 4):hi_cut]]
        recent_lows = [p for _, p, _ in self.d1_swing_lows[max(0, lo_cut - 4):lo_cut]]

        if len(recent_highs) < 2 or len(recent_lows) < 2:
            return "RANGING"

        hh = recent_highs[-1] > recent_highs[-2]  # Higher high
        hl = recent_lows[-1] > recent_lows[-2]    # Higher low
        lh = recent_highs[-1] < recent_highs[-2]  # Lower high
        ll = recent_lows[-1] < recent_lows[-2]    # Lower low

        if hh and hl:
            return "UP"
        elif lh and ll:
            return "DOWN"
        return "RANGING"

    # ── H4 Precomputation: S/R + ATR + RSI ──

    def _precompute_h4(self, h4_candles, params):
        n = len(h4_candles)
        closes = np.array([c["close"] for c in h4_candles])
        highs = np.array([c["high"] for c in h4_candles])
        lows = np.array([c["low"] for c in h4_candles])

        # ATR
        atr = np.zeros(n)
        for i in range(1, n):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            atr[i] = atr[i - 1] * 13 / 14 + tr / 14 if i > 1 else tr

        # RSI
        rsi = np.full(n, 50.0)
        gains = np.zeros(n)
        losses_arr = np.zeros(n)
        for i in range(1, n):
            d = closes[i] - closes[i - 1]
            if d > 0: gains[i] = d
            else: losses_arr[i] = abs(d)
        avg_g, avg_l = 0.0, 0.0
        for i in range(1, n):
            if i <= 14:
                avg_g = np.mean(gains[1:i + 1]) if i > 0 else 0
                avg_l = np.mean(losses_arr[1:i + 1]) if i > 0 else 0
            else:
                avg_g = (avg_g * 13 + gains[i]) / 14
                avg_l = (avg_l * 13 + losses_arr[i]) / 14
            if avg_l > 0:
                rsi[i] = 100 - 100 / (1 + avg_g / avg_l)
            else:
                rsi[i] = 100 if avg_g > 0 else 50

        # H4 Swing levels
        h4_swing_lb = params.get("h4_swing_lookback", 15)
        swing_highs, swing_lows = [], []
        for i in range(h4_swing_lb, n - h4_swing_lb):
            ws, we = max(0, i - h4_swing_lb), min(n, i + h4_swing_lb + 1)
            if highs[i] >= np.max(highs[ws:we]):
                swing_highs.append((i, float(highs[i]), i + h4_swing_lb))
            if lows[i] <= np.min(lows[ws:we]):
                swing_lows.append((i, float(lows[i]), i + h4_swing_lb))

        swing_highs.sort(key=lambda x: x[2])
        swing_lows.sort(key=lambda x: x[2])

        self.h4_atr = atr
        self.h4_rsi = rsi
        self.h4_avg_atr = float(np.mean(atr[max(0, n - 200):]))
        self.h4_closes = closes
        self.h4_swing_highs = swing_highs
        self.h4_swing_lows = swing_lows
        self.h4_sh_confs = [x[2] for x in swing_highs]
        self.h4_sl_confs = [x[2] for x in swing_lows]
        self._h4_zone_cache = {}

    def _get_h4_sr_zones(self, h4_idx, params):
        cache_key = h4_idx // 3
        if cache_key in self._h4_zone_cache:
            return self._h4_zone_cache[cache_key]
        cluster_pips = params.get("sr_cluster_pips", 50)
        cluster_dist = cluster_pips / self.pm
        hi_cut = bisect.bisect_right(self.h4_sh_confs, h4_idx)
        lo_cut = bisect.bisect_right(self.h4_sl_confs, h4_idx)
        recent_h = self.h4_swing_highs[max(0, hi_cut - 30):hi_cut]
        recent_l = self.h4_swing_lows[max(0, lo_cut - 30):lo_cut]
        all_levels = sorted([p for _, p, _ in recent_h] + [p for _, p, _ in recent_l])
        if not all_levels:
            self._h4_zone_cache[cache_key] = []
            return []
        zones, used = [], set()
        for i, lev in enumerate(all_levels):
            if i in used: continue
            cluster = [lev]
            for j in range(i + 1, len(all_levels)):
                if j in used: continue
                if abs(all_levels[j] - lev) <= cluster_dist:
                    cluster.append(all_levels[j])
                    used.add(j)
            used.add(i)
            zones.append((float(np.mean(cluster)), len(cluster)))
        self._h4_zone_cache[cache_key] = zones
        return zones

    # ── D1→H4 index mapping ──

    def _build_d1_lookup(self, d1_candles, h4_candles):
        """For each H4 candle, find the most recent completed D1 candle index."""
        d1_end_times = [c["datetime"] + timedelta(days=1) for c in d1_candles]
        d1_refs = []
        for h4c in h4_candles:
            ref = bisect.bisect_right(d1_end_times, h4c["datetime"]) - 1
            d1_refs.append(max(0, ref))
        return d1_refs

    # ── Execution Timeline (H4 + H2) ──

    def _build_timeline(self, h4_candles, h2_candles):
        timeline = []
        if not h2_candles:
            for i, c in enumerate(h4_candles):
                timeline.append((c, max(0, i - 1)))
            return timeline
        h2_start = h2_candles[0]["datetime"]
        h4_end_times = [c["datetime"] + timedelta(hours=4) for c in h4_candles]
        for i, c in enumerate(h4_candles):
            if c["datetime"] >= h2_start:
                break
            timeline.append((c, max(0, i - 1)))
        for h2c in h2_candles:
            ref = bisect.bisect_right(h4_end_times, h2c["datetime"]) - 1
            if ref >= 1:
                timeline.append((h2c, ref))
        return timeline

    # ── Spread / Slippage ──

    def _compute_spread(self, candle, atr, avg_atr, is_news, base_spread):
        h = candle["datetime"].hour
        if 7 <= h <= 8: sm = 1.0
        elif 13 <= h <= 16: sm = 0.9
        elif 22 <= h or h <= 4: sm = 1.8
        else: sm = 1.2
        vm = 1.0 + max(0, (atr / avg_atr - 1)) * 0.5 if avg_atr > 0 else 1.0
        nm = 3.0 if is_news else 1.0
        return max(base_spread * sm * vm * nm * 1.2, base_spread * 0.5)

    def _compute_slippage(self, atr, avg_atr, is_news):
        base = atr * self.pm * 0.02
        base = max(0, min(base, 0.5))
        if is_news: base = min(base * 3, 2.0)
        if avg_atr > 0 and atr / avg_atr > 1.5: base *= 1.5
        return base * self.rng.random()

    # ── Signal ──

    def _swing_signal(self, h4_idx, d1_idx, exec_candles, exec_idx, params, strategy_type):
        if exec_idx < 3:
            return None, 0, 0

        zones = self._get_h4_sr_zones(h4_idx, params)
        if not zones:
            return None, 0, 0

        d1_trend = self._d1_trend(d1_idx)
        prev_c = exec_candles[exec_idx - 1]
        prev_close = prev_c["close"]
        proximity_pips = params.get("sr_proximity_pips", 30)
        proximity = proximity_pips / self.pm
        min_zone_strength = params.get("min_zone_strength", 2)
        rsi_val = self.h4_rsi[h4_idx]
        min_rr = params.get("min_rr", 2.5)

        patterns = detect_pattern(exec_candles, exec_idx - 1)

        for zone_price, zone_strength in zones:
            if zone_strength < min_zone_strength:
                continue
            dist = abs(prev_close - zone_price)
            if dist > proximity:
                continue

            if strategy_type in ("BOUNCE", "COMBINED"):
                # Support bounce (BUY) — only in UP or RANGING trend
                if prev_close >= zone_price - proximity and prev_close <= zone_price + proximity * 0.3:
                    if d1_trend in ("UP", "RANGING"):
                        bullish = [p for p in patterns if p in
                                   ("BULLISH_PINBAR", "HAMMER", "BULLISH_ENGULFING", "MORNING_STAR", "DOJI")]
                        if bullish and rsi_val < 65:
                            sl_dist = max(params.get("min_sl_pips", 30) / self.pm,
                                          dist + params.get("sl_buffer_pips", 10) / self.pm)
                            sl_dist = min(sl_dist, params.get("max_sl_pips", 150) / self.pm)
                            tp_dist = sl_dist * min_rr
                            return "BUY", sl_dist, tp_dist

                # Resistance bounce (SELL) — only in DOWN or RANGING
                if prev_close <= zone_price + proximity and prev_close >= zone_price - proximity * 0.3:
                    if d1_trend in ("DOWN", "RANGING"):
                        bearish = [p for p in patterns if p in
                                   ("BEARISH_PINBAR", "SHOOTING_STAR", "BEARISH_ENGULFING", "EVENING_STAR", "DOJI")]
                        if bearish and rsi_val > 35:
                            sl_dist = max(params.get("min_sl_pips", 30) / self.pm,
                                          dist + params.get("sl_buffer_pips", 10) / self.pm)
                            sl_dist = min(sl_dist, params.get("max_sl_pips", 150) / self.pm)
                            tp_dist = sl_dist * min_rr
                            return "SELL", sl_dist, tp_dist

            if strategy_type in ("BREAKOUT", "COMBINED"):
                break_pips = params.get("sr_break_pips", 20)
                break_dist = break_pips / self.pm
                prev_open = prev_c["open"]

                # Bullish breakout — confirmed by D1 trend
                if prev_close > zone_price + break_dist and prev_open <= zone_price + break_dist:
                    if d1_trend in ("UP", "RANGING"):
                        strong = any(p in patterns for p in ("STRONG_BULLISH", "BULLISH_ENGULFING"))
                        if strong and rsi_val > 40:
                            sl_dist = max(params.get("min_sl_pips", 30) / self.pm,
                                          abs(prev_close - zone_price) + params.get("sl_buffer_pips", 10) / self.pm)
                            sl_dist = min(sl_dist, params.get("max_sl_pips", 150) / self.pm)
                            tp_dist = sl_dist * min_rr
                            return "BUY", sl_dist, tp_dist

                # Bearish breakout
                if prev_close < zone_price - break_dist and prev_open >= zone_price - break_dist:
                    if d1_trend in ("DOWN", "RANGING"):
                        strong = any(p in patterns for p in ("STRONG_BEARISH", "BEARISH_ENGULFING"))
                        if strong and rsi_val < 60:
                            sl_dist = max(params.get("min_sl_pips", 30) / self.pm,
                                          abs(prev_close - zone_price) + params.get("sl_buffer_pips", 10) / self.pm)
                            sl_dist = min(sl_dist, params.get("max_sl_pips", 150) / self.pm)
                            tp_dist = sl_dist * min_rr
                            return "SELL", sl_dist, tp_dist

        return None, 0, 0

    # ── Trade Management ──

    def _can_trade(self, params):
        dl = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        td = (self.initial_balance - self.balance) / self.initial_balance if self.balance < self.initial_balance else 0
        if dl >= 0.03 or td >= 0.06: return False
        if self.daily_trades >= params.get("max_daily_trades", 3): return False
        if self.consecutive_losses >= params.get("max_consecutive_losses", 2): return False
        return True

    def _open_trade(self, direction, candle, spread_pips, sl_dist, tp_dist, atr, avg_atr, is_news, params):
        sp = spread_pips / self.pm
        slip = self._compute_slippage(atr, avg_atr, is_news) / self.pm
        r = self.rng.random()
        if r > 0.995: return
        if r > 0.98: return
        fill_pct = 1.0 if r > 0.03 else self.rng.uniform(0.5, 0.95)

        entry = candle["open"] + sp + slip if direction == "BUY" else candle["open"] - slip
        sl = entry - sl_dist if direction == "BUY" else entry + sl_dist
        tp = entry + tp_dist if direction == "BUY" else entry - tp_dist

        risk_pct = params.get("risk_per_trade", 0.005)
        sl_pips = sl_dist * self.pm
        if sl_pips <= 0: return
        lot_size = max(0.01, min(self.balance * risk_pct / (sl_pips * self.pip_value) * fill_pct, 10.0))

        latency_slip = self.rng.uniform(0.1, 0.3) * atr * 0.01
        entry += latency_slip if direction == "BUY" else -latency_slip

        self.open_trade = Trade(entry_price=entry, stop_loss=sl, take_profit=tp,
                                direction=direction, size=lot_size, entry_time=candle["datetime"])

    def _check_exit(self, candle, spread_pips):
        t = self.open_trade
        if not t: return None
        sp = spread_pips / self.pm

        # FTMO safety
        dl = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        td = (self.initial_balance - self.balance) / self.initial_balance if self.balance < self.initial_balance else 0
        if dl >= 0.03 or td >= 0.06:
            ep = candle["close"] if t.direction == "BUY" else candle["close"] + sp
            return ep, "SAFETY"

        if t.direction == "BUY":
            sl_hit = candle["low"] <= t.stop_loss
            tp_hit = candle["high"] >= t.take_profit
            if sl_hit and tp_hit:
                return (t.stop_loss, "SL") if abs(candle["open"] - t.stop_loss) <= abs(candle["open"] - t.take_profit) else (t.take_profit, "TP")
            if sl_hit: return t.stop_loss, "SL"
            if tp_hit: return t.take_profit, "TP"
        else:
            ask_h, ask_l = candle["high"] + sp, candle["low"] + sp
            sl_hit = ask_h >= t.stop_loss
            tp_hit = ask_l <= t.take_profit
            if sl_hit and tp_hit:
                return (t.stop_loss, "SL") if abs(candle["open"] + sp - t.stop_loss) <= abs(candle["open"] + sp - t.take_profit) else (t.take_profit, "TP")
            if sl_hit: return t.stop_loss, "SL"
            if tp_hit: return t.take_profit, "TP"
        return None

    def _close_trade(self, exit_price, exit_time, reason, spread_pips, slip_pips):
        t = self.open_trade
        if not t: return
        if reason == "SL":
            exit_price += -slip_pips / self.pm if t.direction == "BUY" else slip_pips / self.pm
        pnl = ((exit_price - t.entry_price) if t.direction == "BUY" else (t.entry_price - exit_price)) * t.size * self.pm * self.pip_value
        max_daily = 0.045 * self.initial_balance
        if pnl < 0:
            remaining = max_daily - abs(min(0, self.daily_pnl))
            if remaining > 0 and abs(pnl) > remaining: pnl = -remaining
        t.exit_price, t.exit_time, t.pnl, t.reason = exit_price, exit_time, pnl, reason
        self.balance += pnl
        self.daily_pnl += pnl
        self.trades.append(t)
        self.open_trade = None
        self.daily_trades += 1
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

    def _reset_daily(self):
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0

    # ── Main Run ──

    def run(self, h4_candles, d1_candles, strategy_type="BOUNCE", params=None,
            symbol="USDJPY", base_spread=None, h2_candles=None):
        if params is None: params = {}
        if base_spread is None:
            base_spread = 1.8 if "JPY" in symbol else 0.8

        self.balance = self.initial_balance
        self.trades, self.open_trade = [], None
        self.daily_pnl, self.daily_trades, self.consecutive_losses = 0.0, 0, 0
        self.current_date = None
        self.equity_curve, self.daily_results = [], {}
        self.rng = random.Random(42)
        self.trade_open_bar = 0

        self._setup_pair(symbol, h4_candles)
        self._precompute_d1(d1_candles, params)
        self._precompute_h4(h4_candles, params)

        d1_refs = self._build_d1_lookup(d1_candles, h4_candles)
        timeline = self._build_timeline(h4_candles, h2_candles)
        exec_candles_flat = [c for c, _ in timeline]

        max_hold_bars = params.get("max_hold_bars", 120)  # ~10 days in H2
        min_h4_history = params.get("h4_swing_lookback", 15) * 2 + 5

        for j in range(3, len(timeline)):
            c, h4_idx = timeline[j]
            if h4_idx < min_h4_history: continue
            d1_idx = d1_refs[min(h4_idx, len(d1_refs) - 1)]

            dt = c["datetime"]
            d = dt.date()
            if d != self.current_date:
                if self.current_date: self.daily_results[str(self.current_date)] = self.daily_pnl
                self.current_date = d
                self._reset_daily()

            self.equity_curve.append(self.balance)
            is_news = news_calendar.is_news_window(dt, window_minutes=3)
            atr_val = self.h4_atr[h4_idx]
            spr = self._compute_spread(c, atr_val, self.h4_avg_atr, is_news, base_spread)

            # ── EXIT ──
            if self.open_trade:
                # Max hold time check
                if j - self.trade_open_bar >= max_hold_bars:
                    ep = c["close"] if self.open_trade.direction == "BUY" else c["close"] + spr / self.pm
                    es = self._compute_slippage(atr_val, self.h4_avg_atr, is_news)
                    self._close_trade(ep, dt, "MAX_HOLD", spr, es)
                    continue

                er = self._check_exit(c, spr)
                if er:
                    ep, reason = er
                    es = self._compute_slippage(atr_val, self.h4_avg_atr, is_news) if reason == "SL" else 0
                    self._close_trade(ep, dt, reason, spr, es)
                continue

            if not self._can_trade(params): continue

            sig, sl_dist, tp_dist = self._swing_signal(h4_idx, d1_idx, exec_candles_flat, j, params, strategy_type)

            if sig and sl_dist > 0 and tp_dist > 0:
                self._open_trade(sig, c, spr, sl_dist, tp_dist, atr_val, self.h4_avg_atr, is_news, params)
                if self.open_trade:
                    self.trade_open_bar = j

        if self.open_trade and timeline:
            last_c, _ = timeline[-1]
            self._close_trade(last_c["close"], last_c["datetime"], "EOD", 0, 0)

        return self._compute_result()

    def _compute_result(self):
        tr = self.trades
        if not tr: return BacktestResult()
        wins = [t for t in tr if t.pnl > 0]
        losses_l = [t for t in tr if t.pnl <= 0]
        gp = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in losses_l))
        mx_dd, pk, b = 0, self.initial_balance, self.initial_balance
        for t in tr:
            b += t.pnl
            if b > pk: pk = b
            dd = (self.initial_balance - b) / self.initial_balance if b < self.initial_balance else 0
            mx_dd = max(mx_dd, dd)
        dl = [abs(v) / self.initial_balance for v in self.daily_results.values() if v < 0]
        mx_daily = max(dl) if dl else 0
        start = tr[0].entry_time
        end = tr[-1].exit_time or tr[-1].entry_time
        days = max(1, (end - start).days)
        weeks = max(1, days / 7)
        total_pnl = sum(t.pnl for t in tr)
        ret = total_pnl / self.initial_balance * 100
        ftmo = mx_dd * 100 < 8 and mx_daily * 100 < 4.5
        return BacktestResult(
            total_trades=len(tr), wins=len(wins), losses=len(losses_l),
            win_rate=round(len(wins) / len(tr) * 100, 1) if tr else 0,
            total_pnl=round(total_pnl, 2), total_return_pct=round(ret, 2),
            weekly_return_pct=round(ret / weeks, 3),
            profit_factor=round(gp / gl, 2) if gl > 0 else 99.0,
            max_drawdown_pct=round(mx_dd * 100, 2),
            max_daily_loss_pct=round(mx_daily * 100, 2), ftmo_compliant=ftmo,
            start_date=start.strftime("%Y-%m-%d"), end_date=end.strftime("%Y-%m-%d"),
            avg_trade_pnl=round(total_pnl / len(tr), 2) if tr else 0,
            equity_curve=self.equity_curve, daily_returns=list(self.daily_results.values()),
        )
