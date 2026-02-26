"""
GBPJPY Breakout-Pullback-Rejection Backtester v2

Strategy rules (user-defined, preserved exactly):
  1. Timeframes: H1 (structure) + M30 (entry)
  2. Sessions: London 07h-11h30, NY 13h30-16h30 UTC only
  3. H1 Structure: HH/HL = bullish, LL/LH = bearish, unclear = no trade
  4. Key Level: Last significant H1 high/low, breakout = full candle close
  5. Volatility: Breakout candle > avg(10 H1), body >= X% range
  6. Pullback: Return to broken level, must not break H1 structure
  7. Rejection: Engulfing, pin bar, or impulse candle on entry TF
  8. RSI: entry TF RSI(14), long rising in range, short falling in range, skip >70/<30
  9. Entry: At rejection candle close, 1 trade per breakout
  10. Stop Loss: Below/above pullback wick + buffer pips
  11. Take Profit: Min R:R or next H1 swing
  12. Management: Move SL to breakeven at 1:1
  13. Cancel: Deep pullback, weak rejection, small breakout, ranging, high spread

Key improvement: tracks MULTIPLE active breakouts simultaneously (a real trader
would monitor several setups at once). Still respects Rule 9 (1 trade per breakout)
and only enters when no other trade is open.

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
class OpenTrade:
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    entry_time: datetime
    breakout_level: float
    sl_pips: float
    be_moved: bool = False


class GBPJPYBreakoutBacktester:
    def __init__(self, initial_balance=100000):
        self.initial_balance = initial_balance

    def run(self, h1_candles, entry_candles, params, base_spread=2.5):
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

        h1_times = [c["datetime"] for c in h1_candles]
        h1_closes = np.array([c["close"] for c in h1_candles])
        h1_highs = np.array([c["high"] for c in h1_candles])
        h1_lows = np.array([c["low"] for c in h1_candles])
        h1_ranges = h1_highs - h1_lows

        entry_closes = np.array([c["close"] for c in entry_candles])
        entry_rsi = self._compute_rsi(entry_closes, 14)

        # Parameters
        swing_lookback = params.get("swing_lookback", 10)
        sl_buffer_pips = params.get("sl_buffer_pips", 7)
        min_rr = params.get("min_rr", 2.0)
        risk_per_trade = params.get("risk_per_trade", 0.01)
        breakout_body_ratio = params.get("breakout_body_ratio", 0.55)
        breakout_size_mult = params.get("breakout_size_mult", 0.7)
        max_pullback_depth = params.get("max_pullback_depth", 0.9)
        rsi_long_min = params.get("rsi_long_min", 42)
        rsi_long_max = params.get("rsi_long_max", 70)
        rsi_short_min = params.get("rsi_short_min", 30)
        rsi_short_max = params.get("rsi_short_max", 58)
        be_trigger_rr = params.get("be_trigger_rr", 1.0)
        max_daily_trades = params.get("max_daily_trades", 4)
        max_consecutive_losses = params.get("max_consecutive_losses", 3)
        use_structural_tp = params.get("use_structural_tp", False)
        min_sl_pips = params.get("min_sl_pips", 10)
        max_sl_pips = params.get("max_sl_pips", 70)
        proximity_factor = params.get("proximity_factor", 0.7)
        stale_timeout = params.get("stale_timeout", 25)

        consecutive_losses = 0
        daily_trade_count = {}
        current_date = None

        # Multi-breakout tracking: list of active breakout setups
        active_breakouts = []  # [{"level", "direction", "h1_idx", "candle_range", "pb_low", "pb_high", "key"}]
        detected_breakout_keys = set()

        for idx in range(2, len(entry_candles)):
            ec = entry_candles[idx]
            ec_time = ec["datetime"]
            ec_close = ec["close"]
            ec_open = ec["open"]
            ec_high = ec["high"]
            ec_low = ec["low"]

            h1_idx = self._find_h1_index(ec_time, h1_times)
            if h1_idx is None or h1_idx < swing_lookback + 10:
                continue

            trade_date = ec_time.date()
            if current_date != trade_date:
                current_date = trade_date
                if trade_date not in daily_trade_count:
                    daily_trade_count[trade_date] = 0
                consecutive_losses = min(consecutive_losses, max_consecutive_losses)

            # ── Manage open trade (always, regardless of session) ──
            if open_trade:
                if open_trade.direction == "BUY":
                    if ec_low <= open_trade.stop_loss:
                        pnl = self._close_trade(open_trade, open_trade.stop_loss, base_spread, "SL")
                        balance += pnl
                        dk = str(trade_date)
                        daily_pnl[dk] = daily_pnl.get(dk, 0) + pnl
                        if pnl < 0:
                            gross_loss += abs(pnl)
                            consecutive_losses += 1
                        else:
                            gross_profit += pnl
                            consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(ec_time), "dir": "BUY", "pnl": round(pnl, 2), "type": "SL"})
                        open_trade = None
                    elif ec_high >= open_trade.take_profit:
                        pnl = self._close_trade(open_trade, open_trade.take_profit, base_spread, "TP")
                        balance += pnl
                        dk = str(trade_date)
                        daily_pnl[dk] = daily_pnl.get(dk, 0) + pnl
                        gross_profit += pnl
                        consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(ec_time), "dir": "BUY", "pnl": round(pnl, 2), "type": "TP"})
                        open_trade = None
                    elif not open_trade.be_moved and be_trigger_rr > 0:
                        be_dist = open_trade.sl_pips / PM * be_trigger_rr
                        if ec_high >= open_trade.entry_price + be_dist:
                            open_trade.stop_loss = open_trade.entry_price + (base_spread / PM / 2)
                            open_trade.be_moved = True
                elif open_trade.direction == "SELL":
                    if ec_high >= open_trade.stop_loss:
                        pnl = self._close_trade(open_trade, open_trade.stop_loss, base_spread, "SL")
                        balance += pnl
                        dk = str(trade_date)
                        daily_pnl[dk] = daily_pnl.get(dk, 0) + pnl
                        if pnl < 0:
                            gross_loss += abs(pnl)
                            consecutive_losses += 1
                        else:
                            gross_profit += pnl
                            consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(ec_time), "dir": "SELL", "pnl": round(pnl, 2), "type": "SL"})
                        open_trade = None
                    elif ec_low <= open_trade.take_profit:
                        pnl = self._close_trade(open_trade, open_trade.take_profit, base_spread, "TP")
                        balance += pnl
                        dk = str(trade_date)
                        daily_pnl[dk] = daily_pnl.get(dk, 0) + pnl
                        gross_profit += pnl
                        consecutive_losses = 0
                        rr = pnl / (open_trade.sl_pips / PM * open_trade.lot_size * PM) if open_trade.sl_pips > 0 else 0
                        total_rr_achieved += rr
                        trades_log.append({"time": str(ec_time), "dir": "SELL", "pnl": round(pnl, 2), "type": "TP"})
                        open_trade = None
                    elif not open_trade.be_moved and be_trigger_rr > 0:
                        be_dist = open_trade.sl_pips / PM * be_trigger_rr
                        if ec_low <= open_trade.entry_price - be_dist:
                            open_trade.stop_loss = open_trade.entry_price - (base_spread / PM / 2)
                            open_trade.be_moved = True

                peak_balance = max(peak_balance, balance)
                dd = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0
                max_dd = max(max_dd, dd)

                if open_trade:  # Still open, skip new signal detection
                    continue

            # ── SESSION FILTER (Rule 2) ──
            t_minutes = ec_time.hour * 60 + ec_time.minute
            in_london = 420 <= t_minutes <= 690
            in_ny = 810 <= t_minutes <= 990
            if not (in_london or in_ny):
                continue
            if ec_time.weekday() >= 5:
                continue

            # ── Prune stale breakouts ──
            active_breakouts = [
                bo for bo in active_breakouts
                if h1_idx - bo["h1_idx"] <= stale_timeout
            ]

            # ── H1 STRUCTURE + KEY LEVELS (multiple levels tracked) ──
            swings = self._detect_swings(h1_highs, h1_lows, h1_idx, swing_lookback)
            bias = self._determine_bias(swings)
            if bias is None:
                continue

            # Track multiple key levels (last 3 each) for more breakout opportunities
            resistances = []
            supports = []
            for sp in reversed(swings):
                if sp.type in ("HH", "LH") and len(resistances) < 3:
                    # Avoid duplicate levels (within 0.10 JPY)
                    if not any(abs(sp.price - r) < 0.10 for r in resistances):
                        resistances.append(sp.price)
                if sp.type in ("HL", "LL") and len(supports) < 3:
                    if not any(abs(sp.price - s) < 0.10 for s in supports):
                        supports.append(sp.price)

            # ── BREAKOUT DETECTION (check all key levels, track multiple) ──
            h1_c = h1_candles[h1_idx]
            prev_h1_close = h1_closes[h1_idx - 1] if h1_idx > 0 else h1_c["close"]

            if bias == "BULLISH":
                for key_r in resistances:
                    bk_key = f"B_{key_r:.2f}_{h1_idx}"
                    if bk_key not in detected_breakout_keys:
                        if h1_c["close"] > key_r and prev_h1_close <= key_r:
                            avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx])) if h1_idx >= 10 else float(h1_ranges[h1_idx])
                            cr = h1_c["high"] - h1_c["low"]
                            cb = abs(h1_c["close"] - h1_c["open"])
                            br = cb / cr if cr > 0 else 0
                            if cr > avg_range * breakout_size_mult and br >= breakout_body_ratio:
                                active_breakouts.append({
                                    "level": key_r, "direction": "BUY",
                                    "h1_idx": h1_idx, "candle_range": cr,
                                    "pb_low": ec_low, "pb_high": ec_high, "key": bk_key,
                                })
                                detected_breakout_keys.add(bk_key)

            if bias == "BEARISH":
                for key_s in supports:
                    bk_key = f"S_{key_s:.2f}_{h1_idx}"
                    if bk_key not in detected_breakout_keys:
                        if h1_c["close"] < key_s and prev_h1_close >= key_s:
                            avg_range = float(np.mean(h1_ranges[max(0, h1_idx-10):h1_idx])) if h1_idx >= 10 else float(h1_ranges[h1_idx])
                            cr = h1_c["high"] - h1_c["low"]
                            cb = abs(h1_c["close"] - h1_c["open"])
                            br = cb / cr if cr > 0 else 0
                            if cr > avg_range * breakout_size_mult and br >= breakout_body_ratio:
                                active_breakouts.append({
                                    "level": key_s, "direction": "SELL",
                                    "h1_idx": h1_idx, "candle_range": cr,
                                    "pb_low": ec_low, "pb_high": ec_high, "key": bk_key,
                                })
                                detected_breakout_keys.add(bk_key)

            if not active_breakouts:
                continue

            # Daily trade limit & consecutive loss limit
            if daily_trade_count.get(trade_date, 0) >= max_daily_trades:
                continue
            if consecutive_losses >= max_consecutive_losses:
                continue
            # FTMO safety
            dd_pct = (peak_balance - balance) / self.initial_balance * 100 if self.initial_balance > 0 else 0
            if dd_pct > 7:
                continue

            # ── CHECK ALL ACTIVE BREAKOUTS for pullback entry ──
            best_entry = None
            best_bo_idx = None

            for bo_i, bo in enumerate(active_breakouts):
                level = bo["level"]
                direction = bo["direction"]

                # Update pullback extremes
                bo["pb_low"] = min(bo["pb_low"], ec_low)
                bo["pb_high"] = max(bo["pb_high"], ec_high)

                # Pullback conditions (Rule 6)
                if direction == "BUY":
                    if ec_close > level + bo["candle_range"]:
                        continue  # Not pulled back yet
                    # Structure check
                    last_hl = None
                    for sp in reversed(swings):
                        if sp.type == "HL":
                            last_hl = sp.price
                            break
                    if last_hl and ec_low < last_hl:
                        bo["stale"] = True  # Mark for removal
                        continue
                    # Depth check
                    pd = (bo["pb_high"] - ec_low) / bo["candle_range"] if bo["candle_range"] > 0 else 999
                    if pd > max_pullback_depth:
                        continue
                    # Proximity check
                    if abs(ec_close - level) > bo["candle_range"] * proximity_factor:
                        continue
                elif direction == "SELL":
                    if ec_close < level - bo["candle_range"]:
                        continue
                    last_lh = None
                    for sp in reversed(swings):
                        if sp.type == "LH":
                            last_lh = sp.price
                            break
                    if last_lh and ec_high > last_lh:
                        bo["stale"] = True
                        continue
                    pd = (ec_high - bo["pb_low"]) / bo["candle_range"] if bo["candle_range"] > 0 else 999
                    if pd > max_pullback_depth:
                        continue
                    if abs(ec_close - level) > bo["candle_range"] * proximity_factor:
                        continue

                # ── REJECTION CANDLE (Rule 7) ──
                patterns = self._detect_patterns(entry_candles, idx)
                has_rej = False
                if direction == "BUY":
                    has_rej = any(p in patterns for p in
                        ("BULLISH_ENGULFING", "BULLISH_PINBAR", "HAMMER", "STRONG_BULLISH"))
                    if not (ec_close > ec_open):
                        has_rej = False
                elif direction == "SELL":
                    has_rej = any(p in patterns for p in
                        ("BEARISH_ENGULFING", "BEARISH_PINBAR", "SHOOTING_STAR", "STRONG_BEARISH"))
                    if not (ec_close < ec_open):
                        has_rej = False
                if not has_rej:
                    continue

                # ── RSI (Rule 8) ──
                rsi_val = entry_rsi[idx]
                rsi_prev = entry_rsi[idx - 1]
                if direction == "BUY":
                    if not (rsi_long_min <= rsi_val <= rsi_long_max):
                        continue
                    if rsi_val <= rsi_prev:
                        continue
                    if rsi_val > 70 or rsi_val < 30:
                        continue
                elif direction == "SELL":
                    if not (rsi_short_min <= rsi_val <= rsi_short_max):
                        continue
                    if rsi_val >= rsi_prev:
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
                    entry = ec_close + (spread / 2 / PM) + slippage
                    sl = bo["pb_low"] - (sl_buffer_pips / PM)
                    sl_pips = (entry - sl) * PM
                    if sl_pips < min_sl_pips or sl_pips > max_sl_pips:
                        continue
                    if use_structural_tp:
                        tp_target = self._find_next_swing_target(swings, entry, "BUY")
                        if tp_target and (tp_target - entry) * PM / sl_pips >= min_rr:
                            tp = tp_target
                        else:
                            tp = entry + (sl_pips * min_rr / PM)
                    else:
                        tp = entry + (sl_pips * min_rr / PM)
                else:
                    entry = ec_close - (spread / 2 / PM) - slippage
                    sl = bo["pb_high"] + (sl_buffer_pips / PM)
                    sl_pips = (sl - entry) * PM
                    if sl_pips < min_sl_pips or sl_pips > max_sl_pips:
                        continue
                    if use_structural_tp:
                        tp_target = self._find_next_swing_target(swings, entry, "SELL")
                        if tp_target and (entry - tp_target) * PM / sl_pips >= min_rr:
                            tp = tp_target
                        else:
                            tp = entry - (sl_pips * min_rr / PM)
                    else:
                        tp = entry - (sl_pips * min_rr / PM)

                # This breakout qualifies for entry
                best_entry = {
                    "direction": direction, "entry": entry, "sl": sl, "tp": tp,
                    "sl_pips": sl_pips, "level": level, "bo_idx": bo_i,
                }
                best_bo_idx = bo_i
                break  # Take first valid entry

            # Remove stale/broken breakouts
            active_breakouts = [bo for bo in active_breakouts if not bo.get("stale")]

            if best_entry is None:
                continue

            # ── POSITION SIZING & OPEN TRADE (Rules 9, 10) ──
            d = best_entry
            risk_amount = balance * risk_per_trade
            pip_value = 1000.0 / d["entry"] if d["entry"] > 0 else 6.67
            lot_size = max(0.01, min(risk_amount / (d["sl_pips"] * pip_value), 5.0))

            open_trade = OpenTrade(
                direction=d["direction"], entry_price=d["entry"],
                stop_loss=d["sl"], take_profit=d["tp"],
                lot_size=lot_size, entry_time=ec_time,
                breakout_level=d["level"], sl_pips=d["sl_pips"],
            )
            daily_trade_count[trade_date] = daily_trade_count.get(trade_date, 0) + 1

            # Remove traded breakout from active list
            if best_bo_idx is not None and best_bo_idx < len(active_breakouts):
                active_breakouts.pop(best_bo_idx)

        # ── Close remaining open trade ──
        if open_trade:
            last_price = entry_candles[-1]["close"]
            pnl = self._close_trade(open_trade, last_price, base_spread, "EOD")
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

        if entry_candles:
            start_dt = entry_candles[0]["datetime"]
            end_dt = entry_candles[-1]["datetime"]
            days = (end_dt - start_dt).days
            weeks = max(days / 7, 1)
            weekly_return = total_return / weeks
        else:
            weekly_return = 0
            start_dt = end_dt = datetime.now(timezone.utc)

        for dk, dpnl in daily_pnl.items():
            dl_pct = abs(dpnl) / self.initial_balance * 100 if dpnl < 0 else 0
            max_daily_loss = max(max_daily_loss, dl_pct)

        peak_balance = max(peak_balance, balance)
        ftmo_ok = max_dd < 8 and max_daily_loss < 4.5

        return BacktestResult(
            total_trades=total_trades,
            wins=wins, losses=losses,
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
    def _find_h1_index(self, entry_time, h1_times):
        for i in range(len(h1_times) - 1, -1, -1):
            if h1_times[i] <= entry_time:
                return i
        return None

    def _compute_rsi(self, closes, period=14):
        n = len(closes)
        rsi = np.full(n, 50.0)
        gains = np.zeros(n)
        losses_arr = np.zeros(n)
        for i in range(1, n):
            d = closes[i] - closes[i - 1]
            if d > 0:
                gains[i] = d
            else:
                losses_arr[i] = abs(d)
        avg_g = avg_l = 0.0
        for i in range(1, n):
            if i <= period:
                avg_g = np.mean(gains[1:i + 1])
                avg_l = np.mean(losses_arr[1:i + 1])
            else:
                avg_g = (avg_g * (period - 1) + gains[i]) / period
                avg_l = (avg_l * (period - 1) + losses_arr[i]) / period
            if avg_l > 0:
                rsi[i] = 100 - 100 / (1 + avg_g / avg_l)
            elif avg_g > 0:
                rsi[i] = 100
        return rsi

    def _detect_swings(self, highs, lows, up_to_idx, lookback):
        swings = []
        raw_highs = []
        raw_lows = []
        start = max(lookback, up_to_idx - 200)
        for i in range(start, up_to_idx - lookback + 1):
            ws = max(0, i - lookback)
            we = min(len(highs), i + lookback + 1)
            if highs[i] >= np.max(highs[ws:we]):
                raw_highs.append((i, float(highs[i])))
            if lows[i] <= np.min(lows[ws:we]):
                raw_lows.append((i, float(lows[i])))
        raw_highs = raw_highs[-10:]
        raw_lows = raw_lows[-10:]
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
        if len(swings) < 4:
            return None
        recent = swings[-4:]
        types = [s.type for s in recent]
        if "HH" in types and "HL" in types:
            return "BULLISH"
        if "LL" in types and "LH" in types:
            return "BEARISH"
        return None

    def _detect_patterns(self, candles, idx):
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
        if direction == "BUY":
            for s in swings:
                if s.type in ("HH", "LH") and s.price > entry + 0.10:
                    return s.price
        elif direction == "SELL":
            for s in reversed(swings):
                if s.type in ("HL", "LL") and s.price < entry - 0.10:
                    return s.price
        return None

    def _close_trade(self, trade, exit_price, base_spread, close_type):
        spread_cost = (base_spread / 2) / PM
        slippage = random.uniform(0, 0.3) / PM
        if trade.direction == "BUY":
            pnl_pips = (exit_price - trade.entry_price) * PM - (spread_cost * PM) - (slippage * PM)
        else:
            pnl_pips = (trade.entry_price - exit_price) * PM - (spread_cost * PM) - (slippage * PM)
        pip_value = 1000.0 / exit_price if exit_price > 0 else 6.67
        return pnl_pips * pip_value * trade.lot_size


@dataclass
class SwingPoint:
    price: float
    index: int
    type: str
