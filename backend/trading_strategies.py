"""
Trading Strategies for the FTMO Bot
- Scalping: RSI + EMA Crossover (quick entries/exits)
- Intraday: Support/Resistance + MACD (longer holds)
"""
import numpy as np
from typing import Optional, Tuple, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """Technical indicator calculations"""
    
    @staticmethod
    def ema(prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        prices_array = np.array(prices[-period*2:])
        multiplier = 2 / (period + 1)
        ema_values = [prices_array[0]]
        
        for price in prices_array[1:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        
        return ema_values[-1]
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        prices_array = np.array(prices[-(period + 1):])
        deltas = np.diff(prices_array)
        
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return round(rsi, 2)
    
    @staticmethod
    def macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """Calculate MACD, Signal line, and Histogram"""
        if len(prices) < slow:
            return 0.0, 0.0, 0.0
        
        ema_fast = TechnicalIndicators.ema(prices, fast)
        ema_slow = TechnicalIndicators.ema(prices, slow)
        
        macd_line = ema_fast - ema_slow
        
        # Simplified signal line calculation
        signal_line = macd_line * 0.9  # Approximation for demo
        histogram = macd_line - signal_line
        
        return round(macd_line, 5), round(signal_line, 5), round(histogram, 5)
    
    @staticmethod
    def support_resistance(prices: List[float], lookback: int = 20) -> Tuple[float, float]:
        """Calculate recent support and resistance levels"""
        if len(prices) < lookback:
            return min(prices), max(prices)
        
        recent = prices[-lookback:]
        support = min(recent)
        resistance = max(recent)
        
        return support, resistance
    
    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculate Average True Range for volatility"""
        if len(closes) < period + 1:
            return 0.001
        
        tr_list = []
        for i in range(1, min(len(closes), period + 1)):
            high = highs[-i] if i <= len(highs) else closes[-i]
            low = lows[-i] if i <= len(lows) else closes[-i]
            prev_close = closes[-(i+1)]
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        
        return np.mean(tr_list) if tr_list else 0.001


class ScalpingStrategy:
    """
    Scalping Strategy using RSI + EMA Crossover
    - Entry: RSI oversold/overbought + EMA crossover confirmation
    - Quick trades with tight SL/TP (10-15 pips)
    """
    
    def __init__(self, tp_pips: float = 10, sl_pips: float = 10):
        self.tp_pips = tp_pips
        self.sl_pips = sl_pips
        self.ema_fast = 8
        self.ema_slow = 21
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        
    def analyze(self, prices: List[float], current_price: float) -> Optional[dict]:
        """
        Analyze market for scalping opportunity
        Returns trade signal or None
        """
        if len(prices) < 30:
            return None
        
        # Calculate indicators
        ema_fast = TechnicalIndicators.ema(prices, self.ema_fast)
        ema_slow = TechnicalIndicators.ema(prices, self.ema_slow)
        rsi = TechnicalIndicators.rsi(prices, self.rsi_period)
        
        # Previous EMAs for crossover detection
        prev_prices = prices[:-1]
        prev_ema_fast = TechnicalIndicators.ema(prev_prices, self.ema_fast)
        prev_ema_slow = TechnicalIndicators.ema(prev_prices, self.ema_slow)
        
        signal = None
        
        # BUY Signal: RSI oversold + EMA bullish crossover
        if rsi < self.rsi_oversold + 10:  # Near oversold
            if prev_ema_fast <= prev_ema_slow and ema_fast > ema_slow:  # Bullish crossover
                signal = {
                    "direction": "BUY",
                    "entry_price": current_price,
                    "stop_loss": current_price - (self.sl_pips * 0.0001),
                    "take_profit": current_price + (self.tp_pips * 0.0001),
                    "strategy": "SCALPING",
                    "reason": f"RSI({rsi:.1f}) near oversold + EMA bullish crossover",
                    "confidence": min(90, 50 + (self.rsi_oversold + 10 - rsi) * 2)
                }
        
        # SELL Signal: RSI overbought + EMA bearish crossover
        elif rsi > self.rsi_overbought - 10:  # Near overbought
            if prev_ema_fast >= prev_ema_slow and ema_fast < ema_slow:  # Bearish crossover
                signal = {
                    "direction": "SELL",
                    "entry_price": current_price,
                    "stop_loss": current_price + (self.sl_pips * 0.0001),
                    "take_profit": current_price - (self.tp_pips * 0.0001),
                    "strategy": "SCALPING",
                    "reason": f"RSI({rsi:.1f}) near overbought + EMA bearish crossover",
                    "confidence": min(90, 50 + (rsi - (self.rsi_overbought - 10)) * 2)
                }
        
        return signal


class IntradayStrategy:
    """
    Intraday Strategy using Support/Resistance + MACD
    - Entry: Price near S/R levels + MACD confirmation
    - Longer holds with wider SL/TP (20-50 pips)
    """
    
    def __init__(self, tp_pips: float = 30, sl_pips: float = 20):
        self.tp_pips = tp_pips
        self.sl_pips = sl_pips
        self.sr_lookback = 50
        self.sr_threshold = 0.0010  # 10 pips from S/R
        
    def analyze(self, prices: List[float], current_price: float) -> Optional[dict]:
        """
        Analyze market for intraday opportunity
        Returns trade signal or None
        """
        if len(prices) < 60:
            return None
        
        # Calculate indicators
        support, resistance = TechnicalIndicators.support_resistance(prices, self.sr_lookback)
        macd_line, signal_line, histogram = TechnicalIndicators.macd(prices)
        
        # Previous MACD for crossover
        prev_prices = prices[:-1]
        prev_macd, prev_signal, _ = TechnicalIndicators.macd(prev_prices)
        
        signal = None
        
        # Distance from support/resistance
        dist_to_support = current_price - support
        dist_to_resistance = resistance - current_price
        
        # BUY Signal: Near support + MACD bullish crossover
        if dist_to_support < self.sr_threshold:  # Near support
            if prev_macd <= prev_signal and macd_line > signal_line:  # MACD bullish crossover
                signal = {
                    "direction": "BUY",
                    "entry_price": current_price,
                    "stop_loss": support - (self.sl_pips * 0.0001 * 0.5),  # Below support
                    "take_profit": current_price + (self.tp_pips * 0.0001),
                    "strategy": "INTRADAY",
                    "reason": f"Near support ({support:.5f}) + MACD bullish crossover",
                    "confidence": min(85, 60 + (self.sr_threshold - dist_to_support) * 10000)
                }
        
        # SELL Signal: Near resistance + MACD bearish crossover
        elif dist_to_resistance < self.sr_threshold:  # Near resistance
            if prev_macd >= prev_signal and macd_line < signal_line:  # MACD bearish crossover
                signal = {
                    "direction": "SELL",
                    "entry_price": current_price,
                    "stop_loss": resistance + (self.sl_pips * 0.0001 * 0.5),  # Above resistance
                    "take_profit": current_price - (self.tp_pips * 0.0001),
                    "strategy": "INTRADAY",
                    "reason": f"Near resistance ({resistance:.5f}) + MACD bearish crossover",
                    "confidence": min(85, 60 + (self.sr_threshold - dist_to_resistance) * 10000)
                }
        
        return signal


class TradingEngine:
    """Main trading engine combining both strategies"""
    
    def __init__(self, settings: dict = None):
        settings = settings or {}
        
        self.scalping = ScalpingStrategy(
            tp_pips=settings.get("scalping_tp_pips", 10),
            sl_pips=settings.get("scalping_sl_pips", 10)
        )
        self.intraday = IntradayStrategy(
            tp_pips=settings.get("intraday_tp_pips", 30),
            sl_pips=settings.get("intraday_sl_pips", 20)
        )
        
        self.scalping_enabled = settings.get("scalping_enabled", True)
        self.intraday_enabled = settings.get("intraday_enabled", True)
        
    def analyze_market(self, prices: List[float], current_price: float) -> List[dict]:
        """
        Analyze market with all enabled strategies
        Returns list of signals
        """
        signals = []
        
        if self.scalping_enabled:
            scalp_signal = self.scalping.analyze(prices, current_price)
            if scalp_signal:
                signals.append(scalp_signal)
        
        if self.intraday_enabled:
            intra_signal = self.intraday.analyze(prices, current_price)
            if intra_signal:
                signals.append(intra_signal)
        
        # Sort by confidence
        signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return signals
    
    def get_indicator_values(self, prices: List[float]) -> dict:
        """Get current indicator values for display"""
        if len(prices) < 30:
            return {}
        
        ema_8 = TechnicalIndicators.ema(prices, 8)
        ema_21 = TechnicalIndicators.ema(prices, 21)
        rsi = TechnicalIndicators.rsi(prices, 14)
        macd_line, signal_line, histogram = TechnicalIndicators.macd(prices)
        support, resistance = TechnicalIndicators.support_resistance(prices, 50)
        
        return {
            "ema_8": round(ema_8, 5),
            "ema_21": round(ema_21, 5),
            "rsi": rsi,
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_histogram": histogram,
            "support": round(support, 5),
            "resistance": round(resistance, 5)
        }
