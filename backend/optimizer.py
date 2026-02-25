"""
Strategy Optimizer for FTMO Trading Bot
Tests multiple parameter combinations to find optimal settings
"""
import numpy as np
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import logging
import itertools
from concurrent.futures import ThreadPoolExecutor
import copy

from backtesting import BacktestEngine, HistoricalDataGenerator

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """Result of a single parameter combination test"""
    params: Dict
    total_return_percent: float
    win_rate: float
    profit_factor: float
    max_drawdown_percent: float
    total_trades: int
    sharpe_ratio: float
    ftmo_compliant: bool
    score: float  # Combined score for ranking


@dataclass
class OptimizationReport:
    """Complete optimization report"""
    best_params: Dict
    best_result: OptimizationResult
    all_results: List[OptimizationResult]
    total_combinations: int
    ftmo_compliant_count: int
    profitable_count: int
    optimization_time_seconds: float
    recommendations: List[str]


class StrategyOptimizer:
    """
    Optimizes trading strategy parameters using grid search
    Focuses on FTMO compliance and profitability
    """
    
    # Parameter ranges to test
    PARAM_RANGES = {
        # Scalping parameters
        "scalping_rsi_oversold": [20, 25, 30],
        "scalping_rsi_overbought": [70, 75, 80],
        "scalping_sl_pips": [6, 8, 10, 12],
        "scalping_tp_pips": [12, 15, 18, 20],
        
        # Intraday parameters  
        "intraday_sr_threshold": [0.08, 0.10, 0.12, 0.15],
        "intraday_sl_pips": [12, 15, 18, 20],
        "intraday_tp_pips": [24, 30, 36, 40],
        
        # Common parameters
        "ema_fast": [5, 8, 10],
        "ema_slow": [18, 21, 26],
        "max_concurrent_trades": [1, 2, 3]
    }
    
    # Quick optimization (fewer combinations)
    QUICK_PARAM_RANGES = {
        "scalping_rsi_oversold": [25, 30],
        "scalping_rsi_overbought": [70, 75],
        "scalping_sl_pips": [8, 10],
        "scalping_tp_pips": [16, 20],
        "intraday_sr_threshold": [0.10, 0.15],
        "intraday_sl_pips": [15, 20],
        "intraday_tp_pips": [30, 40],
        "ema_fast": [8],
        "ema_slow": [21],
        "max_concurrent_trades": [2]
    }
    
    def __init__(
        self,
        initial_balance: float = 100000,
        max_daily_loss: float = 0.045,
        max_total_loss: float = 0.10
    ):
        self.initial_balance = initial_balance
        self.max_daily_loss = max_daily_loss
        self.max_total_loss = max_total_loss
        
    def generate_param_combinations(self, quick: bool = True) -> List[Dict]:
        """Generate all parameter combinations to test"""
        ranges = self.QUICK_PARAM_RANGES if quick else self.PARAM_RANGES
        
        keys = list(ranges.keys())
        values = list(ranges.values())
        
        combinations = []
        for combo in itertools.product(*values):
            param_dict = dict(zip(keys, combo))
            
            # Validate RR ratio >= 1:1
            scalp_rr = param_dict["scalping_tp_pips"] / param_dict["scalping_sl_pips"]
            intra_rr = param_dict["intraday_tp_pips"] / param_dict["intraday_sl_pips"]
            
            if scalp_rr >= 1.0 and intra_rr >= 1.0:
                combinations.append(param_dict)
        
        return combinations
    
    def calculate_score(self, result: Dict) -> float:
        """
        Calculate a combined score for ranking results
        Prioritizes: FTMO compliance > Profitability > Win Rate > Sharpe
        """
        score = 0.0
        
        # FTMO compliance is critical (50% weight)
        if not result.get("ftmo_daily_limit_breached", True) and \
           not result.get("ftmo_total_limit_breached", True):
            score += 50
            
            # Bonus for staying well under limits
            daily_margin = 4.5 - result.get("max_daily_loss_percent", 5)
            total_margin = 10 - result.get("max_drawdown_percent", 11)
            score += max(0, daily_margin * 2)  # Up to 9 points
            score += max(0, total_margin * 1)  # Up to 10 points
        
        # Profitability (25% weight)
        return_pct = result.get("total_return_percent", -100)
        if return_pct > 0:
            score += min(25, return_pct * 2)  # Cap at 25 for 12.5%+ return
        else:
            score += max(-25, return_pct)  # Penalty for losses
        
        # Win rate (15% weight)
        win_rate = result.get("win_rate", 0)
        if win_rate >= 40:
            score += 15
        elif win_rate >= 30:
            score += 10
        elif win_rate >= 25:
            score += 5
        
        # Profit factor (10% weight)
        pf = result.get("profit_factor", 0)
        if pf >= 1.5:
            score += 10
        elif pf >= 1.2:
            score += 7
        elif pf >= 1.0:
            score += 4
        
        return round(score, 2)
    
    def run_single_backtest(
        self,
        params: Dict,
        candles: List[Dict],
        strategy: str = "BOTH"
    ) -> OptimizationResult:
        """Run a single backtest with specific parameters"""
        
        # Create custom backtest engine with parameters
        engine = CustomBacktestEngine(
            initial_balance=self.initial_balance,
            params=params
        )
        
        # Run backtest
        result = engine.run_backtest_on_candles(candles, strategy)
        
        # Calculate score
        score = self.calculate_score(result)
        
        ftmo_compliant = not result.get("ftmo_daily_limit_breached", True) and \
                         not result.get("ftmo_total_limit_breached", True)
        
        return OptimizationResult(
            params=params,
            total_return_percent=result.get("total_return_percent", 0),
            win_rate=result.get("win_rate", 0),
            profit_factor=result.get("profit_factor", 0),
            max_drawdown_percent=result.get("max_drawdown_percent", 100),
            total_trades=result.get("total_trades", 0),
            sharpe_ratio=result.get("sharpe_ratio", 0),
            ftmo_compliant=ftmo_compliant,
            score=score
        )
    
    def optimize(
        self,
        days: int = 180,
        strategy: str = "BOTH",
        quick: bool = True,
        progress_callback=None
    ) -> OptimizationReport:
        """
        Run full optimization
        Returns the best parameters found
        """
        start_time = datetime.now()
        
        logger.info(f"Starting optimization for {days} days, strategy: {strategy}")
        
        # Generate historical data once
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        candles = HistoricalDataGenerator.generate_ohlc_data(
            symbol="EURUSD",
            start_date=start_date,
            end_date=end_date,
            timeframe="H1"
        )
        
        logger.info(f"Generated {len(candles)} candles for optimization")
        
        # Generate parameter combinations
        combinations = self.generate_param_combinations(quick=quick)
        total_combos = len(combinations)
        
        logger.info(f"Testing {total_combos} parameter combinations")
        
        # Run all backtests
        results: List[OptimizationResult] = []
        
        for i, params in enumerate(combinations):
            try:
                result = self.run_single_backtest(params, candles, strategy)
                results.append(result)
                
                if progress_callback:
                    progress_callback(i + 1, total_combos, result)
                    
                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{total_combos} combinations tested")
                    
            except Exception as e:
                logger.error(f"Error testing params {params}: {e}")
                continue
        
        # Sort by score (descending)
        results.sort(key=lambda x: x.score, reverse=True)
        
        # Calculate statistics
        ftmo_compliant_count = sum(1 for r in results if r.ftmo_compliant)
        profitable_count = sum(1 for r in results if r.total_return_percent > 0)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(results)
        
        # Get best result
        best_result = results[0] if results else None
        best_params = best_result.params if best_result else {}
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"Optimization complete in {elapsed_time:.1f}s")
        logger.info(f"Best score: {best_result.score if best_result else 0}")
        
        return OptimizationReport(
            best_params=best_params,
            best_result=best_result,
            all_results=results[:20],  # Top 20 results
            total_combinations=total_combos,
            ftmo_compliant_count=ftmo_compliant_count,
            profitable_count=profitable_count,
            optimization_time_seconds=round(elapsed_time, 1),
            recommendations=recommendations
        )
    
    def _generate_recommendations(self, results: List[OptimizationResult]) -> List[str]:
        """Generate actionable recommendations based on results"""
        recommendations = []
        
        if not results:
            return ["Aucun résultat disponible"]
        
        # Check FTMO compliance rate
        ftmo_rate = sum(1 for r in results if r.ftmo_compliant) / len(results) * 100
        if ftmo_rate < 50:
            recommendations.append(
                f"⚠️ Seulement {ftmo_rate:.0f}% des configurations respectent les limites FTMO. "
                "Considérez des SL plus serrés."
            )
        
        # Check profitability
        profitable_rate = sum(1 for r in results if r.total_return_percent > 0) / len(results) * 100
        if profitable_rate < 30:
            recommendations.append(
                f"📊 {profitable_rate:.0f}% des configurations sont rentables. "
                "Les stratégies nécessitent plus d'optimisation ou de filtres."
            )
        
        # Best configuration analysis
        best = results[0]
        if best.win_rate < 35:
            recommendations.append(
                f"🎯 Win rate de {best.win_rate}% - Ajoutez des filtres de session "
                "(London 8-16h, NY 13-21h) pour améliorer la qualité des signaux."
            )
        
        if best.profit_factor < 1.0:
            recommendations.append(
                "💡 Profit factor < 1.0 - Augmentez le ratio TP/SL ou ajoutez un trailing stop."
            )
        
        if best.total_return_percent > 0:
            recommendations.append(
                f"✅ Meilleure configuration: +{best.total_return_percent}% avec "
                f"{best.win_rate}% win rate et {best.max_drawdown_percent}% max DD."
            )
        
        # Parameter-specific recommendations
        if best.params.get("scalping_tp_pips", 0) / best.params.get("scalping_sl_pips", 1) < 1.5:
            recommendations.append(
                "📈 Considérez un ratio TP/SL de 2:1 ou plus pour le scalping."
            )
        
        return recommendations


class CustomBacktestEngine(BacktestEngine):
    """Extended backtest engine with customizable parameters"""
    
    def __init__(self, initial_balance: float, params: Dict):
        super().__init__(initial_balance=initial_balance)
        self.params = params
        
    def check_scalping_signal(self, indicators: Dict, prev_indicators: Dict) -> Optional[Tuple[str, str]]:
        """Scalping signal with custom parameters"""
        if not indicators or not prev_indicators:
            return None
        
        rsi = indicators.get("rsi", 50)
        prev_rsi = prev_indicators.get("rsi", 50)
        ema8 = indicators.get("ema_8", 0)
        ema21 = indicators.get("ema_21", 0)
        prev_ema8 = prev_indicators.get("ema_8", 0)
        prev_ema21 = prev_indicators.get("ema_21", 0)
        close = indicators.get("close", 0)
        
        oversold = self.params.get("scalping_rsi_oversold", 30)
        overbought = self.params.get("scalping_rsi_overbought", 70)
        
        # BUY: RSI reversal from oversold + bullish structure
        if prev_rsi < oversold and rsi > oversold and close > ema8 and ema8 > ema21:
            return ("BUY", f"RSI reversal {prev_rsi:.0f}->{rsi:.0f}")
        
        # SELL: RSI reversal from overbought + bearish structure
        if prev_rsi > overbought and rsi < overbought and close < ema8 and ema8 < ema21:
            return ("SELL", f"RSI reversal {prev_rsi:.0f}->{rsi:.0f}")
        
        # EMA crossover
        if prev_ema8 <= prev_ema21 and ema8 > ema21:
            if rsi > 40 and rsi < 60:
                return ("BUY", "EMA bullish crossover")
        
        if prev_ema8 >= prev_ema21 and ema8 < ema21:
            if rsi > 40 and rsi < 60:
                return ("SELL", "EMA bearish crossover")
        
        return None
    
    def check_intraday_signal(self, indicators: Dict, prev_indicators: Dict, current_price: float) -> Optional[Tuple[str, str]]:
        """Intraday signal with custom parameters"""
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
        prev_rsi = prev_indicators.get("rsi", 50)
        
        range_size = resistance - support
        if range_size <= 0.0005:
            return None
        
        threshold_pct = self.params.get("intraday_sr_threshold", 0.10)
        threshold = range_size * threshold_pct
        
        dist_to_support = current_price - support
        dist_to_resistance = resistance - current_price
        
        # BUY at support with confirmations
        if dist_to_support < threshold:
            confirmations = 0
            if prev_macd <= prev_macd_signal and macd > macd_signal:
                confirmations += 1
            if prev_hist <= 0 and macd_hist > 0:
                confirmations += 1
            if prev_rsi < 35 and rsi > 35:
                confirmations += 1
            
            if confirmations >= 2:
                return ("BUY", f"Support bounce ({confirmations} conf)")
        
        # SELL at resistance with confirmations
        if dist_to_resistance < threshold:
            confirmations = 0
            if prev_macd >= prev_macd_signal and macd < macd_signal:
                confirmations += 1
            if prev_hist >= 0 and macd_hist < 0:
                confirmations += 1
            if prev_rsi > 65 and rsi < 65:
                confirmations += 1
            
            if confirmations >= 2:
                return ("SELL", f"Resistance rejection ({confirmations} conf)")
        
        return None
    
    def open_trade(self, candle: Dict, direction: str, strategy: str, reason: str):
        """Open trade with custom SL/TP parameters"""
        from backtesting import BacktestTrade
        
        current_date = candle["datetime"].strftime("%Y-%m-%d")
        can_trade, msg = self.can_open_trade(current_date)
        if not can_trade:
            return None
        
        # Check max concurrent trades
        max_trades = self.params.get("max_concurrent_trades", 2)
        if len(self.open_trades) >= max_trades:
            return None
        
        entry_price = candle["close"]
        
        # Custom SL/TP based on strategy
        if strategy == "SCALPING":
            sl_pips = self.params.get("scalping_sl_pips", 10)
            tp_pips = self.params.get("scalping_tp_pips", 15)
        else:
            sl_pips = self.params.get("intraday_sl_pips", 15)
            tp_pips = self.params.get("intraday_tp_pips", 30)
        
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
    
    def run_backtest_on_candles(self, candles: List[Dict], strategy: str = "BOTH") -> Dict:
        """Run backtest on pre-generated candles"""
        self.reset()
        
        prev_indicators = None
        
        for i, candle in enumerate(candles):
            if i < 30:
                continue
            
            indicators = self.calculate_indicators(candles, i)
            
            # Check exits
            for trade in self.open_trades[:]:
                self.check_trade_exit(trade, candle)
            
            # Check new signals
            if strategy in ["SCALPING", "BOTH"]:
                signal = self.check_scalping_signal(indicators, prev_indicators)
                if signal:
                    direction, reason = signal
                    self.open_trade(candle, direction, "SCALPING", reason)
            
            if strategy in ["INTRADAY", "BOTH"]:
                signal = self.check_intraday_signal(
                    indicators, prev_indicators, candle["close"]
                )
                if signal:
                    direction, reason = signal
                    self.open_trade(candle, direction, "INTRADAY", reason)
            
            prev_indicators = indicators
        
        # Close remaining trades
        if candles:
            last_candle = candles[-1]
            for trade in self.open_trades[:]:
                self.close_trade(trade, last_candle["close"], last_candle["datetime"], "EOD")
        
        # Compile results
        return self._compile_results_dict()
    
    def _compile_results_dict(self) -> Dict:
        """Compile results as dictionary"""
        winning_trades = [t for t in self.trades if t.status == "WIN"]
        losing_trades = [t for t in self.trades if t.status == "LOSS"]
        
        total_trades = len(self.trades)
        win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
        
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
        
        # Sharpe ratio
        returns = [t.pnl_percent for t in self.trades]
        if returns:
            import numpy as np
            avg_return = np.mean(returns)
            std_return = np.std(returns) if len(returns) > 1 else 1
            sharpe_ratio = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Max daily loss
        max_daily_loss = abs(min(self.daily_pnl.values())) if self.daily_pnl else 0
        max_daily_loss_percent = max_daily_loss / self.initial_balance * 100
        
        return {
            "total_return": round(self.balance - self.initial_balance, 2),
            "total_return_percent": round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_percent": round(self.max_drawdown_percent, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "max_daily_loss_percent": round(max_daily_loss_percent, 2),
            "ftmo_daily_limit_breached": max_daily_loss_percent > 4.5,
            "ftmo_total_limit_breached": self.max_drawdown_percent > 10
        }


# Global optimizer instance
strategy_optimizer = StrategyOptimizer()
