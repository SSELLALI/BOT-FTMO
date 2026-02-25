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
        days: int = 180
    ) -> BacktestReport:
        """
        Run complete backtest with multi-timeframe data
        Optimized to use M15 instead of M5 for faster execution
        """
        self.reset()
        
        # Generate data - round to hour boundary for alignment
        end_date = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start_date = end_date - timedelta(days=days)
        start_date = start_date.replace(minute=0, second=0, microsecond=0)
        
        logger.info(f"Generating multi-timeframe data for {symbol}...")
        
        # Skip M5 for performance - use M15 for both strategies
        m15_candles = MultiTimeframeDataGenerator.generate_m15_data(symbol, start_date, end_date)
        h1_candles = MultiTimeframeDataGenerator.generate_h1_data(symbol, start_date, end_date)
        
        logger.info(f"Data generated: M15={len(m15_candles)}, H1={len(h1_candles)}")
        
        # Create time index mapping for H1 candles
        h1_by_time = {}
        for i, c in enumerate(h1_candles):
            # Map to the hour (rounded down)
            t = c["datetime"]
            key = t.replace(minute=0, second=0, microsecond=0)
            h1_by_time[key] = i
        
        # Track current day for daily reset
        current_day = None
        
        # Main backtest loop using M15 candles
        for m15_idx, m15_candle in enumerate(m15_candles):
            if m15_idx < 50:  # Need enough data for indicators
                continue
            
            candle_time = m15_candle["datetime"]
            candle_day = candle_time.strftime("%Y-%m-%d")
            
            # Daily reset
            if candle_day != current_day:
                if current_day is not None:
                    # Check if trading was stopped today
                    if self.risk_manager.scalping_state.is_stopped_today or \
                       self.risk_manager.intraday_state.is_stopped_today:
                        self.days_stopped += 1
                
                self.risk_manager.reset_daily()
                current_day = candle_day
            
            # Check open trades for exit
            self._check_exits(m15_candle)
            
            # Find corresponding H1 candle
            h1_time = candle_time.replace(minute=0, second=0, microsecond=0)
            h1_idx = h1_by_time.get(h1_time, -1)
            
            # === SCALPING STRATEGY (using M15 data) ===
            if strategy in ["SCALPING", "BOTH"]:
                if not self.risk_manager.scalping_state.is_stopped_today and \
                   not self.risk_manager.scalping_state.is_stopped_global:
                    
                    signal = self.scalping.analyze(m15_candles, m15_idx, symbol)
                    
                    if signal:
                        can_trade, reason = self.risk_manager.can_open_trade(
                            signal, self.risk_manager.scalping_state
                        )
                        
                        if can_trade:
                            self._open_trade(signal, m15_candle)
            
            # === INTRADAY STRATEGY (H1 + M15) ===
            if strategy in ["INTRADAY", "BOTH"]:
                if h1_idx >= 200:
                    if not self.risk_manager.intraday_state.is_stopped_today and \
                       not self.risk_manager.intraday_state.is_stopped_global:
                        
                        signal = self.intraday.analyze(
                            h1_candles, m15_candles,
                            h1_idx, m15_idx, symbol
                        )
                        
                        if signal:
                            can_trade, reason = self.risk_manager.can_open_trade(
                                signal, self.risk_manager.intraday_state
                            )
                            
                            if can_trade:
                                self._open_trade(signal, m15_candle)
            
            # Record equity periodically
            if m15_idx % 50 == 0:
                self.equity_curve.append({
                    "timestamp": candle_time.isoformat(),
                    "equity": round(self.risk_manager.current_balance, 2),
                    "drawdown": round((self.peak_balance - self.risk_manager.current_balance) / self.peak_balance * 100, 2)
                })
        
        # Close any remaining trades
        if m15_candles:
            last_candle = m15_candles[-1]
            for signal, _ in self.open_trades[:]:
                self._close_trade(signal, last_candle["close"], last_candle["datetime"], "EOD")
        
        # Compile report
        return self._compile_report(symbol, strategy, start_date, end_date)
    
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
    
    def _check_exits(self, candle: Dict):
        """Check if any open trades should be closed"""
        for signal, entry_candle in self.open_trades[:]:
            exit_price = None
            exit_reason = None
            
            if signal.direction == "BUY":
                # Check SL first (worst case)
                if candle["low"] <= signal.stop_loss:
                    exit_price = signal.stop_loss
                    exit_reason = "SL"
                elif candle["high"] >= signal.take_profit:
                    exit_price = signal.take_profit
                    exit_reason = "TP"
            else:  # SELL
                if candle["high"] >= signal.stop_loss:
                    exit_price = signal.stop_loss
                    exit_reason = "SL"
                elif candle["low"] <= signal.take_profit:
                    exit_price = signal.take_profit
                    exit_reason = "TP"
            
            if exit_price:
                self._close_trade(signal, exit_price, candle["datetime"], exit_reason)
        
        # SAFETY: Force-close ALL remaining open trades if daily/total limits breached
        daily_loss_pct = abs(self.risk_manager.daily_pnl) / self.risk_manager.daily_starting_balance if self.risk_manager.daily_pnl < 0 and self.risk_manager.daily_starting_balance > 0 else 0
        total_dd = (self.risk_manager.peak_balance - self.risk_manager.current_balance) / self.risk_manager.peak_balance if self.risk_manager.peak_balance > 0 else 0
        
        if daily_loss_pct >= 0.025 or total_dd >= 0.06:  # Pre-emptive at 2.5% daily and 6% total
            for signal, _ in self.open_trades[:]:
                self._close_trade(signal, candle["close"], candle["datetime"], "SAFETY_CLOSE")
    
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
        pnl_percent = pnl / self.risk_manager.current_balance * 100
        
        # Record with risk manager
        self.risk_manager.record_trade_close(signal, pnl)
        
        # Update max drawdown
        if self.risk_manager.current_balance > self.peak_balance:
            self.peak_balance = self.risk_manager.current_balance
        
        current_dd = (self.peak_balance - self.risk_manager.current_balance) / self.peak_balance
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
        end_date: datetime
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
            daily_returns=daily_returns
        )


# Global backtester instance
professional_backtester = ProfessionalBacktester()
