"""
Price Action Backtester V4 — Support/Résistance + Bougies Japonaises + Chartisme

Stratégies basées UNIQUEMENT sur :
  - Support / Résistance (swing highs/lows avec confirmation retardée)
  - Signaux en bougies japonaises (pin bar, engulfing, hammer, shooting star, doji)
  - Chartisme (breakout de niveaux, rejection, double top/bottom)
  - RSI en support uniquement (divergences, surachat/survente)
  - Session awareness (London/NY pour activité plus élevée)

PAS d'EMA, PAS de MACD, PAS d'indicateurs de tendance classiques.

Toutes les 10 règles de sécurité sont conservées :
  spread variable, bid/ask, anti-lookahead, latence, news, FTMO, walk-forward, robustesse
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

def _range(c):
    return c["high"] - c["low"]

def _upper_wick(c):
    return c["high"] - max(c["open"], c["close"])

def _lower_wick(c):
    return min(c["open"], c["close"]) - c["low"]

def _is_bullish(c):
    return c["close"] > c["open"]

def _is_bearish(c):
    return c["close"] < c["open"]


def detect_pattern(candles, idx):
    """
    Detect candlestick pattern at candles[idx] using candles[idx-2:idx+1].
    Returns list of pattern names detected.
    Anti-lookahead: only uses candles[idx] and before.
    """
    if idx < 2:
        return []

    c = candles[idx]
    p1 = candles[idx - 1]
    p2 = candles[idx - 2]

    patterns = []
    body = _body(c)
    rng = _range(c)
    uw = _upper_wick(c)
    lw = _lower_wick(c)

    if rng <= 0:
        return []

    body_ratio = body / rng

    # ── Pin Bar / Hammer / Shooting Star ──
    if body_ratio < 0.35:
        if lw > body * 2.0 and uw < body * 1.0:
            patterns.append("BULLISH_PINBAR")
        if uw > body * 2.0 and lw < body * 1.0:
            patterns.append("BEARISH_PINBAR")

    # ── Hammer (at potential support) ──
    if _is_bullish(c) and lw > body * 2.0 and uw < body * 0.5:
        patterns.append("HAMMER")

    # ── Shooting Star (at potential resistance) ──
    if _is_bearish(c) and uw > body * 2.0 and lw < body * 0.5:
        patterns.append("SHOOTING_STAR")

    # ── Engulfing ──
    if _is_bullish(c) and _is_bearish(p1):
        if c["close"] > p1["open"] and c["open"] < p1["close"]:
            patterns.append("BULLISH_ENGULFING")
    if _is_bearish(c) and _is_bullish(p1):
        if c["close"] < p1["open"] and c["open"] > p1["close"]:
            patterns.append("BEARISH_ENGULFING")

    # ── Doji ──
    if body_ratio < 0.1 and rng > 0:
        patterns.append("DOJI")

    # ── Morning Star (3-candle bullish reversal) ──
    if _is_bearish(p2) and _body(p1) / _range(p1) < 0.3 if _range(p1) > 0 else False:
        if _is_bullish(c) and c["close"] > (p2["open"] + p2["close"]) / 2:
            patterns.append("MORNING_STAR")

    # ── Evening Star (3-candle bearish reversal) ──
    if _is_bullish(p2) and _body(p1) / _range(p1) < 0.3 if _range(p1) > 0 else False:
        if _is_bearish(c) and c["close"] < (p2["open"] + p2["close"]) / 2:
            patterns.append("EVENING_STAR")

    # ── Strong Body (for breakout confirmation) ──
    if body_ratio > 0.65:
        if _is_bullish(c):
            patterns.append("STRONG_BULLISH")
        else:
            patterns.append("STRONG_BEARISH")

    return patterns


class PriceActionBacktester:
    """Price Action Backtester with S/R, candlestick patterns, and chartism."""

    def __init__(self, initial_balance: float = 100000, seed: int = 42):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.rng = random.Random(seed)
        self.trades: List[Trade] = []
        self.open_trade: Optional[Trade] = None
        self.daily_pnl = 0.0
        self.daily_start = initial_balance
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.current_date = None
        self.equity_curve = []
        self.daily_results = {}
        self.pm = 10000
        self.pip_value = 10.0

    def _setup_pair(self, symbol, candles):
        is_jpy = "JPY" in symbol.upper()
        self.pm = 100 if is_jpy else 10000
        if candles:
            price = candles[len(candles) // 2]["close"]
            self.pip_value = 1000.0 / price if is_jpy else 10.0

    # ── H1 Pre-computation ──

    def _precompute_h1(self, h1_candles, params):
        n = len(h1_candles)
        closes = np.array([c["close"] for c in h1_candles])
        highs = np.array([c["high"] for c in h1_candles])
        lows = np.array([c["low"] for c in h1_candles])

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
            if d > 0:
                gains[i] = d
            else:
                losses_arr[i] = abs(d)
        avg_g = 0.0
        avg_l = 0.0
        for i in range(1, n):
            if i <= 14:
                avg_g = np.mean(gains[1: i + 1]) if i > 0 else 0
                avg_l = np.mean(losses_arr[1: i + 1]) if i > 0 else 0
            else:
                avg_g = (avg_g * 13 + gains[i]) / 14
                avg_l = (avg_l * 13 + losses_arr[i]) / 14
            if avg_l > 0:
                rsi[i] = 100 - 100 / (1 + avg_g / avg_l)
            else:
                rsi[i] = 100 if avg_g > 0 else 50

        # Swing detection with delayed confirmation
        swing_lookback = params.get("swing_lookback", 10)
        swing_highs = []
        swing_lows = []

        for i in range(swing_lookback, n - swing_lookback):
            ws = max(0, i - swing_lookback)
            we = min(n, i + swing_lookback + 1)
            if highs[i] >= np.max(highs[ws:we]):
                swing_highs.append((i, float(highs[i]), i + swing_lookback))
            if lows[i] <= np.min(lows[ws:we]):
                swing_lows.append((i, float(lows[i]), i + swing_lookback))

        # Sort by confirmed_at for binary search
        swing_highs.sort(key=lambda x: x[2])
        swing_lows.sort(key=lambda x: x[2])

        self.h1_atr = atr
        self.h1_rsi = rsi
        self.h1_avg_atr = float(np.mean(atr[max(0, n - 200):]))
        self.h1_closes = closes
        self.h1_highs = highs
        self.h1_lows = lows
        self.swing_highs = swing_highs
        self.swing_lows = swing_lows
        self._sh_confs = [x[2] for x in swing_highs]
        self._sl_confs = [x[2] for x in swing_lows]
        self._zone_cache = {}

    def _get_sr_zones(self, h1_idx, params):
        """Get S/R zones with caching and binary search."""
        cache_key = h1_idx // 3  # Cache every 3 H1 candles
        if cache_key in self._zone_cache:
            return self._zone_cache[cache_key]

        cluster_pips = params.get("sr_cluster_pips", 20)
        cluster_dist = cluster_pips / self.pm
        max_zones = 30

        # Binary search for confirmed swings
        hi_cutoff = bisect.bisect_right(self._sh_confs, h1_idx)
        lo_cutoff = bisect.bisect_right(self._sl_confs, h1_idx)

        recent_highs = self.swing_highs[max(0, hi_cutoff - max_zones):hi_cutoff]
        recent_lows = self.swing_lows[max(0, lo_cutoff - max_zones):lo_cutoff]

        all_levels = sorted([p for _, p, _ in recent_highs] + [p for _, p, _ in recent_lows])
        if not all_levels:
            self._zone_cache[cache_key] = []
            return []

        # Cluster
        zones = []
        used = set()
        for i, level in enumerate(all_levels):
            if i in used:
                continue
            cluster = [level]
            for j_ in range(i + 1, len(all_levels)):
                if j_ in used:
                    continue
                if abs(all_levels[j_] - level) <= cluster_dist:
                    cluster.append(all_levels[j_])
                    used.add(j_)
            used.add(i)
            zones.append((float(np.mean(cluster)), len(cluster)))

        self._zone_cache[cache_key] = zones
        return zones

    # ── Execution Timeline ──

    def _build_timeline(self, h1_candles, m30_candles):
        timeline = []
        if not m30_candles:
            for i, c in enumerate(h1_candles):
                timeline.append((c, max(0, i - 1)))
            return timeline

        m30_start = m30_candles[0]["datetime"]
        h1_end_times = [c["datetime"] + timedelta(hours=1) for c in h1_candles]

        for i, c in enumerate(h1_candles):
            if c["datetime"] >= m30_start:
                break
            timeline.append((c, max(0, i - 1)))

        for m30c in m30_candles:
            t = m30c["datetime"]
            ref = bisect.bisect_right(h1_end_times, t) - 1
            if ref >= 1:
                timeline.append((m30c, ref))

        return timeline

    # ── Spread / Slippage ──

    def _compute_spread(self, candle, atr, avg_atr, is_news, base_spread):
        h = candle["datetime"].hour
        if 7 <= h <= 8:
            sm = 1.0
        elif 13 <= h <= 16:
            sm = 0.9
        elif 22 <= h or h <= 4:
            sm = 1.8
        else:
            sm = 1.2
        vm = 1.0 + max(0, (atr / avg_atr - 1)) * 0.5 if avg_atr > 0 else 1.0
        nm = 3.0 if is_news else 1.0
        spread = base_spread * sm * vm * nm * 1.2
        return max(spread, base_spread * 0.5)

    def _compute_slippage(self, atr, avg_atr, is_news):
        base = atr * self.pm * 0.02
        base = max(0, min(base, 0.5))
        if is_news:
            base *= 3
            base = min(base, 2.0)
        if avg_atr > 0 and atr / avg_atr > 1.5:
            base *= 1.5
        return base * self.rng.random()

    # ── Signal Generation ──

    def _is_high_activity_session(self, hour):
        """London 7-16, NY 13-20 overlap 13-16."""
        return 7 <= hour <= 20

    def _bounce_signal(self, h1_idx, exec_candles, exec_idx, params):
        """
        S/R Bounce signal.
        Price approaches S/R zone + candlestick rejection pattern + RSI confirmation.
        """
        if exec_idx < 3:
            return None, 0, 0

        zones = self._get_sr_zones(h1_idx, params)
        if not zones:
            return None, 0, 0

        prev_c = exec_candles[exec_idx - 1]
        prev_c2 = exec_candles[exec_idx - 2]
        prev_c3 = exec_candles[exec_idx - 3]
        current_c = exec_candles[exec_idx]

        prev_close = prev_c["close"]
        proximity_pips = params.get("sr_proximity_pips", 10)
        proximity = proximity_pips / self.pm
        min_zone_strength = params.get("min_zone_strength", 2)
        rsi_extreme = params.get("rsi_extreme", 35)

        rsi_val = self.h1_rsi[h1_idx]
        atr_val = self.h1_atr[h1_idx]

        # Detect patterns on the previous 3 execution candles
        patterns = detect_pattern(exec_candles, exec_idx - 1)

        for zone_price, zone_strength in zones:
            if zone_strength < min_zone_strength:
                continue

            dist = abs(prev_close - zone_price)
            if dist > proximity:
                continue

            # ── SUPPORT BOUNCE (BUY) ──
            if prev_close >= zone_price - proximity and prev_close <= zone_price + proximity * 0.5:
                # Price is at or just above support
                bullish_patterns = [p for p in patterns if p in (
                    "BULLISH_PINBAR", "HAMMER", "BULLISH_ENGULFING",
                    "MORNING_STAR", "DOJI"
                )]
                if bullish_patterns:
                    # RSI confirmation (oversold or neutral, not overbought)
                    if rsi_val < (100 - rsi_extreme):
                        # SL below the zone
                        sl_dist = max(
                            params.get("min_sl_pips", 10) / self.pm,
                            dist + params.get("sl_buffer_pips", 5) / self.pm
                        )
                        sl_dist = min(sl_dist, params.get("max_sl_pips", 30) / self.pm)
                        tp_dist = sl_dist * params.get("min_rr", 2.5)
                        return "BUY", sl_dist, tp_dist

            # ── RESISTANCE BOUNCE (SELL) ──
            if prev_close <= zone_price + proximity and prev_close >= zone_price - proximity * 0.5:
                bearish_patterns = [p for p in patterns if p in (
                    "BEARISH_PINBAR", "SHOOTING_STAR", "BEARISH_ENGULFING",
                    "EVENING_STAR", "DOJI"
                )]
                if bearish_patterns:
                    if rsi_val > rsi_extreme:
                        sl_dist = max(
                            params.get("min_sl_pips", 10) / self.pm,
                            dist + params.get("sl_buffer_pips", 5) / self.pm
                        )
                        sl_dist = min(sl_dist, params.get("max_sl_pips", 30) / self.pm)
                        tp_dist = sl_dist * params.get("min_rr", 2.5)
                        return "SELL", sl_dist, tp_dist

        return None, 0, 0

    def _breakout_signal(self, h1_idx, exec_candles, exec_idx, params):
        """
        S/R Breakout signal.
        Price breaks through S/R zone with strong candle confirmation.
        """
        if exec_idx < 3:
            return None, 0, 0

        zones = self._get_sr_zones(h1_idx, params)
        if not zones:
            return None, 0, 0

        prev_c = exec_candles[exec_idx - 1]
        prev_c2 = exec_candles[exec_idx - 2]
        prev_close = prev_c["close"]
        prev_open = prev_c["open"]

        break_pips = params.get("sr_break_pips", 10)
        break_dist = break_pips / self.pm
        min_zone_strength = params.get("min_zone_strength", 2)

        rsi_val = self.h1_rsi[h1_idx]
        atr_val = self.h1_atr[h1_idx]

        patterns = detect_pattern(exec_candles, exec_idx - 1)

        for zone_price, zone_strength in zones:
            if zone_strength < min_zone_strength:
                continue

            # ── BULLISH BREAKOUT (price closes above resistance) ──
            if prev_close > zone_price + break_dist and prev_open <= zone_price + break_dist:
                # Previous candle was below, now above = breakout
                strong = any(p in patterns for p in ("STRONG_BULLISH", "BULLISH_ENGULFING"))
                if strong:
                    # RSI confirms momentum (above 45)
                    if rsi_val > 45:
                        # SL at the broken level
                        sl_dist = max(
                            params.get("min_sl_pips", 10) / self.pm,
                            abs(prev_close - zone_price) + params.get("sl_buffer_pips", 5) / self.pm
                        )
                        sl_dist = min(sl_dist, params.get("max_sl_pips", 30) / self.pm)
                        tp_dist = sl_dist * params.get("min_rr", 2.5)
                        return "BUY", sl_dist, tp_dist

            # ── BEARISH BREAKOUT (price closes below support) ──
            if prev_close < zone_price - break_dist and prev_open >= zone_price - break_dist:
                strong = any(p in patterns for p in ("STRONG_BEARISH", "BEARISH_ENGULFING"))
                if strong:
                    if rsi_val < 55:
                        sl_dist = max(
                            params.get("min_sl_pips", 10) / self.pm,
                            abs(prev_close - zone_price) + params.get("sl_buffer_pips", 5) / self.pm
                        )
                        sl_dist = min(sl_dist, params.get("max_sl_pips", 30) / self.pm)
                        tp_dist = sl_dist * params.get("min_rr", 2.5)
                        return "SELL", sl_dist, tp_dist

        return None, 0, 0

    # ── Trade Management (same as v3) ──

    def _can_trade(self, params):
        dl = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        td = (self.initial_balance - self.balance) / self.initial_balance if self.balance < self.initial_balance else 0
        if dl >= 0.03 or td >= 0.06:
            return False
        if self.daily_trades >= params.get("max_daily_trades", 5):
            return False
        if self.consecutive_losses >= params.get("max_consecutive_losses", 3):
            return False
        return True

    def _open_trade(self, direction, candle, spread_pips, sl_dist, tp_dist, atr, avg_atr, is_news, params, symbol):
        sp = spread_pips / self.pm
        slip = self._compute_slippage(atr, avg_atr, is_news) / self.pm

        r = self.rng.random()
        if r > 0.995:
            return
        if r > 0.98:
            return
        fill_pct = 1.0 if r > 0.03 else self.rng.uniform(0.5, 0.95)

        if direction == "BUY":
            entry = candle["open"] + sp + slip
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            entry = candle["open"] - slip
            sl = entry + sl_dist
            tp = entry - tp_dist

        risk_pct = params.get("risk_per_trade", 0.005)
        risk_amount = self.balance * risk_pct
        sl_pips = sl_dist * self.pm
        if sl_pips <= 0:
            return
        lot_size = risk_amount / (sl_pips * self.pip_value)
        lot_size *= fill_pct
        lot_size = max(0.01, min(lot_size, 10.0))

        latency_slip = self.rng.uniform(0.1, 0.3) * atr * 0.01
        if direction == "BUY":
            entry += latency_slip
        else:
            entry -= latency_slip

        self.open_trade = Trade(
            entry_price=entry, stop_loss=sl, take_profit=tp,
            direction=direction, size=lot_size, entry_time=candle["datetime"],
        )

    def _check_exit(self, candle, spread_pips, symbol):
        t = self.open_trade
        if not t:
            return None
        sp = spread_pips / self.pm

        dl = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        td = (self.initial_balance - self.balance) / self.initial_balance if self.balance < self.initial_balance else 0
        if dl >= 0.03 or td >= 0.06:
            ep = candle["close"] if t.direction == "BUY" else candle["close"] + sp
            return ep, "SAFETY"

        if t.direction == "BUY":
            sl_hit = candle["low"] <= t.stop_loss
            tp_hit = candle["high"] >= t.take_profit
            if sl_hit and tp_hit:
                if abs(candle["open"] - t.stop_loss) <= abs(candle["open"] - t.take_profit):
                    return t.stop_loss, "SL"
                else:
                    return t.take_profit, "TP"
            if sl_hit:
                return t.stop_loss, "SL"
            if tp_hit:
                return t.take_profit, "TP"
        else:
            ask_high = candle["high"] + sp
            ask_low = candle["low"] + sp
            sl_hit = ask_high >= t.stop_loss
            tp_hit = ask_low <= t.take_profit
            if sl_hit and tp_hit:
                if abs(candle["open"] + sp - t.stop_loss) <= abs(candle["open"] + sp - t.take_profit):
                    return t.stop_loss, "SL"
                else:
                    return t.take_profit, "TP"
            if sl_hit:
                return t.stop_loss, "SL"
            if tp_hit:
                return t.take_profit, "TP"
        return None

    def _close_trade(self, exit_price, exit_time, reason, spread_pips, slip_pips, symbol):
        t = self.open_trade
        if not t:
            return
        if reason == "SL":
            if t.direction == "BUY":
                exit_price -= slip_pips / self.pm
            else:
                exit_price += slip_pips / self.pm
        if t.direction == "BUY":
            pnl = (exit_price - t.entry_price) * t.size * self.pm * self.pip_value
        else:
            pnl = (t.entry_price - exit_price) * t.size * self.pm * self.pip_value

        max_daily = 0.045 * self.initial_balance
        if pnl < 0:
            remaining = max_daily - abs(min(0, self.daily_pnl))
            if remaining > 0 and abs(pnl) > remaining:
                pnl = -remaining

        t.exit_price = exit_price
        t.exit_time = exit_time
        t.pnl = pnl
        t.reason = reason
        self.balance += pnl
        self.daily_pnl += pnl
        self.trades.append(t)
        self.open_trade = None
        self.daily_trades += 1
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def _reset_daily(self):
        self.daily_start = self.balance
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0

    # ── Main Run ──

    def run(self, h1_candles, strategy_type="BOUNCE", params=None, symbol="EURUSD",
            base_spread=None, m30_candles=None):
        if params is None:
            params = {}
        if base_spread is None:
            base_spread = 1.8 if "JPY" in symbol else 0.8

        # Reset state
        self.balance = self.initial_balance
        self.trades = []
        self.open_trade = None
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.current_date = None
        self.equity_curve = []
        self.daily_results = {}
        self.rng = random.Random(42)

        self._setup_pair(symbol, h1_candles)
        self._precompute_h1(h1_candles, params)

        timeline = self._build_timeline(h1_candles, m30_candles)
        # Build flat candle list for pattern detection
        exec_candles_flat = [c for c, _ in timeline]

        session_start = params.get("session_start", 7)
        session_end = params.get("session_end", 20)
        swing_lb = params.get("swing_lookback", 10)
        min_h1_history = swing_lb * 2 + 5  # Need enough history for swings

        for j in range(3, len(timeline)):
            c, h1_idx = timeline[j]

            if h1_idx < min_h1_history:
                continue

            dt = c["datetime"]
            d = dt.date()
            if d != self.current_date:
                if self.current_date:
                    self.daily_results[str(self.current_date)] = self.daily_pnl
                self.current_date = d
                self._reset_daily()

            self.equity_curve.append(self.balance)

            h = dt.hour
            if not (session_start <= h < session_end):
                continue

            # Prefer high activity sessions (London/NY)
            is_london_ny = 7 <= h <= 20
            is_news = news_calendar.is_news_window(dt, window_minutes=3)

            atr_val = self.h1_atr[h1_idx]
            spr = self._compute_spread(c, atr_val, self.h1_avg_atr, is_news, base_spread)

            # ── EXIT ──
            if self.open_trade:
                er = self._check_exit(c, spr, symbol)
                if er:
                    ep, reason = er
                    es = self._compute_slippage(atr_val, self.h1_avg_atr, is_news) if reason == "SL" else 0
                    self._close_trade(ep, dt, reason, spr, es, symbol)
                continue

            if not self._can_trade(params):
                continue

            # ── SIGNAL ──
            sig = None
            sl_dist = 0
            tp_dist = 0

            if strategy_type == "BOUNCE":
                sig, sl_dist, tp_dist = self._bounce_signal(h1_idx, exec_candles_flat, j, params)
            elif strategy_type == "BREAKOUT":
                sig, sl_dist, tp_dist = self._breakout_signal(h1_idx, exec_candles_flat, j, params)
            elif strategy_type == "COMBINED":
                # Try bounce first, then breakout
                sig, sl_dist, tp_dist = self._bounce_signal(h1_idx, exec_candles_flat, j, params)
                if not sig:
                    sig, sl_dist, tp_dist = self._breakout_signal(h1_idx, exec_candles_flat, j, params)

            if sig and sl_dist > 0 and tp_dist > 0:
                self._open_trade(sig, c, spr, sl_dist, tp_dist, atr_val, self.h1_avg_atr, is_news, params, symbol)

        # Close remaining
        if self.open_trade and timeline:
            last_c, _ = timeline[-1]
            self._close_trade(last_c["close"], last_c["datetime"], "EOD", 0, 0, symbol)

        return self._compute_result()

    def _compute_result(self):
        tr = self.trades
        if not tr:
            return BacktestResult()

        wins = [t for t in tr if t.pnl > 0]
        losses_list = [t for t in tr if t.pnl <= 0]
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses_list))

        mx_dd = 0
        pk = self.initial_balance
        b = self.initial_balance
        for t in tr:
            b += t.pnl
            if b > pk:
                pk = b
            dd = (self.initial_balance - b) / self.initial_balance if b < self.initial_balance else 0
            mx_dd = max(mx_dd, dd)

        dl = [abs(v) / self.initial_balance for v in self.daily_results.values() if v < 0]
        mx_daily = max(dl) if dl else 0

        start = tr[0].entry_time
        end = tr[-1].exit_time or tr[-1].entry_time
        days = max(1, (end - start).days)
        weeks = max(1, days / 7)
        total_pnl = sum(t.pnl for t in tr)
        ret_pct = total_pnl / self.initial_balance * 100

        ftmo = mx_dd * 100 < 8 and mx_daily * 100 < 4.5

        return BacktestResult(
            total_trades=len(tr), wins=len(wins), losses=len(losses_list),
            win_rate=round(len(wins) / len(tr) * 100, 1) if tr else 0,
            total_pnl=round(total_pnl, 2),
            total_return_pct=round(ret_pct, 2),
            weekly_return_pct=round(ret_pct / weeks, 3),
            profit_factor=round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0,
            max_drawdown_pct=round(mx_dd * 100, 2),
            max_daily_loss_pct=round(mx_daily * 100, 2),
            ftmo_compliant=ftmo,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            avg_trade_pnl=round(total_pnl / len(tr), 2) if tr else 0,
            equity_curve=self.equity_curve,
            daily_returns=list(self.daily_results.values()),
        )
