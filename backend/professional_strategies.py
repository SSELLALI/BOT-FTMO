"""
FTMO Professional Trading Strategies
Based on precise specifications with strict risk management

Strategy 1: SCALPING - Breakout + Pullback (M5, 5-15 pips)
Strategy 2: INTRADAY - Trend Continuation H1/M15 (30-80 pips)

Risk Rules:
- 1% max risk per trade
- 4.5% max daily loss
- 8% max total drawdown
- Stop after 3 consecutive losses (scalping) or 2 (intraday)
"""
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TradingSession(Enum):
    """Trading sessions with UTC hours"""
    ASIAN = (0, 8)      # 00:00 - 08:00 UTC
    LONDON = (8, 16)    # 08:00 - 16:00 UTC
    NEW_YORK = (13, 21) # 13:00 - 21:00 UTC
    OVERLAP = (13, 16)  # London/NY overlap


@dataclass
class TradeSignal:
    """Trade signal with all parameters"""
    symbol: str
    direction: str  # BUY or SELL
    strategy: str   # SCALPING or INTRADAY
    entry_price: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    risk_reward: float
    lot_size: float
    reason: str
    confidence: int
    session: str
    timestamp: datetime


@dataclass
class StrategyState:
    """Track strategy state for risk management"""
    daily_trades: int = 0
    daily_losses: int = 0
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    is_stopped_today: bool = False
    is_stopped_global: bool = False
    stop_reason: str = ""


class TechnicalAnalysis:
    """Technical analysis utilities"""
    
    @staticmethod
    def ema(prices: List[float], period: int) -> List[float]:
        """Calculate EMA series"""
        if len(prices) < period:
            return [prices[-1]] * len(prices)
        
        multiplier = 2 / (period + 1)
        ema_values = [np.mean(prices[:period])]
        
        for price in prices[period:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        
        # Pad beginning
        padding = [ema_values[0]] * (len(prices) - len(ema_values))
        return padding + ema_values
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """Calculate RSI"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices[-(period + 1):])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def find_swing_high(highs: List[float], lookback: int = 10) -> float:
        """Find recent swing high"""
        if len(highs) < lookback:
            return max(highs)
        return max(highs[-lookback:])
    
    @staticmethod
    def find_swing_low(lows: List[float], lookback: int = 10) -> float:
        """Find recent swing low"""
        if len(lows) < lookback:
            return min(lows)
        return min(lows[-lookback:])
    
    @staticmethod
    def is_bullish_engulfing(candles: List[Dict], index: int) -> bool:
        """Check for bullish engulfing pattern"""
        if index < 1:
            return False
        
        prev = candles[index - 1]
        curr = candles[index]
        
        # Previous candle bearish, current bullish
        prev_bearish = prev["close"] < prev["open"]
        curr_bullish = curr["close"] > curr["open"]
        
        # Current body engulfs previous
        engulfs = curr["open"] <= prev["close"] and curr["close"] >= prev["open"]
        
        return prev_bearish and curr_bullish and engulfs
    
    @staticmethod
    def is_bearish_engulfing(candles: List[Dict], index: int) -> bool:
        """Check for bearish engulfing pattern"""
        if index < 1:
            return False
        
        prev = candles[index - 1]
        curr = candles[index]
        
        prev_bullish = prev["close"] > prev["open"]
        curr_bearish = curr["close"] < curr["open"]
        
        engulfs = curr["open"] >= prev["close"] and curr["close"] <= prev["open"]
        
        return prev_bullish and curr_bearish and engulfs
    
    @staticmethod
    def is_bullish_rejection(candle: Dict) -> bool:
        """Check for bullish rejection candle (hammer/pin bar)"""
        body = abs(candle["close"] - candle["open"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        
        # Lower wick at least 2x body, small upper wick
        return lower_wick > body * 2 and upper_wick < body * 0.5
    
    @staticmethod
    def is_bearish_rejection(candle: Dict) -> bool:
        """Check for bearish rejection candle"""
        body = abs(candle["close"] - candle["open"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        
        return upper_wick > body * 2 and lower_wick < body * 0.5
    
    @staticmethod
    def detect_structure(highs: List[float], lows: List[float]) -> str:
        """Detect market structure (HH/HL or LH/LL)"""
        if len(highs) < 4 or len(lows) < 4:
            return "UNKNOWN"
        
        # Check last 2 swing points
        recent_highs = highs[-4:]
        recent_lows = lows[-4:]
        
        # Higher highs and higher lows = bullish
        hh = recent_highs[-1] > recent_highs[-3]
        hl = recent_lows[-1] > recent_lows[-3]
        
        # Lower highs and lower lows = bearish
        lh = recent_highs[-1] < recent_highs[-3]
        ll = recent_lows[-1] < recent_lows[-3]
        
        if hh and hl:
            return "BULLISH"
        elif lh and ll:
            return "BEARISH"
        else:
            return "RANGING"


class ScalpingStrategy:
    """
    STRATEGY 1: SCALPING - Breakout + Pullback
    
    Timeframe: M5
    Session: London & early New York (08:00-16:00 UTC)
    Target: 5-15 pips
    Max trades/day: 3-8
    
    Entry conditions (BUY):
    - EMA 20 > EMA 50 (uptrend)
    - Price above both EMAs
    - Break of recent high
    - Pullback to EMA 20
    - RSI between 50-65
    
    Risk: 1% per trade, SL 5-8 pips, TP 1.5-2R
    """
    
    def __init__(self):
        self.name = "SCALPING"
        self.max_trades_per_day = 8
        self.max_consecutive_losses = 3
        self.min_sl_pips = 5
        self.max_sl_pips = 8
        self.min_rr = 1.5
        self.target_rr = 2.0
        
    def is_valid_session(self, hour: int) -> bool:
        """Check if current hour is in valid trading session"""
        # London: 8-16, Early NY: 13-16
        return 8 <= hour <= 16
    
    def analyze(
        self,
        candles: List[Dict],
        current_index: int,
        symbol: str = "EURUSD"
    ) -> Optional[TradeSignal]:
        """
        Analyze for scalping entry
        """
        if current_index < 50:
            return None
        
        # Check session
        current_candle = candles[current_index]
        hour = current_candle["datetime"].hour
        
        if not self.is_valid_session(hour):
            return None
        
        # Extract price data
        closes = [c["close"] for c in candles[:current_index + 1]]
        highs = [c["high"] for c in candles[:current_index + 1]]
        lows = [c["low"] for c in candles[:current_index + 1]]
        
        # Calculate indicators
        ema20 = TechnicalAnalysis.ema(closes, 20)
        ema50 = TechnicalAnalysis.ema(closes, 50)
        rsi = TechnicalAnalysis.rsi(closes, 14)
        
        current_price = closes[-1]
        current_ema20 = ema20[-1]
        current_ema50 = ema50[-1]
        prev_ema20 = ema20[-2] if len(ema20) > 1 else current_ema20
        
        # Recent swing points
        recent_high = TechnicalAnalysis.find_swing_high(highs[-20:], 10)
        recent_low = TechnicalAnalysis.find_swing_low(lows[-20:], 10)
        
        signal = None
        
        # ========== BUY SETUP ==========
        if current_ema20 > current_ema50:  # Uptrend
            if current_price > current_ema20 and current_price > current_ema50:  # Above EMAs
                if 50 <= rsi <= 65:  # RSI in range
                    # Check for pullback to EMA20
                    prev_candle = candles[current_index - 1]
                    touched_ema20 = prev_candle["low"] <= prev_ema20 * 1.0003  # Within 3 pips
                    
                    # Check for bullish rejection at EMA20
                    is_rejection = TechnicalAnalysis.is_bullish_rejection(current_candle)
                    is_engulfing = TechnicalAnalysis.is_bullish_engulfing(candles, current_index)
                    
                    if touched_ema20 and (is_rejection or is_engulfing or current_price > prev_candle["high"]):
                        # Calculate SL/TP
                        sl_price = min(lows[-3:])  # Below recent low
                        sl_pips = (current_price - sl_price) * 10000
                        
                        if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                            tp_pips = sl_pips * self.min_rr
                            tp_price = current_price + (tp_pips / 10000)
                            
                            signal = TradeSignal(
                                symbol=symbol,
                                direction="BUY",
                                strategy=self.name,
                                entry_price=current_price,
                                stop_loss=sl_price,
                                take_profit=tp_price,
                                sl_pips=round(sl_pips, 1),
                                tp_pips=round(tp_pips, 1),
                                risk_reward=round(tp_pips / sl_pips, 2),
                                lot_size=0,  # Calculated later
                                reason=f"Pullback to EMA20, RSI {rsi:.0f}",
                                confidence=75,
                                session="LONDON" if hour < 13 else "NY_OVERLAP",
                                timestamp=current_candle["datetime"]
                            )
        
        # ========== SELL SETUP ==========
        elif current_ema20 < current_ema50:  # Downtrend
            if current_price < current_ema20 and current_price < current_ema50:
                if 35 <= rsi <= 50:
                    prev_candle = candles[current_index - 1]
                    touched_ema20 = prev_candle["high"] >= prev_ema20 * 0.9997
                    
                    is_rejection = TechnicalAnalysis.is_bearish_rejection(current_candle)
                    is_engulfing = TechnicalAnalysis.is_bearish_engulfing(candles, current_index)
                    
                    if touched_ema20 and (is_rejection or is_engulfing or current_price < prev_candle["low"]):
                        sl_price = max(highs[-3:])
                        sl_pips = (sl_price - current_price) * 10000
                        
                        if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                            tp_pips = sl_pips * self.min_rr
                            tp_price = current_price - (tp_pips / 10000)
                            
                            signal = TradeSignal(
                                symbol=symbol,
                                direction="SELL",
                                strategy=self.name,
                                entry_price=current_price,
                                stop_loss=sl_price,
                                take_profit=tp_price,
                                sl_pips=round(sl_pips, 1),
                                tp_pips=round(tp_pips, 1),
                                risk_reward=round(tp_pips / sl_pips, 2),
                                lot_size=0,
                                reason=f"Pullback to EMA20, RSI {rsi:.0f}",
                                confidence=75,
                                session="LONDON" if hour < 13 else "NY_OVERLAP",
                                timestamp=current_candle["datetime"]
                            )
        
        return signal


class IntradayStrategy:
    """
    STRATEGY 2: INTRADAY - Trend Continuation
    
    Analysis Timeframe: H1
    Entry Timeframe: M15
    Session: London & New York
    Target: 30-80 pips
    Max trades/day: 1-3
    
    Entry conditions (BUY):
    - EMA 50 > EMA 200 on H1 (uptrend)
    - Clear bullish structure (HH/HL)
    - Pullback to EMA 50 or support
    - M15 confirmation (engulfing or rejection)
    
    Risk: 1% per trade, SL 15-30 pips, TP 2R minimum
    """
    
    def __init__(self):
        self.name = "INTRADAY"
        self.max_trades_per_day = 3
        self.max_consecutive_losses = 2
        self.min_sl_pips = 15
        self.max_sl_pips = 30
        self.min_rr = 2.0
        self.target_rr = 2.5
    
    def is_valid_session(self, hour: int) -> bool:
        """Check if in valid session"""
        # London + NY: 8-21 UTC
        return 8 <= hour <= 21
    
    def analyze(
        self,
        candles_h1: List[Dict],
        candles_m15: List[Dict],
        current_index_h1: int,
        current_index_m15: int,
        symbol: str = "EURUSD"
    ) -> Optional[TradeSignal]:
        """
        Analyze for intraday entry
        Uses H1 for trend, M15 for entry
        """
        if current_index_h1 < 200 or current_index_m15 < 20:
            return None
        
        # Check session
        current_candle = candles_m15[current_index_m15]
        hour = current_candle["datetime"].hour
        
        if not self.is_valid_session(hour):
            return None
        
        # H1 Analysis
        h1_closes = [c["close"] for c in candles_h1[:current_index_h1 + 1]]
        h1_highs = [c["high"] for c in candles_h1[:current_index_h1 + 1]]
        h1_lows = [c["low"] for c in candles_h1[:current_index_h1 + 1]]
        
        ema50_h1 = TechnicalAnalysis.ema(h1_closes, 50)
        ema200_h1 = TechnicalAnalysis.ema(h1_closes, 200)
        
        current_ema50 = ema50_h1[-1]
        current_ema200 = ema200_h1[-1]
        
        # M15 Analysis
        m15_closes = [c["close"] for c in candles_m15[:current_index_m15 + 1]]
        m15_highs = [c["high"] for c in candles_m15[:current_index_m15 + 1]]
        m15_lows = [c["low"] for c in candles_m15[:current_index_m15 + 1]]
        
        current_price = m15_closes[-1]
        
        # Detect structure on H1 - more lenient
        structure = TechnicalAnalysis.detect_structure(h1_highs[-20:], h1_lows[-20:])
        
        # Find support/resistance on H1
        h1_support = TechnicalAnalysis.find_swing_low(h1_lows[-50:], 20)
        h1_resistance = TechnicalAnalysis.find_swing_high(h1_highs[-50:], 20)
        
        # Calculate RSI for additional confirmation
        rsi = TechnicalAnalysis.rsi(m15_closes, 14)
        
        signal = None
        
        # ========== BUY SETUP ==========
        if current_ema50 > current_ema200:  # H1 Uptrend
            # More lenient structure check
            if structure in ["BULLISH", "RANGING"]:
                # Check pullback to EMA50 or support - wider threshold
                near_ema50 = abs(current_price - current_ema50) / current_price < 0.004  # Within 40 pips
                near_support = abs(current_price - h1_support) / current_price < 0.005
                
                # Price should be above support
                above_support = current_price > h1_support
                
                if (near_ema50 or near_support) and above_support:
                    # M15 confirmation - engulfing, rejection, or RSI oversold reversal
                    is_engulfing = TechnicalAnalysis.is_bullish_engulfing(candles_m15, current_index_m15)
                    is_rejection = TechnicalAnalysis.is_bullish_rejection(candles_m15[current_index_m15])
                    rsi_reversal = rsi < 40  # RSI in oversold zone
                    
                    if is_engulfing or is_rejection or rsi_reversal:
                        # Calculate SL below M15 swing low
                        m15_swing_low = TechnicalAnalysis.find_swing_low(m15_lows[-10:], 5)
                        sl_price = m15_swing_low - 0.0003  # 3 pips buffer
                        sl_pips = (current_price - sl_price) * 10000
                        
                        if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                            tp_pips = sl_pips * self.min_rr
                            tp_price = current_price + (tp_pips / 10000)
                            
                            # Don't cap at resistance if it's too close
                            if h1_resistance > current_price * 1.003:  # At least 30 pips away
                                tp_price = min(tp_price, h1_resistance)
                            
                            actual_tp_pips = (tp_price - current_price) * 10000
                            
                            if actual_tp_pips / sl_pips >= 1.5:  # Minimum 1.5:1 RR
                                signal = TradeSignal(
                                    symbol=symbol,
                                    direction="BUY",
                                    strategy=self.name,
                                    entry_price=current_price,
                                    stop_loss=sl_price,
                                    take_profit=tp_price,
                                    sl_pips=round(sl_pips, 1),
                                    tp_pips=round(actual_tp_pips, 1),
                                    risk_reward=round(actual_tp_pips / sl_pips, 2),
                                    lot_size=0,
                                    reason=f"H1 uptrend, pullback, RSI {rsi:.0f}",
                                    confidence=80,
                                    session="LONDON" if hour < 13 else "NEW_YORK",
                                    timestamp=current_candle["datetime"]
                                )
        
        # ========== SELL SETUP ==========
        elif current_ema50 < current_ema200:  # H1 Downtrend
            if structure in ["BEARISH", "RANGING"]:
                near_ema50 = abs(current_price - current_ema50) / current_price < 0.004
                near_resistance = abs(current_price - h1_resistance) / current_price < 0.005
                below_resistance = current_price < h1_resistance
                
                if (near_ema50 or near_resistance) and below_resistance:
                    is_engulfing = TechnicalAnalysis.is_bearish_engulfing(candles_m15, current_index_m15)
                    is_rejection = TechnicalAnalysis.is_bearish_rejection(candles_m15[current_index_m15])
                    rsi_reversal = rsi > 60
                    
                    if is_engulfing or is_rejection or rsi_reversal:
                        m15_swing_high = TechnicalAnalysis.find_swing_high(m15_highs[-10:], 5)
                        sl_price = m15_swing_high + 0.0003
                        sl_pips = (sl_price - current_price) * 10000
                        
                        if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                            tp_pips = sl_pips * self.min_rr
                            tp_price = current_price - (tp_pips / 10000)
                            
                            if h1_support < current_price * 0.997:
                                tp_price = max(tp_price, h1_support)
                            
                            actual_tp_pips = (current_price - tp_price) * 10000
                            
                            if actual_tp_pips / sl_pips >= 1.5:
                                signal = TradeSignal(
                                    symbol=symbol,
                                    direction="SELL",
                                    strategy=self.name,
                                    entry_price=current_price,
                                    stop_loss=sl_price,
                                    take_profit=tp_price,
                                    sl_pips=round(sl_pips, 1),
                                    tp_pips=round(actual_tp_pips, 1),
                                    risk_reward=round(actual_tp_pips / sl_pips, 2),
                                    lot_size=0,
                                    reason=f"H1 downtrend, pullback, RSI {rsi:.0f}",
                                    confidence=80,
                                    session="LONDON" if hour < 13 else "NEW_YORK",
                                    timestamp=current_candle["datetime"]
                                )
        
        return signal


class ProfessionalRiskManager:
    """
    Professional risk management for FTMO compliance
    
    Rules:
    - 1% max risk per trade
    - 4.5% max daily loss → stop trading for the day
    - 8% max total drawdown → stop all trading
    - No correlated pairs simultaneously
    """
    
    def __init__(
        self,
        initial_balance: float = 10000,
        max_risk_per_trade: float = 0.01,  # 1%
        max_daily_loss: float = 0.045,     # 4.5%
        max_total_drawdown: float = 0.08   # 8%
    ):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_total_drawdown = max_total_drawdown
        
        # State tracking
        self.daily_starting_balance = initial_balance
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.peak_balance = initial_balance
        
        # Strategy states
        self.scalping_state = StrategyState()
        self.intraday_state = StrategyState()
        
        # Active positions tracking (for correlation check)
        self.active_positions: Dict[str, str] = {}  # symbol -> direction
    
    def reset_daily(self):
        """Reset daily tracking"""
        self.daily_starting_balance = self.current_balance
        self.daily_pnl = 0.0
        self.scalping_state.daily_trades = 0
        self.scalping_state.daily_losses = 0
        self.scalping_state.consecutive_losses = 0
        self.scalping_state.is_stopped_today = False
        self.intraday_state.daily_trades = 0
        self.intraday_state.daily_losses = 0
        self.intraday_state.consecutive_losses = 0
        self.intraday_state.is_stopped_today = False
    
    def calculate_lot_size(self, sl_pips: float, symbol: str = "EURUSD") -> float:
        """
        Calculate position size for exactly 1% risk
        
        Formula: Lot Size = Risk Amount / (SL pips × Pip Value per Lot)
        """
        risk_amount = self.current_balance * self.max_risk_per_trade
        
        # Pip value per standard lot (100,000 units)
        # For EUR/USD, pip value ≈ $10 per standard lot
        pip_value_per_lot = 10.0
        
        # Adjust for JPY pairs
        if "JPY" in symbol:
            pip_value_per_lot = 1000 / 100  # Approximate
        
        lot_size = risk_amount / (sl_pips * pip_value_per_lot)
        
        # Round to 2 decimals, min 0.01 lot
        return max(0.01, round(lot_size, 2))
    
    def can_open_trade(
        self,
        signal: TradeSignal,
        strategy_state: StrategyState
    ) -> Tuple[bool, str]:
        """Check if trade can be opened based on all risk rules"""
        
        # Check global stop
        if strategy_state.is_stopped_global:
            return False, "Global stop active (8% drawdown)"
        
        # Check daily stop
        if strategy_state.is_stopped_today:
            return False, f"Daily stop: {strategy_state.stop_reason}"
        
        # Check daily loss limit
        daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_balance if self.daily_pnl < 0 else 0
        if daily_loss_pct >= self.max_daily_loss:
            strategy_state.is_stopped_today = True
            strategy_state.stop_reason = f"Daily loss limit reached ({daily_loss_pct*100:.2f}%)"
            return False, strategy_state.stop_reason
        
        # Check total drawdown
        total_dd = (self.peak_balance - self.current_balance) / self.peak_balance
        if total_dd >= self.max_total_drawdown:
            strategy_state.is_stopped_global = True
            strategy_state.stop_reason = f"Max drawdown reached ({total_dd*100:.2f}%)"
            return False, strategy_state.stop_reason
        
        # Check consecutive losses
        if signal.strategy == "SCALPING":
            max_consec = 3
            max_daily = 8
        else:
            max_consec = 2
            max_daily = 3
        
        if strategy_state.consecutive_losses >= max_consec:
            strategy_state.is_stopped_today = True
            strategy_state.stop_reason = f"{max_consec} consecutive losses"
            return False, strategy_state.stop_reason
        
        # Check max daily trades
        if strategy_state.daily_trades >= max_daily:
            return False, f"Max daily trades reached ({max_daily})"
        
        # Check correlation (no 2 USD pairs simultaneously)
        base_currency = signal.symbol[:3]
        quote_currency = signal.symbol[3:]
        
        for active_symbol in self.active_positions:
            if base_currency in active_symbol or quote_currency in active_symbol:
                if active_symbol != signal.symbol:
                    return False, f"Correlated position already open ({active_symbol})"
        
        # Check remaining risk capacity
        potential_loss = self.current_balance * self.max_risk_per_trade
        remaining_daily_capacity = (self.max_daily_loss * self.daily_starting_balance) - abs(min(0, self.daily_pnl))
        
        if potential_loss > remaining_daily_capacity:
            return False, "Insufficient daily risk capacity"
        
        return True, "OK"
    
    def record_trade_open(self, signal: TradeSignal):
        """Record trade opening"""
        self.active_positions[signal.symbol] = signal.direction
        
        state = self.scalping_state if signal.strategy == "SCALPING" else self.intraday_state
        state.daily_trades += 1
    
    def record_trade_close(self, signal: TradeSignal, pnl: float):
        """Record trade closing and update stats"""
        # Remove from active positions
        if signal.symbol in self.active_positions:
            del self.active_positions[signal.symbol]
        
        # Update balances
        self.current_balance += pnl
        self.daily_pnl += pnl
        self.total_pnl += pnl
        
        # Update peak balance
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        # Update strategy state
        state = self.scalping_state if signal.strategy == "SCALPING" else self.intraday_state
        
        if pnl < 0:
            state.daily_losses += 1
            state.consecutive_losses += 1
        else:
            state.consecutive_losses = 0
    
    def get_status(self) -> Dict:
        """Get current risk status"""
        daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_balance * 100 if self.daily_pnl < 0 else 0
        total_dd_pct = (self.peak_balance - self.current_balance) / self.peak_balance * 100
        
        return {
            "current_balance": round(self.current_balance, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_percent": round(self.daily_pnl / self.daily_starting_balance * 100, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_percent": round(self.total_pnl / self.initial_balance * 100, 2),
            "max_drawdown_percent": round(total_dd_pct, 2),
            "daily_loss_limit_used": round(daily_loss_pct, 2),
            "daily_loss_limit": self.max_daily_loss * 100,
            "total_dd_limit_used": round(total_dd_pct, 2),
            "total_dd_limit": self.max_total_drawdown * 100,
            "scalping_stopped": self.scalping_state.is_stopped_today or self.scalping_state.is_stopped_global,
            "intraday_stopped": self.intraday_state.is_stopped_today or self.intraday_state.is_stopped_global,
            "can_trade": not (self.scalping_state.is_stopped_global and self.intraday_state.is_stopped_global)
        }


# Export strategies
scalping_strategy = ScalpingStrategy()
intraday_strategy = IntradayStrategy()
