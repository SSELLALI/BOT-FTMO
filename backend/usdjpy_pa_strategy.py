"""
USDJPY Price Action Live Strategy — Signal Generator

Extracts the validated BREAKOUT + BOUNCE signal logic from the backtester
for use in live trading. Uses H1 S/R zones + M30 candlestick patterns.

Validated parameters (from walk-forward optimization):
  BREAKOUT: +0.288%/week, PF=1.23, 100% robust (12/12)
  BOUNCE:   +0.653%/week, PF=1.26, 92% robust (11/12)
  Combined: ~0.94%/week realistic | All FTMO compliant

DO NOT MODIFY validated parameters without re-running full walk-forward.
"""
import bisect
import logging
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

from news_calendar import news_calendar

logger = logging.getLogger(__name__)

# ── Validated Parameters (LOCKED) ──
BREAKOUT_PARAMS = {
    "swing_lookback": 15,
    "sr_cluster_pips": 15,
    "sr_proximity_pips": 10,
    "min_rr": 3.0,
    "min_sl_pips": 20,
    "max_sl_pips": 45,
    "risk_per_trade": 0.005,
    "sr_break_pips": 12,
    "rsi_extreme": 33,
    "min_zone_strength": 2,
    "sl_buffer_pips": 5,
    "session_start": 7,
    "session_end": 20,
    "max_daily_trades": 5,
    "max_consecutive_losses": 3,
}

BOUNCE_PARAMS = {
    "swing_lookback": 10,
    "sr_cluster_pips": 25,
    "sr_proximity_pips": 18,
    "min_rr": 3.0,
    "min_sl_pips": 20,
    "max_sl_pips": 30,
    "risk_per_trade": 0.005,
    "rsi_extreme": 33,
    "min_zone_strength": 2,
    "sl_buffer_pips": 5,
    "session_start": 7,
    "session_end": 20,
    "max_daily_trades": 5,
    "max_consecutive_losses": 3,
}

SYMBOL = "USDJPY"
BASE_SPREAD = 0.9
PM = 100  # Pip multiplier for JPY pairs
PIP_VALUE = 1000.0 / 150.0  # Approximate for USDJPY


@dataclass
class PASignal:
    direction: str       # "BUY" or "SELL"
    strategy: str        # "PA_BREAKOUT" or "PA_BOUNCE"
    entry_price: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    risk_reward: float
    lot_size: float
    reason: str
    confidence: float
    symbol: str = "USDJPY"


# ── Candlestick Pattern Detection ──

def _body(c):
    return abs(c["close"] - c["open"])

def _range_c(c):
    return c["high"] - c["low"]

def _is_bullish(c):
    return c["close"] > c["open"]

def _is_bearish(c):
    return c["close"] < c["open"]

def detect_patterns(candles, idx):
    """Detect candlestick patterns at given index."""
    if idx < 2 or idx >= len(candles):
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

    if body_ratio < 0.35:
        if lw > body * 2.0 and uw < body * 1.0:
            patterns.append("BULLISH_PINBAR")
        if uw > body * 2.0 and lw < body * 1.0:
            patterns.append("BEARISH_PINBAR")
    if _is_bullish(c) and lw > body * 2.0 and uw < body * 0.5:
        patterns.append("HAMMER")
    if _is_bearish(c) and uw > body * 2.0 and lw < body * 0.5:
        patterns.append("SHOOTING_STAR")
    if _is_bullish(c) and _is_bearish(p1) and c["close"] > p1["open"] and c["open"] < p1["close"]:
        patterns.append("BULLISH_ENGULFING")
    if _is_bearish(c) and _is_bullish(p1) and c["close"] < p1["open"] and c["open"] > p1["close"]:
        patterns.append("BEARISH_ENGULFING")
    if body_ratio < 0.1:
        patterns.append("DOJI")
    if _range_c(p1) > 0 and _body(p1) / _range_c(p1) < 0.3:
        if _is_bearish(p2) and _is_bullish(c) and c["close"] > (p2["open"] + p2["close"]) / 2:
            patterns.append("MORNING_STAR")
        if _is_bullish(p2) and _is_bearish(c) and c["close"] < (p2["open"] + p2["close"]) / 2:
            patterns.append("EVENING_STAR")
    if body_ratio > 0.65:
        patterns.append("STRONG_BULLISH" if _is_bullish(c) else "STRONG_BEARISH")
    return patterns


class PriceActionSignalGenerator:
    """
    Live signal generator for the validated USDJPY Price Action strategy.

    Usage:
        gen = PriceActionSignalGenerator()
        gen.update(h1_candles, m30_candles)
        signals = gen.check_signals(current_price, account_balance)
    """

    def __init__(self, initial_balance=10000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.current_date = None
        self.last_signal_time = None

        # Precomputed H1 data
        self._h1_atr = None
        self._h1_rsi = None
        self._h1_avg_atr = 0
        self._sr_zones = {}
        self._h1_ready = False

    def update(self, h1_candles: List[Dict], m30_candles: List[Dict] = None):
        """Update internal state with latest candle data."""
        if len(h1_candles) < 100:
            self._h1_ready = False
            return

        self._precompute_h1(h1_candles)
        self._h1_candles = h1_candles
        self._m30_candles = m30_candles or []
        self._h1_ready = True

    def _precompute_h1(self, candles):
        """Compute S/R zones, ATR, RSI from H1 data."""
        n = len(candles)
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])

        # ATR (14-period)
        atr = np.zeros(n)
        for i in range(1, n):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            atr[i] = atr[i-1] * 13/14 + tr/14 if i > 1 else tr
        self._h1_atr = atr
        self._h1_avg_atr = float(np.mean(atr[max(0, n-200):]))

        # RSI (14-period)
        rsi = np.full(n, 50.0)
        gains = np.zeros(n)
        losses_arr = np.zeros(n)
        for i in range(1, n):
            d = closes[i] - closes[i-1]
            if d > 0:
                gains[i] = d
            else:
                losses_arr[i] = abs(d)
        avg_g, avg_l = 0.0, 0.0
        for i in range(1, n):
            if i <= 14:
                avg_g = np.mean(gains[1:i+1]) if i > 0 else 0
                avg_l = np.mean(losses_arr[1:i+1]) if i > 0 else 0
            else:
                avg_g = (avg_g * 13 + gains[i]) / 14
                avg_l = (avg_l * 13 + losses_arr[i]) / 14
            if avg_l > 0:
                rsi[i] = 100 - 100 / (1 + avg_g / avg_l)
            else:
                rsi[i] = 100 if avg_g > 0 else 50
        self._h1_rsi = rsi

    def _get_sr_zones(self, h1_candles, params):
        """Get confirmed S/R zones from H1 swing highs/lows."""
        n = len(h1_candles)
        highs = np.array([c["high"] for c in h1_candles])
        lows = np.array([c["low"] for c in h1_candles])
        lb = params["swing_lookback"]
        cluster_dist = params["sr_cluster_pips"] / PM

        swing_highs = []
        swing_lows = []
        for i in range(lb, n - lb):
            ws, we = max(0, i - lb), min(n, i + lb + 1)
            if highs[i] >= np.max(highs[ws:we]):
                swing_highs.append(float(highs[i]))
            if lows[i] <= np.min(lows[ws:we]):
                swing_lows.append(float(lows[i]))

        # Cluster nearby levels
        all_levels = sorted(swing_highs[-30:] + swing_lows[-30:])
        if not all_levels:
            return []

        zones = []
        used = set()
        for i, lev in enumerate(all_levels):
            if i in used:
                continue
            cluster = [lev]
            for j in range(i + 1, len(all_levels)):
                if j in used:
                    continue
                if abs(all_levels[j] - lev) <= cluster_dist:
                    cluster.append(all_levels[j])
                    used.add(j)
            used.add(i)
            zones.append((float(np.mean(cluster)), len(cluster)))
        return zones

    def check_signals(self, account_balance: float) -> List[PASignal]:
        """Check for trading signals. Call after each new M30 candle."""
        if not self._h1_ready:
            return []

        now = datetime.now(timezone.utc)
        h = now.hour

        # Daily reset
        if self.current_date != now.date():
            self.current_date = now.date()
            self.daily_trades = 0
            self.consecutive_losses = 0

        self.balance = account_balance
        signals = []

        # Check BREAKOUT
        sig = self._check_strategy("BREAKOUT", BREAKOUT_PARAMS, h)
        if sig:
            signals.append(sig)

        # Check BOUNCE (only if no BREAKOUT signal to avoid doubling)
        if not sig:
            sig = self._check_strategy("BOUNCE", BOUNCE_PARAMS, h)
            if sig:
                signals.append(sig)

        return signals

    def _check_strategy(self, strategy_type: str, params: dict, hour: int) -> Optional[PASignal]:
        """Check a single strategy for signals."""
        # Session filter
        if not (params["session_start"] <= hour < params["session_end"]):
            return None

        # Daily limits
        if self.daily_trades >= params["max_daily_trades"]:
            return None
        if self.consecutive_losses >= params["max_consecutive_losses"]:
            return None

        # FTMO safety
        if self.balance < self.initial_balance:
            dd = (self.initial_balance - self.balance) / self.initial_balance
            if dd >= 0.06:
                return None

        h1 = self._h1_candles
        h1_idx = len(h1) - 1
        if h1_idx < 50:
            return None

        # Use M30 candles for pattern detection (more precision)
        exec_candles = self._m30_candles if len(self._m30_candles) >= 5 else h1
        exec_idx = len(exec_candles) - 1
        if exec_idx < 3:
            return None

        zones = self._get_sr_zones(h1, params)
        if not zones:
            return None

        rsi_val = self._h1_rsi[h1_idx]
        prev_c = exec_candles[exec_idx - 1]  # Use completed candle (not current)
        prev_close = prev_c["close"]
        proximity = params["sr_proximity_pips"] / PM
        min_zone_strength = params["min_zone_strength"]
        min_rr = params["min_rr"]

        patterns = detect_patterns(exec_candles, exec_idx - 1)

        is_news = news_calendar.is_news_window(datetime.now(timezone.utc), window_minutes=5)
        if is_news:
            return None  # Skip news windows for safety

        for zone_price, zone_strength in zones:
            if zone_strength < min_zone_strength:
                continue
            dist = abs(prev_close - zone_price)
            if dist > proximity:
                continue

            signal_dir = None
            sl_dist = 0
            tp_dist = 0
            reason = ""

            if strategy_type in ("BOUNCE", "COMBINED"):
                # Support bounce (BUY)
                if prev_close >= zone_price - proximity and prev_close <= zone_price + proximity * 0.3:
                    bullish = [p for p in patterns if p in
                               ("BULLISH_PINBAR", "HAMMER", "BULLISH_ENGULFING", "MORNING_STAR", "DOJI")]
                    if bullish and rsi_val < 65:
                        sl_dist = max(params["min_sl_pips"] / PM, dist + params["sl_buffer_pips"] / PM)
                        sl_dist = min(sl_dist, params["max_sl_pips"] / PM)
                        tp_dist = sl_dist * min_rr
                        signal_dir = "BUY"
                        reason = f"Bounce support @{zone_price:.3f} [{bullish[0]}]"

                # Resistance bounce (SELL)
                if not signal_dir:
                    if prev_close <= zone_price + proximity and prev_close >= zone_price - proximity * 0.3:
                        bearish = [p for p in patterns if p in
                                   ("BEARISH_PINBAR", "SHOOTING_STAR", "BEARISH_ENGULFING", "EVENING_STAR", "DOJI")]
                        if bearish and rsi_val > 35:
                            sl_dist = max(params["min_sl_pips"] / PM, dist + params["sl_buffer_pips"] / PM)
                            sl_dist = min(sl_dist, params["max_sl_pips"] / PM)
                            tp_dist = sl_dist * min_rr
                            signal_dir = "SELL"
                            reason = f"Bounce resistance @{zone_price:.3f} [{bearish[0]}]"

            if strategy_type in ("BREAKOUT", "COMBINED") and not signal_dir:
                break_dist = params.get("sr_break_pips", 10) / PM
                prev_open = prev_c["open"]

                # Bullish breakout
                if prev_close > zone_price + break_dist and prev_open <= zone_price + break_dist:
                    strong = any(p in patterns for p in ("STRONG_BULLISH", "BULLISH_ENGULFING"))
                    if strong and rsi_val > 40:
                        sl_dist = max(params["min_sl_pips"] / PM,
                                      abs(prev_close - zone_price) + params["sl_buffer_pips"] / PM)
                        sl_dist = min(sl_dist, params["max_sl_pips"] / PM)
                        tp_dist = sl_dist * min_rr
                        signal_dir = "BUY"
                        reason = f"Breakout above @{zone_price:.3f}"

                # Bearish breakout
                if not signal_dir:
                    if prev_close < zone_price - break_dist and prev_open >= zone_price - break_dist:
                        strong = any(p in patterns for p in ("STRONG_BEARISH", "BEARISH_ENGULFING"))
                        if strong and rsi_val < 60:
                            sl_dist = max(params["min_sl_pips"] / PM,
                                          abs(prev_close - zone_price) + params["sl_buffer_pips"] / PM)
                            sl_dist = min(sl_dist, params["max_sl_pips"] / PM)
                            tp_dist = sl_dist * min_rr
                            signal_dir = "SELL"
                            reason = f"Breakout below @{zone_price:.3f}"

            if signal_dir and sl_dist > 0 and tp_dist > 0:
                entry = prev_close  # Will be adjusted by market order
                sl = entry - sl_dist if signal_dir == "BUY" else entry + sl_dist
                tp = entry + tp_dist if signal_dir == "BUY" else entry - tp_dist
                sl_pips = sl_dist * PM
                tp_pips = tp_dist * PM

                # Position sizing (risk-based)
                risk_amount = self.balance * params["risk_per_trade"]
                pip_val = 1000.0 / entry if entry > 0 else PIP_VALUE
                lot_size = max(0.01, min(risk_amount / (sl_pips * pip_val), 5.0))

                strat_name = f"PA_{strategy_type}"
                return PASignal(
                    direction=signal_dir,
                    strategy=strat_name,
                    entry_price=round(entry, 3),
                    stop_loss=round(sl, 3),
                    take_profit=round(tp, 3),
                    sl_pips=round(sl_pips, 1),
                    tp_pips=round(tp_pips, 1),
                    risk_reward=round(min_rr, 1),
                    lot_size=round(lot_size, 2),
                    reason=reason,
                    confidence=0.7 + (zone_strength - 2) * 0.1,
                )

        return None

    def record_result(self, pnl: float):
        """Record trade result for risk management."""
        self.daily_trades += 1
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def get_status(self) -> Dict:
        """Get strategy status for API."""
        return {
            "strategy": "USDJPY Price Action (BREAKOUT + BOUNCE)",
            "symbol": SYMBOL,
            "h1_ready": self._h1_ready,
            "h1_candles": len(self._h1_candles) if self._h1_ready else 0,
            "m30_candles": len(self._m30_candles) if self._h1_ready else 0,
            "daily_trades": self.daily_trades,
            "consecutive_losses": self.consecutive_losses,
            "sr_zones": len(self._sr_zones) if self._sr_zones else 0,
            "validated_performance": {
                "breakout_weekly": "+0.288%",
                "bounce_weekly": "+0.653%",
                "combined_weekly": "~0.94%",
                "robustness_breakout": "100%",
                "robustness_bounce": "92%",
                "ftmo_compliant": True,
            },
        }
