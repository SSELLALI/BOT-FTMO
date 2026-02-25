"""
Database models for the FTMO Trading Bot
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Literal
from datetime import datetime, timezone
import uuid


class Trade(BaseModel):
    """Trade model for storing trade history"""
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    exit_price: Optional[float] = None
    stop_loss: float
    take_profit: float
    lot_size: float
    strategy: Literal["SCALPING", "INTRADAY"]
    status: Literal["OPEN", "CLOSED", "CANCELLED"] = "OPEN"
    pnl: float = 0.0
    pnl_percent: float = 0.0
    risk_reward: float
    entry_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    exit_time: Optional[datetime] = None
    notes: Optional[str] = None


class TradeCreate(BaseModel):
    """Model for creating a new trade"""
    symbol: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    strategy: Literal["SCALPING", "INTRADAY"]


class AccountStats(BaseModel):
    """Account statistics model"""
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    initial_balance: float = 100000.0
    current_balance: float = 100000.0
    equity: float = 100000.0
    daily_pnl: float = 0.0
    daily_pnl_percent: float = 0.0
    total_pnl: float = 0.0
    total_pnl_percent: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DailyStats(BaseModel):
    """Daily statistics for tracking FTMO limits"""
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: str  # YYYY-MM-DD format
    starting_balance: float
    ending_balance: float
    pnl: float = 0.0
    pnl_percent: float = 0.0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    max_drawdown: float = 0.0
    within_limits: bool = True


class RiskLimits(BaseModel):
    """FTMO Risk limits configuration"""
    max_loss_per_trade_percent: float = 1.0  # 1% max per trade
    min_risk_reward: float = 1.0  # Minimum 1:1 RR
    max_daily_loss_percent: float = 4.5  # 4.5% max daily loss
    max_total_loss_percent: float = 10.0  # 10% max total drawdown
    
    
class TradingSettings(BaseModel):
    """Trading bot settings"""
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bot_active: bool = False
    scalping_enabled: bool = True
    intraday_enabled: bool = True
    symbols: List[str] = ["EURUSD"]
    
    # Scalping settings
    scalping_lot_size: float = 0.1
    scalping_tp_pips: float = 10
    scalping_sl_pips: float = 10
    
    # Intraday settings
    intraday_lot_size: float = 0.05
    intraday_tp_pips: float = 30
    intraday_sl_pips: float = 20
    
    # Risk management
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)
    
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MarketData(BaseModel):
    """Market data model"""
    symbol: str
    bid: float
    ask: float
    spread: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Alert(BaseModel):
    """Alert/notification model"""
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["INFO", "WARNING", "ERROR", "SUCCESS"]
    title: str
    message: str
    read: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
