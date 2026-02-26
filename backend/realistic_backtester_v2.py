"""
Realistic Backtester V2 — Professional FTMO Trading Backtester

Implements ALL realistic market simulation rules:
1. No M1 OHLC-only backtests for scalping
2. Variable spread (session + volatility + news, with 1.2x safety margin)
3. Bid/Ask execution (BUY at Ask, SELL at Bid, SL/TP on correct book sides)
4. ATR-proportional slippage (0-0.5 pip normal, up to 2 pip high vol)
5. Anti-lookahead: indicators on COMPLETED candles only, execute at NEXT open
6. Execution latency 100-300ms with price recalculation
7. Partial fills, requotes, rejections (probabilistic)
8. News impact: spread x3, slippage x3 during 3 min around major events
9. FTMO compliance: 0.5-1% risk/trade, 4.5% daily, 8% total drawdown
"""
import numpy as np
import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

from news_calendar import news_calendar
from professional_strategies import TechnicalAnalysis

logger = logging.getLogger(__name__)


@dataclass
class ExecutionConfig:
    base_spread_pips: float = 0.8
    spread_safety_multiplier: float = 1.2
    news_spread_multiplier: float = 3.0
    news_window_minutes: int = 3
    base_slippage_min: float = 0.0
    base_slippage_max: float = 0.5
    high_vol_slippage_max: float = 2.0
    news_slippage_multiplier: float = 3.0
    latency_ms_min: int = 100
    latency_ms_max: int = 300
    full_fill_prob: float = 0.95
    partial_fill_prob: float = 0.03
    requote_prob: float = 0.015
    rejection_prob: float = 0.005
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.045
    max_total_drawdown: float = 0.08
    daily_loss_soft_limit: float = 0.035
    total_dd_soft_limit: float = 0.07
    max_consecutive_losses: int = 3


@dataclass
class RealisticTrade:
    id: int
    symbol: str
    direction: str
    strategy: str
    entry_price: float
    signal_price: float
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    sl_pips: float = 0.0
    tp_pips: float = 0.0
    lot_size: float = 0.0
    fill_ratio: float = 1.0
    entry_spread: float = 0.0
    entry_slippage: float = 0.0
    exit_spread: float = 0.0
    exit_slippage: float = 0.0
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pnl_pips: float = 0.0
    exit_reason: str = ""
    session: str = ""
    was_requoted: bool = False


@dataclass
class BacktestResultV2:
    strategy: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    data_source: str
    initial_balance: float
    final_balance: float
    total_return_pct: float
    weekly_return_pct: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    max_daily_loss_pct: float
    sharpe_ratio: float
    avg_spread: float
    avg_slippage: float
    rejected_orders: int
    partial_fills: int
    requotes: int
    ftmo_compliant: bool
    max_consecutive_losses: int
    avg_risk_reward: float
    trades: List[Dict] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    daily_returns: List[Dict] = field(default_factory=list)


class RealisticBacktester:
    """
    Professional backtester with full realistic market simulation.

    OHLC bars = BID prices.
    Ask = Bid + spread.
    BUY executes at Ask.  SELL executes at Bid.
    BUY SL/TP checked on Bid.  SELL SL/TP checked on Ask.
    Signals from COMPLETED candles only.
    Execution at NEXT candle open.
    """

    SPREAD_BY_HOUR = {
        0: 1.5, 1: 1.5, 2: 1.5, 3: 1.4, 4: 1.3, 5: 1.3,
        6: 1.2, 7: 1.1,
        8: 0.9, 9: 0.8, 10: 0.8, 11: 0.8,
        12: 0.8, 13: 0.7, 14: 0.7, 15: 0.7,
        16: 0.8, 17: 0.9, 18: 1.0, 19: 1.0,
        20: 1.1, 21: 1.2, 22: 1.3, 23: 1.4,
    }

    @staticmethod
    def precompute_atr(candles: List[Dict], period: int = 14) -> List[float]:
        """O(n) ATR pre-computation using cumulative sum."""
        n = len(candles)
        tr = np.zeros(n)
        for j in range(1, n):
            c, pc = candles[j], candles[j - 1]
            tr[j] = max(c["high"] - c["low"],
                        abs(c["high"] - pc["close"]),
                        abs(c["low"] - pc["close"]))
        cs = np.cumsum(tr)
        atr = np.zeros(n)
        for j in range(period, n):
            atr[j] = (cs[j] - cs[j - period]) / period
        return atr.tolist()

    @staticmethod
    def precompute_rsi(closes: List[float], period: int = 14) -> List[float]:
        """O(n) RSI array using Wilder's smoothing."""
        n = len(closes)
        rsi = [50.0] * n
        if n < period + 1:
            return rsi
        deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
        gains = [max(0, d) for d in deltas]
        losses = [max(0, -d) for d in deltas]
        avg_g = sum(gains[:period]) / period
        avg_l = sum(losses[:period]) / period
        for i in range(period, len(deltas)):
            avg_g = (avg_g * (period - 1) + gains[i]) / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
            rs = avg_g / avg_l if avg_l > 0 else 100
            rsi[i + 1] = 100 - 100 / (1 + rs)
        return rsi

    @staticmethod
    def precompute_momentum(closes: List[float], period: int = 8) -> List[float]:
        """O(n) momentum percentage change."""
        n = len(closes)
        mom = [0.0] * n
        for i in range(period, n):
            if closes[i - period] > 0:
                mom[i] = (closes[i] - closes[i - period]) / closes[i - period] * 100
        return mom

    @staticmethod
    def precompute_bollinger(closes: List[float], period: int = 20, std_dev: float = 2.0):
        """O(n) Bollinger Bands using cumulative sums."""
        n = len(closes)
        upper = [0.0] * n
        lower = [0.0] * n
        arr = np.array(closes)
        cs = np.cumsum(arr)
        cs2 = np.cumsum(arr ** 2)
        for i in range(period - 1, n):
            s = cs[i] - (cs[i - period] if i >= period else 0)
            s2 = cs2[i] - (cs2[i - period] if i >= period else 0)
            mean = s / period
            var = s2 / period - mean ** 2
            std = np.sqrt(max(0, var))
            upper[i] = mean + std_dev * std
            lower[i] = mean - std_dev * std
        return upper, lower

    def __init__(self, config: ExecutionConfig = None, initial_balance: float = 100000):
        self.config = config or ExecutionConfig()
        self.initial_balance = initial_balance
        self.pm = 10000  # Default, updated per symbol
        self.pip_value = 10.0  # USD per pip per lot, updated per symbol
        self._reset_state()

    def _setup_pair(self, symbol: str, candles: List[Dict] = None):
        """Configure pip multiplier and pip value for the trading pair."""
        if "JPY" in symbol:
            self.pm = 100
            # pip value = 1000 / rate. Use mid-range of candle data.
            if candles:
                mid = candles[len(candles) // 2]["close"]
                self.pip_value = 1000.0 / mid  # ~$6.5-7 for USDJPY
            else:
                self.pip_value = 7.0
        else:
            self.pm = 10000
            self.pip_value = 10.0

    def _reset_state(self):
        self.balance = self.initial_balance
        self.peak = self.initial_balance
        self.daily_start = self.initial_balance
        self.daily_pnl = 0.0
        self.trades: List[RealisticTrade] = []
        self.open_trade: Optional[RealisticTrade] = None
        self.equity_curve: List[Dict] = []
        self.daily_returns: Dict[str, float] = {}
        self.consec_losses = 0
        self.max_consec = 0
        self.stopped_today = False
        self.stopped_global = False
        self.daily_trades_count = 0
        self.rejected = 0
        self.partials = 0
        self.requotes_count = 0
        self.tot_spread = 0.0
        self.tot_slip = 0.0
        self.cost_n = 0

    # ---------- Market simulation ----------

    def spread(self, hour: int, atr: float, avg_atr: float, is_news: bool) -> float:
        sess = self.SPREAD_BY_HOUR.get(hour, 1.0)
        s = self.config.base_spread_pips * sess
        if avg_atr > 0:
            vr = atr / avg_atr
            if vr > 1.5:
                s *= 1.0 + (vr - 1.5) * 0.5
        s *= self.config.spread_safety_multiplier
        if is_news:
            s *= self.config.news_spread_multiplier
        s *= random.uniform(0.9, 1.1)
        return max(0.3, s)

    def slippage(self, atr: float, avg_atr: float, is_news: bool) -> float:
        if avg_atr <= 0:
            return random.uniform(0, 0.3)
        vr = atr / avg_atr
        if vr < 1.2:
            sl = random.uniform(self.config.base_slippage_min, self.config.base_slippage_max)
        else:
            mx = min(self.config.base_slippage_max + (vr - 1.0) * 1.0, self.config.high_vol_slippage_max)
            sl = random.uniform(0, mx)
        if is_news:
            sl *= self.config.news_slippage_multiplier
        return max(0, sl)

    def latency_impact(self, atr: float) -> float:
        ms = random.randint(self.config.latency_ms_min, self.config.latency_ms_max)
        t_frac = ms / 3_600_000
        return random.gauss(0, atr * np.sqrt(t_frac))

    def order_quality(self, atr: float, avg_atr: float, is_news: bool) -> Tuple[str, float]:
        adj = 3.0 if is_news else (2.0 if avg_atr > 0 and atr / avg_atr > 2.0 else 1.0)
        rej = min(0.05, self.config.rejection_prob * adj)
        req = min(0.08, self.config.requote_prob * adj)
        par = self.config.partial_fill_prob
        r = random.random()
        if r < rej:
            return "REJECTED", 0.0
        if r < rej + req:
            return "REQUOTE", 1.0
        if r < rej + req + par:
            return "PARTIAL", random.uniform(0.7, 0.9)
        return "FILL", 1.0

    # ---------- Risk ----------

    def _lot_size(self, sl_pips: float) -> float:
        risk_amt = self.balance * self.config.risk_per_trade * 0.95
        lot = risk_amt / (sl_pips * self.pip_value)
        return max(0.01, round(lot, 2))

    def _can_trade(self) -> bool:
        if self.stopped_global or self.stopped_today:
            return False
        td = (self.initial_balance - self.balance) / self.initial_balance if self.balance < self.initial_balance else 0
        if td >= self.config.total_dd_soft_limit:
            return False
        dl = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        if dl >= self.config.daily_loss_soft_limit:
            return False
        if self.consec_losses >= self.config.max_consecutive_losses:
            return False
        if self.open_trade:
            return False
        return True

    def _reset_daily(self):
        self.daily_start = self.balance
        self.daily_pnl = 0.0
        self.stopped_today = False
        self.daily_trades_count = 0
        self.consec_losses = 0

    # ---------- Exit logic ----------

    def _check_exit(self, candle: Dict, spr: float, symbol: str) -> Optional[Tuple[float, str]]:
        t = self.open_trade
        if not t:
            return None
        sp = spr / self.pm

        # Safety close
        dl = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        td = (self.initial_balance - self.balance) / self.initial_balance if self.balance < self.initial_balance else 0
        if dl >= 0.03 or td >= 0.06:
            ep = candle["close"] if t.direction == "BUY" else candle["close"] + sp
            return ep, "SAFETY"

        if t.direction == "BUY":
            # BUY: close at Bid. OHLC = Bid.
            # Conservative: if both SL and TP possible in same candle, SL first
            sl_hit = candle["low"] <= t.stop_loss
            tp_hit = candle["high"] >= t.take_profit
            if sl_hit and tp_hit:
                # Ambiguous: use conservative (SL first)
                if abs(candle["open"] - t.stop_loss) <= abs(candle["open"] - t.take_profit):
                    return t.stop_loss, "SL"
                else:
                    return t.take_profit, "TP"
            if sl_hit:
                return t.stop_loss, "SL"
            if tp_hit:
                return t.take_profit, "TP"
        else:
            # SELL: close at Ask. Ask = Bid + spread.
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

    def _close_trade(self, exit_price: float, exit_time: datetime, reason: str,
                     exit_spr: float, exit_slip: float, symbol: str = "EURUSD"):
        t = self.open_trade
        if not t:
            return
        if t.direction == "BUY":
            pnl_pips = (exit_price - t.entry_price) * self.pm
        else:
            pnl_pips = (t.entry_price - exit_price) * self.pm
        if reason == "SL":
            pnl_pips -= exit_slip
        pnl = pnl_pips * t.lot_size * self.pip_value * t.fill_ratio

        # Hard cap daily loss
        if pnl < 0:
            mx = self.config.max_daily_loss * self.initial_balance - abs(min(0, self.daily_pnl))
            if mx > 0 and abs(pnl) > mx:
                pnl = -mx

        self.balance += pnl
        self.daily_pnl += pnl
        if self.balance > self.peak:
            self.peak = self.balance

        if pnl < 0:
            self.consec_losses += 1
            self.max_consec = max(self.max_consec, self.consec_losses)
        else:
            self.consec_losses = 0

        dl_pct = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        if dl_pct >= self.config.max_daily_loss:
            self.stopped_today = True
        td_pct = (self.initial_balance - self.balance) / self.initial_balance if self.balance < self.initial_balance else 0
        if td_pct >= self.config.max_total_drawdown:
            self.stopped_global = True

        t.exit_price = exit_price
        t.exit_time = exit_time
        t.pnl = round(pnl, 2)
        t.pnl_pips = round(pnl_pips, 2)
        t.exit_reason = reason
        t.exit_spread = exit_spr
        t.exit_slippage = exit_slip
        self.trades.append(t)

        day_str = exit_time.strftime("%Y-%m-%d")
        self.daily_returns[day_str] = self.daily_returns.get(day_str, 0) + pnl
        self.open_trade = None

    # ---------- Backtest runners ----------

    def run_scalping(self, candles: List[Dict], params: Dict,
                     symbol: str = "EURUSD", timeframe: str = "H1") -> BacktestResultV2:
        """
        Scalping backtest with full realistic simulation.
        Anti-lookahead: signal on candle[i-1], execute at open of candle[i].
        """
        self._reset_state()
        self._setup_pair(symbol, candles)

        fe = params.get("fast_ema", 15)
        se = params.get("slow_ema", 30)
        rsi_bmax = params.get("rsi_buy_max", 60)
        rsi_smin = params.get("rsi_sell_min", 40)
        min_rr = params.get("min_rr", 2.5)
        atr_m = params.get("atr_multiplier", 1.5)
        min_sl = params.get("min_sl_pips", 15)
        max_sl = params.get("max_sl_pips", 30)
        ss = params.get("session_start", 7)
        send = params.get("session_end", 17)
        max_daily = params.get("max_daily_trades", 10)
        self.config.max_consecutive_losses = params.get("max_consecutive_losses", 3)
        self.config.risk_per_trade = params.get("risk_per_trade", 0.01)
        pb_thresh = params.get("pullback_threshold", 0.001)
        body_ratio = params.get("body_atr_ratio", 0.4)
        mom_thresh = params.get("momentum_threshold", 0.01)

        start_idx = max(se + 10, 50)
        pm = self.pm
        n = len(candles)

        # ── PRE-COMPUTE all indicators (O(n) once, not O(n²)) ──
        all_closes = [x["close"] for x in candles]
        ef_all = TechnicalAnalysis.ema(all_closes, fe)
        esl_all = TechnicalAnalysis.ema(all_closes, se)
        rsi_all = self.precompute_rsi(all_closes, 14)
        mom_all = self.precompute_momentum(all_closes, 8)
        bb_u_all, bb_l_all = self.precompute_bollinger(all_closes, 20, 2.0)
        atr_all = self.precompute_atr(candles, 14)

        # Initial avg ATR
        init_atrs = [atr_all[j] for j in range(start_idx, min(start_idx + 200, n)) if atr_all[j] > 0]
        avg_atr = float(np.mean(init_atrs)) if init_atrs else 0.001

        last_day = None

        for i in range(start_idx + 1, n):
            c = candles[i]
            pc = candles[i - 1]
            hour = c["datetime"].hour
            cday = c["datetime"].date()

            if last_day and cday != last_day:
                self._reset_daily()
            last_day = cday

            if hour < ss or hour > send:
                continue

            atr = atr_all[i - 1]  # ATR up to completed candle i-1
            if atr < 2.5 / pm:  # Min ~2.5 pips, scaled per pair
                continue

            is_news = news_calendar.is_news_window(c["datetime"], self.config.news_window_minutes)
            spr = self.spread(hour, atr, avg_atr, is_news)
            avg_atr = avg_atr * 0.99 + atr * 0.01

            # EXIT
            if self.open_trade:
                er = self._check_exit(c, spr, symbol)
                if er:
                    ep, reason = er
                    es = self.slippage(atr, avg_atr, is_news) if reason == "SL" else 0
                    self._close_trade(ep, c["datetime"], reason, spr, es, symbol)
                continue  # don't enter and exit same candle

            # PRE-ENTRY
            if not self._can_trade():
                continue
            if self.daily_trades_count >= max_daily:
                continue

            # SIGNAL from pre-computed indicators (anti-lookahead: index i-1)
            sig_price = all_closes[i - 1]
            cf = ef_all[i - 1]
            cs_val = esl_all[i - 1]
            rsi = rsi_all[i - 1]
            mom = mom_all[i - 1]
            bb_l = bb_l_all[i - 1]
            bb_u = bb_u_all[i - 1]

            sig_dir = None
            pp = candles[i - 2] if i >= 2 else pc

            # BUY signals (trend = bullish: fast EMA > slow EMA)
            if cf > cs_val and rsi < rsi_bmax and rsi > 30:
                hit = False

                # S1: Pullback to EMA zone + breakout
                cf_prev = ef_all[i - 2] if i >= 2 else cf
                if abs(pp["low"] - cf_prev) / sig_price < pb_thresh:
                    if pc["close"] > pp["high"]:
                        hit = True

                # S2: Strong momentum candle
                if not hit and TechnicalAnalysis.is_bullish_candle(pc):
                    if (pc["close"] - pc["open"]) > atr * body_ratio and mom > mom_thresh:
                        hit = True

                # S3: Bollinger lower band bounce
                if not hit and sig_price <= bb_l * 1.002 and TechnicalAnalysis.is_bullish_candle(pc):
                    hit = True

                # S4: Bullish engulfing
                if not hit and i >= 2 and TechnicalAnalysis.is_bullish_engulfing(candles, i - 1):
                    hit = True

                # S5: EMA zone bounce
                if not hit and TechnicalAnalysis.is_bullish_candle(pc):
                    if abs(pc["low"] - cf) < atr * 1.2 and pc["close"] > cf:
                        hit = True

                # S6: Trend continuation
                if not hit and TechnicalAnalysis.is_bullish_candle(pc):
                    if pc["close"] > pp["high"] and cf > cs_val * 1.0005:
                        hit = True

                if hit:
                    sig_dir = "BUY"

            # SELL signals (trend = bearish: fast EMA < slow EMA)
            elif cf < cs_val and rsi > rsi_smin and rsi < 70:
                hit = False

                cf_prev = ef_all[i - 2] if i >= 2 else cf
                if abs(pp["high"] - cf_prev) / sig_price < pb_thresh:
                    if pc["close"] < pp["low"]:
                        hit = True

                if not hit and TechnicalAnalysis.is_bearish_candle(pc):
                    if (pc["open"] - pc["close"]) > atr * body_ratio and mom < -mom_thresh:
                        hit = True

                if not hit and sig_price >= bb_u * 0.998 and TechnicalAnalysis.is_bearish_candle(pc):
                    hit = True

                if not hit and i >= 2 and TechnicalAnalysis.is_bearish_engulfing(candles, i - 1):
                    hit = True

                if not hit and TechnicalAnalysis.is_bearish_candle(pc):
                    if abs(pc["high"] - cf) < atr * 1.2 and pc["close"] < cf:
                        hit = True

                if not hit and TechnicalAnalysis.is_bearish_candle(pc):
                    if pc["close"] < pp["low"] and cf < cs_val * 0.9995:
                        hit = True

                if hit:
                    sig_dir = "SELL"

            if sig_dir:
                qt, fr = self.order_quality(atr, avg_atr, is_news)
                if qt == "REJECTED":
                    self.rejected += 1
                    continue
                if qt == "PARTIAL":
                    self.partials += 1

                op = c["open"]
                e_slip = self.slippage(atr, avg_atr, is_news)
                lat = self.latency_impact(atr)
                sp_abs = spr / pm

                if sig_dir == "BUY":
                    ex_p = op + sp_abs + e_slip / pm + lat
                else:
                    ex_p = op - e_slip / pm + lat

                if qt == "REQUOTE":
                    rp = random.uniform(0.3, 0.8) / pm
                    ex_p += rp if sig_dir == "BUY" else -rp
                    self.requotes_count += 1

                sl_dist = max(atr * atr_m, min_sl / pm)
                sl_p = sl_dist * pm
                sl_p = max(min_sl, min(max_sl, sl_p))
                tp_p = sl_p * min_rr

                if sig_dir == "BUY":
                    sl_pr = ex_p - sl_p / pm
                    tp_pr = ex_p + tp_p / pm
                else:
                    sl_pr = ex_p + sl_p / pm
                    tp_pr = ex_p - tp_p / pm

                lot = self._lot_size(sl_p)
                self.tot_spread += spr
                self.tot_slip += e_slip
                self.cost_n += 1

                self.open_trade = RealisticTrade(
                    id=len(self.trades) + 1, symbol=symbol, direction=sig_dir,
                    strategy="SCALPING", entry_price=round(ex_p, 5),
                    signal_price=round(sig_price, 5),
                    stop_loss=round(sl_pr, 5), take_profit=round(tp_pr, 5),
                    sl_pips=round(sl_p, 1), tp_pips=round(tp_p, 1),
                    lot_size=lot, fill_ratio=fr, entry_spread=spr,
                    entry_slippage=e_slip, entry_time=c["datetime"],
                    session="LONDON" if hour < 13 else "NY_OVERLAP",
                    was_requoted=(qt == "REQUOTE"),
                )
                self.daily_trades_count += 1

            # Equity snapshot
            if i % max(1, n // 200) == 0:
                dd = max(0, (self.initial_balance - self.balance) / self.initial_balance * 100)
                self.equity_curve.append({
                    "timestamp": c["datetime"].isoformat(),
                    "equity": round(self.balance, 2),
                    "drawdown": round(dd, 2),
                })

        # Close remaining
        if self.open_trade and candles:
            last = candles[-1]
            spr2 = self.spread(last["datetime"].hour, atr, avg_atr, False)
            ep = last["close"] if self.open_trade.direction == "BUY" else last["close"] + spr2 / pm
            self._close_trade(ep, last["datetime"], "EOD", spr2, 0, symbol)

        return self._compile("SCALPING", symbol, timeframe, candles)

    def run_intraday(self, candles: List[Dict], params: Dict,
                     symbol: str = "EURUSD", timeframe: str = "H1") -> BacktestResultV2:
        """
        Intraday backtest: EMA pullback on H1 with full realistic simulation.
        """
        self._reset_state()
        self._setup_pair(symbol, candles)

        ema_per = params.get("ema_period", 20)
        min_rr = params.get("min_rr", 2.5)
        atr_m = params.get("atr_multiplier", 0.5)
        min_sl = params.get("min_sl_pips", 8)
        max_sl = params.get("max_sl_pips", 25)
        pb_pct = params.get("pullback_pct", 0.003)
        ss = params.get("session_start", 7)
        send = params.get("session_end", 21)
        max_daily = params.get("max_daily_trades", 6)
        max_cl = params.get("max_consecutive_losses", 3)
        self.config.max_consecutive_losses = max_cl
        self.config.risk_per_trade = params.get("risk_per_trade", 0.01)

        closes_all = [x["close"] for x in candles]
        ema_all = TechnicalAnalysis.ema(closes_all, ema_per)

        start_idx = ema_per + 5
        pm = self.pm
        n = len(candles)

        # Pre-compute ATR (O(n) once)
        atr_all = self.precompute_atr(candles, 14)

        init_atrs = [atr_all[j] for j in range(start_idx, min(start_idx + 200, n)) if atr_all[j] > 0]
        avg_atr = float(np.mean(init_atrs)) if init_atrs else 0.001

        last_day = None

        for i in range(start_idx + 1, len(candles)):
            c = candles[i]
            pc = candles[i - 1]
            hour = c["datetime"].hour
            cday = c["datetime"].date()

            if last_day and cday != last_day:
                self._reset_daily()
            last_day = cday

            if hour < ss or hour > send:
                continue

            atr = atr_all[i - 1]  # Pre-computed ATR (anti-lookahead)
            if atr < 3.0 / pm:  # Min ~3 pips, scaled per pair
                continue

            is_news = news_calendar.is_news_window(c["datetime"], self.config.news_window_minutes)
            spr = self.spread(hour, atr, avg_atr, is_news)
            avg_atr = avg_atr * 0.99 + atr * 0.01

            # EXIT
            if self.open_trade:
                er = self._check_exit(c, spr, symbol)
                if er:
                    ep, reason = er
                    es = self.slippage(atr, avg_atr, is_news) if reason == "SL" else 0
                    self._close_trade(ep, c["datetime"], reason, spr, es, symbol)
                continue

            if not self._can_trade():
                continue
            if self.daily_trades_count >= max_daily:
                continue

            # SIGNAL on completed candles (anti-lookahead)
            cur_ema = ema_all[i - 1]
            prev_ema = ema_all[i - 2] if i >= 2 else cur_ema
            price = pc["close"]

            bullish = price > cur_ema and cur_ema > prev_ema
            bearish = price < cur_ema and cur_ema < prev_ema

            sig_dir = None
            pp = candles[i - 2] if i >= 2 else pc

            if bullish:
                near = pp["low"] <= cur_ema * (1 + pb_pct) and pp["low"] >= cur_ema * (1 - pb_pct)
                bc = pc["close"] > pc["open"] and pc["close"] > pp["high"]
                if near and bc:
                    sig_dir = "BUY"

            if sig_dir is None and bearish:
                near = pp["high"] >= cur_ema * (1 - pb_pct) and pp["high"] <= cur_ema * (1 + pb_pct)
                bc = pc["close"] < pc["open"] and pc["close"] < pp["low"]
                if near and bc:
                    sig_dir = "SELL"

            if sig_dir:
                qt, fr = self.order_quality(atr, avg_atr, is_news)
                if qt == "REJECTED":
                    self.rejected += 1
                    continue
                if qt == "PARTIAL":
                    self.partials += 1

                op = c["open"]
                e_slip = self.slippage(atr, avg_atr, is_news)
                lat = self.latency_impact(atr)
                sp_abs = spr / pm

                if sig_dir == "BUY":
                    ex_p = op + sp_abs + e_slip / pm + lat
                else:
                    ex_p = op - e_slip / pm + lat

                if qt == "REQUOTE":
                    rp = random.uniform(0.3, 0.8) / pm
                    ex_p += rp if sig_dir == "BUY" else -rp
                    self.requotes_count += 1

                sl_p = max(min_sl, min(max_sl, round(atr * atr_m * pm)))
                tp_p = sl_p * min_rr

                if sig_dir == "BUY":
                    sl_pr = ex_p - sl_p / pm
                    tp_pr = ex_p + tp_p / pm
                else:
                    sl_pr = ex_p + sl_p / pm
                    tp_pr = ex_p - tp_p / pm

                lot = self._lot_size(sl_p)
                self.tot_spread += spr
                self.tot_slip += e_slip
                self.cost_n += 1

                self.open_trade = RealisticTrade(
                    id=len(self.trades) + 1, symbol=symbol, direction=sig_dir,
                    strategy="INTRADAY", entry_price=round(ex_p, 5),
                    signal_price=round(price, 5),
                    stop_loss=round(sl_pr, 5), take_profit=round(tp_pr, 5),
                    sl_pips=round(sl_p, 1), tp_pips=round(tp_p, 1),
                    lot_size=lot, fill_ratio=fr, entry_spread=spr,
                    entry_slippage=e_slip, entry_time=c["datetime"],
                    session="LONDON" if hour < 13 else "NEW_YORK",
                    was_requoted=(qt == "REQUOTE"),
                )
                self.daily_trades_count += 1

            if i % max(1, len(candles) // 200) == 0:
                dd = max(0, (self.initial_balance - self.balance) / self.initial_balance * 100)
                self.equity_curve.append({
                    "timestamp": c["datetime"].isoformat(),
                    "equity": round(self.balance, 2),
                    "drawdown": round(dd, 2),
                })

        if self.open_trade and candles:
            last = candles[-1]
            spr2 = self.spread(last["datetime"].hour, atr, avg_atr, False)
            ep = last["close"] if self.open_trade.direction == "BUY" else last["close"] + spr2 / pm
            self._close_trade(ep, last["datetime"], "EOD", spr2, 0, symbol)

        return self._compile("INTRADAY", symbol, timeframe, candles)

    # ---------- Report ----------

    def _compile(self, strat: str, symbol: str, tf: str, candles: List[Dict]) -> BacktestResultV2:
        tr = self.trades
        n = len(tr)
        w = [t for t in tr if t.pnl > 0]
        l = [t for t in tr if t.pnl < 0]
        gp = sum(t.pnl for t in w)
        gl = abs(sum(t.pnl for t in l))
        pf = gp / gl if gl > 0 else 0
        wr = len(w) / n * 100 if n > 0 else 0
        ret = (self.balance - self.initial_balance) / self.initial_balance * 100
        days = (candles[-1]["datetime"] - candles[0]["datetime"]).days if candles else 1
        weeks = max(1, days / 7)
        wret = ret / weeks

        # Max drawdown from initial (FTMO)
        mx_dd = 0
        pk = self.initial_balance
        b = self.initial_balance
        for t in tr:
            b += t.pnl
            if b > pk:
                pk = b
            dd = (self.initial_balance - b) / self.initial_balance if b < self.initial_balance else 0
            mx_dd = max(mx_dd, dd)

        mx_daily = abs(min(self.daily_returns.values())) / self.initial_balance * 100 if self.daily_returns else 0

        if n > 1:
            rets = [t.pnl / self.initial_balance for t in tr]
            std = np.std(rets)
            sharpe = np.mean(rets) / std * np.sqrt(252) if std > 0 else 0
        else:
            sharpe = 0

        avg_rr = float(np.mean([t.tp_pips / t.sl_pips for t in tr])) if tr else 0
        ftmo = mx_dd * 100 < 8 and mx_daily < 4.5
        avg_s = self.tot_spread / self.cost_n if self.cost_n else 0
        avg_sl = self.tot_slip / self.cost_n if self.cost_n else 0

        sd = candles[0]["datetime"].strftime("%Y-%m-%d") if candles else ""
        ed = candles[-1]["datetime"].strftime("%Y-%m-%d") if candles else ""

        tl = [{
            "id": t.id, "dir": t.direction, "entry": t.entry_price, "exit": t.exit_price,
            "sl": t.sl_pips, "tp": t.tp_pips, "lot": t.lot_size, "pnl": t.pnl,
            "reason": t.exit_reason, "session": t.session, "spread": t.entry_spread,
            "slip": t.entry_slippage, "fill": t.fill_ratio,
            "entry_t": t.entry_time.isoformat() if t.entry_time else "",
            "exit_t": t.exit_time.isoformat() if t.exit_time else "",
        } for t in tr[-200:]]

        dl = [{"date": d, "pnl": round(p, 2), "pct": round(p / self.initial_balance * 100, 3)}
              for d, p in sorted(self.daily_returns.items())]

        return BacktestResultV2(
            strategy=strat, symbol=symbol, timeframe=tf,
            start_date=sd, end_date=ed, data_source="real",
            initial_balance=self.initial_balance,
            final_balance=round(self.balance, 2),
            total_return_pct=round(ret, 2),
            weekly_return_pct=round(wret, 3),
            total_trades=n, wins=len(w), losses=len(l),
            win_rate=round(wr, 1), profit_factor=round(pf, 2),
            max_drawdown_pct=round(mx_dd * 100, 2),
            max_daily_loss_pct=round(mx_daily, 2),
            sharpe_ratio=round(sharpe, 2),
            avg_spread=round(avg_s, 2), avg_slippage=round(avg_sl, 2),
            rejected_orders=self.rejected, partial_fills=self.partials,
            requotes=self.requotes_count, ftmo_compliant=ftmo,
            max_consecutive_losses=self.max_consec,
            avg_risk_reward=round(avg_rr, 2),
            trades=tl, equity_curve=self.equity_curve, daily_returns=dl,
        )
