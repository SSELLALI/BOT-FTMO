"""
FTMO Professional Trading Strategies - AGGRESSIVE MODE
Maximizes trade frequency while strictly respecting FTMO risk rules.

Strategy 1: SCALPING - Multi-Signal Momentum (M15, 8-20 pips)
Strategy 2: INTRADAY - Trend Momentum + Breakout (H1/M15, 25-70 pips)

HARD SAFETY BARRIERS:
- 1% max risk per trade (position sizing)
- 4.5% max daily loss -> STOP trading for the day
- 8% max total drawdown -> STOP all trading permanently
- Stop after 3 consecutive losses (scalping) / 2 (intraday)
"""
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TradingSession(Enum):
    ASIAN = (0, 8)
    LONDON = (8, 16)
    NEW_YORK = (13, 21)
    OVERLAP = (13, 16)


@dataclass
class TradeSignal:
    symbol: str
    direction: str
    strategy: str
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
    daily_trades: int = 0
    daily_losses: int = 0
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    is_stopped_today: bool = False
    is_stopped_global: bool = False
    stop_reason: str = ""


class TechnicalAnalysis:
    """Optimized technical analysis utilities"""

    @staticmethod
    def ema(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return [prices[-1]] * len(prices)
        multiplier = 2 / (period + 1)
        ema_values = [np.mean(prices[:period])]
        for price in prices[period:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        padding = [ema_values[0]] * (len(prices) - len(ema_values))
        return padding + ema_values

    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
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
    def atr(candles: List[Dict], period: int = 14) -> float:
        """Average True Range from candle data"""
        if len(candles) < period + 1:
            return 0.001
        tr_list = []
        for i in range(-period, 0):
            c = candles[i]
            prev_close = candles[i - 1]["close"]
            tr = max(
                c["high"] - c["low"],
                abs(c["high"] - prev_close),
                abs(c["low"] - prev_close)
            )
            tr_list.append(tr)
        return np.mean(tr_list)

    @staticmethod
    def stochastic(closes: List[float], highs: List[float], lows: List[float], k_period: int = 14, d_period: int = 3) -> Tuple[float, float]:
        """Stochastic oscillator %K and %D"""
        if len(closes) < k_period:
            return 50.0, 50.0
        recent_highs = highs[-k_period:]
        recent_lows = lows[-k_period:]
        highest = max(recent_highs)
        lowest = min(recent_lows)
        if highest == lowest:
            return 50.0, 50.0
        k = ((closes[-1] - lowest) / (highest - lowest)) * 100
        # Simplified %D
        k_values = []
        for i in range(min(d_period, len(closes) - k_period + 1)):
            idx = -(i + 1)
            h = max(highs[idx - k_period + 1:idx + 1]) if abs(idx) + k_period <= len(highs) else highest
            lo = min(lows[idx - k_period + 1:idx + 1]) if abs(idx) + k_period <= len(lows) else lowest
            if h != lo:
                k_values.append(((closes[idx] - lo) / (h - lo)) * 100)
        d = np.mean(k_values) if k_values else k
        return k, d

    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
        """Bollinger Bands: upper, middle, lower"""
        if len(prices) < period:
            return prices[-1] + 0.001, prices[-1], prices[-1] - 0.001
        recent = prices[-period:]
        middle = np.mean(recent)
        std = np.std(recent)
        return middle + std_dev * std, middle, middle - std_dev * std

    @staticmethod
    def momentum(prices: List[float], period: int = 10) -> float:
        """Price momentum (rate of change)"""
        if len(prices) < period + 1:
            return 0.0
        return (prices[-1] - prices[-period - 1]) / prices[-period - 1] * 100

    @staticmethod
    def find_swing_high(highs: List[float], lookback: int = 10) -> float:
        if len(highs) < lookback:
            return max(highs)
        return max(highs[-lookback:])

    @staticmethod
    def find_swing_low(lows: List[float], lookback: int = 10) -> float:
        if len(lows) < lookback:
            return min(lows)
        return min(lows[-lookback:])

    @staticmethod
    def is_bullish_candle(candle: Dict) -> bool:
        body = candle["close"] - candle["open"]
        total_range = candle["high"] - candle["low"]
        return body > 0 and total_range > 0 and body / total_range > 0.4

    @staticmethod
    def is_bearish_candle(candle: Dict) -> bool:
        body = candle["open"] - candle["close"]
        total_range = candle["high"] - candle["low"]
        return body > 0 and total_range > 0 and body / total_range > 0.4

    @staticmethod
    def is_bullish_engulfing(candles: List[Dict], index: int) -> bool:
        if index < 1:
            return False
        prev = candles[index - 1]
        curr = candles[index]
        return (prev["close"] < prev["open"] and
                curr["close"] > curr["open"] and
                curr["open"] <= prev["close"] and
                curr["close"] >= prev["open"])

    @staticmethod
    def is_bearish_engulfing(candles: List[Dict], index: int) -> bool:
        if index < 1:
            return False
        prev = candles[index - 1]
        curr = candles[index]
        return (prev["close"] > prev["open"] and
                curr["close"] < curr["open"] and
                curr["open"] >= prev["close"] and
                curr["close"] <= prev["open"])

    @staticmethod
    def is_bullish_rejection(candle: Dict) -> bool:
        body = abs(candle["close"] - candle["open"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        return body > 0 and lower_wick > body * 1.5 and upper_wick < body * 0.5

    @staticmethod
    def is_bearish_rejection(candle: Dict) -> bool:
        body = abs(candle["close"] - candle["open"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        return body > 0 and upper_wick > body * 1.5 and lower_wick < body * 0.5


class ScalpingStrategy:
    """
    AGGRESSIVE SCALPING - Multi-Signal Momentum

    Timeframe: M15
    Sessions: London (08-16 UTC), overlap emphasis
    Target: 8-20 pips, R:R 1.5-2.5
    Max trades/day: 10

    Entry signals (multiple methods):
    1. EMA pullback + momentum confirmation
    2. Bollinger Band bounce + RSI divergence
    3. Strong candle pattern + trend alignment

    All entries require:
    - EMA 9 and EMA 21 aligned with trade direction
    - RSI not at extreme (no buying above 75, no selling below 25)
    - ATR filter for minimum volatility
    """

    def __init__(self):
        self.name = "SCALPING"
        self.max_trades_per_day = 10
        self.max_consecutive_losses = 3
        self.min_sl_pips = 5
        self.max_sl_pips = 20
        self.min_rr = 1.5
        self.fast_ema_period = 15
        self.slow_ema_period = 30
        self.atr_multiplier = 2.0

    def is_valid_session(self, hour: int) -> bool:
        return 7 <= hour <= 17  # Extended London + early NY

    def analyze(self, candles: List[Dict], current_index: int, symbol: str = "EURUSD") -> Optional[TradeSignal]:
        if current_index < 50:
            return None

        current_candle = candles[current_index]
        hour = current_candle["datetime"].hour
        if not self.is_valid_session(hour):
            return None

        # Extract data
        closes = [c["close"] for c in candles[:current_index + 1]]

        # Indicators (optimized: EMA 15/30 instead of 9/21)
        ema_fast = TechnicalAnalysis.ema(closes, self.fast_ema_period)
        ema_slow = TechnicalAnalysis.ema(closes, self.slow_ema_period)
        rsi = TechnicalAnalysis.rsi(closes, 14)
        atr = TechnicalAnalysis.atr(candles[:current_index + 1], 14)
        bb_upper, bb_mid, bb_lower = TechnicalAnalysis.bollinger_bands(closes, 20, 2.0)
        momentum = TechnicalAnalysis.momentum(closes, 8)

        current_price = closes[-1]
        cur_fast = ema_fast[-1]
        cur_slow = ema_slow[-1]
        prev_fast = ema_fast[-2]

        # Minimum volatility filter (skip very quiet markets)
        min_atr = 0.00025 if "JPY" not in symbol else 0.025
        if atr < min_atr:
            return None

        signal = None

        # =============== BUY SETUPS ===============
        ema_bullish = cur_ema9 > cur_ema21
        rsi_ok_buy = 30 <= rsi <= 72

        if ema_bullish and rsi_ok_buy:
            # Aggressive: EMA trend is already filtering. Need just 1 confirmation
            entry_triggered = False
            reason = ""
            prev_candle = candles[current_index - 1]

            # Signal 1: Price bounced from EMA9 area
            near_ema9 = abs(prev_candle["low"] - prev_ema9) / current_price < 0.0006
            if near_ema9 and current_price > prev_candle["high"]:
                entry_triggered = True
                reason = f"EMA9 bounce, RSI {rsi:.0f}"

            # Signal 2: Bullish candle pattern
            if not entry_triggered:
                if (TechnicalAnalysis.is_bullish_engulfing(candles, current_index) or
                        TechnicalAnalysis.is_bullish_rejection(current_candle)):
                    entry_triggered = True
                    reason = f"Bullish pattern, RSI {rsi:.0f}"

            # Signal 3: Strong momentum candle in trend
            if not entry_triggered and TechnicalAnalysis.is_bullish_candle(current_candle):
                body = current_candle["close"] - current_candle["open"]
                if body > atr * 0.4 and momentum > 0:
                    entry_triggered = True
                    reason = f"Momentum candle, RSI {rsi:.0f}"

            # Signal 4: Price crossed above EMA21 with momentum
            if not entry_triggered:
                if prev_candle["close"] <= cur_ema21 and current_price > cur_ema21 and momentum > 0:
                    entry_triggered = True
                    reason = f"EMA21 breakout, RSI {rsi:.0f}"

            # Signal 5: BB lower band reversal
            if not entry_triggered and current_price <= bb_lower * 1.001:
                if TechnicalAnalysis.is_bullish_candle(current_candle):
                    entry_triggered = True
                    reason = f"BB lower reversal, RSI {rsi:.0f}"

            if entry_triggered:
                # Dynamic SL based on ATR
                sl_distance = max(atr * 1.2, self.min_sl_pips / 10000)
                sl_price = current_price - sl_distance
                sl_pips = (current_price - sl_price) * 10000

                if "JPY" in symbol:
                    sl_pips = (current_price - sl_price) * 100

                # Clamp SL
                if sl_pips < self.min_sl_pips:
                    sl_pips = self.min_sl_pips
                    sl_price = current_price - (sl_pips / 10000)
                elif sl_pips > self.max_sl_pips:
                    sl_pips = self.max_sl_pips
                    sl_price = current_price - (sl_pips / 10000)

                tp_pips = sl_pips * self.min_rr
                tp_price = current_price + (tp_pips / 10000)

                # Confidence
                confidence = 70
                if 13 <= hour <= 16:
                    confidence += 5  # Overlap bonus

                signal = TradeSignal(
                    symbol=symbol,
                    direction="BUY",
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=round(sl_price, 5),
                    take_profit=round(tp_price, 5),
                    sl_pips=round(sl_pips, 1),
                    tp_pips=round(tp_pips, 1),
                    risk_reward=round(tp_pips / sl_pips, 2),
                    lot_size=0,
                    reason=reason,
                    confidence=min(90, confidence),
                    session="LONDON" if hour < 13 else "NY_OVERLAP",
                    timestamp=current_candle["datetime"]
                )

        # =============== SELL SETUPS ===============
        ema_bearish = cur_ema9 < cur_ema21
        rsi_ok_sell = 28 <= rsi <= 70

        if signal is None and ema_bearish and rsi_ok_sell:
            entry_triggered = False
            reason = ""
            prev_candle = candles[current_index - 1]

            # Signal 1: EMA9 rejection
            near_ema9 = abs(prev_candle["high"] - prev_ema9) / current_price < 0.0006
            if near_ema9 and current_price < prev_candle["low"]:
                entry_triggered = True
                reason = f"EMA9 rejection, RSI {rsi:.0f}"

            # Signal 2: Bearish pattern
            if not entry_triggered:
                if (TechnicalAnalysis.is_bearish_engulfing(candles, current_index) or
                        TechnicalAnalysis.is_bearish_rejection(current_candle)):
                    entry_triggered = True
                    reason = f"Bearish pattern, RSI {rsi:.0f}"

            # Signal 3: Strong bearish momentum
            if not entry_triggered and TechnicalAnalysis.is_bearish_candle(current_candle):
                body = current_candle["open"] - current_candle["close"]
                if body > atr * 0.4 and momentum < 0:
                    entry_triggered = True
                    reason = f"Bearish momentum, RSI {rsi:.0f}"

            # Signal 4: Break below EMA21
            if not entry_triggered:
                if prev_candle["close"] >= cur_ema21 and current_price < cur_ema21 and momentum < 0:
                    entry_triggered = True
                    reason = f"EMA21 breakdown, RSI {rsi:.0f}"

            # Signal 5: BB upper band rejection
            if not entry_triggered and current_price >= bb_upper * 0.999:
                if TechnicalAnalysis.is_bearish_candle(current_candle):
                    entry_triggered = True
                    reason = f"BB upper rejection, RSI {rsi:.0f}"

            if entry_triggered:
                reason_text = reason
                sl_distance = max(atr * 1.2, self.min_sl_pips / 10000)
                sl_price = current_price + sl_distance
                sl_pips = (sl_price - current_price) * 10000

                if sl_pips < self.min_sl_pips:
                    sl_pips = self.min_sl_pips
                    sl_price = current_price + (sl_pips / 10000)
                elif sl_pips > self.max_sl_pips:
                    sl_pips = self.max_sl_pips
                    sl_price = current_price + (sl_pips / 10000)

                tp_pips = sl_pips * self.min_rr
                tp_price = current_price - (tp_pips / 10000)

                confidence = 70
                if 13 <= hour <= 16:
                    confidence += 5

                signal = TradeSignal(
                    symbol=symbol,
                    direction="SELL",
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=round(sl_price, 5),
                    take_profit=round(tp_price, 5),
                    sl_pips=round(sl_pips, 1),
                    tp_pips=round(tp_pips, 1),
                    risk_reward=round(tp_pips / sl_pips, 2),
                    lot_size=0,
                    reason=reason_text,
                    confidence=min(90, confidence),
                    session="LONDON" if hour < 13 else "NY_OVERLAP",
                    timestamp=current_candle["datetime"]
                )

        return signal


class IntradayStrategy:
    """
    AGGRESSIVE INTRADAY - Trend Momentum + Breakout

    Analysis: H1 | Entry: M15
    Sessions: London + New York (08-21 UTC)
    Target: 25-70 pips, R:R 2.0-3.0
    Max trades/day: 5

    Entry signals:
    1. Trend continuation after H1 pullback
    2. Breakout of H1 structure (support/resistance)
    3. EMA50/200 zone bounce on H1 + M15 confirmation

    All entries require:
    - H1 trend alignment (EMA 50 vs 200)
    - M15 candle pattern confirmation
    - RSI not extreme
    """

    def __init__(self):
        self.name = "INTRADAY"
        self.max_trades_per_day = 5
        self.max_consecutive_losses = 2
        self.min_sl_pips = 12
        self.max_sl_pips = 35
        self.min_rr = 2.0

    def is_valid_session(self, hour: int) -> bool:
        return 7 <= hour <= 21

    def analyze(
        self,
        candles_h1: List[Dict],
        candles_m15: List[Dict],
        current_index_h1: int,
        current_index_m15: int,
        symbol: str = "EURUSD"
    ) -> Optional[TradeSignal]:
        if current_index_h1 < 200 or current_index_m15 < 30:
            return None

        current_candle = candles_m15[current_index_m15]
        hour = current_candle["datetime"].hour
        if not self.is_valid_session(hour):
            return None

        # H1 data
        h1_closes = [c["close"] for c in candles_h1[:current_index_h1 + 1]]
        h1_highs = [c["high"] for c in candles_h1[:current_index_h1 + 1]]
        h1_lows = [c["low"] for c in candles_h1[:current_index_h1 + 1]]

        ema50_h1 = TechnicalAnalysis.ema(h1_closes, 50)
        ema200_h1 = TechnicalAnalysis.ema(h1_closes, 200)

        cur_ema50 = ema50_h1[-1]
        cur_ema200 = ema200_h1[-1]

        # H1 structure
        h1_swing_high = TechnicalAnalysis.find_swing_high(h1_highs[-20:], 10)
        h1_swing_low = TechnicalAnalysis.find_swing_low(h1_lows[-20:], 10)
        h1_atr = TechnicalAnalysis.atr(candles_h1[:current_index_h1 + 1], 14)

        # M15 data
        m15_closes = [c["close"] for c in candles_m15[:current_index_m15 + 1]]
        m15_highs = [c["high"] for c in candles_m15[:current_index_m15 + 1]]
        m15_lows = [c["low"] for c in candles_m15[:current_index_m15 + 1]]
        current_price = m15_closes[-1]

        rsi_m15 = TechnicalAnalysis.rsi(m15_closes, 14)
        ema9_m15 = TechnicalAnalysis.ema(m15_closes, 9)
        ema21_m15 = TechnicalAnalysis.ema(m15_closes, 21)
        momentum_m15 = TechnicalAnalysis.momentum(m15_closes, 8)

        signal = None

        # =============== BUY SETUPS ===============
        h1_bullish = cur_ema50 > cur_ema200
        rsi_buy_ok = rsi_m15 < 68

        if h1_bullish and rsi_buy_ok:
            entry_triggered = False
            reason = ""

            # Setup 1: H1 pullback to EMA50 zone + M15 confirmation
            near_ema50 = current_price <= cur_ema50 * 1.004 and current_price >= cur_ema50 * 0.994
            if near_ema50:
                m15_bullish = (TechnicalAnalysis.is_bullish_engulfing(candles_m15, current_index_m15) or
                               TechnicalAnalysis.is_bullish_rejection(current_candle) or
                               TechnicalAnalysis.is_bullish_candle(current_candle))
                if m15_bullish and momentum_m15 > -0.05:
                    entry_triggered = True
                    reason = f"H1 EMA50 pullback + M15 bullish, RSI {rsi_m15:.0f}"

            # Setup 2: H1 support bounce
            if not entry_triggered:
                near_support = abs(current_price - h1_swing_low) / current_price < 0.005
                above_support = current_price > h1_swing_low * 0.998
                if near_support and above_support:
                    m15_bullish = (TechnicalAnalysis.is_bullish_candle(current_candle) or
                                   TechnicalAnalysis.is_bullish_engulfing(candles_m15, current_index_m15))
                    if m15_bullish:
                        entry_triggered = True
                        reason = f"H1 support bounce {h1_swing_low:.5f}, RSI {rsi_m15:.0f}"

            # Setup 3: Breakout above H1 resistance
            if not entry_triggered:
                broke_resistance = current_price > h1_swing_high and candles_m15[current_index_m15 - 1]["close"] <= h1_swing_high
                if broke_resistance and momentum_m15 > 0.02:
                    entry_triggered = True
                    reason = f"H1 resistance breakout {h1_swing_high:.5f}, RSI {rsi_m15:.0f}"

            # Setup 4: M15 EMA crossover aligned with H1 trend
            if not entry_triggered:
                prev_ema9 = ema9_m15[-2]
                prev_ema21 = ema21_m15[-2]
                cur_e9 = ema9_m15[-1]
                cur_e21 = ema21_m15[-1]
                if prev_ema9 <= prev_ema21 and cur_e9 > cur_e21 and current_price > cur_ema50:
                    entry_triggered = True
                    reason = f"M15 EMA cross + H1 bullish, RSI {rsi_m15:.0f}"

            if entry_triggered:
                # Dynamic SL
                m15_swing_low = TechnicalAnalysis.find_swing_low(m15_lows[-10:], 5)
                sl_price = min(m15_swing_low, current_price - h1_atr * 0.5) - 0.0002
                sl_pips = (current_price - sl_price) * 10000

                if sl_pips < self.min_sl_pips:
                    sl_pips = self.min_sl_pips
                    sl_price = current_price - (sl_pips / 10000)
                elif sl_pips > self.max_sl_pips:
                    sl_pips = self.max_sl_pips
                    sl_price = current_price - (sl_pips / 10000)

                tp_pips = sl_pips * self.min_rr
                tp_price = current_price + (tp_pips / 10000)

                confidence = 70
                if 13 <= hour <= 16:
                    confidence += 5
                if momentum_m15 > 0.03:
                    confidence += 5
                if 40 <= rsi_m15 <= 55:
                    confidence += 5

                signal = TradeSignal(
                    symbol=symbol,
                    direction="BUY",
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=round(sl_price, 5),
                    take_profit=round(tp_price, 5),
                    sl_pips=round(sl_pips, 1),
                    tp_pips=round(tp_pips, 1),
                    risk_reward=round(tp_pips / sl_pips, 2),
                    lot_size=0,
                    reason=reason,
                    confidence=min(90, confidence),
                    session="LONDON" if hour < 13 else "NEW_YORK",
                    timestamp=current_candle["datetime"]
                )

        # =============== SELL SETUPS ===============
        h1_bearish = cur_ema50 < cur_ema200
        rsi_sell_ok = rsi_m15 > 32

        if signal is None and h1_bearish and rsi_sell_ok:
            entry_triggered = False
            reason = ""

            # Setup 1: H1 pullback to EMA50 zone + M15 confirmation
            near_ema50 = current_price >= cur_ema50 * 0.996 and current_price <= cur_ema50 * 1.006
            if near_ema50:
                m15_bearish = (TechnicalAnalysis.is_bearish_engulfing(candles_m15, current_index_m15) or
                               TechnicalAnalysis.is_bearish_rejection(current_candle) or
                               TechnicalAnalysis.is_bearish_candle(current_candle))
                if m15_bearish and momentum_m15 < 0.05:
                    entry_triggered = True
                    reason = f"H1 EMA50 pullback + M15 bearish, RSI {rsi_m15:.0f}"

            # Setup 2: H1 resistance rejection
            if not entry_triggered:
                near_resistance = abs(current_price - h1_swing_high) / current_price < 0.005
                below_resistance = current_price < h1_swing_high * 1.002
                if near_resistance and below_resistance:
                    m15_bearish = (TechnicalAnalysis.is_bearish_candle(current_candle) or
                                   TechnicalAnalysis.is_bearish_engulfing(candles_m15, current_index_m15))
                    if m15_bearish:
                        entry_triggered = True
                        reason = f"H1 resistance rejection {h1_swing_high:.5f}, RSI {rsi_m15:.0f}"

            # Setup 3: Breakout below H1 support
            if not entry_triggered:
                broke_support = current_price < h1_swing_low and candles_m15[current_index_m15 - 1]["close"] >= h1_swing_low
                if broke_support and momentum_m15 < -0.02:
                    entry_triggered = True
                    reason = f"H1 support breakdown {h1_swing_low:.5f}, RSI {rsi_m15:.0f}"

            # Setup 4: M15 EMA crossover aligned with H1
            if not entry_triggered:
                prev_ema9 = ema9_m15[-2]
                prev_ema21 = ema21_m15[-2]
                cur_e9 = ema9_m15[-1]
                cur_e21 = ema21_m15[-1]
                if prev_ema9 >= prev_ema21 and cur_e9 < cur_e21 and current_price < cur_ema50:
                    entry_triggered = True
                    reason = f"M15 EMA cross + H1 bearish, RSI {rsi_m15:.0f}"

            if entry_triggered:
                m15_swing_high = TechnicalAnalysis.find_swing_high(m15_highs[-10:], 5)
                sl_price = max(m15_swing_high, current_price + h1_atr * 0.5) + 0.0002
                sl_pips = (sl_price - current_price) * 10000

                if sl_pips < self.min_sl_pips:
                    sl_pips = self.min_sl_pips
                    sl_price = current_price + (sl_pips / 10000)
                elif sl_pips > self.max_sl_pips:
                    sl_pips = self.max_sl_pips
                    sl_price = current_price + (sl_pips / 10000)

                tp_pips = sl_pips * self.min_rr
                tp_price = current_price - (tp_pips / 10000)

                confidence = 70
                if 13 <= hour <= 16:
                    confidence += 5
                if momentum_m15 < -0.03:
                    confidence += 5
                if 45 <= rsi_m15 <= 60:
                    confidence += 5

                signal = TradeSignal(
                    symbol=symbol,
                    direction="SELL",
                    strategy=self.name,
                    entry_price=current_price,
                    stop_loss=round(sl_price, 5),
                    take_profit=round(tp_price, 5),
                    sl_pips=round(sl_pips, 1),
                    tp_pips=round(tp_pips, 1),
                    risk_reward=round(tp_pips / sl_pips, 2),
                    lot_size=0,
                    reason=reason,
                    confidence=min(90, confidence),
                    session="LONDON" if hour < 13 else "NEW_YORK",
                    timestamp=current_candle["datetime"]
                )

        return signal


class ProfessionalRiskManager:
    """
    HARD SAFETY BARRIERS - FTMO Compliance

    ABSOLUTE RULES (never bypassed):
    - 1% max risk per trade (position sizing)
    - 4.5% max daily loss -> IMMEDIATE stop for the day
    - 8% max total drawdown -> PERMANENT stop
    - 3 consecutive losses -> stop scalping for the day
    - 2 consecutive losses -> stop intraday for the day
    """

    def __init__(
        self,
        initial_balance: float = 10000,
        max_risk_per_trade: float = 0.01,
        max_daily_loss: float = 0.045,
        max_total_drawdown: float = 0.08
    ):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_total_drawdown = max_total_drawdown

        self.daily_starting_balance = initial_balance
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.peak_balance = initial_balance

        self.scalping_state = StrategyState()
        self.intraday_state = StrategyState()
        self.active_positions: Dict[str, str] = {}
        self.open_trade_count = 0
        self.max_concurrent_scalping = 1
        self.max_concurrent_intraday = 1
        self.max_concurrent_total = 1

    def reset_daily(self):
        self.daily_starting_balance = self.current_balance
        self.daily_pnl = 0.0
        self.scalping_state.daily_trades = 0
        self.scalping_state.daily_losses = 0
        self.scalping_state.consecutive_losses = 0
        self.scalping_state.is_stopped_today = False
        self.scalping_state.stop_reason = ""
        self.intraday_state.daily_trades = 0
        self.intraday_state.daily_losses = 0
        self.intraday_state.consecutive_losses = 0
        self.intraday_state.is_stopped_today = False
        self.intraday_state.stop_reason = ""

    def calculate_lot_size(self, sl_pips: float, symbol: str = "EURUSD") -> float:
        """Position size for exactly 1% risk (with safety buffer)"""
        risk_amount = self.current_balance * self.max_risk_per_trade * 0.95  # 5% safety buffer
        pip_value_per_lot = 10.0
        if "JPY" in symbol:
            pip_value_per_lot = 1000 / 100
        lot_size = risk_amount / (sl_pips * pip_value_per_lot)
        return max(0.01, round(lot_size, 2))

    def can_open_trade(self, signal: TradeSignal, strategy_state: StrategyState) -> Tuple[bool, str]:
        """
        SAFETY BARRIER CHECK - All rules enforced here
        Uses INITIAL BALANCE as reference for all % calculations (FTMO rule)
        """
        # BARRIER 1: Global stop (8% total drawdown from initial balance)
        if strategy_state.is_stopped_global:
            return False, "BARRIER: Global stop (8% max drawdown reached)"

        total_dd_amount = self.initial_balance - self.current_balance
        total_dd_pct = total_dd_amount / self.initial_balance if total_dd_amount > 0 else 0
        if total_dd_pct >= self.max_total_drawdown:
            strategy_state.is_stopped_global = True
            strategy_state.stop_reason = f"BARRIER: Max drawdown {total_dd_pct * 100:.2f}%"
            return False, strategy_state.stop_reason

        # BARRIER 2: Daily stop (4.5% daily loss from initial balance)
        if strategy_state.is_stopped_today:
            return False, f"BARRIER: Daily stop - {strategy_state.stop_reason}"

        daily_loss_abs = abs(self.daily_pnl) if self.daily_pnl < 0 else 0
        daily_loss_pct = daily_loss_abs / self.initial_balance
        if daily_loss_pct >= self.max_daily_loss:
            strategy_state.is_stopped_today = True
            strategy_state.stop_reason = f"Daily loss {daily_loss_pct * 100:.2f}%"
            return False, f"BARRIER: {strategy_state.stop_reason}"

        # BARRIER 3: Consecutive losses
        if signal.strategy == "SCALPING":
            max_consec = 3
            max_daily = 10
        else:
            max_consec = 2
            max_daily = 5

        if strategy_state.consecutive_losses >= max_consec:
            strategy_state.is_stopped_today = True
            strategy_state.stop_reason = f"{max_consec} consecutive losses"
            return False, f"BARRIER: {strategy_state.stop_reason}"

        # BARRIER 4: Max daily trades
        if strategy_state.daily_trades >= max_daily:
            return False, f"Max daily trades reached ({max_daily})"

        # BARRIER 5: Remaining daily risk capacity (based on initial balance - FTMO rule)
        potential_loss = self.current_balance * self.max_risk_per_trade * 0.95
        current_daily_loss = abs(min(0, self.daily_pnl))
        total_open_exposure = (self.open_trade_count + 1) * potential_loss
        if (current_daily_loss + total_open_exposure) / self.initial_balance > self.max_daily_loss:
            return False, "Would exceed daily loss limit with open exposure"

        # BARRIER 5b: Pre-trade total drawdown buffer (based on initial balance)
        total_loss_from_initial = self.initial_balance - self.current_balance
        if total_loss_from_initial > 0 and (total_loss_from_initial + potential_loss) / self.initial_balance >= self.max_total_drawdown:
            strategy_state.is_stopped_global = True
            strategy_state.stop_reason = "Approaching max drawdown limit"
            return False, "BARRIER: Would exceed total drawdown limit"

        # BARRIER 6: Max concurrent positions
        if self.open_trade_count >= self.max_concurrent_total:
            return False, f"Max concurrent positions ({self.max_concurrent_total})"

        if signal.strategy == "SCALPING" and self.open_trade_count >= self.max_concurrent_scalping:
            return False, "Max concurrent scalping positions"
        if signal.strategy == "INTRADAY" and self.open_trade_count >= self.max_concurrent_intraday:
            return False, "Max concurrent intraday positions"

        # BARRIER 7: Pre-trade exposure check
        # If all current open trades + this new one hit SL, would we breach 4.5% daily?
        total_potential_loss = (self.open_trade_count + 1) * self.current_balance * self.max_risk_per_trade
        current_daily_loss = abs(min(0, self.daily_pnl))
        if (current_daily_loss + total_potential_loss) / self.daily_starting_balance > self.max_daily_loss:
            return False, "Would exceed daily exposure limit with open positions"

        # BARRIER 8: No correlated positions
        for active_symbol in self.active_positions:
            if active_symbol != signal.symbol:
                base = signal.symbol[:3]
                quote = signal.symbol[3:]
                if base in active_symbol or quote in active_symbol:
                    return False, f"Correlated position open ({active_symbol})"

        return True, "OK"

    def record_trade_open(self, signal: TradeSignal):
        self.active_positions[signal.symbol] = signal.direction
        self.open_trade_count += 1
        state = self.scalping_state if signal.strategy == "SCALPING" else self.intraday_state
        state.daily_trades += 1

    def record_trade_close(self, signal: TradeSignal, pnl: float):
        if signal.symbol in self.active_positions:
            del self.active_positions[signal.symbol]
        self.open_trade_count = max(0, self.open_trade_count - 1)

        self.current_balance += pnl
        self.daily_pnl += pnl
        self.total_pnl += pnl

        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        state = self.scalping_state if signal.strategy == "SCALPING" else self.intraday_state
        if pnl < 0:
            state.daily_losses += 1
            state.consecutive_losses += 1
        else:
            state.consecutive_losses = 0

        # POST-TRADE SAFETY CHECK: immediately check daily & total limits (vs initial balance)
        daily_loss_pct = abs(self.daily_pnl) / self.initial_balance if self.daily_pnl < 0 else 0
        if daily_loss_pct >= self.max_daily_loss:
            self.scalping_state.is_stopped_today = True
            self.scalping_state.stop_reason = f"Daily loss limit post-trade ({daily_loss_pct * 100:.2f}%)"
            self.intraday_state.is_stopped_today = True
            self.intraday_state.stop_reason = f"Daily loss limit post-trade ({daily_loss_pct * 100:.2f}%)"

        total_dd_pct = (self.initial_balance - self.current_balance) / self.initial_balance if self.current_balance < self.initial_balance else 0
        if total_dd_pct >= self.max_total_drawdown:
            self.scalping_state.is_stopped_global = True
            self.scalping_state.stop_reason = f"Max drawdown post-trade ({total_dd_pct * 100:.2f}%)"
            self.intraday_state.is_stopped_global = True
            self.intraday_state.stop_reason = f"Max drawdown post-trade ({total_dd_pct * 100:.2f}%)"

    def get_status(self) -> Dict:
        daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_balance * 100 if self.daily_pnl < 0 else 0
        total_dd_pct = (self.peak_balance - self.current_balance) / self.peak_balance * 100 if self.peak_balance > 0 else 0
        return {
            "current_balance": round(self.current_balance, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_percent": round(self.daily_pnl / self.daily_starting_balance * 100, 2) if self.daily_starting_balance > 0 else 0,
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


scalping_strategy = ScalpingStrategy()
intraday_strategy = IntradayStrategy()
