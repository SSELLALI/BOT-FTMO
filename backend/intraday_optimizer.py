"""
Intraday Strategy Optimizer
Finds profitable parameters using real historical data.
"""
import sys
sys.path.insert(0, '/app/backend')

from professional_strategies import TechnicalAnalysis
from historical_data_loader import get_real_data


class IntradayRiskMgr:
    def __init__(self, initial_balance):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.peak_balance = initial_balance
        self.daily_pnl = 0.0
        self.max_daily_loss = 0.045
        self.max_risk_per_trade = 0.01
        self.consecutive_losses = 0
        self.daily_trades = 0
        self.open_trade_count = 0

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.daily_trades = 0

    def calculate_lot_size(self, sl_pips, symbol="EURUSD"):
        risk_amount = self.current_balance * self.max_risk_per_trade * 0.95
        pip_value = 10.0
        return max(0.01, round(risk_amount / (sl_pips * pip_value), 2))


def run_intraday_with_params(
    h1_candles, m15_candles,
    m15_ema_fast=9, m15_ema_slow=21,
    min_rr=1.5, min_sl_pips=12, max_sl_pips=35,
    rsi_buy_max=68, rsi_sell_min=32,
    momentum_threshold=0.02,
    initial_balance=100000
):
    rm = IntradayRiskMgr(initial_balance)
    open_trade = None
    last_day = None
    trades = []
    max_dd = 0

    # Build H1 time index
    h1_by_time = {}
    for idx, c in enumerate(h1_candles):
        key = c["datetime"].replace(minute=0, second=0, microsecond=0)
        h1_by_time[key] = idx

    for i in range(50, len(m15_candles)):
        candle = m15_candles[i]
        hour = candle["datetime"].hour
        current_day = candle["datetime"].date()

        if last_day and current_day != last_day:
            rm.reset_daily()
        last_day = current_day

        if hour < 7 or hour > 21:
            continue

        # Find corresponding H1 index
        h1_time = candle["datetime"].replace(minute=0, second=0, microsecond=0)
        h1_idx = h1_by_time.get(h1_time, -1)
        if h1_idx < 200:
            continue

        # === EXIT ===
        if open_trade:
            sig = open_trade
            exited = False
            exit_price = 0
            exit_reason = ""

            daily_loss = abs(rm.daily_pnl) / rm.initial_balance if rm.daily_pnl < 0 else 0
            total_dd = (rm.initial_balance - rm.current_balance) / rm.initial_balance if rm.current_balance < rm.initial_balance else 0

            if daily_loss >= 0.03 or total_dd >= 0.06:
                exit_price = candle["close"]
                exit_reason = "SAFETY"
                exited = True
            elif sig["direction"] == "BUY":
                if candle["low"] <= sig["sl"]:
                    exit_price = sig["sl"]
                    exit_reason = "SL"
                    exited = True
                elif candle["high"] >= sig["tp"]:
                    exit_price = sig["tp"]
                    exit_reason = "TP"
                    exited = True
            else:
                if candle["high"] >= sig["sl"]:
                    exit_price = sig["sl"]
                    exit_reason = "SL"
                    exited = True
                elif candle["low"] <= sig["tp"]:
                    exit_price = sig["tp"]
                    exit_reason = "TP"
                    exited = True

            if exited:
                if sig["direction"] == "BUY":
                    pnl_pips = (exit_price - sig["entry"]) * 10000
                else:
                    pnl_pips = (sig["entry"] - exit_price) * 10000
                pnl = pnl_pips * sig["lot_size"] * 10

                if pnl < 0:
                    max_loss = rm.max_daily_loss * rm.initial_balance - abs(min(0, rm.daily_pnl))
                    if max_loss > 0 and abs(pnl) > max_loss:
                        pnl = -max_loss

                rm.current_balance += pnl
                rm.daily_pnl += pnl
                if rm.current_balance > rm.peak_balance:
                    rm.peak_balance = rm.current_balance
                if pnl < 0:
                    rm.consecutive_losses += 1
                else:
                    rm.consecutive_losses = 0

                trades.append({"pnl": pnl, "reason": exit_reason})
                dd = (rm.initial_balance - rm.current_balance) / rm.initial_balance if rm.current_balance < rm.initial_balance else 0
                if dd > max_dd:
                    max_dd = dd

                rm.open_trade_count = 0
                open_trade = None
                continue

        if open_trade:
            continue

        # === PRE-ENTRY CHECKS ===
        if rm.consecutive_losses >= 2:
            continue
        if rm.daily_trades >= 5:
            continue
        if rm.open_trade_count >= 1:
            continue
        daily_loss = abs(rm.daily_pnl) / rm.initial_balance if rm.daily_pnl < 0 else 0
        if daily_loss >= 0.035:
            continue
        total_dd = (rm.initial_balance - rm.current_balance) / rm.initial_balance if rm.current_balance < rm.initial_balance else 0
        if total_dd >= 0.07:
            continue

        # === H1 INDICATORS ===
        h1_closes = [c["close"] for c in h1_candles[:h1_idx + 1]]
        h1_highs = [c["high"] for c in h1_candles[:h1_idx + 1]]
        h1_lows = [c["low"] for c in h1_candles[:h1_idx + 1]]
        ema50_h1 = TechnicalAnalysis.ema(h1_closes, 50)
        ema200_h1 = TechnicalAnalysis.ema(h1_closes, 200)
        cur_ema50 = ema50_h1[-1]
        cur_ema200 = ema200_h1[-1]
        h1_swing_high = TechnicalAnalysis.find_swing_high(h1_highs[-20:], 10)
        h1_swing_low = TechnicalAnalysis.find_swing_low(h1_lows[-20:], 10)
        h1_atr = TechnicalAnalysis.atr(h1_candles[:h1_idx + 1], 14)

        # === M15 INDICATORS ===
        m15_closes = [c["close"] for c in m15_candles[:i + 1]]
        m15_highs = [c["high"] for c in m15_candles[:i + 1]]
        m15_lows = [c["low"] for c in m15_candles[:i + 1]]
        current_price = m15_closes[-1]
        rsi_m15 = TechnicalAnalysis.rsi(m15_closes, 14)
        ema_fast_m15 = TechnicalAnalysis.ema(m15_closes, m15_ema_fast)
        ema_slow_m15 = TechnicalAnalysis.ema(m15_closes, m15_ema_slow)
        momentum_m15 = TechnicalAnalysis.momentum(m15_closes, 8)

        signal = None

        # === BUY ===
        if cur_ema50 > cur_ema200 and rsi_m15 < rsi_buy_max:
            entry = False

            # Setup 1: H1 pullback to EMA50
            near_ema50 = current_price <= cur_ema50 * 1.004 and current_price >= cur_ema50 * 0.994
            if near_ema50:
                if (TechnicalAnalysis.is_bullish_engulfing(m15_candles, i) or
                    TechnicalAnalysis.is_bullish_candle(candle)) and momentum_m15 > -0.05:
                    entry = True

            # Setup 2: H1 support bounce
            if not entry:
                near_support = abs(current_price - h1_swing_low) / current_price < 0.005
                if near_support and current_price > h1_swing_low * 0.998:
                    if TechnicalAnalysis.is_bullish_candle(candle) or TechnicalAnalysis.is_bullish_engulfing(m15_candles, i):
                        entry = True

            # Setup 3: Breakout above resistance
            if not entry:
                prev_close = m15_candles[i - 1]["close"]
                if current_price > h1_swing_high and prev_close <= h1_swing_high and momentum_m15 > momentum_threshold:
                    entry = True

            # Setup 4: M15 EMA crossover aligned with H1
            if not entry:
                prev_fast = ema_fast_m15[-2]
                prev_slow = ema_slow_m15[-2]
                cur_fast = ema_fast_m15[-1]
                cur_slow = ema_slow_m15[-1]
                if prev_fast <= prev_slow and cur_fast > cur_slow and current_price > cur_ema50:
                    entry = True

            if entry:
                m15_sw_low = TechnicalAnalysis.find_swing_low(m15_lows[-10:], 5)
                sl_price = min(m15_sw_low, current_price - h1_atr * 0.5) - 0.0002
                sl_pips = (current_price - sl_price) * 10000
                if sl_pips < min_sl_pips:
                    sl_pips = min_sl_pips
                elif sl_pips > max_sl_pips:
                    sl_pips = max_sl_pips
                tp_pips = sl_pips * min_rr
                sl = current_price - (sl_pips / 10000)
                tp = current_price + (tp_pips / 10000)
                lot = rm.calculate_lot_size(sl_pips)
                signal = {"direction": "BUY", "entry": current_price, "sl": sl, "tp": tp, "lot_size": lot, "sl_pips": sl_pips, "tp_pips": tp_pips}

        # === SELL ===
        if signal is None and cur_ema50 < cur_ema200 and rsi_m15 > rsi_sell_min:
            entry = False

            # Setup 1: H1 pullback to EMA50
            near_ema50 = current_price >= cur_ema50 * 0.996 and current_price <= cur_ema50 * 1.006
            if near_ema50:
                if (TechnicalAnalysis.is_bearish_engulfing(m15_candles, i) or
                    TechnicalAnalysis.is_bearish_candle(candle)) and momentum_m15 < 0.05:
                    entry = True

            # Setup 2: H1 resistance rejection
            if not entry:
                near_resistance = abs(current_price - h1_swing_high) / current_price < 0.005
                if near_resistance and current_price < h1_swing_high * 1.002:
                    if TechnicalAnalysis.is_bearish_candle(candle) or TechnicalAnalysis.is_bearish_engulfing(m15_candles, i):
                        entry = True

            # Setup 3: Breakout below support
            if not entry:
                prev_close = m15_candles[i - 1]["close"]
                if current_price < h1_swing_low and prev_close >= h1_swing_low and momentum_m15 < -momentum_threshold:
                    entry = True

            # Setup 4: M15 EMA crossover aligned with H1
            if not entry:
                prev_fast = ema_fast_m15[-2]
                prev_slow = ema_slow_m15[-2]
                cur_fast = ema_fast_m15[-1]
                cur_slow = ema_slow_m15[-1]
                if prev_fast >= prev_slow and cur_fast < cur_slow and current_price < cur_ema50:
                    entry = True

            if entry:
                m15_sw_high = TechnicalAnalysis.find_swing_high(m15_highs[-10:], 5)
                sl_price = max(m15_sw_high, current_price + h1_atr * 0.5) + 0.0002
                sl_pips = (sl_price - current_price) * 10000
                if sl_pips < min_sl_pips:
                    sl_pips = min_sl_pips
                elif sl_pips > max_sl_pips:
                    sl_pips = max_sl_pips
                tp_pips = sl_pips * min_rr
                sl = current_price + (sl_pips / 10000)
                tp = current_price - (tp_pips / 10000)
                lot = rm.calculate_lot_size(sl_pips)
                signal = {"direction": "SELL", "entry": current_price, "sl": sl, "tp": tp, "lot_size": lot, "sl_pips": sl_pips, "tp_pips": tp_pips}

        if signal:
            open_trade = signal
            rm.open_trade_count = 1
            rm.daily_trades += 1

    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] <= 0)
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
        "return_pct": round((rm.current_balance - initial_balance) / initial_balance * 100, 2),
        "final_balance": round(rm.current_balance, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999,
        "max_dd": round(max_dd * 100, 2),
        "params": {
            "m15_fast": m15_ema_fast, "m15_slow": m15_ema_slow,
            "min_rr": min_rr, "min_sl": min_sl_pips, "max_sl": max_sl_pips,
            "rsi_buy": rsi_buy_max, "momentum": momentum_threshold
        }
    }


if __name__ == "__main__":
    h1, m15 = get_real_data("EURUSD", 60)
    print(f"Data: H1={len(h1)}, M15={len(m15)}")

    results = []
    count = 0
    for m15_fast in [5, 8, 9, 12]:
        for m15_slow in [15, 21, 30]:
            if m15_fast >= m15_slow:
                continue
            for rr in [1.5, 2.0, 2.5, 3.0]:
                for sl_min in [8, 12, 15]:
                    for sl_max in [25, 35, 45]:
                        for rsi in [60, 65, 68, 70]:
                            for mom in [0.01, 0.02, 0.03]:
                                count += 1
                                r = run_intraday_with_params(
                                    h1, m15,
                                    m15_ema_fast=m15_fast, m15_ema_slow=m15_slow,
                                    min_rr=rr, min_sl_pips=sl_min, max_sl_pips=sl_max,
                                    rsi_buy_max=rsi, rsi_sell_min=100-rsi,
                                    momentum_threshold=mom,
                                    initial_balance=100000
                                )
                                if r["trades"] >= 5:
                                    results.append(r)

    results.sort(key=lambda x: x["return_pct"], reverse=True)
    print(f"\nTested {count} combos, {len(results)} viable")
    print(f"\nTop 20:")
    print(f"{'#':<3} {'Trades':<7} {'WR%':<6} {'Ret%':<8} {'Wk%':<6} {'PF':<5} {'DD%':<6} {'Fast':<5} {'Slow':<5} {'RR':<4} {'SLm':<4} {'SLM':<4} {'RSI':<4} {'Mom':<5}")
    print("-" * 85)
    for i, r in enumerate(results[:20]):
        p = r["params"]
        wk = r["return_pct"] / 8.4
        print(f"{i+1:<3} {r['trades']:<7} {r['win_rate']:<6} {r['return_pct']:<8} {wk:<6.2f} {r['profit_factor']:<5} {r['max_dd']:<6} {p['m15_fast']:<5} {p['m15_slow']:<5} {p['min_rr']:<4} {p['min_sl']:<4} {p['max_sl']:<4} {p['rsi_buy']:<4} {p['momentum']:<5}")
