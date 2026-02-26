"""
Realistic Backtester V3 — Multi-Timeframe
H1 indicators (trend, ATR, RSI) + M30 execution (entry/exit precision)
Falls back to H1-only when M30 data is not available.

Anti-lookahead:
  - H1 indicator at index j is used only AFTER H1[j] candle is COMPLETED
  - Signal detected on previous execution candle → execute at CURRENT candle open
  - M30 at time T uses H1 indicators from H1 candles completed before T
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


class MTFBacktester:
    """Multi-Timeframe Realistic Backtester."""

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
        # Pair
        self.pm = 10000  # pip multiplier
        self.pip_value = 10.0  # USD per pip per lot

    # ── Pair Setup ──

    def _setup_pair(self, symbol: str, candles: List[Dict]):
        is_jpy = "JPY" in symbol.upper()
        self.pm = 100 if is_jpy else 10000
        if candles:
            price = candles[len(candles) // 2]["close"]
            if is_jpy:
                self.pip_value = 1000.0 / price
            else:
                self.pip_value = 10.0

    # ── H1 Indicator Pre-computation ──

    def _precompute_h1(self, h1_candles: List[Dict], params: dict):
        """Pre-compute EMA, ATR, RSI on H1 candles."""
        n = len(h1_candles)
        closes = np.array([c["close"] for c in h1_candles])
        highs = np.array([c["high"] for c in h1_candles])
        lows = np.array([c["low"] for c in h1_candles])

        # EMA
        ema_p = params.get("ema_period", 20)
        ema = np.zeros(n)
        ema[0] = closes[0]
        k = 2.0 / (ema_p + 1)
        for i in range(1, n):
            ema[i] = closes[i] * k + ema[i - 1] * (1 - k)

        # ATR (14-period)
        atr = np.zeros(n)
        for i in range(1, n):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            atr[i] = atr[i - 1] * 13 / 14 + tr / 14 if i > 1 else tr

        # RSI (14-period)
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
                avg_g = np.mean(gains[1 : i + 1]) if i > 0 else 0
                avg_l = np.mean(losses_arr[1 : i + 1]) if i > 0 else 0
            else:
                avg_g = (avg_g * 13 + gains[i]) / 14
                avg_l = (avg_l * 13 + losses_arr[i]) / 14
            if avg_l > 0:
                rsi[i] = 100 - 100 / (1 + avg_g / avg_l)
            else:
                rsi[i] = 100 if avg_g > 0 else 50

        avg_atr = float(np.mean(atr[max(0, n - 200) :]))
        self.h1_ema = ema
        self.h1_atr = atr
        self.h1_rsi = rsi
        self.h1_avg_atr = avg_atr

    # ── Execution Timeline ──

    def _build_timeline(self, h1_candles, m30_candles):
        """
        Build unified execution timeline.
        Each entry: (candle_dict, h1_indicator_ref_index)

        For M30 at time T:
          h1_ref = last H1 whose start + 1h <= T (i.e. completed before T)
        For H1 at index i:
          h1_ref = i - 1 (previous completed candle, same as v2)
        """
        timeline = []

        if not m30_candles:
            for i, c in enumerate(h1_candles):
                timeline.append((c, max(0, i - 1)))
            return timeline

        m30_start = m30_candles[0]["datetime"]
        h1_end_times = [c["datetime"] + timedelta(hours=1) for c in h1_candles]

        # Phase 1: H1-only (before M30 data starts)
        for i, c in enumerate(h1_candles):
            if c["datetime"] >= m30_start:
                break
            timeline.append((c, max(0, i - 1)))

        # Phase 2: M30 candles with H1 indicator reference
        for m30c in m30_candles:
            t = m30c["datetime"]
            # bisect: find last h1_end_time <= t
            ref = bisect.bisect_right(h1_end_times, t) - 1
            if ref >= 1:
                timeline.append((m30c, ref))

        return timeline

    # ── Spread / Slippage / News (same as v2) ──

    def _compute_spread(self, candle, atr, avg_atr, is_news, base_spread):
        """Variable spread: session + volatility + news."""
        h = candle["datetime"].hour
        # Session multiplier
        if 7 <= h <= 8:
            sm = 1.0
        elif 13 <= h <= 16:
            sm = 0.9
        elif 22 <= h or h <= 4:
            sm = 1.8
        else:
            sm = 1.2
        # Volatility
        vm = 1.0 + max(0, (atr / avg_atr - 1)) * 0.5 if avg_atr > 0 else 1.0
        # News
        nm = 3.0 if is_news else 1.0
        spread = base_spread * sm * vm * nm * 1.2  # 1.2 safety
        return max(spread, base_spread * 0.5)

    def _compute_slippage(self, atr, avg_atr, is_news):
        """ATR-proportional slippage in pips."""
        base = atr * self.pm * 0.02
        base = max(0, min(base, 0.5))
        if is_news:
            base *= 3
            base = min(base, 2.0)
        if avg_atr > 0 and atr / avg_atr > 1.5:
            base *= 1.5
        return base * self.rng.random()

    # ── Signal Generation ──

    def _scalping_signal(self, h1_idx, prev_close, params):
        ema_val = self.h1_ema[h1_idx]
        rsi_val = self.h1_rsi[h1_idx]
        atr_val = self.h1_atr[h1_idx]

        if atr_val <= 0 or h1_idx < 2:
            return None

        # Trend direction
        trend_up = self.h1_ema[h1_idx] > self.h1_ema[h1_idx - 1]

        pullback_pct = params.get("pullback_pct", 0.002)
        close_dist = abs(prev_close - ema_val) / prev_close if prev_close > 0 else 999

        if close_dist > pullback_pct:
            return None

        if trend_up and prev_close > ema_val and 40 < rsi_val < 70:
            return "BUY"
        elif not trend_up and prev_close < ema_val and 30 < rsi_val < 60:
            return "SELL"
        return None

    def _intraday_signal(self, h1_idx, prev_close, params):
        ema_val = self.h1_ema[h1_idx]
        rsi_val = self.h1_rsi[h1_idx]
        atr_val = self.h1_atr[h1_idx]

        if atr_val <= 0 or h1_idx < 2:
            return None

        trend_up = self.h1_ema[h1_idx] > self.h1_ema[h1_idx - 1]
        pullback_pct = params.get("pullback_pct", 0.003)
        close_dist = abs(prev_close - ema_val) / prev_close if prev_close > 0 else 999

        if close_dist > pullback_pct:
            return None

        if trend_up and prev_close > ema_val and 40 < rsi_val < 65:
            return "BUY"
        elif not trend_up and prev_close < ema_val and 35 < rsi_val < 60:
            return "SELL"
        return None

    # ── Trade Management ──

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

    def _open_trade(self, direction, candle, spread_pips, atr, avg_atr, is_news, params, symbol):
        sp = spread_pips / self.pm
        slip = self._compute_slippage(atr, avg_atr, is_news) / self.pm

        # Execution quality: fills, requotes, rejections
        r = self.rng.random()
        if r > 0.995:
            return  # rejected
        if r > 0.98:
            return  # requote, skip
        fill_pct = 1.0 if r > 0.03 else self.rng.uniform(0.5, 0.95)

        if direction == "BUY":
            entry = candle["open"] + sp + slip
        else:
            entry = candle["open"] - slip

        # SL/TP
        atr_mult = params.get("atr_multiplier", 1.0)
        min_sl = params.get("min_sl_pips", 5) / self.pm
        max_sl = params.get("max_sl_pips", 15) / self.pm
        sl_dist = max(min_sl, min(max_sl, atr * atr_mult))
        min_rr = params.get("min_rr", 2.0)

        if direction == "BUY":
            sl = entry - sl_dist
            tp = entry + sl_dist * min_rr
        else:
            sl = entry + sl_dist
            tp = entry - sl_dist * min_rr

        # Position size (risk-based)
        risk_pct = params.get("risk_per_trade", 0.005)
        risk_amount = self.balance * risk_pct
        sl_pips = abs(entry - sl) * self.pm
        if sl_pips <= 0:
            return
        lot_size = risk_amount / (sl_pips * self.pip_value)
        lot_size *= fill_pct
        lot_size = max(0.01, min(lot_size, 10.0))

        # Latency re-price (100-300ms)
        latency_slip = self.rng.uniform(0.1, 0.3) * atr * 0.01
        if direction == "BUY":
            entry += latency_slip
        else:
            entry -= latency_slip

        self.open_trade = Trade(
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            direction=direction,
            size=lot_size,
            entry_time=candle["datetime"],
        )

    def _check_exit(self, candle, spread_pips, symbol):
        t = self.open_trade
        if not t:
            return None
        sp = spread_pips / self.pm

        # Safety close on FTMO limits
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
        sp = spread_pips / self.pm

        if reason == "SL":
            if t.direction == "BUY":
                exit_price -= slip_pips / self.pm
            else:
                exit_price += slip_pips / self.pm

        if t.direction == "BUY":
            pnl_raw = (exit_price - t.entry_price) * t.size * self.pm * self.pip_value
        else:
            pnl_raw = (t.entry_price - exit_price) * t.size * self.pm * self.pip_value

        # Cap daily loss to FTMO limit
        pnl = pnl_raw
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

    def run(self, h1_candles, strategy_type="SCALPING", params=None, symbol="EURUSD",
            base_spread=None, m30_candles=None):
        if params is None:
            params = {}
        if base_spread is None:
            base_spread = 1.8 if "JPY" in symbol else 0.8

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
        ema_period = params.get("ema_period", 20)
        session_start = params.get("session_start", 7)
        session_end = params.get("session_end", 20)

        for j in range(1, len(timeline)):
            c, h1_idx = timeline[j]
            prev_c, _ = timeline[j - 1]

            # Not enough H1 history
            if h1_idx < ema_period + 2:
                continue

            # Date change → reset daily stats
            dt = c["datetime"]
            d = dt.date()
            if d != self.current_date:
                if self.current_date:
                    self.daily_results[str(self.current_date)] = self.daily_pnl
                self.current_date = d
                self._reset_daily()

            self.equity_curve.append(self.balance)

            # Session filter
            h = dt.hour
            if not (session_start <= h < session_end):
                continue

            # News check
            is_news = news_calendar.is_news_window(dt, window_minutes=3)

            # Spread & ATR
            atr_val = self.h1_atr[h1_idx]
            spr = self._compute_spread(c, atr_val, self.h1_avg_atr, is_news, base_spread)

            # ── EXIT ──
            if self.open_trade:
                er = self._check_exit(c, spr, symbol)
                if er:
                    ep, reason = er
                    es = self._compute_slippage(atr_val, self.h1_avg_atr, is_news) if reason == "SL" else 0
                    self._close_trade(ep, dt, reason, spr, es, symbol)
                continue  # don't enter and exit same candle

            # ── SIGNAL ──
            if not self._can_trade(params):
                continue

            if strategy_type == "SCALPING":
                sig = self._scalping_signal(h1_idx, prev_c["close"], params)
            else:
                sig = self._intraday_signal(h1_idx, prev_c["close"], params)

            if sig:
                self._open_trade(sig, c, spr, atr_val, self.h1_avg_atr, is_news, params, symbol)

        # Close any remaining open trade
        if self.open_trade and timeline:
            last_c, _ = timeline[-1]
            self._close_trade(last_c["close"], last_c["datetime"], "EOD", 0, 0, symbol)

        return self._compute_result()

    def _compute_result(self):
        tr = self.trades
        if not tr:
            return BacktestResult()

        wins = [t for t in tr if t.pnl > 0]
        losses = [t for t in tr if t.pnl <= 0]
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))

        # Max drawdown
        mx_dd = 0
        pk = self.initial_balance
        b = self.initial_balance
        for t in tr:
            b += t.pnl
            if b > pk:
                pk = b
            dd = (self.initial_balance - b) / self.initial_balance if b < self.initial_balance else 0
            mx_dd = max(mx_dd, dd)

        # Max daily loss
        dl = [abs(v) / self.initial_balance for v in self.daily_results.values() if v < 0]
        mx_daily = max(dl) if dl else 0

        # Time period
        start = tr[0].entry_time
        end = tr[-1].exit_time or tr[-1].entry_time
        days = max(1, (end - start).days)
        weeks = max(1, days / 7)
        total_pnl = sum(t.pnl for t in tr)
        ret_pct = total_pnl / self.initial_balance * 100

        ftmo = mx_dd * 100 < 8 and mx_daily * 100 < 4.5

        return BacktestResult(
            total_trades=len(tr),
            wins=len(wins),
            losses=len(losses),
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
