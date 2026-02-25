"""
Backtesting Engine for FTMO Trading Strategies
Tests strategies on historical data with realistic simulation
"""
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import logging
import random

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Represents a trade during backtesting"""
    id: int
    symbol: str
    direction: str  # BUY or SELL
    strategy: str  # SCALPING or INTRADAY
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    lot_size: float
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pnl_percent: float = 0.0
    status: str = "OPEN"  # OPEN, WIN, LOSS, BREAKEVEN
    exit_reason: str = ""  # TP, SL, SIGNAL, EOD


@dataclass
class BacktestResult:
    """Complete backtest results"""
    # General info
    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    
    # Performance metrics
    total_return: float
    total_return_percent: float
    max_drawdown: float
    max_drawdown_percent: float
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    
    # P&L statistics
    gross_profit: float
    gross_loss: float
    profit_factor: float
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    
    # Risk metrics
    sharpe_ratio: float
    sortino_ratio: float
    avg_risk_reward: float
    
    # FTMO compliance
    max_daily_loss: float
    max_daily_loss_percent: float
    ftmo_daily_limit_breached: bool
    ftmo_total_limit_breached: bool
    
    # Time analysis
    avg_trade_duration_hours: float
    best_trading_hour: int
    worst_trading_hour: int
    
    # Equity curve
    equity_curve: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)
    daily_returns: List[Dict] = field(default_factory=list)


class HistoricalDataGenerator:
    """
    Generates realistic historical forex data for backtesting
    Uses statistical properties of real forex markets
    """
    
    # EUR/USD historical characteristics
    EURUSD_PARAMS = {
        "base_price": 1.0850,
        "daily_volatility": 0.0065,  # ~65 pips daily range
        "hourly_volatility": 0.0012,
        "trend_strength": 0.3,
        "mean_reversion": 0.1,
        "spread_pips": 0.8
    }
    
    @classmethod
    def generate_ohlc_data(
        cls,
        symbol: str = "EURUSD",
        start_date: datetime = None,
        end_date: datetime = None,
        timeframe: str = "H1"  # H1, M15, M5, M1, D1
    ) -> List[Dict]:
        """
        Generate realistic OHLC candles for backtesting
        """
        if start_date is None:
            start_date = datetime.now(timezone.utc) - timedelta(days=365)
        if end_date is None:
            end_date = datetime.now(timezone.utc)
        
        params = cls.EURUSD_PARAMS
        
        # Calculate number of candles based on timeframe
        timeframe_minutes = {
            "M1": 1, "M5": 5, "M15": 15, "M30": 30,
            "H1": 60, "H4": 240, "D1": 1440
        }
        
        minutes_per_candle = timeframe_minutes.get(timeframe, 60)
        total_minutes = int((end_date - start_date).total_seconds() / 60)
        num_candles = total_minutes // minutes_per_candle
        
        # Limit to reasonable size
        num_candles = min(num_candles, 50000)
        
        candles = []
        current_price = params["base_price"]
        current_time = start_date
        
        # Generate trend component
        trend_direction = random.choice([-1, 1])
        trend_change_probability = 0.01
        
        for i in range(num_candles):
            # Skip weekends (simplified)
            while current_time.weekday() >= 5:
                current_time += timedelta(minutes=minutes_per_candle)
            
            # Occasionally change trend
            if random.random() < trend_change_probability:
                trend_direction *= -1
            
            # Calculate volatility based on time of day (London/NY sessions more volatile)
            hour = current_time.hour
            session_multiplier = 1.0
            if 8 <= hour <= 16:  # London session
                session_multiplier = 1.3
            elif 13 <= hour <= 21:  # NY overlap and session
                session_multiplier = 1.4
            elif 0 <= hour <= 6:  # Asian session
                session_multiplier = 0.7
            
            # Generate OHLC
            volatility = params["hourly_volatility"] * session_multiplier
            
            # Open is previous close (or current price for first candle)
            open_price = current_price
            
            # Generate random walk for high, low, close
            moves = np.random.normal(0, volatility, 4)
            
            # Add trend bias
            trend_bias = trend_direction * params["trend_strength"] * volatility
            moves += trend_bias
            
            # Mean reversion
            mean_reversion_force = (params["base_price"] - current_price) * params["mean_reversion"]
            moves += mean_reversion_force
            
            # Calculate OHLC
            intrabar_prices = [open_price]
            for move in moves:
                intrabar_prices.append(intrabar_prices[-1] * (1 + move))
            
            high_price = max(intrabar_prices)
            low_price = min(intrabar_prices)
            close_price = intrabar_prices[-1]
            
            # Ensure high >= open, close and low <= open, close
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)
            
            # Volume (simplified)
            volume = int(1000 + random.random() * 4000 * session_multiplier)
            
            candles.append({
                "timestamp": current_time.isoformat(),
                "datetime": current_time,
                "open": round(open_price, 5),
                "high": round(high_price, 5),
                "low": round(low_price, 5),
                "close": round(close_price, 5),
                "volume": volume
            })
            
            # Update for next candle
            current_price = close_price
            current_time += timedelta(minutes=minutes_per_candle)
        
        return candles


class BacktestEngine:
    """
    Main backtesting engine
    Simulates trading strategies on historical data
    """
    
    def __init__(
        self,
        initial_balance: float = 100000,
        max_risk_per_trade: float = 0.01,  # 1%
        max_daily_loss: float = 0.045,  # 4.5%
        max_total_loss: float = 0.10,  # 10%
        min_risk_reward: float = 1.0
    ):
        self.initial_balance = initial_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_total_loss = max_total_loss
        self.min_risk_reward = min_risk_reward
        
        # State
        self.balance = initial_balance
        self.equity = initial_balance
        self.trades: List[BacktestTrade] = []
        self.open_trades: List[BacktestTrade] = []
        self.equity_curve: List[Dict] = []
        self.daily_pnl: Dict[str, float] = {}
        
        # Metrics
        self.peak_equity = initial_balance
        self.max_drawdown = 0
        self.max_drawdown_percent = 0
        
    def reset(self):
        """Reset engine state for new backtest"""
        self.balance = self.initial_balance
        self.equity = self.initial_balance
        self.trades = []
        self.open_trades = []
        self.equity_curve = []
        self.daily_pnl = {}
        self.peak_equity = self.initial_balance
        self.max_drawdown = 0
        self.max_drawdown_percent = 0
    
    def calculate_indicators(self, candles: List[Dict], index: int) -> Dict:
        """Calculate technical indicators at a given candle index"""
        if index < 30:
            return {}
        
        closes = [c["close"] for c in candles[max(0, index-50):index+1]]
        
        # EMA calculations
        def ema(prices, period):
            if len(prices) < period:
                return prices[-1]
            multiplier = 2 / (period + 1)
            ema_val = prices[0]
            for price in prices[1:]:
                ema_val = (price - ema_val) * multiplier + ema_val
            return ema_val
        
        # RSI calculation
        def rsi(prices, period=14):
            if len(prices) < period + 1:
                return 50
            deltas = np.diff(prices[-(period+1):])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains)
            avg_loss = np.mean(losses)
            if avg_loss == 0:
                return 100
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
        
        # MACD calculation
        def macd(prices):
            ema12 = ema(prices, 12)
            ema26 = ema(prices, 26)
            macd_line = ema12 - ema26
            signal = macd_line * 0.9
            return macd_line, signal, macd_line - signal
        
        # Support/Resistance
        recent = closes[-20:]
        support = min(recent)
        resistance = max(recent)
        
        ema8 = ema(closes, 8)
        ema21 = ema(closes, 21)
        rsi_val = rsi(closes)
        macd_line, macd_signal, macd_hist = macd(closes)
        
        return {
            "ema_8": ema8,
            "ema_21": ema21,
            "rsi": rsi_val,
            "macd": macd_line,
            "macd_signal": macd_signal,
            "macd_histogram": macd_hist,
            "support": support,
            "resistance": resistance,
            "close": closes[-1]
        }
    
    def check_scalping_signal(
        self,
        indicators: Dict,
        prev_indicators: Dict
    ) -> Optional[Tuple[str, str]]:
        """
        Check for scalping entry signal - Optimized version
        Returns (direction, reason) or None
        """
        if not indicators or not prev_indicators:
            return None
        
        rsi = indicators.get("rsi", 50)
        ema8 = indicators.get("ema_8", 0)
        ema21 = indicators.get("ema_21", 0)
        prev_ema8 = prev_indicators.get("ema_8", 0)
        prev_ema21 = prev_indicators.get("ema_21", 0)
        close = indicators.get("close", 0)
        
        # More selective entries - only strong signals
        
        # BUY: Strong oversold with reversal confirmation
        if rsi < 30 and close > ema8:
            if ema8 > prev_ema8:  # EMA turning up
                return ("BUY", f"Strong oversold RSI({rsi:.1f}) + reversal")
        
        # SELL: Strong overbought with reversal confirmation
        if rsi > 70 and close < ema8:
            if ema8 < prev_ema8:  # EMA turning down
                return ("SELL", f"Strong overbought RSI({rsi:.1f}) + reversal")
        
        # EMA crossover with trend confirmation
        if prev_ema8 <= prev_ema21 and ema8 > ema21:
            if rsi > 45 and rsi < 65:  # Not overbought
                return ("BUY", f"EMA bullish crossover + RSI({rsi:.1f}) neutral")
        
        if prev_ema8 >= prev_ema21 and ema8 < ema21:
            if rsi < 55 and rsi > 35:  # Not oversold
                return ("SELL", f"EMA bearish crossover + RSI({rsi:.1f}) neutral")
        
        return None
    
    def check_intraday_signal(
        self,
        indicators: Dict,
        prev_indicators: Dict,
        current_price: float
    ) -> Optional[Tuple[str, str]]:
        """
        Check for intraday entry signal - Optimized version
        Returns (direction, reason) or None
        """
        if not indicators or not prev_indicators:
            return None
        
        support = indicators.get("support", 0)
        resistance = indicators.get("resistance", 0)
        macd = indicators.get("macd", 0)
        macd_signal = indicators.get("macd_signal", 0)
        prev_macd = prev_indicators.get("macd", 0)
        prev_macd_signal = prev_indicators.get("macd_signal", 0)
        macd_hist = indicators.get("macd_histogram", 0)
        prev_hist = prev_indicators.get("macd_histogram", 0)
        rsi = indicators.get("rsi", 50)
        
        dist_to_support = current_price - support
        dist_to_resistance = resistance - current_price
        range_size = resistance - support
        
        if range_size <= 0:
            return None
            
        threshold = range_size * 0.15  # 15% of range - tighter
        
        # BUY: At support + MACD bullish + RSI not overbought
        if dist_to_support < threshold and rsi < 60:
            if prev_macd <= prev_macd_signal and macd > macd_signal:
                return ("BUY", f"Support bounce ({support:.5f}) + MACD cross")
            elif prev_hist <= 0 and macd_hist > 0:
                return ("BUY", f"Support ({support:.5f}) + MACD histogram flip")
        
        # SELL: At resistance + MACD bearish + RSI not oversold
        if dist_to_resistance < threshold and rsi > 40:
            if prev_macd >= prev_macd_signal and macd < macd_signal:
                return ("SELL", f"Resistance rejection ({resistance:.5f}) + MACD cross")
            elif prev_hist >= 0 and macd_hist < 0:
                return ("SELL", f"Resistance ({resistance:.5f}) + MACD histogram flip")
        
        return None
    
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """Calculate position size based on risk management"""
        risk_pips = abs(entry_price - stop_loss) * 10000
        if risk_pips == 0:
            return 0.01
        
        max_risk_amount = self.balance * self.max_risk_per_trade
        pip_value_per_lot = 10.0  # Approximate for EUR/USD
        
        lot_size = max_risk_amount / (risk_pips * pip_value_per_lot)
        return max(0.01, min(round(lot_size, 2), 1.0))
    
    def can_open_trade(self, current_date: str) -> Tuple[bool, str]:
        """Check if we can open a new trade (FTMO rules)"""
        # Check daily loss limit
        daily_loss = abs(self.daily_pnl.get(current_date, 0))
        daily_loss_percent = daily_loss / self.initial_balance
        
        if daily_loss_percent >= self.max_daily_loss * 0.9:  # 90% of limit
            return False, "Approaching daily loss limit"
        
        # Check total drawdown
        total_loss = self.initial_balance - self.balance
        total_loss_percent = total_loss / self.initial_balance
        
        if total_loss_percent >= self.max_total_loss * 0.9:
            return False, "Approaching total loss limit"
        
        return True, "OK"
    
    def open_trade(
        self,
        candle: Dict,
        direction: str,
        strategy: str,
        reason: str
    ):
        """Open a new trade"""
        current_date = candle["datetime"].strftime("%Y-%m-%d")
        
        # Check if we can trade
        can_trade, msg = self.can_open_trade(current_date)
        if not can_trade:
            return None
        
        entry_price = candle["close"]
        
        # Set SL/TP based on strategy - Optimized for better RR
        if strategy == "SCALPING":
            sl_pips = 8
            tp_pips = 16  # 2:1 RR
        else:  # INTRADAY
            sl_pips = 15
            tp_pips = 30  # 2:1 RR
        
        pip_value = 0.0001
        
        if direction == "BUY":
            stop_loss = entry_price - (sl_pips * pip_value)
            take_profit = entry_price + (tp_pips * pip_value)
        else:
            stop_loss = entry_price + (sl_pips * pip_value)
            take_profit = entry_price - (tp_pips * pip_value)
        
        lot_size = self.calculate_position_size(entry_price, stop_loss)
        
        trade = BacktestTrade(
            id=len(self.trades) + 1,
            symbol="EURUSD",
            direction=direction,
            strategy=strategy,
            entry_price=entry_price,
            entry_time=candle["datetime"],
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=lot_size
        )
        
        self.open_trades.append(trade)
        return trade
    
    def check_trade_exit(self, trade: BacktestTrade, candle: Dict):
        """Check if trade should be closed"""
        high = candle["high"]
        low = candle["low"]
        close = candle["close"]
        
        exit_price = None
        exit_reason = ""
        
        if trade.direction == "BUY":
            # Check SL hit
            if low <= trade.stop_loss:
                exit_price = trade.stop_loss
                exit_reason = "SL"
            # Check TP hit
            elif high >= trade.take_profit:
                exit_price = trade.take_profit
                exit_reason = "TP"
        else:  # SELL
            # Check SL hit
            if high >= trade.stop_loss:
                exit_price = trade.stop_loss
                exit_reason = "SL"
            # Check TP hit
            elif low <= trade.take_profit:
                exit_price = trade.take_profit
                exit_reason = "TP"
        
        if exit_price:
            self.close_trade(trade, exit_price, candle["datetime"], exit_reason)
    
    def close_trade(
        self,
        trade: BacktestTrade,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str
    ):
        """Close a trade and calculate P&L"""
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = exit_reason
        
        # Calculate P&L
        if trade.direction == "BUY":
            pnl_pips = (exit_price - trade.entry_price) * 10000
        else:
            pnl_pips = (trade.entry_price - exit_price) * 10000
        
        trade.pnl = round(pnl_pips * trade.lot_size * 10, 2)
        trade.pnl_percent = round(trade.pnl / self.initial_balance * 100, 4)
        
        # Determine status
        if trade.pnl > 0:
            trade.status = "WIN"
        elif trade.pnl < 0:
            trade.status = "LOSS"
        else:
            trade.status = "BREAKEVEN"
        
        # Update balance
        self.balance += trade.pnl
        
        # Update daily P&L
        date_str = exit_time.strftime("%Y-%m-%d")
        self.daily_pnl[date_str] = self.daily_pnl.get(date_str, 0) + trade.pnl
        
        # Update max drawdown
        if self.balance > self.peak_equity:
            self.peak_equity = self.balance
        
        current_drawdown = self.peak_equity - self.balance
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
            self.max_drawdown_percent = current_drawdown / self.peak_equity * 100
        
        # Move to closed trades
        self.trades.append(trade)
        self.open_trades.remove(trade)
    
    def run_backtest(
        self,
        symbol: str = "EURUSD",
        strategy: str = "BOTH",  # SCALPING, INTRADAY, or BOTH
        start_date: datetime = None,
        end_date: datetime = None,
        timeframe: str = "H1"
    ) -> BacktestResult:
        """
        Run complete backtest
        """
        self.reset()
        
        # Generate historical data
        if start_date is None:
            start_date = datetime.now(timezone.utc) - timedelta(days=180)
        if end_date is None:
            end_date = datetime.now(timezone.utc)
        
        logger.info(f"Generating historical data from {start_date} to {end_date}")
        candles = HistoricalDataGenerator.generate_ohlc_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe
        )
        
        logger.info(f"Running backtest on {len(candles)} candles")
        
        prev_indicators = None
        
        for i, candle in enumerate(candles):
            # Skip if not enough data for indicators
            if i < 30:
                continue
            
            # Calculate indicators
            indicators = self.calculate_indicators(candles, i)
            
            # Check for exits on open trades
            for trade in self.open_trades[:]:
                self.check_trade_exit(trade, candle)
            
            # Check for new signals
            if strategy in ["SCALPING", "BOTH"]:
                signal = self.check_scalping_signal(indicators, prev_indicators)
                if signal and len(self.open_trades) < 2:  # Max 2 concurrent trades
                    direction, reason = signal
                    self.open_trade(candle, direction, "SCALPING", reason)
            
            if strategy in ["INTRADAY", "BOTH"]:
                signal = self.check_intraday_signal(
                    indicators, prev_indicators, candle["close"]
                )
                if signal and len(self.open_trades) < 2:
                    direction, reason = signal
                    self.open_trade(candle, direction, "INTRADAY", reason)
            
            # Record equity curve (every 10 candles)
            if i % 10 == 0:
                unrealized_pnl = sum(
                    self._calculate_unrealized_pnl(t, candle["close"])
                    for t in self.open_trades
                )
                self.equity_curve.append({
                    "index": len(self.equity_curve),
                    "timestamp": candle["timestamp"],
                    "equity": round(self.balance + unrealized_pnl, 2),
                    "balance": round(self.balance, 2)
                })
            
            prev_indicators = indicators
        
        # Close any remaining open trades at last candle price
        if candles:
            last_candle = candles[-1]
            for trade in self.open_trades[:]:
                self.close_trade(
                    trade,
                    last_candle["close"],
                    last_candle["datetime"],
                    "EOD"
                )
        
        # Calculate final results
        return self._compile_results(symbol, strategy, start_date, end_date)
    
    def _calculate_unrealized_pnl(self, trade: BacktestTrade, current_price: float) -> float:
        """Calculate unrealized P&L for an open trade"""
        if trade.direction == "BUY":
            pnl_pips = (current_price - trade.entry_price) * 10000
        else:
            pnl_pips = (trade.entry_price - current_price) * 10000
        return pnl_pips * trade.lot_size * 10
    
    def _compile_results(
        self,
        symbol: str,
        strategy: str,
        start_date: datetime,
        end_date: datetime
    ) -> BacktestResult:
        """Compile all backtest results"""
        
        winning_trades = [t for t in self.trades if t.status == "WIN"]
        losing_trades = [t for t in self.trades if t.status == "LOSS"]
        
        total_trades = len(self.trades)
        win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
        
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
        
        avg_win = gross_profit / len(winning_trades) if winning_trades else 0
        avg_loss = gross_loss / len(losing_trades) if losing_trades else 0
        
        largest_win = max((t.pnl for t in winning_trades), default=0)
        largest_loss = min((t.pnl for t in losing_trades), default=0)
        
        # Calculate Sharpe ratio (simplified)
        returns = [t.pnl_percent for t in self.trades]
        if returns:
            avg_return = np.mean(returns)
            std_return = np.std(returns) if len(returns) > 1 else 1
            sharpe_ratio = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Calculate Sortino ratio
        negative_returns = [r for r in returns if r < 0]
        if negative_returns:
            downside_std = np.std(negative_returns)
            sortino_ratio = avg_return / downside_std * np.sqrt(252) if downside_std > 0 else 0
        else:
            sortino_ratio = sharpe_ratio
        
        # Average risk/reward
        avg_rr = avg_win / avg_loss if avg_loss > 0 else avg_win
        
        # Trade duration
        durations = []
        for t in self.trades:
            if t.exit_time and t.entry_time:
                duration = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(duration)
        avg_duration = np.mean(durations) if durations else 0
        
        # Best/worst trading hour
        hour_pnl: Dict[int, float] = {}
        for t in self.trades:
            hour = t.entry_time.hour
            hour_pnl[hour] = hour_pnl.get(hour, 0) + t.pnl
        
        best_hour = max(hour_pnl.keys(), key=lambda h: hour_pnl[h]) if hour_pnl else 0
        worst_hour = min(hour_pnl.keys(), key=lambda h: hour_pnl[h]) if hour_pnl else 0
        
        # Max daily loss
        max_daily_loss = abs(min(self.daily_pnl.values())) if self.daily_pnl else 0
        max_daily_loss_percent = max_daily_loss / self.initial_balance * 100
        
        # FTMO compliance
        ftmo_daily_breached = max_daily_loss_percent > 4.5
        ftmo_total_breached = self.max_drawdown_percent > 10
        
        # Daily returns for chart
        daily_returns = [
            {"date": date, "pnl": pnl, "pnl_percent": round(pnl / self.initial_balance * 100, 2)}
            for date, pnl in sorted(self.daily_pnl.items())
        ]
        
        # Trade list for details
        trades_list = [
            {
                "id": t.id,
                "symbol": t.symbol,
                "direction": t.direction,
                "strategy": t.strategy,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                "pnl": t.pnl,
                "pnl_percent": t.pnl_percent,
                "status": t.status,
                "exit_reason": t.exit_reason,
                "lot_size": t.lot_size
            }
            for t in self.trades
        ]
        
        return BacktestResult(
            symbol=symbol,
            strategy=strategy,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            initial_balance=self.initial_balance,
            final_balance=round(self.balance, 2),
            total_return=round(self.balance - self.initial_balance, 2),
            total_return_percent=round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            max_drawdown=round(self.max_drawdown, 2),
            max_drawdown_percent=round(self.max_drawdown_percent, 2),
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=round(win_rate, 1),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=round(profit_factor, 2),
            average_win=round(avg_win, 2),
            average_loss=round(avg_loss, 2),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            sortino_ratio=round(sortino_ratio, 2),
            avg_risk_reward=round(avg_rr, 2),
            max_daily_loss=round(max_daily_loss, 2),
            max_daily_loss_percent=round(max_daily_loss_percent, 2),
            ftmo_daily_limit_breached=ftmo_daily_breached,
            ftmo_total_limit_breached=ftmo_total_breached,
            avg_trade_duration_hours=round(avg_duration, 1),
            best_trading_hour=best_hour,
            worst_trading_hour=worst_hour,
            equity_curve=self.equity_curve,
            trades=trades_list,
            daily_returns=daily_returns
        )


# Global backtest engine instance
backtest_engine = BacktestEngine()
