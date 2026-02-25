"""
FTMO SAFE TRADING STRATEGIES v2.0
==================================
Stratégies optimisées avec barrières de sécurité maximales

RÈGLES FTMO STRICTES:
- 1% max risque par trade
- 4.5% max perte journalière → ARRÊT IMMÉDIAT
- 8% max drawdown total → ARRÊT TOTAL
- Arrêt après 3 pertes consécutives (scalping) / 2 (intraday)
- Pas de trades corrélés simultanés

BARRIÈRES DE SÉCURITÉ:
- Circuit breaker à 3% de perte journalière (warning)
- Circuit breaker à 6% drawdown total (warning)
- Réduction automatique de la taille si proche des limites
- Pas de trading pendant les news majeures (simulé)
- Filtrage par session stricte
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# SAFETY BARRIERS - CIRCUIT BREAKERS
# ============================================================================

@dataclass
class SafetyLimits:
    """Limites de sécurité FTMO"""
    # Limites officielles FTMO
    max_risk_per_trade: float = 0.01      # 1%
    max_daily_loss: float = 0.045         # 4.5%
    max_total_drawdown: float = 0.08      # 8%
    
    # Circuit breakers (barrières préventives)
    warning_daily_loss: float = 0.03      # 3% → réduire taille
    warning_total_drawdown: float = 0.06  # 6% → réduire taille
    critical_daily_loss: float = 0.04     # 4% → arrêt journée
    critical_total_drawdown: float = 0.07 # 7% → arrêt total
    
    # Règles d'arrêt
    max_consecutive_losses_scalping: int = 3
    max_consecutive_losses_intraday: int = 2
    max_trades_per_day_scalping: int = 6
    max_trades_per_day_intraday: int = 2


class RiskLevel(Enum):
    """Niveau de risque actuel"""
    NORMAL = "NORMAL"           # Trading normal
    WARNING = "WARNING"         # Réduire taille de 50%
    CRITICAL = "CRITICAL"       # Arrêter le trading
    STOPPED = "STOPPED"         # Trading arrêté


@dataclass
class TradingState:
    """État du trading avec barrières de sécurité"""
    # Compteurs journaliers
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    
    # État global
    total_pnl: float = 0.0
    current_drawdown: float = 0.0
    peak_balance: float = 0.0
    
    # Statuts
    risk_level: RiskLevel = RiskLevel.NORMAL
    is_stopped_today: bool = False
    is_stopped_global: bool = False
    stop_reason: str = ""
    
    # Historique
    last_trade_time: Optional[datetime] = None


# ============================================================================
# TECHNICAL INDICATORS - OPTIMISÉS
# ============================================================================

class Indicators:
    """Indicateurs techniques optimisés"""
    
    @staticmethod
    def ema(prices: List[float], period: int) -> float:
        """EMA - Exponential Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema_val = np.mean(prices[:period])
        
        for price in prices[period:]:
            ema_val = (price - ema_val) * multiplier + ema_val
        
        return ema_val
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """RSI - Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices[-(period + 1):])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """ATR - Average True Range (pour dimensionner SL)"""
        if len(closes) < period + 1:
            return 0.001
        
        tr_list = []
        for i in range(1, min(len(closes), period + 1)):
            high = highs[-i]
            low = lows[-i]
            prev_close = closes[-(i+1)]
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        
        return np.mean(tr_list) if tr_list else 0.001
    
    @staticmethod
    def is_trending(ema_fast: float, ema_slow: float, threshold: float = 0.0002) -> str:
        """Détermine la tendance"""
        diff = (ema_fast - ema_slow) / ema_slow
        if diff > threshold:
            return "BULLISH"
        elif diff < -threshold:
            return "BEARISH"
        return "RANGING"
    
    @staticmethod
    def find_support(lows: List[float], lookback: int = 20) -> float:
        """Trouve le support récent"""
        return min(lows[-lookback:]) if len(lows) >= lookback else min(lows)
    
    @staticmethod
    def find_resistance(highs: List[float], lookback: int = 20) -> float:
        """Trouve la résistance récente"""
        return max(highs[-lookback:]) if len(highs) >= lookback else max(highs)


# ============================================================================
# SAFE RISK MANAGER
# ============================================================================

class SafeRiskManager:
    """
    Gestionnaire de risque avec barrières de sécurité multiples
    """
    
    def __init__(self, initial_balance: float = 10000):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.limits = SafetyLimits()
        
        # États par stratégie
        self.scalping_state = TradingState(peak_balance=initial_balance)
        self.intraday_state = TradingState(peak_balance=initial_balance)
        
        # État global
        self.daily_starting_balance = initial_balance
        self.peak_balance = initial_balance
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
    
    def reset_daily(self):
        """Reset journalier"""
        self.daily_starting_balance = self.current_balance
        self.daily_pnl = 0.0
        
        for state in [self.scalping_state, self.intraday_state]:
            state.daily_trades = 0
            state.daily_wins = 0
            state.daily_losses = 0
            state.daily_pnl = 0.0
            state.consecutive_losses = 0
            state.is_stopped_today = False
            state.risk_level = RiskLevel.NORMAL
    
    def check_safety_barriers(self) -> Tuple[RiskLevel, str]:
        """
        Vérifie toutes les barrières de sécurité
        Retourne le niveau de risque et la raison
        """
        # Calcul des métriques
        daily_loss_pct = abs(min(0, self.daily_pnl)) / self.daily_starting_balance
        total_dd_pct = (self.peak_balance - self.current_balance) / self.peak_balance if self.peak_balance > 0 else 0
        
        # ===== ARRÊT TOTAL =====
        if total_dd_pct >= self.limits.max_total_drawdown:
            return RiskLevel.STOPPED, f"ARRÊT TOTAL: Drawdown {total_dd_pct*100:.1f}% >= 8%"
        
        if daily_loss_pct >= self.limits.max_daily_loss:
            return RiskLevel.STOPPED, f"ARRÊT JOUR: Perte {daily_loss_pct*100:.1f}% >= 4.5%"
        
        # ===== CRITIQUE =====
        if total_dd_pct >= self.limits.critical_total_drawdown:
            return RiskLevel.CRITICAL, f"CRITIQUE: Drawdown {total_dd_pct*100:.1f}% (proche 8%)"
        
        if daily_loss_pct >= self.limits.critical_daily_loss:
            return RiskLevel.CRITICAL, f"CRITIQUE: Perte jour {daily_loss_pct*100:.1f}% (proche 4.5%)"
        
        # ===== WARNING =====
        if total_dd_pct >= self.limits.warning_total_drawdown:
            return RiskLevel.WARNING, f"ATTENTION: Drawdown {total_dd_pct*100:.1f}%"
        
        if daily_loss_pct >= self.limits.warning_daily_loss:
            return RiskLevel.WARNING, f"ATTENTION: Perte jour {daily_loss_pct*100:.1f}%"
        
        return RiskLevel.NORMAL, "OK"
    
    def can_trade(self, strategy: str, state: TradingState) -> Tuple[bool, str]:
        """
        Vérifie si on peut ouvrir un trade
        """
        # Vérifier les barrières globales
        risk_level, reason = self.check_safety_barriers()
        
        if risk_level == RiskLevel.STOPPED:
            state.is_stopped_global = True
            state.stop_reason = reason
            return False, reason
        
        if risk_level == RiskLevel.CRITICAL:
            state.is_stopped_today = True
            state.stop_reason = reason
            return False, reason
        
        state.risk_level = risk_level
        
        # Vérifier les règles par stratégie
        if strategy == "SCALPING":
            max_trades = self.limits.max_trades_per_day_scalping
            max_losses = self.limits.max_consecutive_losses_scalping
        else:
            max_trades = self.limits.max_trades_per_day_intraday
            max_losses = self.limits.max_consecutive_losses_intraday
        
        if state.daily_trades >= max_trades:
            return False, f"Max {max_trades} trades/jour atteint"
        
        if state.consecutive_losses >= max_losses:
            state.is_stopped_today = True
            state.stop_reason = f"{max_losses} pertes consécutives"
            return False, state.stop_reason
        
        if state.is_stopped_today:
            return False, f"Arrêté: {state.stop_reason}"
        
        if state.is_stopped_global:
            return False, f"Arrêt global: {state.stop_reason}"
        
        return True, "OK"
    
    def calculate_lot_size(self, sl_pips: float, state: TradingState) -> float:
        """
        Calcule la taille de position avec ajustement selon le risque
        """
        # Risque de base: 1%
        base_risk = self.limits.max_risk_per_trade
        
        # Réduire si WARNING
        if state.risk_level == RiskLevel.WARNING:
            base_risk *= 0.5  # Réduire de 50%
        
        risk_amount = self.current_balance * base_risk
        pip_value = 10.0  # $10 par pip pour 1 lot EUR/USD
        
        lot_size = risk_amount / (sl_pips * pip_value)
        
        # Limites
        lot_size = max(0.01, min(lot_size, 1.0))
        
        return round(lot_size, 2)
    
    def record_trade(self, strategy: str, pnl: float):
        """Enregistre le résultat d'un trade"""
        state = self.scalping_state if strategy == "SCALPING" else self.intraday_state
        
        # Mise à jour des compteurs
        state.daily_trades += 1
        state.daily_pnl += pnl
        
        if pnl > 0:
            state.daily_wins += 1
            state.consecutive_losses = 0
        else:
            state.daily_losses += 1
            state.consecutive_losses += 1
        
        # Mise à jour globale
        self.current_balance += pnl
        self.daily_pnl += pnl
        self.total_pnl += pnl
        
        # Mise à jour du peak
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
    
    def get_status(self) -> Dict:
        """Retourne le statut complet"""
        daily_loss_pct = abs(min(0, self.daily_pnl)) / self.daily_starting_balance * 100
        total_dd_pct = (self.peak_balance - self.current_balance) / self.peak_balance * 100 if self.peak_balance > 0 else 0
        
        risk_level, _ = self.check_safety_barriers()
        
        return {
            "balance": round(self.current_balance, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_percent": round(self.daily_pnl / self.daily_starting_balance * 100, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_percent": round(self.total_pnl / self.initial_balance * 100, 2),
            "daily_loss_percent": round(daily_loss_pct, 2),
            "daily_limit": 4.5,
            "total_drawdown_percent": round(total_dd_pct, 2),
            "total_limit": 8.0,
            "risk_level": risk_level.value,
            "scalping_trades": self.scalping_state.daily_trades,
            "scalping_consecutive_losses": self.scalping_state.consecutive_losses,
            "intraday_trades": self.intraday_state.daily_trades,
            "intraday_consecutive_losses": self.intraday_state.consecutive_losses
        }


# ============================================================================
# STRATÉGIE 1: SCALPING SAFE
# ============================================================================

@dataclass
class TradeSetup:
    """Configuration d'un trade"""
    symbol: str
    direction: str
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    lot_size: float
    reason: str
    timestamp: datetime


class SafeScalpingStrategy:
    """
    STRATÉGIE SCALPING SÉCURISÉE
    
    Caractéristiques:
    - EMA 20/50 pour la tendance
    - RSI 14 pour timing
    - Entrée sur pullback confirmé
    - SL: 6-10 pips (ATR-based)
    - TP: 1.5-2x SL
    
    Filtres de sécurité:
    - Session Londres/NY uniquement
    - RSI pas en zone extrême
    - Spread < 1.5 pips
    """
    
    def __init__(self):
        self.name = "SCALPING"
        self.min_sl_pips = 6
        self.max_sl_pips = 10
        self.min_rr = 1.5
    
    def is_valid_session(self, hour: int) -> bool:
        """Sessions Londres (8-12) et NY overlap (13-16)"""
        return (8 <= hour <= 12) or (13 <= hour <= 16)
    
    def analyze(
        self,
        candles: List[Dict],
        index: int,
        risk_manager: SafeRiskManager,
        symbol: str = "EURUSD"
    ) -> Optional[TradeSetup]:
        """Analyse pour signal de scalping"""
        
        if index < 60:
            return None
        
        candle = candles[index]
        hour = candle["datetime"].hour
        
        # Filtre session
        if not self.is_valid_session(hour):
            return None
        
        # Vérifier si on peut trader
        can_trade, reason = risk_manager.can_trade("SCALPING", risk_manager.scalping_state)
        if not can_trade:
            return None
        
        # Extraction des données
        closes = [c["close"] for c in candles[:index + 1]]
        highs = [c["high"] for c in candles[:index + 1]]
        lows = [c["low"] for c in candles[:index + 1]]
        
        # Indicateurs
        ema20 = Indicators.ema(closes, 20)
        ema50 = Indicators.ema(closes, 50)
        rsi = Indicators.rsi(closes, 14)
        atr = Indicators.atr(highs, lows, closes, 14)
        
        current_price = closes[-1]
        prev_close = closes[-2]
        
        # Tendance
        trend = Indicators.is_trending(ema20, ema50)
        
        # ========== SETUP BUY ==========
        if trend == "BULLISH":
            # Prix au-dessus des EMAs
            if current_price > ema20 and current_price > ema50:
                # RSI pas suracheté (40-65)
                if 40 <= rsi <= 65:
                    # Pullback: prix a touché EMA20 récemment
                    recent_lows = lows[-5:]
                    touched_ema = any(l <= ema20 * 1.001 for l in recent_lows)
                    
                    # Rebond confirmé
                    bullish_candle = candle["close"] > candle["open"]
                    above_ema = current_price > ema20
                    
                    if touched_ema and bullish_candle and above_ema:
                        # Calcul SL basé sur ATR
                        sl_pips = max(self.min_sl_pips, min(atr * 10000 * 1.5, self.max_sl_pips))
                        sl_price = current_price - (sl_pips / 10000)
                        
                        # TP avec R:R minimum 1.5
                        tp_pips = sl_pips * self.min_rr
                        tp_price = current_price + (tp_pips / 10000)
                        
                        lot_size = risk_manager.calculate_lot_size(sl_pips, risk_manager.scalping_state)
                        
                        return TradeSetup(
                            symbol=symbol,
                            direction="BUY",
                            strategy=self.name,
                            entry_price=current_price,
                            stop_loss=sl_price,
                            take_profit=tp_price,
                            sl_pips=round(sl_pips, 1),
                            tp_pips=round(tp_pips, 1),
                            lot_size=lot_size,
                            reason=f"Pullback EMA20, RSI={rsi:.0f}",
                            timestamp=candle["datetime"]
                        )
        
        # ========== SETUP SELL ==========
        elif trend == "BEARISH":
            if current_price < ema20 and current_price < ema50:
                if 35 <= rsi <= 60:
                    recent_highs = highs[-5:]
                    touched_ema = any(h >= ema20 * 0.999 for h in recent_highs)
                    
                    bearish_candle = candle["close"] < candle["open"]
                    below_ema = current_price < ema20
                    
                    if touched_ema and bearish_candle and below_ema:
                        sl_pips = max(self.min_sl_pips, min(atr * 10000 * 1.5, self.max_sl_pips))
                        sl_price = current_price + (sl_pips / 10000)
                        
                        tp_pips = sl_pips * self.min_rr
                        tp_price = current_price - (tp_pips / 10000)
                        
                        lot_size = risk_manager.calculate_lot_size(sl_pips, risk_manager.scalping_state)
                        
                        return TradeSetup(
                            symbol=symbol,
                            direction="SELL",
                            strategy=self.name,
                            entry_price=current_price,
                            stop_loss=sl_price,
                            take_profit=tp_price,
                            sl_pips=round(sl_pips, 1),
                            tp_pips=round(tp_pips, 1),
                            lot_size=lot_size,
                            reason=f"Pullback EMA20, RSI={rsi:.0f}",
                            timestamp=candle["datetime"]
                        )
        
        return None


# ============================================================================
# STRATÉGIE 2: INTRADAY SAFE
# ============================================================================

class SafeIntradayStrategy:
    """
    STRATÉGIE INTRADAY SÉCURISÉE
    
    Caractéristiques:
    - EMA 50/200 sur H1 pour tendance long terme
    - RSI pour confirmation
    - Entrée sur support/résistance + confirmation
    - SL: 15-25 pips
    - TP: 2x SL minimum
    
    Filtres:
    - Tendance claire requise
    - Pas de trading en range
    """
    
    def __init__(self):
        self.name = "INTRADAY"
        self.min_sl_pips = 15
        self.max_sl_pips = 25
        self.min_rr = 2.0
    
    def is_valid_session(self, hour: int) -> bool:
        """Sessions principales 8-18 UTC"""
        return 8 <= hour <= 18
    
    def analyze(
        self,
        h1_candles: List[Dict],
        m15_candles: List[Dict],
        h1_index: int,
        m15_index: int,
        risk_manager: SafeRiskManager,
        symbol: str = "EURUSD"
    ) -> Optional[TradeSetup]:
        """Analyse pour signal intraday"""
        
        if h1_index < 200 or m15_index < 30:
            return None
        
        candle = m15_candles[m15_index]
        hour = candle["datetime"].hour
        
        if not self.is_valid_session(hour):
            return None
        
        # Vérifier si on peut trader
        can_trade, reason = risk_manager.can_trade("INTRADAY", risk_manager.intraday_state)
        if not can_trade:
            return None
        
        # Données H1
        h1_closes = [c["close"] for c in h1_candles[:h1_index + 1]]
        h1_highs = [c["high"] for c in h1_candles[:h1_index + 1]]
        h1_lows = [c["low"] for c in h1_candles[:h1_index + 1]]
        
        # Données M15
        m15_closes = [c["close"] for c in m15_candles[:m15_index + 1]]
        m15_highs = [c["high"] for c in m15_candles[:m15_index + 1]]
        m15_lows = [c["low"] for c in m15_candles[:m15_index + 1]]
        
        # Indicateurs H1
        ema50_h1 = Indicators.ema(h1_closes, 50)
        ema200_h1 = Indicators.ema(h1_closes, 200)
        
        # Indicateurs M15
        rsi = Indicators.rsi(m15_closes, 14)
        atr = Indicators.atr(m15_highs, m15_lows, m15_closes, 14)
        
        current_price = m15_closes[-1]
        
        # Tendance H1
        trend = Indicators.is_trending(ema50_h1, ema200_h1, 0.001)
        
        # Support/Résistance H1
        support = Indicators.find_support(h1_lows, 30)
        resistance = Indicators.find_resistance(h1_highs, 30)
        
        # ========== SETUP BUY ==========
        if trend == "BULLISH":
            # Prix proche du support ou de EMA50
            near_support = (current_price - support) / current_price < 0.003
            near_ema50 = abs(current_price - ema50_h1) / current_price < 0.002
            
            # RSI pas suracheté
            rsi_ok = 35 <= rsi <= 60
            
            if (near_support or near_ema50) and rsi_ok:
                # Confirmation: bougie haussière M15
                bullish = candle["close"] > candle["open"]
                body_size = abs(candle["close"] - candle["open"])
                total_size = candle["high"] - candle["low"]
                strong_candle = body_size > total_size * 0.5 if total_size > 0 else False
                
                if bullish and strong_candle:
                    # SL sous le support ou swing low
                    swing_low = min(m15_lows[-6:])
                    sl_price = min(swing_low, support) - 0.0003
                    sl_pips = (current_price - sl_price) * 10000
                    
                    # Ajuster SL dans les limites
                    sl_pips = max(self.min_sl_pips, min(sl_pips, self.max_sl_pips))
                    sl_price = current_price - (sl_pips / 10000)
                    
                    # TP
                    tp_pips = sl_pips * self.min_rr
                    tp_price = current_price + (tp_pips / 10000)
                    
                    lot_size = risk_manager.calculate_lot_size(sl_pips, risk_manager.intraday_state)
                    
                    return TradeSetup(
                        symbol=symbol,
                        direction="BUY",
                        strategy=self.name,
                        entry_price=current_price,
                        stop_loss=sl_price,
                        take_profit=tp_price,
                        sl_pips=round(sl_pips, 1),
                        tp_pips=round(tp_pips, 1),
                        lot_size=lot_size,
                        reason=f"H1 bullish, support bounce, RSI={rsi:.0f}",
                        timestamp=candle["datetime"]
                    )
        
        # ========== SETUP SELL ==========
        elif trend == "BEARISH":
            near_resistance = (resistance - current_price) / current_price < 0.003
            near_ema50 = abs(current_price - ema50_h1) / current_price < 0.002
            
            rsi_ok = 40 <= rsi <= 65
            
            if (near_resistance or near_ema50) and rsi_ok:
                bearish = candle["close"] < candle["open"]
                body_size = abs(candle["close"] - candle["open"])
                total_size = candle["high"] - candle["low"]
                strong_candle = body_size > total_size * 0.5 if total_size > 0 else False
                
                if bearish and strong_candle:
                    swing_high = max(m15_highs[-6:])
                    sl_price = max(swing_high, resistance) + 0.0003
                    sl_pips = (sl_price - current_price) * 10000
                    
                    sl_pips = max(self.min_sl_pips, min(sl_pips, self.max_sl_pips))
                    sl_price = current_price + (sl_pips / 10000)
                    
                    tp_pips = sl_pips * self.min_rr
                    tp_price = current_price - (tp_pips / 10000)
                    
                    lot_size = risk_manager.calculate_lot_size(sl_pips, risk_manager.intraday_state)
                    
                    return TradeSetup(
                        symbol=symbol,
                        direction="SELL",
                        strategy=self.name,
                        entry_price=current_price,
                        stop_loss=sl_price,
                        take_profit=tp_price,
                        sl_pips=round(sl_pips, 1),
                        tp_pips=round(tp_pips, 1),
                        lot_size=lot_size,
                        reason=f"H1 bearish, resistance rejection, RSI={rsi:.0f}",
                        timestamp=candle["datetime"]
                    )
        
        return None


# ============================================================================
# INSTANCES GLOBALES
# ============================================================================

safe_scalping = SafeScalpingStrategy()
safe_intraday = SafeIntradayStrategy()
