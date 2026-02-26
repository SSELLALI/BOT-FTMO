"""
Strategy Optimizer - Tests parameter combinations on real data
to find the most profitable settings while maintaining FTMO compliance.
"""
import itertools
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from copy import deepcopy

from historical_data_loader import get_real_data
from professional_strategies import (
    ScalpingStrategy, IntradayStrategy, ProfessionalRiskManager,
    TradeSignal, TechnicalAnalysis
)

logger = logging.getLogger(__name__)


def run_scalping_with_params(
    m15_candles: List[Dict],
    fast_ema: int,
    slow_ema: int,
    rsi_period: int,
    rsi_buy_max: float,
    rsi_sell_min: float,
    min_rr: float,
    min_sl_pips: float,
    max_sl_pips: float,
    atr_multiplier: float,
    initial_balance: float = 100000
) -> Dict:
    """Run scalping strategy with custom parameters on real data."""
    risk_mgr = ProfessionalRiskManager(
        initial_balance=initial_balance,
        max_risk_per_trade=0.01,
        max_daily_loss=0.045,
        max_total_drawdown=0.08
    )

    trades = []
    open_trade = None
    last_day = None

    for i in range(max(slow_ema + 10, 50), len(m15_candles)):
        candle = m15_candles[i]
        hour = candle["datetime"].hour
        current_day = candle["datetime"].date()

        # Reset daily
        if last_day and current_day != last_day:
            risk_mgr.reset_daily()
        last_day = current_day

        # Only trade during profitable hours
        if hour not in (9, 10, 11, 13, 14, 17):
            continue

        # Check open trade exit
        if open_trade:
            signal = open_trade["signal"]
            exited = False

            # Safety check
            daily_loss = abs(risk_mgr.daily_pnl) / risk_mgr.initial_balance if risk_mgr.daily_pnl < 0 else 0
            total_dd = (risk_mgr.initial_balance - risk_mgr.current_balance) / risk_mgr.initial_balance if risk_mgr.current_balance < risk_mgr.initial_balance else 0

            if daily_loss >= 0.03 or total_dd >= 0.06:
                exit_price = candle["close"]
                exit_reason = "SAFETY"
                exited = True
            elif signal["direction"] == "BUY":
                if candle["low"] <= signal["sl"]:
                    exit_price = signal["sl"]
                    exit_reason = "SL"
                    exited = True
                elif candle["high"] >= signal["tp"]:
                    exit_price = signal["tp"]
                    exit_reason = "TP"
                    exited = True
            else:
                if candle["high"] >= signal["sl"]:
                    exit_price = signal["sl"]
                    exit_reason = "SL"
                    exited = True
                elif candle["low"] <= signal["tp"]:
                    exit_price = signal["tp"]
                    exit_reason = "TP"
                    exited = True

            if exited:
                if signal["direction"] == "BUY":
                    pnl_pips = (exit_price - signal["entry"]) * 10000
                else:
                    pnl_pips = (signal["entry"] - exit_price) * 10000

                pnl = pnl_pips * signal["lot_size"] * 10
                # Hard cap
                if pnl < 0:
                    max_loss = risk_mgr.max_daily_loss * risk_mgr.initial_balance - abs(min(0, risk_mgr.daily_pnl))
                    if max_loss > 0 and abs(pnl) > max_loss:
                        pnl = -max_loss

                risk_mgr.current_balance += pnl
                risk_mgr.daily_pnl += pnl
                if risk_mgr.current_balance > risk_mgr.peak_balance:
                    risk_mgr.peak_balance = risk_mgr.current_balance

                if pnl < 0:
                    risk_mgr.scalping_state.consecutive_losses += 1
                else:
                    risk_mgr.scalping_state.consecutive_losses = 0

                trades.append({
                    "pnl": pnl,
                    "pnl_pips": pnl_pips,
                    "exit_reason": exit_reason,
                    "direction": signal["direction"]
                })
                risk_mgr.open_trade_count = 0
                open_trade = None
                continue

        # Skip if trade already open or stopped
        if open_trade:
            continue
        if risk_mgr.scalping_state.is_stopped_today or risk_mgr.scalping_state.is_stopped_global:
            continue
        if risk_mgr.scalping_state.consecutive_losses >= 3:
            continue
        if risk_mgr.open_trade_count >= 1:
            continue

        # Daily loss check
        daily_loss = abs(risk_mgr.daily_pnl) / risk_mgr.initial_balance if risk_mgr.daily_pnl < 0 else 0
        if daily_loss >= 0.035:
            continue
        total_dd = (risk_mgr.initial_balance - risk_mgr.current_balance) / risk_mgr.initial_balance if risk_mgr.current_balance < risk_mgr.initial_balance else 0
        if total_dd >= 0.07:
            continue

        # Calculate indicators
        closes = [c["close"] for c in m15_candles[:i + 1]]
        ema_fast = TechnicalAnalysis.ema(closes, fast_ema)
        ema_slow = TechnicalAnalysis.ema(closes, slow_ema)
        rsi = TechnicalAnalysis.rsi(closes, rsi_period)
        atr = TechnicalAnalysis.atr(m15_candles[:i + 1], 14)
        momentum = TechnicalAnalysis.momentum(closes, 8)
        bb_upper, bb_mid, bb_lower = TechnicalAnalysis.bollinger_bands(closes, 20, 2.0)

        current_price = closes[-1]
        cur_fast = ema_fast[-1]
        cur_slow = ema_slow[-1]
        prev_candle = m15_candles[i - 1]

        # Min ATR filter
        if atr < 0.00025:
            continue

        signal = None

        # BUY: fast EMA > slow EMA, RSI not overbought
        if cur_fast > cur_slow and rsi < rsi_buy_max and rsi > 30:
            entry = False
            reason = ""

            # Pullback to fast EMA
            if abs(prev_candle["low"] - ema_fast[-2]) / current_price < 0.0006:
                if current_price > prev_candle["high"]:
                    entry = True
                    reason = "pullback"

            # Strong bullish candle + momentum
            if not entry and TechnicalAnalysis.is_bullish_candle(candle):
                body = candle["close"] - candle["open"]
                if body > atr * 0.4 and momentum > 0.01:
                    entry = True
                    reason = "momentum"

            # BB lower bounce
            if not entry and current_price <= bb_lower * 1.001:
                if TechnicalAnalysis.is_bullish_candle(candle):
                    entry = True
                    reason = "bb_bounce"

            # Engulfing pattern
            if not entry and TechnicalAnalysis.is_bullish_engulfing(m15_candles, i):
                entry = True
                reason = "engulfing"

            if entry:
                sl_dist = max(atr * atr_multiplier, min_sl_pips / 10000)
                sl_pips = sl_dist * 10000
                if sl_pips < min_sl_pips:
                    sl_pips = min_sl_pips
                elif sl_pips > max_sl_pips:
                    sl_pips = max_sl_pips
                tp_pips = sl_pips * min_rr
                sl = current_price - (sl_pips / 10000)
                tp = current_price + (tp_pips / 10000)
                lot = risk_mgr.calculate_lot_size(sl_pips, "EURUSD")
                signal = {"direction": "BUY", "entry": current_price, "sl": sl, "tp": tp, "lot_size": lot}

        # SELL: fast EMA < slow EMA, RSI not oversold
        elif cur_fast < cur_slow and rsi > rsi_sell_min and rsi < 70:
            entry = False

            if abs(prev_candle["high"] - ema_fast[-2]) / current_price < 0.0006:
                if current_price < prev_candle["low"]:
                    entry = True

            if not entry and TechnicalAnalysis.is_bearish_candle(candle):
                body = candle["open"] - candle["close"]
                if body > atr * 0.4 and momentum < -0.01:
                    entry = True

            if not entry and current_price >= bb_upper * 0.999:
                if TechnicalAnalysis.is_bearish_candle(candle):
                    entry = True

            if not entry and TechnicalAnalysis.is_bearish_engulfing(m15_candles, i):
                entry = True

            if entry:
                sl_dist = max(atr * atr_multiplier, min_sl_pips / 10000)
                sl_pips = sl_dist * 10000
                if sl_pips < min_sl_pips:
                    sl_pips = min_sl_pips
                elif sl_pips > max_sl_pips:
                    sl_pips = max_sl_pips
                tp_pips = sl_pips * min_rr
                sl = current_price + (sl_pips / 10000)
                tp = current_price - (tp_pips / 10000)
                lot = risk_mgr.calculate_lot_size(sl_pips, "EURUSD")
                signal = {"direction": "SELL", "entry": current_price, "sl": sl, "tp": tp, "lot_size": lot}

        if signal:
            open_trade = {"signal": signal, "candle_idx": i}
            risk_mgr.open_trade_count = 1
            risk_mgr.scalping_state.daily_trades += 1

    # Compile results
    total = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] <= 0)
    total_pnl = sum(t["pnl"] for t in trades)
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else 0
    wr = (wins / total * 100) if total > 0 else 0
    ret = total_pnl / initial_balance * 100
    max_dd = (initial_balance - risk_mgr.current_balance) / initial_balance * 100 if risk_mgr.current_balance < initial_balance else 0

    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wr, 1),
        "return_pct": round(ret, 2),
        "profit_factor": round(pf, 2),
        "max_dd": round(max_dd, 2),
        "final_balance": round(risk_mgr.current_balance, 2),
        "params": {
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "rsi_period": rsi_period,
            "rsi_buy_max": rsi_buy_max,
            "rsi_sell_min": rsi_sell_min,
            "min_rr": min_rr,
            "atr_mult": atr_multiplier,
            "min_sl": min_sl_pips,
            "max_sl": max_sl_pips
        }
    }


def optimize_scalping(symbol: str = "EURUSD", days: int = 60) -> List[Dict]:
    """Test multiple parameter combinations and return sorted results."""
    h1, m15 = get_real_data(symbol, days)
    if len(m15) < 200:
        return [{"error": "Not enough data"}]

    # Parameter grid
    param_sets = []
    for fast_ema in [10, 15, 20]:
        for slow_ema in [30, 50]:
            if fast_ema >= slow_ema:
                continue
            for rsi_buy_max in [65, 70]:
                for min_rr in [1.0, 1.2, 1.5]:
                    for atr_mult in [1.0, 1.5, 2.0]:
                        param_sets.append({
                            "fast_ema": fast_ema,
                            "slow_ema": slow_ema,
                            "rsi_period": 14,
                            "rsi_buy_max": rsi_buy_max,
                            "rsi_sell_min": 100 - rsi_buy_max,
                            "min_rr": min_rr,
                            "min_sl_pips": 5,
                            "max_sl_pips": 20,
                            "atr_multiplier": atr_mult,
                        })

    logger.info(f"Testing {len(param_sets)} parameter combinations...")
    results = []

    for params in param_sets:
        result = run_scalping_with_params(m15, **params)
        if result["trades"] >= 5:  # Minimum trades to be meaningful
            results.append(result)

    # Sort by profit factor (profitable strategies first)
    results.sort(key=lambda x: (x["return_pct"] > 0, x["profit_factor"], x["win_rate"]), reverse=True)

    return results[:20]  # Top 20


if __name__ == "__main__":
    print("Optimizing scalping strategy on real EURUSD data...")
    results = optimize_scalping("EURUSD", 60)
    print(f"\nTop {len(results)} results:")
    print(f"{'#':<3} {'Trades':<8} {'WR%':<7} {'Return%':<10} {'PF':<6} {'MaxDD%':<8} {'Fast':<6} {'Slow':<6} {'R:R':<5} {'ATR':<5}")
    print("-" * 70)
    for i, r in enumerate(results):
        p = r["params"]
        print(f"{i+1:<3} {r['trades']:<8} {r['win_rate']:<7} {r['return_pct']:<10} {r['profit_factor']:<6} {r['max_dd']:<8} {p['fast_ema']:<6} {p['slow_ema']:<6} {p['min_rr']:<5} {p['atr_mult']:<5}")
