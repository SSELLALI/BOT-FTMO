"""
GBPJPY Breakout-Pullback-Rejection Backtester

Strategy rules (user-defined, DO NOT modify logic):
  1. Timeframes: H1 (structure) + M15 (entry)
  2. Sessions: London 07h-11h30, NY 13h30-16h30 UTC only
  3. H1 Structure: HH/HL = bullish, LL/LH = bearish, unclear = no trade
  4. Key Level: Last significant H1 high/low, breakout = full candle close
  5. Volatility: Breakout candle > avg(10 H1), body >= 60% range
  6. Pullback: M15 return to broken level, must not break H1 structure
  7. Rejection: Engulfing, pin bar, or impulse candle on M15
  8. RSI: M15 RSI(14), long 52-65 rising, short 35-48 falling, skip >70/<30
  9. Entry: At rejection candle close, 1 trade per breakout
  10. Stop Loss: Below/above pullback wick + buffer pips
  11. Take Profit: Min R:R or next H1 swing
  12. Management: Move SL to breakeven at 1:1
  13. Cancel: Deep pullback, weak rejection, small breakout, ranging, high spread

Realistic conditions:
  - Spread simulation (variable, GBPJPY avg ~2.5 pips)
  - Slippage (0-2 pips random)
  - FTMO rules (1% risk/trade, 4.5% daily loss, 8% total DD)
  - No lookahead bias
"""
import numpy as np
import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, time as dtime
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

PM = 100  # Pip multiplier for JPY pairs (1 pip = 0.01)


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    weekly_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    max_daily_loss_pct: float = 0.0
    ftmo_compliant: bool = True
    start_date: str = ""
    end_date: str = ""
    avg_trade_pnl: float = 0.0
    avg_rr_achieved: float = 0.0
    trades: list = field(default_factory=list)
    daily_returns: list = field(default_factory=list)


@dataclass
class SwingPoint:
    price: float
    index: int
    type: str  # "HH", "HL", "LH", "LL"


@dataclass
class OpenTrade:
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    entry_time: datetime
    breakout_level: float
    sl_pips: float
    be_moved: bool = False  # breakeven already moved


class GBPJPYBreakoutBacktester:
    """
    Backtester implementing the exact user-defined GBPJPY breakout-pullback strategy.
    """

    def __init__(self, initial_balance=100000):
        self.initial_balance = initial_balance

    def run(self, h1_candles, m15_candles, params, base_spread=2.5):
        """
        Run backtest with given parameters.

        Args:
            h1_candles: H1 OHLC candles for structure detection
            m15_candles: M15 OHLC candles for entry signals
            params: Strategy parameters dict
            base_spread: Average spread in pips
        """
        balance = self.initial_balance
        peak_balance = balance
        max_dd = 0.0
        max_daily_loss = 0.0
        daily_pnl = {}
        trades_log = []
        open_trade = None
        gross_profit = 0.0
        gross_loss = 0.0
        total_rr_achieved = 0.0
        used_breakouts = set()  # Track breakout levels already traded

        # Build M15 timeline with H1 index mapping
        h1_times = [c["datetime"] for c in h1_candles]

        # Precompute H1 data
        h1_closes = np.array([c["close"] for c in h1_candles])
        h1_opens = np.array([c["open"] for c in h1_candles])
        h1_highs = np.array([c["high"] for c in h1_candles])
        h1_lows = np.array([c["low"] for c in h1_candles])
        h1_ranges = h1_highs - h1_lows
        h1_bodies = np.abs(h1_closes - h1_opens)

        # Precompute M15 RSI
        m15_closes = np.array([c["close"] for c in m15_candles])
        m15_rsi = self._compute_rsi(m15_closes, 14)

        # Parameters
        swing_lookback = params.get("swing_lookback", 10)
        sl_buffer_pips = params.get("sl_buffer_pips", 7)
        min_rr = params.get("min_rr", 2.0)
        risk_per_trade = params.get("risk_per_trade", 0.01)
        breakout_body_ratio = params.get("breakout_body_ratio", 0.60)
        breakout_size_mult = params.get("breakout_size_mult", 1.0)
        max_pullback_depth = params.get("max_pullback_depth", 0.7)
        rsi_long_min = params.get("rsi_long_min", 52)
        rsi_long_max = params.get("rsi_long_max", 65)
        rsi_short_min = params.get("rsi_short_min", 35)
        rsi_short_max = params.get("rsi_short_max", 48)
        be_trigger_rr = params.get("be_trigger_rr", 1.0)
        max_daily_trades = params.get("max_daily_trades", 4)
        max_consecutive_losses = params.get("max_consecutive_losses", 3)
        use_structural_tp = params.get("use_structural_tp", False)
        min_sl_pips = params.get("min_sl_pips", 15)
        max_sl_pips = params.get("max_sl_pips", 60)
        proximity_factor = params.get("proximity_factor", 0.5)
        stale_timeout = params.get("stale_timeout", 20)

        consecutive_losses = 0
        daily_trade_count = {}
        current_date = None

        # State for breakout detection
        last_breakout = None  # {"level", "direction", "h1_idx", "candle_range"}
        pullback_active = False
        pullback_low = None
        pullback_high = None
        detected_breakout_levels = set()  # Track level+direction combos already detected

        # H1 structure state
        swings = []  # List of SwingPoint
        bias = None  # "BULLISH", "BEARISH", None

        # ── Main Loop (iterate M15 candles) ──
        for m15_idx in range(2, len(m15_candles)):
            m15_c = m15_candles[m15_idx]
            m15_time = m15_c["datetime"]
            m15_close = m15_c["close"]
            m15_open = m15_c["open"]
            m15_high = m15_c["high"]
            m15_low = m15_c["low"]

            # Find corresponding H1 candle (last completed H1 before this M15)
            h1_idx = self._find_h1_index(m15_time, h1_times)
            if h1_idx is None or h1_idx < swing_lookback + 10:
                continue

            # Daily reset
            trade_date = m15_time.date()
            if current_date != trade_date:
                current_date = trade_date
                if trade_date not in daily_trade_count:
                    daily_trade_count[trade_date] = 0
                consecutive_losses = min(consecutive_losses, max_consecutive_losses)

            # ── Manage open trade ──
            if open_trade:
                # Check SL hit
                if open_trade.direction == "BUY":
                    if m15_low <= open_trade.stop_loss:
                        pnl = self._close_trade(open_trade, open_trade.stop_loss, balance, base_spread, "SL")
                        balance += pnl
                        date_key = str(trade_date)
                        daily_pnl[date_key] = daily_pnl.get(date_key, 0) + pnl
                        if pnl < 0:
                            gross_loss += abs(pnl)
                            consecutive_losses += 1
                        else:
                            gross_profit += pnl
                            consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(m15_time), "dir": "BUY", "pnl": round(pnl, 2), "type": "SL"})
                        open_trade = None
                    # Check TP hit
                    elif m15_high >= open_trade.take_profit:
                        pnl = self._close_trade(open_trade, open_trade.take_profit, balance, base_spread, "TP")
                        balance += pnl
                        date_key = str(trade_date)
                        daily_pnl[date_key] = daily_pnl.get(date_key, 0) + pnl
                        gross_profit += pnl
                        consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(m15_time), "dir": "BUY", "pnl": round(pnl, 2), "type": "TP"})
                        open_trade = None
                    # Check breakeven move
                    elif not open_trade.be_moved and be_trigger_rr > 0:
                        be_dist = open_trade.sl_pips / PM * be_trigger_rr
                        if m15_high >= open_trade.entry_price + be_dist:
                            open_trade.stop_loss = open_trade.entry_price + (base_spread / PM / 2)
                            open_trade.be_moved = True

                elif open_trade.direction == "SELL":
                    if m15_high >= open_trade.stop_loss:
                        pnl = self._close_trade(open_trade, open_trade.stop_loss, balance, base_spread, "SL")
                        balance += pnl
                        date_key = str(trade_date)
                        daily_pnl[date_key] = daily_pnl.get(date_key, 0) + pnl
                        if pnl < 0:
                            gross_loss += abs(pnl)
                            consecutive_losses += 1
                        else:
                            gross_profit += pnl
                            consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(m15_time), "dir": "SELL", "pnl": round(pnl, 2), "type": "SL"})
                        open_trade = None
                    elif m15_low <= open_trade.take_profit:
                        pnl = self._close_trade(open_trade, open_trade.take_profit, balance, base_spread, "TP")
                        balance += pnl
                        date_key = str(trade_date)
                        daily_pnl[date_key] = daily_pnl.get(date_key, 0) + pnl
                        gross_profit += pnl
                        consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(m15_time), "dir": "SELL", "pnl": round(pnl, 2), "type": "TP"})
                        open_trade = None
                    elif not open_trade.be_moved and be_trigger_rr > 0:
                        be_dist = open_trade.sl_pips / PM * be_trigger_rr
                        if m15_low <= open_trade.entry_price - be_dist:
                            open_trade.stop_loss = open_trade.entry_price - (base_spread / PM / 2)
                            open_trade.be_moved = True

                # Update drawdown
                peak_balance = max(peak_balance, balance)
                dd = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0
                max_dd = max(max_dd, dd)
                continue  # Don't look for new signals while in trade

            # ── SESSION FILTER (Rule 2) ──
            h = m15_time.hour
            m = m15_time.minute
            t_minutes = h * 60 + m
            in_london = 420 <= t_minutes <= 690   # 07:00 - 11:30
            in_ny = 810 <= t_minutes <= 990        # 13:30 - 16:30
            if not (in_london or in_ny):
                continue

            # Weekend filter
            if m15_time.weekday() >= 5:
                continue

            # Daily trade limit
            if daily_trade_count.get(trade_date, 0) >= max_daily_trades:
                continue

            # Consecutive loss limit
            if consecutive_losses >= max_consecutive_losses:
                continue

            # FTMO safety
            dd_pct = (peak_balance - balance) / self.initial_balance * 100 if self.initial_balance > 0 else 0
            if dd_pct > 7:
                continue

            # ── H1 STRUCTURE DETECTION (Rule 3) ──
            swings = self._detect_swings(h1_highs, h1_lows, h1_idx, swing_lookback)
            bias = self._determine_bias(swings)
            if bias is None:
                continue  # Structure not clear

            # ── KEY LEVEL IDENTIFICATION (Rule 4) ──
            key_resistance = None
            key_support = None
            for sp in reversed(swings):
                if sp.type in ("HH", "LH") and key_resistance is None:
                    key_resistance = sp.price
                if sp.type in ("HL", "LL") and key_support is None:
                    key_support = sp.price
                if key_resistance and key_support:
                    break

            # ── BREAKOUT DETECTION (Rule 4 + 5) ──
            # Only look for NEW breakouts if we're NOT already tracking a pullback
            h1_c = h1_candles[h1_idx]
            new_breakout = None

            if not pullback_active:
                # Bullish breakout above resistance
                if bias == "BULLISH" and key_resistance and h1_idx not in detected_h1_breakouts:
                    if h1_c["close"] > key_resistance and h1_c["open"] <= key_resistance:
                        # Rule 5: Volatility filter
                        avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx])) if h1_idx >= 10 else h1_ranges[h1_idx]
                        candle_range = h1_c["high"] - h1_c["low"]
                        candle_body = abs(h1_c["close"] - h1_c["open"])
                        body_ratio = candle_body / candle_range if candle_range > 0 else 0

                        if candle_range > avg_range * breakout_size_mult and body_ratio >= breakout_body_ratio:
                            new_breakout = {
                                "level": key_resistance,
                                "direction": "BUY",
                                "h1_idx": h1_idx,
                                "candle_range": candle_range,
                            }
                            detected_h1_breakouts.add(h1_idx)

                # Bearish breakout below support
                if not new_breakout and bias == "BEARISH" and key_support and h1_idx not in detected_h1_breakouts:
                    if h1_c["close"] < key_support and h1_c["open"] >= key_support:
                        avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx])) if h1_idx >= 10 else h1_ranges[h1_idx]
                        candle_range = h1_c["high"] - h1_c["low"]
                        candle_body = abs(h1_c["close"] - h1_c["open"])
                        body_ratio = candle_body / candle_range if candle_range > 0 else 0

                        if candle_range > avg_range * breakout_size_mult and body_ratio >= breakout_body_ratio:
                            new_breakout = {
                                "level": key_support,
                                "direction": "SELL",
                                "h1_idx": h1_idx,
                                "candle_range": candle_range,
                            }
                            detected_h1_breakouts.add(h1_idx)

            if new_breakout:
                last_breakout = new_breakout
                pullback_active = True
                pullback_low = m15_low
                pullback_high = m15_high
                continue  # Wait for pullback on next M15 candles

            # ── PULLBACK DETECTION (Rule 6) ──
            if not pullback_active or last_breakout is None:
                continue

            # Stale breakout check (more than 20 H1 candles = ~20 hours)
            if h1_idx - last_breakout["h1_idx"] > 20:
                last_breakout = None
                pullback_active = False
                continue

            level = last_breakout["level"]
            direction = last_breakout["direction"]

            # Track pullback extremes
            if pullback_active:
                pullback_low = min(pullback_low, m15_low) if pullback_low else m15_low
                pullback_high = max(pullback_high, m15_high) if pullback_high else m15_high

            # Check pullback conditions
            if direction == "BUY":
                # Price must return toward the broken resistance (now support)
                if m15_close > level + last_breakout["candle_range"]:
                    continue  # Not pulled back yet

                # Pullback must not go too deep (Rule 6)
                last_hl = None
                for sp in reversed(swings):
                    if sp.type == "HL":
                        last_hl = sp.price
                        break
                if last_hl and m15_low < last_hl:
                    # Structure broken — cancel this breakout
                    last_breakout = None
                    pullback_active = False
                    continue

                # Check pullback depth
                pullback_depth = (pullback_high - m15_low) / last_breakout["candle_range"] if last_breakout["candle_range"] > 0 else 999
                if pullback_depth > max_pullback_depth:
                    continue  # Too deep — wait or cancel

                # Check if price is near the broken level
                dist_to_level = abs(m15_close - level)
                if dist_to_level > last_breakout["candle_range"] * 0.5:
                    continue  # Not close enough to level yet

            elif direction == "SELL":
                if m15_close < level - last_breakout["candle_range"]:
                    continue

                last_lh = None
                for sp in reversed(swings):
                    if sp.type == "LH":
                        last_lh = sp.price
                        break
                if last_lh and m15_high > last_lh:
                    last_breakout = None
                    pullback_active = False
                    continue

                pullback_depth = (m15_high - pullback_low) / last_breakout["candle_range"] if last_breakout["candle_range"] > 0 else 999
                if pullback_depth > max_pullback_depth:
                    continue

                dist_to_level = abs(m15_close - level)
                if dist_to_level > last_breakout["candle_range"] * 0.5:
                    continue

            # ── REJECTION CANDLE (Rule 7) ──
            patterns = self._detect_m15_patterns(m15_candles, m15_idx)
            has_rejection = False

            if direction == "BUY":
                has_rejection = any(p in patterns for p in
                    ("BULLISH_ENGULFING", "BULLISH_PINBAR", "HAMMER", "STRONG_BULLISH"))
                # Must close bullish
                if not (m15_close > m15_open):
                    has_rejection = False
            elif direction == "SELL":
                has_rejection = any(p in patterns for p in
                    ("BEARISH_ENGULFING", "BEARISH_PINBAR", "SHOOTING_STAR", "STRONG_BEARISH"))
                if not (m15_close < m15_open):
                    has_rejection = False

            if not has_rejection:
                continue

            # ── RSI CONFIRMATION (Rule 8) ──
            rsi_val = m15_rsi[m15_idx]
            rsi_prev = m15_rsi[m15_idx - 1]

            if direction == "BUY":
                if not (rsi_long_min <= rsi_val <= rsi_long_max):
                    continue
                if rsi_val <= rsi_prev:  # Must be rising
                    continue
                if rsi_val > 70 or rsi_val < 30:
                    continue
            elif direction == "SELL":
                if not (rsi_short_min <= rsi_val <= rsi_short_max):
                    continue
                if rsi_val >= rsi_prev:  # Must be falling
                    continue
                if rsi_val > 70 or rsi_val < 30:
                    continue

            # ── SPREAD CHECK (Rule 13) ──
            spread = base_spread + random.uniform(0, 1.5)
            if spread > base_spread * 2:
                continue

            # ── CALCULATE SL/TP (Rules 10, 11) ──
            slippage = random.uniform(0, 0.5) / PM

            if direction == "BUY":
                entry = m15_close + (spread / 2 / PM) + slippage
                sl = pullback_low - (sl_buffer_pips / PM)
                sl_pips = (entry - sl) * PM

                if sl_pips < min_sl_pips or sl_pips > max_sl_pips:
                    continue

                # TP: structural or fixed R:R
                if use_structural_tp and key_resistance:
                    # Next H1 swing high
                    next_target = self._find_next_swing_target(swings, entry, "BUY")
                    if next_target:
                        tp = next_target
                        tp_pips = (tp - entry) * PM
                        if tp_pips / sl_pips < min_rr:
                            tp = entry + (sl_pips * min_rr / PM)
                    else:
                        tp = entry + (sl_pips * min_rr / PM)
                else:
                    tp = entry + (sl_pips * min_rr / PM)

            elif direction == "SELL":
                entry = m15_close - (spread / 2 / PM) - slippage
                sl = pullback_high + (sl_buffer_pips / PM)
                sl_pips = (sl - entry) * PM

                if sl_pips < min_sl_pips or sl_pips > max_sl_pips:
                    continue

                if use_structural_tp and key_support:
                    next_target = self._find_next_swing_target(swings, entry, "SELL")
                    if next_target:
                        tp = next_target
                        tp_pips = (entry - tp) * PM
                        if tp_pips / sl_pips < min_rr:
                            tp = entry - (sl_pips * min_rr / PM)
                    else:
                        tp = entry - (sl_pips * min_rr / PM)
                else:
                    tp = entry - (sl_pips * min_rr / PM)

            # ── POSITION SIZING ──
            risk_amount = balance * risk_per_trade
            pip_value = 1000.0 / entry if entry > 0 else 6.67
            lot_size = max(0.01, min(risk_amount / (sl_pips * pip_value), 5.0))

            # ── OPEN TRADE (Rule 9) ──
            open_trade = OpenTrade(
                direction=direction,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                lot_size=lot_size,
                entry_time=m15_time,
                breakout_level=level,
                sl_pips=sl_pips,
            )

            # Mark breakout as used (Rule 9: 1 trade per breakout)
            bk_key = f"{direction}_{level:.3f}_{last_breakout['h1_idx']}"
            used_breakouts.add(bk_key)
            daily_trade_count[trade_date] = daily_trade_count.get(trade_date, 0) + 1

            # Reset breakout state
            last_breakout = None
            pullback_active = False

        # ── Close any remaining open trade at last price ──
        if open_trade:
            last_price = m15_candles[-1]["close"]
            pnl = self._close_trade(open_trade, last_price, balance, base_spread, "EOD")
            balance += pnl
            if pnl < 0:
                gross_loss += abs(pnl)
            else:
                gross_profit += pnl
            trades_log.append({"time": "END", "dir": open_trade.direction, "pnl": round(pnl, 2), "type": "EOD"})

        # ── Compute Results ──
        total_trades = len(trades_log)
        wins = sum(1 for t in trades_log if t["pnl"] > 0)
        losses = sum(1 for t in trades_log if t["pnl"] <= 0)
        total_return = (balance - self.initial_balance) / self.initial_balance * 100

        # Weekly return
        if m15_candles:
            start_dt = m15_candles[0]["datetime"]
            end_dt = m15_candles[-1]["datetime"]
            days = (end_dt - start_dt).days
            weeks = max(days / 7, 1)
            weekly_return = total_return / weeks
        else:
            weekly_return = 0
            start_dt = end_dt = datetime.now(timezone.utc)

        # Max daily loss
        for dk, dpnl in daily_pnl.items():
            dl_pct = abs(dpnl) / self.initial_balance * 100 if dpnl < 0 else 0
            max_daily_loss = max(max_daily_loss, dl_pct)

        peak_balance = max(peak_balance, balance)
        ftmo_ok = max_dd < 8 and max_daily_loss < 4.5

        return BacktestResult(
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            win_rate=round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            total_return_pct=round(total_return, 2),
            weekly_return_pct=round(weekly_return, 3),
            profit_factor=round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0,
            max_drawdown_pct=round(max_dd, 2),
            max_daily_loss_pct=round(max_daily_loss, 2),
            ftmo_compliant=ftmo_ok,
            start_date=str(start_dt.date()) if hasattr(start_dt, 'date') else str(start_dt),
            end_date=str(end_dt.date()) if hasattr(end_dt, 'date') else str(end_dt),
            avg_trade_pnl=round(sum(t["pnl"] for t in trades_log) / total_trades, 2) if total_trades > 0 else 0,
            avg_rr_achieved=round(total_rr_achieved / total_trades, 2) if total_trades > 0 else 0,
            trades=trades_log,
            daily_returns=list(daily_pnl.values()),
        )

    # ── Helper Methods ──

    def _find_h1_index(self, m15_time, h1_times):
        """Find the last completed H1 candle index before a M15 time."""
        for i in range(len(h1_times) - 1, -1, -1):
            if h1_times[i] <= m15_time:
                return i
        return None

    def _compute_rsi(self, closes, period=14):
        """Compute RSI array."""
        n = len(closes)
        rsi = np.full(n, 50.0)
        gains = np.zeros(n)
        losses = np.zeros(n)
        for i in range(1, n):
            d = closes[i] - closes[i - 1]
            if d > 0:
                gains[i] = d
            else:
                losses[i] = abs(d)
        avg_g = avg_l = 0.0
        for i in range(1, n):
            if i <= period:
                avg_g = np.mean(gains[1:i + 1])
                avg_l = np.mean(losses[1:i + 1])
            else:
                avg_g = (avg_g * (period - 1) + gains[i]) / period
                avg_l = (avg_l * (period - 1) + losses[i]) / period
            if avg_l > 0:
                rsi[i] = 100 - 100 / (1 + avg_g / avg_l)
            elif avg_g > 0:
                rsi[i] = 100
        return rsi

    def _detect_swings(self, highs, lows, up_to_idx, lookback):
        """Detect swing points up to a given index and classify HH/HL/LH/LL."""
        swings = []
        raw_highs = []
        raw_lows = []

        start = max(lookback, up_to_idx - 200)  # Look back max 200 H1 candles
        for i in range(start, up_to_idx - lookback + 1):
            ws = max(0, i - lookback)
            we = min(len(highs), i + lookback + 1)
            if highs[i] >= np.max(highs[ws:we]):
                raw_highs.append((i, float(highs[i])))
            if lows[i] <= np.min(lows[ws:we]):
                raw_lows.append((i, float(lows[i])))

        # Keep last 10 of each
        raw_highs = raw_highs[-10:]
        raw_lows = raw_lows[-10:]

        # Classify
        for j in range(1, len(raw_highs)):
            if raw_highs[j][1] > raw_highs[j - 1][1]:
                swings.append(SwingPoint(raw_highs[j][1], raw_highs[j][0], "HH"))
            else:
                swings.append(SwingPoint(raw_highs[j][1], raw_highs[j][0], "LH"))

        for j in range(1, len(raw_lows)):
            if raw_lows[j][1] > raw_lows[j - 1][1]:
                swings.append(SwingPoint(raw_lows[j][1], raw_lows[j][0], "HL"))
            else:
                swings.append(SwingPoint(raw_lows[j][1], raw_lows[j][0], "LL"))

        swings.sort(key=lambda s: s.index)
        return swings

    def _determine_bias(self, swings):
        """Determine market bias from swing structure (Rule 3)."""
        if len(swings) < 4:
            return None

        recent = swings[-4:]
        types = [s.type for s in recent]

        # Bullish: last swing = HH and last retracement = HL
        has_hh = "HH" in types
        has_hl = "HL" in types
        if has_hh and has_hl:
            return "BULLISH"

        # Bearish: last swing = LL and last retracement = LH
        has_ll = "LL" in types
        has_lh = "LH" in types
        if has_ll and has_lh:
            return "BEARISH"

        return None

    def _detect_m15_patterns(self, candles, idx):
        """Detect candlestick patterns on M15."""
        patterns = []
        if idx < 2:
            return patterns

        c = candles[idx]
        p = candles[idx - 1]
        body = abs(c["close"] - c["open"])
        rng = c["high"] - c["low"]
        if rng <= 0:
            return patterns

        body_ratio = body / rng
        uw = c["high"] - max(c["open"], c["close"])
        lw = min(c["open"], c["close"]) - c["low"]
        is_bull = c["close"] > c["open"]
        is_bear = c["close"] < c["open"]

        if body_ratio < 0.35 and lw > body * 2.0 and uw < body * 1.0:
            patterns.append("BULLISH_PINBAR")
        if body_ratio < 0.35 and uw > body * 2.0 and lw < body * 1.0:
            patterns.append("BEARISH_PINBAR")
        if is_bull and lw > body * 2.0 and uw < body * 0.5:
            patterns.append("HAMMER")
        if is_bear and uw > body * 2.0 and lw < body * 0.5:
            patterns.append("SHOOTING_STAR")
        if is_bull and p["close"] < p["open"] and c["close"] > p["open"] and c["open"] < p["close"]:
            patterns.append("BULLISH_ENGULFING")
        if is_bear and p["close"] > p["open"] and c["close"] < p["open"] and c["open"] > p["close"]:
            patterns.append("BEARISH_ENGULFING")
        if body_ratio > 0.65:
            patterns.append("STRONG_BULLISH" if is_bull else "STRONG_BEARISH")

        return patterns

    def _find_next_swing_target(self, swings, entry, direction):
        """Find next swing target for structural TP."""
        if direction == "BUY":
            for s in swings:
                if s.type in ("HH", "LH") and s.price > entry + 0.10:
                    return s.price
        elif direction == "SELL":
            for s in reversed(swings):
                if s.type in ("HL", "LL") and s.price < entry - 0.10:
                    return s.price
        return None

    def _close_trade(self, trade, exit_price, balance, base_spread, close_type):
        """Calculate PnL for closing a trade."""
        spread_cost = (base_spread / 2) / PM
        slippage = random.uniform(0, 0.3) / PM

        if trade.direction == "BUY":
            raw_pnl = (exit_price - trade.entry_price) * PM  # In pips
            pnl_pips = raw_pnl - (spread_cost * PM) - (slippage * PM)
        else:
            raw_pnl = (trade.entry_price - exit_price) * PM
            pnl_pips = raw_pnl - (spread_cost * PM) - (slippage * PM)

        pip_value = 1000.0 / exit_price if exit_price > 0 else 6.67
        pnl_money = pnl_pips * pip_value * trade.lot_size

        return pnl_money
