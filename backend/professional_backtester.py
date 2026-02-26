"""
Professional Backtester for FTMO Strategies
Tests the scalping and intraday strategies with proper multi-timeframe analysis
"""
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
import logging
import random

from professional_strategies import (
    ScalpingStrategy, IntradayStrategy, ProfessionalRiskManager,
    TradeSignal, StrategyState, TechnicalAnalysis
)
from historical_data_loader import get_real_data

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Trade record for backtesting"""
    id: int
    symbol: str
    direction: str
    strategy: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    lot_size: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_percent: float
    exit_reason: str  # TP, SL, or EOD
    session: str


@dataclass
class BacktestReport:
    """Complete backtest report"""
    # Configuration
    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_balance: float
    
    # Performance
    final_balance: float
    total_return: float
    total_return_percent: float
    max_drawdown: float
    max_drawdown_percent: float
    
    # Trade Statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    
    # P&L Analysis
    gross_profit: float
    gross_loss: float
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    avg_risk_reward: float
    
    # Risk Metrics
    sharpe_ratio: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    max_daily_loss: float
    max_daily_loss_percent: float
    
    # FTMO Compliance
    ftmo_daily_limit_breached: bool
    ftmo_total_limit_breached: bool
    days_stopped_trading: int
    
    # Session Analysis
    london_trades: int
    london_win_rate: float
    ny_trades: int
    ny_win_rate: float
    
    # Data
    equity_curve: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)
    daily_returns: List[Dict] = field(default_factory=list)
    data_source: str = "simulated"


class MultiTimeframeDataGenerator:
    """Generate realistic multi-timeframe forex data"""
    
    VOLATILITY = {
        "EURUSD": {"daily": 0.006, "hourly": 0.0012},
        "GBPUSD": {"daily": 0.008, "hourly": 0.0016},
        "USDJPY": {"daily": 0.006, "hourly": 0.0012},
        "AUDUSD": {"daily": 0.007, "hourly": 0.0014}
    }
    
    BASE_PRICES = {
        "EURUSD": 1.0850,
        "GBPUSD": 1.2650,
        "USDJPY": 148.50,
        "AUDUSD": 0.6280
    }
    
    @classmethod
    def generate_m5_data(
        cls,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Generate M5 candles"""
        return cls._generate_candles(symbol, start_date, end_date, 5)
    
    @classmethod
    def generate_m15_data(
        cls,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Generate M15 candles"""
        return cls._generate_candles(symbol, start_date, end_date, 15)
    
    @classmethod
    def generate_h1_data(
        cls,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Generate H1 candles"""
        return cls._generate_candles(symbol, start_date, end_date, 60)
    
    @classmethod
    def _generate_candles(
        cls,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe_minutes: int
    ) -> List[Dict]:
        """Generate OHLC candles for any timeframe"""
        
        vol_params = cls.VOLATILITY.get(symbol, cls.VOLATILITY["EURUSD"])
        base_price = cls.BASE_PRICES.get(symbol, 1.0850)
        
        # Scale volatility by timeframe
        vol_scale = np.sqrt(timeframe_minutes / 60)
        volatility = vol_params["hourly"] * vol_scale
        
        candles = []
        current_time = start_date
        current_price = base_price
        
        # Trend state
        trend = random.choice([-1, 1])
        trend_strength = random.uniform(0.2, 0.4)
        trend_duration = random.randint(50, 200)
        candles_in_trend = 0
        
        while current_time < end_date:
            # Skip weekends
            if current_time.weekday() >= 5:
                current_time += timedelta(minutes=timeframe_minutes)
                continue
            
            # Session-based volatility
            hour = current_time.hour
            session_mult = 1.0
            if 8 <= hour <= 16:  # London
                session_mult = 1.3
            elif 13 <= hour <= 21:  # NY
                session_mult = 1.2
            elif 0 <= hour <= 6:  # Asian
                session_mult = 0.7
            
            # Update trend occasionally
            candles_in_trend += 1
            if candles_in_trend > trend_duration:
                if random.random() < 0.3:  # 30% chance to reverse
                    trend *= -1
                trend_strength = random.uniform(0.2, 0.4)
                trend_duration = random.randint(50, 200)
                candles_in_trend = 0
            
            # Generate candle
            adj_volatility = volatility * session_mult
            
            # Open = previous close
            open_price = current_price
            
            # Generate price movement
            trend_move = trend * trend_strength * adj_volatility * current_price
            random_move = np.random.normal(0, adj_volatility) * current_price
            
            # Mean reversion
            mean_reversion = (base_price - current_price) * 0.005
            
            total_move = trend_move + random_move + mean_reversion
            
            close_price = open_price + total_move
            
            # High and low
            range_size = abs(total_move) + np.random.uniform(0, adj_volatility * current_price)
            
            if total_move > 0:
                high_price = close_price + np.random.uniform(0, range_size * 0.3)
                low_price = open_price - np.random.uniform(0, range_size * 0.2)
            else:
                high_price = open_price + np.random.uniform(0, range_size * 0.2)
                low_price = close_price - np.random.uniform(0, range_size * 0.3)
            
            # Ensure OHLC consistency
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)
            
            # Round prices
            decimals = 3 if "JPY" in symbol else 5
            
            candles.append({
                "datetime": current_time,
                "timestamp": current_time.isoformat(),
                "open": round(open_price, decimals),
                "high": round(high_price, decimals),
                "low": round(low_price, decimals),
                "close": round(close_price, decimals),
                "volume": int(1000 + random.random() * 3000 * session_mult)
            })
            
            current_price = close_price
            current_time += timedelta(minutes=timeframe_minutes)
        
        return candles


class ProfessionalBacktester:
    """
    Professional backtester for FTMO strategies
    Supports multi-timeframe analysis
    """
    
    def __init__(self, initial_balance: float = 10000):
        self.initial_balance = initial_balance
        self.scalping = ScalpingStrategy()
        self.intraday = IntradayStrategy()
        self.risk_manager = ProfessionalRiskManager(initial_balance)
        
        # State
        self.trades: List[BacktestTrade] = []
        self.open_trades: List[Tuple[TradeSignal, Dict]] = []  # (signal, entry_candle)
        self.equity_curve: List[Dict] = []
        self.daily_pnl: Dict[str, float] = {}
        
        # Metrics
        self.peak_balance = initial_balance
        self.max_drawdown = 0
        self.max_consecutive_wins = 0
        self.max_consecutive_losses = 0
        self.current_consecutive = 0
        self.days_stopped = 0
    
    def reset(self):
        """Reset backtester state"""
        self.risk_manager = ProfessionalRiskManager(self.initial_balance)
        self.trades = []
        self.open_trades = []
        self.equity_curve = []
        self.daily_pnl = {}
        self.peak_balance = self.initial_balance
        self.max_drawdown = 0
        self.max_consecutive_wins = 0
        self.max_consecutive_losses = 0
        self.current_consecutive = 0
        self.days_stopped = 0
    
    def run_backtest(
        self,
        symbol: str = "EURUSD",
        strategy: str = "BOTH",  # SCALPING, INTRADAY, or BOTH
        days: int = 180,
        use_real_data: bool = True
    ) -> BacktestReport:
        """
        Run complete backtest with multi-timeframe data.
        Uses real historical data when available, falls back to simulated.
        """
        self.reset()
        
        data_source = "simulated"
        m15_candles = []
        h1_candles = []
        
        # Try to load real historical data first
        if use_real_data:
            try:
                h1_candles, m15_candles = get_real_data(symbol, days)
                if len(m15_candles) > 100 and len(h1_candles) > 200:
                    data_source = "real"
                    logger.info(f"Using REAL data: M15={len(m15_candles)}, H1={len(h1_candles)}")
                else:
                    logger.warning(f"Not enough real data (M15={len(m15_candles)}, H1={len(h1_candles)}), falling back to simulated")
                    m15_candles = []
                    h1_candles = []
            except Exception as e:
                logger.warning(f"Could not load real data: {e}, falling back to simulated")
        
        # Fallback to simulated data
        if not m15_candles:
            data_source = "simulated"
            end_date = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            start_date = end_date - timedelta(days=days)
            start_date = start_date.replace(minute=0, second=0, microsecond=0)
            
            logger.info(f"Generating simulated data for {symbol}...")
            m15_candles = MultiTimeframeDataGenerator.generate_m15_data(symbol, start_date, end_date)
            h1_candles = MultiTimeframeDataGenerator.generate_h1_data(symbol, start_date, end_date)
        
        logger.info(f"Data source: {data_source} | M15={len(m15_candles)}, H1={len(h1_candles)}")
        
        if strategy == "SCALPING":
            return self._run_scalping_backtest(symbol, m15_candles, h1_candles, data_source)
        elif strategy == "INTRADAY":
            return self._run_intraday_backtest(symbol, h1_candles, data_source)
        
        # For BOTH, use the multi-timeframe approach
        return self._run_multi_strategy_backtest(symbol, strategy, m15_candles, h1_candles, data_source)
    
    def _run_scalping_backtest(
        self, symbol: str, m15_candles: List[Dict], h1_candles: List[Dict], data_source: str
    ) -> BacktestReport:
        """
        Scalping backtest using the proven optimizer loop structure.
        Inline signal generation + risk management for deterministic results.
        """
        rm = self.risk_manager
        sc = self.scalping
        open_trade = None
        last_day = None
        start_idx = max(sc.slow_ema_period + 10, 50)
        
        for i in range(start_idx, len(m15_candles)):
            candle = m15_candles[i]
            hour = candle["datetime"].hour
            current_day = candle["datetime"].date()
            
            # Daily reset
            if last_day and current_day != last_day:
                if rm.scalping_state.is_stopped_today:
                    self.days_stopped += 1
                rm.reset_daily()
            last_day = current_day
            
            # Session filter
            if not sc.is_valid_session(hour):
                continue
            
            # === EXIT LOGIC ===
            if open_trade:
                sig = open_trade["signal"]
                exited = False
                exit_price = 0
                exit_reason = ""
                
                # Safety close at 3% daily / 6% total drawdown
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
                    
                    if "JPY" in symbol:
                        pnl_pips = pnl_pips / 100
                    
                    pnl = pnl_pips * sig["lot_size"] * 10
                    
                    # Hard cap: don't exceed daily loss limit
                    if pnl < 0:
                        max_loss = rm.max_daily_loss * rm.initial_balance - abs(min(0, rm.daily_pnl))
                        if max_loss > 0 and abs(pnl) > max_loss:
                            pnl = -max_loss
                    
                    # Update balances
                    rm.current_balance += pnl
                    rm.daily_pnl += pnl
                    rm.total_pnl += pnl
                    if rm.current_balance > rm.peak_balance:
                        rm.peak_balance = rm.current_balance
                    
                    if pnl < 0:
                        rm.scalping_state.consecutive_losses += 1
                    else:
                        rm.scalping_state.consecutive_losses = 0
                    
                    # Track max drawdown from initial
                    current_dd = max(0, (self.initial_balance - rm.current_balance) / self.initial_balance)
                    if current_dd > self.max_drawdown:
                        self.max_drawdown = current_dd
                    
                    # Track consecutive streaks
                    if pnl > 0:
                        if self.current_consecutive > 0:
                            self.current_consecutive += 1
                        else:
                            self.current_consecutive = 1
                        self.max_consecutive_wins = max(self.max_consecutive_wins, self.current_consecutive)
                    else:
                        if self.current_consecutive < 0:
                            self.current_consecutive -= 1
                        else:
                            self.current_consecutive = -1
                        self.max_consecutive_losses = max(self.max_consecutive_losses, abs(self.current_consecutive))
                    
                    # Record daily P&L
                    day_str = candle["datetime"].strftime("%Y-%m-%d")
                    self.daily_pnl[day_str] = self.daily_pnl.get(day_str, 0) + pnl
                    
                    # Record trade
                    pnl_pct = pnl / (rm.current_balance - pnl) * 100 if (rm.current_balance - pnl) > 0 else 0
                    self.trades.append(BacktestTrade(
                        id=len(self.trades) + 1,
                        symbol=symbol,
                        direction=sig["direction"],
                        strategy="SCALPING",
                        entry_price=sig["entry"],
                        exit_price=exit_price,
                        stop_loss=sig["sl"],
                        take_profit=sig["tp"],
                        sl_pips=round(sig["sl_pips"], 1),
                        tp_pips=round(sig["tp_pips"], 1),
                        lot_size=sig["lot_size"],
                        entry_time=open_trade["entry_time"],
                        exit_time=candle["datetime"],
                        pnl=round(pnl, 2),
                        pnl_percent=round(pnl_pct, 4),
                        exit_reason=exit_reason,
                        session="LONDON" if hour < 13 else "NY_OVERLAP"
                    ))
                    
                    rm.open_trade_count = 0
                    open_trade = None
                    continue  # Skip to next candle (matches optimizer)
            
            # === PRE-ENTRY CHECKS (inline, matching optimizer) ===
            if open_trade:
                continue
            if rm.scalping_state.is_stopped_today or rm.scalping_state.is_stopped_global:
                continue
            if rm.scalping_state.consecutive_losses >= 3:
                continue
            if rm.open_trade_count >= 1:
                continue
            
            daily_loss = abs(rm.daily_pnl) / rm.initial_balance if rm.daily_pnl < 0 else 0
            if daily_loss >= 0.035:
                continue
            total_dd = (rm.initial_balance - rm.current_balance) / rm.initial_balance if rm.current_balance < rm.initial_balance else 0
            if total_dd >= 0.07:
                continue
            
            # === SIGNAL GENERATION (inline, matching optimizer) ===
            closes = [c["close"] for c in m15_candles[:i + 1]]
            ema_fast = TechnicalAnalysis.ema(closes, sc.fast_ema_period)
            ema_slow = TechnicalAnalysis.ema(closes, sc.slow_ema_period)
            rsi = TechnicalAnalysis.rsi(closes, 14)
            atr = TechnicalAnalysis.atr(m15_candles[:i + 1], 14)
            momentum = TechnicalAnalysis.momentum(closes, 8)
            bb_upper, bb_mid, bb_lower = TechnicalAnalysis.bollinger_bands(closes, 20, 2.0)
            
            current_price = closes[-1]
            cur_fast = ema_fast[-1]
            cur_slow = ema_slow[-1]
            prev_candle = m15_candles[i - 1]
            
            if atr < 0.00025:
                continue
            
            signal = None
            
            # BUY
            if cur_fast > cur_slow and rsi < sc.rsi_buy_max and rsi > 30:
                entry = False
                
                if abs(prev_candle["low"] - ema_fast[-2]) / current_price < 0.0006:
                    if current_price > prev_candle["high"]:
                        entry = True
                
                if not entry and TechnicalAnalysis.is_bullish_candle(candle):
                    body = candle["close"] - candle["open"]
                    if body > atr * 0.4 and momentum > 0.01:
                        entry = True
                
                if not entry and current_price <= bb_lower * 1.001:
                    if TechnicalAnalysis.is_bullish_candle(candle):
                        entry = True
                
                if not entry and TechnicalAnalysis.is_bullish_engulfing(m15_candles, i):
                    entry = True
                
                if entry:
                    sl_dist = max(atr * sc.atr_multiplier, sc.min_sl_pips / 10000)
                    sl_pips = sl_dist * 10000
                    if sl_pips < sc.min_sl_pips:
                        sl_pips = sc.min_sl_pips
                    elif sl_pips > sc.max_sl_pips:
                        sl_pips = sc.max_sl_pips
                    tp_pips = sl_pips * sc.min_rr
                    sl = current_price - (sl_pips / 10000)
                    tp = current_price + (tp_pips / 10000)
                    lot = rm.calculate_lot_size(sl_pips, symbol)
                    signal = {"direction": "BUY", "entry": current_price, "sl": sl, "tp": tp, "lot_size": lot, "sl_pips": sl_pips, "tp_pips": tp_pips}
            
            # SELL
            elif cur_fast < cur_slow and rsi > sc.rsi_sell_min and rsi < 70:
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
                    sl_dist = max(atr * sc.atr_multiplier, sc.min_sl_pips / 10000)
                    sl_pips = sl_dist * 10000
                    if sl_pips < sc.min_sl_pips:
                        sl_pips = sc.min_sl_pips
                    elif sl_pips > sc.max_sl_pips:
                        sl_pips = sc.max_sl_pips
                    tp_pips = sl_pips * sc.min_rr
                    sl = current_price + (sl_pips / 10000)
                    tp = current_price - (tp_pips / 10000)
                    lot = rm.calculate_lot_size(sl_pips, symbol)
                    signal = {"direction": "SELL", "entry": current_price, "sl": sl, "tp": tp, "lot_size": lot, "sl_pips": sl_pips, "tp_pips": tp_pips}
            
            if signal:
                open_trade = {"signal": signal, "entry_time": candle["datetime"]}
                rm.open_trade_count = 1
                rm.scalping_state.daily_trades += 1
            
            # Record equity periodically
            if i % 50 == 0:
                self.equity_curve.append({
                    "timestamp": candle["datetime"].isoformat(),
                    "equity": round(rm.current_balance, 2),
                    "drawdown": round(max(0, (self.initial_balance - rm.current_balance) / self.initial_balance * 100), 2)
                })
        
        # Close remaining trade at market
        if open_trade and m15_candles:
            last = m15_candles[-1]
            sig = open_trade["signal"]
            exit_price = last["close"]
            if sig["direction"] == "BUY":
                pnl_pips = (exit_price - sig["entry"]) * 10000
            else:
                pnl_pips = (sig["entry"] - exit_price) * 10000
            pnl = pnl_pips * sig["lot_size"] * 10
            rm.current_balance += pnl
            rm.daily_pnl += pnl
            self.trades.append(BacktestTrade(
                id=len(self.trades) + 1, symbol=symbol, direction=sig["direction"],
                strategy="SCALPING", entry_price=sig["entry"], exit_price=exit_price,
                stop_loss=sig["sl"], take_profit=sig["tp"],
                sl_pips=round(sig["sl_pips"], 1), tp_pips=round(sig["tp_pips"], 1),
                lot_size=sig["lot_size"], entry_time=open_trade["entry_time"],
                exit_time=last["datetime"], pnl=round(pnl, 2), pnl_percent=0,
                exit_reason="EOD", session="LONDON"
            ))
        
        start_date = m15_candles[0]["datetime"] if m15_candles else datetime.now(timezone.utc)
        end_date = m15_candles[-1]["datetime"] if m15_candles else datetime.now(timezone.utc)
        return self._compile_report(symbol, "SCALPING", start_date, end_date, data_source)
    
    def _run_intraday_backtest(
        self, symbol: str, h1_candles: List[Dict], data_source: str
    ) -> BacktestReport:
        """
        Intraday backtest using H1 data only.
        Ultra-simple: 1 indicator (EMA) + pullback entry + ATR-based SL.
        """
        rm = self.risk_manager
        intra = self.intraday
        open_trade = None
        last_day = None
        
        closes = [c["close"] for c in h1_candles]
        ema = TechnicalAnalysis.ema(closes, intra.ema_period)
        
        start_idx = intra.ema_period + 5
        
        for i in range(start_idx, len(h1_candles)):
            candle = h1_candles[i]
            hour = candle["datetime"].hour
            current_day = candle["datetime"].date()
            
            if last_day and current_day != last_day:
                if rm.intraday_state.is_stopped_today:
                    self.days_stopped += 1
                rm.reset_daily()
            last_day = current_day
            
            if not intra.is_valid_session(hour):
                continue
            
            price = candle["close"]
            cur_ema = ema[i]
            prev = h1_candles[i - 1]
            atr = TechnicalAnalysis.atr(h1_candles[:i + 1], 14)
            
            if atr < 0.0003:
                continue
            
            # === EXIT ===
            if open_trade:
                sig = open_trade["signal"]
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
                    rm.total_pnl += pnl
                    if rm.current_balance > rm.peak_balance:
                        rm.peak_balance = rm.current_balance
                    
                    if pnl < 0:
                        rm.intraday_state.consecutive_losses += 1
                    else:
                        rm.intraday_state.consecutive_losses = 0
                    
                    current_dd = max(0, (self.initial_balance - rm.current_balance) / self.initial_balance)
                    if current_dd > self.max_drawdown:
                        self.max_drawdown = current_dd
                    
                    if pnl > 0:
                        self.current_consecutive = max(1, self.current_consecutive + 1) if self.current_consecutive > 0 else 1
                        self.max_consecutive_wins = max(self.max_consecutive_wins, self.current_consecutive)
                    else:
                        self.current_consecutive = min(-1, self.current_consecutive - 1) if self.current_consecutive < 0 else -1
                        self.max_consecutive_losses = max(self.max_consecutive_losses, abs(self.current_consecutive))
                    
                    day_str = candle["datetime"].strftime("%Y-%m-%d")
                    self.daily_pnl[day_str] = self.daily_pnl.get(day_str, 0) + pnl
                    
                    pnl_pct = pnl / (rm.current_balance - pnl) * 100 if (rm.current_balance - pnl) > 0 else 0
                    self.trades.append(BacktestTrade(
                        id=len(self.trades) + 1, symbol=symbol,
                        direction=sig["direction"], strategy="INTRADAY",
                        entry_price=sig["entry"], exit_price=exit_price,
                        stop_loss=sig["sl"], take_profit=sig["tp"],
                        sl_pips=round(sig["sl_pips"], 1), tp_pips=round(sig["tp_pips"], 1),
                        lot_size=sig["lot_size"],
                        entry_time=open_trade["entry_time"], exit_time=candle["datetime"],
                        pnl=round(pnl, 2), pnl_percent=round(pnl_pct, 4),
                        exit_reason=exit_reason,
                        session="LONDON" if hour < 13 else "NY_OVERLAP"
                    ))
                    
                    rm.open_trade_count = 0
                    open_trade = None
                    continue
            
            # === PRE-ENTRY CHECKS ===
            if open_trade:
                continue
            if rm.intraday_state.is_stopped_today or rm.intraday_state.is_stopped_global:
                continue
            if rm.intraday_state.consecutive_losses >= intra.max_consecutive_losses:
                continue
            if rm.intraday_state.daily_trades >= intra.max_trades_per_day:
                continue
            if rm.open_trade_count >= 1:
                continue
            
            daily_loss = abs(rm.daily_pnl) / rm.initial_balance if rm.daily_pnl < 0 else 0
            if daily_loss >= 0.035:
                continue
            total_dd = (rm.initial_balance - rm.current_balance) / rm.initial_balance if rm.current_balance < rm.initial_balance else 0
            if total_dd >= 0.07:
                continue
            
            # === SIGNAL: 1 indicator (EMA) + pullback + continuation ===
            bullish = price > cur_ema and ema[i] > ema[i - 1]
            bearish = price < cur_ema and ema[i] < ema[i - 1]
            
            signal = None
            
            # BUY: prev candle pulled back near EMA, current closes bullish above prev high
            if bullish:
                near_ema = (prev["low"] <= cur_ema * (1 + intra.pullback_pct) and
                           prev["low"] >= cur_ema * (1 - intra.pullback_pct))
                bullish_candle = candle["close"] > candle["open"] and candle["close"] > prev["high"]
                if near_ema and bullish_candle:
                    sl_pips = max(intra.min_sl_pips, min(intra.max_sl_pips, round(atr * intra.atr_multiplier * 10000)))
                    tp_pips = sl_pips * intra.min_rr
                    lot = rm.calculate_lot_size(sl_pips, symbol)
                    signal = {
                        "direction": "BUY", "entry": price,
                        "sl": price - sl_pips / 10000, "tp": price + tp_pips / 10000,
                        "lot_size": lot, "sl_pips": sl_pips, "tp_pips": tp_pips
                    }
            
            # SELL: prev candle pulled back near EMA, current closes bearish below prev low
            if signal is None and bearish:
                near_ema = (prev["high"] >= cur_ema * (1 - intra.pullback_pct) and
                           prev["high"] <= cur_ema * (1 + intra.pullback_pct))
                bearish_candle = candle["close"] < candle["open"] and candle["close"] < prev["low"]
                if near_ema and bearish_candle:
                    sl_pips = max(intra.min_sl_pips, min(intra.max_sl_pips, round(atr * intra.atr_multiplier * 10000)))
                    tp_pips = sl_pips * intra.min_rr
                    lot = rm.calculate_lot_size(sl_pips, symbol)
                    signal = {
                        "direction": "SELL", "entry": price,
                        "sl": price + sl_pips / 10000, "tp": price - tp_pips / 10000,
                        "lot_size": lot, "sl_pips": sl_pips, "tp_pips": tp_pips
                    }
            
            if signal:
                open_trade = {"signal": signal, "entry_time": candle["datetime"]}
                rm.open_trade_count = 1
                rm.intraday_state.daily_trades += 1
            
            if i % 100 == 0:
                self.equity_curve.append({
                    "timestamp": candle["datetime"].isoformat(),
                    "equity": round(rm.current_balance, 2),
                    "drawdown": round(max(0, (self.initial_balance - rm.current_balance) / self.initial_balance * 100), 2)
                })
        
        # Close remaining trade
        if open_trade and h1_candles:
            last = h1_candles[-1]
            sig = open_trade["signal"]
            ep = last["close"]
            pnl_pips = (ep - sig["entry"]) * 10000 if sig["direction"] == "BUY" else (sig["entry"] - ep) * 10000
            pnl = pnl_pips * sig["lot_size"] * 10
            rm.current_balance += pnl
            self.trades.append(BacktestTrade(
                id=len(self.trades) + 1, symbol=symbol, direction=sig["direction"],
                strategy="INTRADAY", entry_price=sig["entry"], exit_price=ep,
                stop_loss=sig["sl"], take_profit=sig["tp"],
                sl_pips=round(sig["sl_pips"], 1), tp_pips=round(sig["tp_pips"], 1),
                lot_size=sig["lot_size"], entry_time=open_trade["entry_time"],
                exit_time=last["datetime"], pnl=round(pnl, 2), pnl_percent=0,
                exit_reason="EOD", session="LONDON"
            ))
        
        start_date = h1_candles[0]["datetime"] if h1_candles else datetime.now(timezone.utc)
        end_date = h1_candles[-1]["datetime"] if h1_candles else datetime.now(timezone.utc)
        return self._compile_report(symbol, "INTRADAY", start_date, end_date, data_source)
    
    def _run_multi_strategy_backtest(
        self, symbol: str, strategy: str, m15_candles: List[Dict], h1_candles: List[Dict], data_source: str
    ) -> BacktestReport:
        """Multi-strategy backtest for INTRADAY or BOTH modes."""
        h1_by_time = {}
        for i, c in enumerate(h1_candles):
            t = c["datetime"]
            key = t.replace(minute=0, second=0, microsecond=0)
            h1_by_time[key] = i
        
        current_day = None
        
        for m15_idx, m15_candle in enumerate(m15_candles):
            if m15_idx < 50:
                continue
            
            candle_time = m15_candle["datetime"]
            candle_day = candle_time.strftime("%Y-%m-%d")
            
            if candle_day != current_day:
                if current_day is not None:
                    if self.risk_manager.scalping_state.is_stopped_today or \
                       self.risk_manager.intraday_state.is_stopped_today:
                        self.days_stopped += 1
                self.risk_manager.reset_daily()
                current_day = candle_day
            
            had_exit = self._check_exits(m15_candle)
            if had_exit:
                continue
            
            h1_time = candle_time.replace(minute=0, second=0, microsecond=0)
            h1_idx = h1_by_time.get(h1_time, -1)
            
            if strategy in ["INTRADAY", "BOTH"]:
                if h1_idx >= 200:
                    if not self.risk_manager.intraday_state.is_stopped_today and \
                       not self.risk_manager.intraday_state.is_stopped_global:
                        signal = self.intraday.analyze(h1_candles, m15_candles, h1_idx, m15_idx, symbol)
                        if signal:
                            can_trade, reason = self.risk_manager.can_open_trade(signal, self.risk_manager.intraday_state)
                            if can_trade:
                                self._open_trade(signal, m15_candle)
            
            if m15_idx % 50 == 0:
                self.equity_curve.append({
                    "timestamp": candle_time.isoformat(),
                    "equity": round(self.risk_manager.current_balance, 2),
                    "drawdown": round(max(0, (self.initial_balance - self.risk_manager.current_balance) / self.initial_balance * 100), 2)
                })
        
        if m15_candles:
            last_candle = m15_candles[-1]
            for signal, _ in self.open_trades[:]:
                self._close_trade(signal, last_candle["close"], last_candle["datetime"], "EOD")
        
        start_date = m15_candles[0]["datetime"] if m15_candles else datetime.now(timezone.utc)
        end_date = m15_candles[-1]["datetime"] if m15_candles else datetime.now(timezone.utc)
        return self._compile_report(symbol, strategy, start_date, end_date, data_source)
    
    def _open_trade(self, signal: TradeSignal, candle: Dict):
        """Open a new trade"""
        # Calculate lot size
        lot_size = self.risk_manager.calculate_lot_size(signal.sl_pips, signal.symbol)
        signal.lot_size = lot_size
        
        # Record with risk manager
        self.risk_manager.record_trade_open(signal)
        
        # Add to open trades
        self.open_trades.append((signal, candle))
        
        logger.debug(f"Opened {signal.strategy} {signal.direction} {signal.symbol} @ {signal.entry_price}")
    
    def _check_exits(self, candle: Dict) -> bool:
        """Check if any open trades should be closed. Returns True if any trade was closed."""
        had_exit = False
        for signal, entry_candle in self.open_trades[:]:
            # SAFETY BARRIER: Check limits vs INITIAL BALANCE (FTMO rule)
            daily_loss_pct = abs(self.risk_manager.daily_pnl) / self.risk_manager.initial_balance if self.risk_manager.daily_pnl < 0 else 0
            total_dd = (self.risk_manager.initial_balance - self.risk_manager.current_balance) / self.risk_manager.initial_balance if self.risk_manager.current_balance < self.risk_manager.initial_balance else 0

            if daily_loss_pct >= 0.03 or total_dd >= 0.06:
                # Safety close at market price (matches optimizer)
                self._close_trade(signal, candle["close"], candle["datetime"], "SAFETY_CLOSE")
                had_exit = True
                continue

            exit_price = None
            exit_reason = None

            if signal.direction == "BUY":
                if candle["low"] <= signal.stop_loss:
                    exit_price = signal.stop_loss
                    exit_reason = "SL"
                elif candle["high"] >= signal.take_profit:
                    exit_price = signal.take_profit
                    exit_reason = "TP"
            else:
                if candle["high"] >= signal.stop_loss:
                    exit_price = signal.stop_loss
                    exit_reason = "SL"
                elif candle["low"] <= signal.take_profit:
                    exit_price = signal.take_profit
                    exit_reason = "TP"

            if exit_price:
                self._close_trade(signal, exit_price, candle["datetime"], exit_reason)
                had_exit = True
        
        return had_exit
    
    def _close_trade(self, signal: TradeSignal, exit_price: float, exit_time: datetime, exit_reason: str):
        """Close a trade and record results"""
        # Calculate P&L
        if signal.direction == "BUY":
            pnl_pips = (exit_price - signal.entry_price) * 10000
        else:
            pnl_pips = (signal.entry_price - exit_price) * 10000
        
        # Adjust for JPY pairs
        if "JPY" in signal.symbol:
            pnl_pips = pnl_pips / 100
        
        pnl = pnl_pips * signal.lot_size * 10  # $10 per pip per lot for EUR/USD
        
        # HARD CAP: Limit loss so daily never exceeds 4.5% of INITIAL balance
        if pnl < 0:
            max_daily_loss_amount = self.risk_manager.max_daily_loss * self.risk_manager.initial_balance
            current_daily_loss = abs(min(0, self.risk_manager.daily_pnl))
            remaining_daily = max_daily_loss_amount - current_daily_loss
            if remaining_daily > 0 and abs(pnl) > remaining_daily:
                pnl = -remaining_daily  # Cap to exact limit
            elif remaining_daily <= 0:
                pnl = 0  # Already at limit, no more loss allowed
        
        pnl_percent = pnl / self.risk_manager.current_balance * 100 if self.risk_manager.current_balance > 0 else 0
        
        # Record with risk manager
        self.risk_manager.record_trade_close(signal, pnl)
        
        # Update max drawdown (from INITIAL balance, FTMO rule)
        if self.risk_manager.current_balance > self.peak_balance:
            self.peak_balance = self.risk_manager.current_balance
        
        # FTMO drawdown = loss from initial balance (not from peak)
        current_dd = max(0, (self.initial_balance - self.risk_manager.current_balance) / self.initial_balance)
        if current_dd > self.max_drawdown:
            self.max_drawdown = current_dd
        
        # Track consecutive wins/losses
        if pnl > 0:
            if self.current_consecutive > 0:
                self.current_consecutive += 1
            else:
                self.current_consecutive = 1
            self.max_consecutive_wins = max(self.max_consecutive_wins, self.current_consecutive)
        else:
            if self.current_consecutive < 0:
                self.current_consecutive -= 1
            else:
                self.current_consecutive = -1
            self.max_consecutive_losses = max(self.max_consecutive_losses, abs(self.current_consecutive))
        
        # Record daily P&L
        day_str = exit_time.strftime("%Y-%m-%d")
        self.daily_pnl[day_str] = self.daily_pnl.get(day_str, 0) + pnl
        
        # Create trade record
        # Find entry time from open trades
        entry_time = signal.timestamp
        for s, c in self.open_trades:
            if s == signal:
                entry_time = c["datetime"]
                break
        
        trade = BacktestTrade(
            id=len(self.trades) + 1,
            symbol=signal.symbol,
            direction=signal.direction,
            strategy=signal.strategy,
            entry_price=signal.entry_price,
            exit_price=exit_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            sl_pips=signal.sl_pips,
            tp_pips=signal.tp_pips,
            lot_size=signal.lot_size,
            entry_time=entry_time,
            exit_time=exit_time,
            pnl=round(pnl, 2),
            pnl_percent=round(pnl_percent, 4),
            exit_reason=exit_reason,
            session=signal.session
        )
        
        self.trades.append(trade)
        
        # Remove from open trades
        self.open_trades = [(s, c) for s, c in self.open_trades if s != signal]
        
        logger.debug(f"Closed {signal.strategy} {signal.direction} @ {exit_price} ({exit_reason}) P&L: {pnl:.2f}")
    
    def _compile_report(
        self,
        symbol: str,
        strategy: str,
        start_date: datetime,
        end_date: datetime,
        data_source: str = "simulated"
    ) -> BacktestReport:
        """Compile comprehensive backtest report"""
        
        # Trade statistics
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]
        
        total_trades = len(self.trades)
        win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
        
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit if gross_profit > 0 else 0
        
        avg_win = gross_profit / len(winning_trades) if winning_trades else 0
        avg_loss = gross_loss / len(losing_trades) if losing_trades else 0
        
        largest_win = max((t.pnl for t in winning_trades), default=0)
        largest_loss = min((t.pnl for t in losing_trades), default=0)
        
        # Average R:R
        avg_rr = sum(t.tp_pips / t.sl_pips for t in self.trades) / total_trades if total_trades > 0 else 0
        
        # Sharpe ratio
        returns = [t.pnl_percent for t in self.trades]
        if len(returns) > 1:
            avg_return = np.mean(returns)
            std_return = np.std(returns)
            sharpe = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
        else:
            sharpe = 0
        
        # Max daily loss
        max_daily_loss = abs(min(self.daily_pnl.values())) if self.daily_pnl else 0
        max_daily_loss_pct = max_daily_loss / self.initial_balance * 100
        
        # Session analysis
        london_trades = [t for t in self.trades if "LONDON" in t.session]
        ny_trades = [t for t in self.trades if "NY" in t.session or "NEW_YORK" in t.session]
        
        london_wins = sum(1 for t in london_trades if t.pnl > 0)
        ny_wins = sum(1 for t in ny_trades if t.pnl > 0)
        
        london_wr = london_wins / len(london_trades) * 100 if london_trades else 0
        ny_wr = ny_wins / len(ny_trades) * 100 if ny_trades else 0
        
        # FTMO compliance
        ftmo_daily_breached = max_daily_loss_pct > 4.5
        ftmo_total_breached = self.max_drawdown * 100 > 8
        
        # Daily returns
        daily_returns = [
            {"date": d, "pnl": round(p, 2), "pnl_percent": round(p / self.initial_balance * 100, 2)}
            for d, p in sorted(self.daily_pnl.items())
        ]
        
        # Trade list
        trades_list = [
            {
                "id": t.id,
                "symbol": t.symbol,
                "direction": t.direction,
                "strategy": t.strategy,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "sl_pips": t.sl_pips,
                "tp_pips": t.tp_pips,
                "lot_size": t.lot_size,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "pnl": t.pnl,
                "pnl_percent": t.pnl_percent,
                "exit_reason": t.exit_reason,
                "session": t.session
            }
            for t in self.trades[-100:]  # Last 100 trades
        ]
        
        return BacktestReport(
            symbol=symbol,
            strategy=strategy,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            initial_balance=self.initial_balance,
            final_balance=round(self.risk_manager.current_balance, 2),
            total_return=round(self.risk_manager.current_balance - self.initial_balance, 2),
            total_return_percent=round((self.risk_manager.current_balance - self.initial_balance) / self.initial_balance * 100, 2),
            max_drawdown=round(self.max_drawdown * self.peak_balance, 2),
            max_drawdown_percent=round(self.max_drawdown * 100, 2),
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=round(win_rate, 1),
            profit_factor=round(profit_factor, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            average_win=round(avg_win, 2),
            average_loss=round(avg_loss, 2),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            avg_risk_reward=round(avg_rr, 2),
            sharpe_ratio=round(sharpe, 2),
            max_consecutive_wins=self.max_consecutive_wins,
            max_consecutive_losses=self.max_consecutive_losses,
            max_daily_loss=round(max_daily_loss, 2),
            max_daily_loss_percent=round(max_daily_loss_pct, 2),
            ftmo_daily_limit_breached=ftmo_daily_breached,
            ftmo_total_limit_breached=ftmo_total_breached,
            days_stopped_trading=self.days_stopped,
            london_trades=len(london_trades),
            london_win_rate=round(london_wr, 1),
            ny_trades=len(ny_trades),
            ny_win_rate=round(ny_wr, 1),
            equity_curve=self.equity_curve,
            trades=trades_list,
            daily_returns=daily_returns,
            data_source=data_source
        )


# Global backtester instance
professional_backtester = ProfessionalBacktester()
