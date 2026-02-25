"""
FTMO Trading Bot - Main FastAPI Server
"""
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta
import uuid
import asyncio

# Local imports
from models import (
    Trade, TradeCreate, AccountStats, DailyStats,
    TradingSettings, RiskLimits, Alert, MarketData
)
from risk_manager import RiskManager
from trading_strategies import TradingEngine, TechnicalIndicators
from market_simulator import market_simulator

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI(title="FTMO Trading Bot API")

# Create router with /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize components
risk_manager = RiskManager()
trading_engine = TradingEngine()

# Bot state
bot_state = {
    "active": False,
    "last_signal_check": None,
    "pending_signals": []
}


# ==================== HELPER FUNCTIONS ====================

async def get_or_create_settings() -> dict:
    """Get or create default trading settings"""
    settings = await db.settings.find_one({}, {"_id": 0})
    if not settings:
        default_settings = TradingSettings().model_dump()
        default_settings['updated_at'] = default_settings['updated_at'].isoformat()
        await db.settings.insert_one(default_settings)
        return default_settings
    return settings


async def get_or_create_account() -> dict:
    """Get or create account stats"""
    account = await db.account.find_one({}, {"_id": 0})
    if not account:
        default_account = AccountStats().model_dump()
        default_account['updated_at'] = default_account['updated_at'].isoformat()
        await db.account.insert_one(default_account)
        return default_account
    return account


async def update_account_stats():
    """Recalculate account statistics from trades"""
    account = await get_or_create_account()
    
    # Get all closed trades
    trades = await db.trades.find({"status": "CLOSED"}, {"_id": 0}).to_list(1000)
    
    if not trades:
        return account
    
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    winning_trades = [t for t in trades if t.get("pnl", 0) > 0]
    losing_trades = [t for t in trades if t.get("pnl", 0) < 0]
    
    win_rate = len(winning_trades) / len(trades) * 100 if trades else 0
    avg_win = sum(t["pnl"] for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(t["pnl"] for t in losing_trades) / len(losing_trades) if losing_trades else 0
    
    total_wins = sum(t["pnl"] for t in winning_trades)
    total_losses = abs(sum(t["pnl"] for t in losing_trades))
    profit_factor = total_wins / total_losses if total_losses > 0 else total_wins
    
    # Calculate daily P&L
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_trades = [t for t in trades if t.get("exit_time", "").startswith(today)]
    daily_pnl = sum(t.get("pnl", 0) for t in today_trades)
    
    current_balance = account.get("initial_balance", 100000) + total_pnl
    
    update_data = {
        "current_balance": round(current_balance, 2),
        "equity": round(current_balance, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_percent": round(total_pnl / account.get("initial_balance", 100000) * 100, 2),
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_percent": round(daily_pnl / account.get("initial_balance", 100000) * 100, 2),
        "total_trades": len(trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "best_trade": max((t["pnl"] for t in trades), default=0),
        "worst_trade": min((t["pnl"] for t in trades), default=0),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.account.update_one({}, {"$set": update_data})
    
    # Update risk manager state
    risk_manager.update_state(current_balance, daily_pnl, total_pnl)
    
    return {**account, **update_data}


async def create_alert(alert_type: str, title: str, message: str):
    """Create a new alert"""
    alert = Alert(type=alert_type, title=title, message=message)
    alert_dict = alert.model_dump()
    alert_dict['timestamp'] = alert_dict['timestamp'].isoformat()
    await db.alerts.insert_one(alert_dict)


# ==================== API ENDPOINTS ====================

@api_router.get("/")
async def root():
    return {"message": "FTMO Trading Bot API", "status": "running"}


# ---------- Dashboard Endpoints ----------

@api_router.get("/dashboard")
async def get_dashboard():
    """Get complete dashboard data"""
    account = await update_account_stats()
    settings = await get_or_create_settings()
    
    # Get recent trades
    recent_trades = await db.trades.find(
        {}, {"_id": 0}
    ).sort("entry_time", -1).limit(10).to_list(10)
    
    # Get open trades
    open_trades = await db.trades.find(
        {"status": "OPEN"}, {"_id": 0}
    ).to_list(100)
    
    # Get market data
    market_data = market_simulator.get_all_quotes()
    
    # Get risk status
    risk_status = risk_manager.get_risk_status()
    
    # Get indicator values for main symbol
    settings_symbols = settings.get("symbols", ["EURUSD"])
    main_symbol = settings_symbols[0] if settings_symbols else "EURUSD"
    prices = market_simulator.get_prices(main_symbol, 100)
    indicators = trading_engine.get_indicator_values(prices)
    
    return {
        "account": account,
        "risk_status": risk_status,
        "recent_trades": recent_trades,
        "open_trades": open_trades,
        "market_data": market_data,
        "indicators": indicators,
        "bot_active": settings.get("bot_active", False),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@api_router.get("/stats/daily")
async def get_daily_stats():
    """Get daily statistics for the past 30 days"""
    # Generate simulated daily stats for demo
    stats = []
    base_balance = 100000
    cumulative_pnl = 0
    
    for i in range(30, 0, -1):
        date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_pnl = (0.002 + (0.008 * (1 - i/30))) * base_balance * (1 if i % 3 != 0 else -0.5)
        cumulative_pnl += daily_pnl
        
        stats.append({
            "date": date,
            "pnl": round(daily_pnl, 2),
            "pnl_percent": round(daily_pnl / base_balance * 100, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "cumulative_percent": round(cumulative_pnl / base_balance * 100, 2),
            "trades": 3 + (i % 5),
            "wins": 2 + (i % 3),
            "losses": 1 + (i % 2)
        })
    
    return {"stats": stats}


@api_router.get("/stats/equity-curve")
async def get_equity_curve():
    """Get equity curve data"""
    trades = await db.trades.find(
        {"status": "CLOSED"}, {"_id": 0}
    ).sort("exit_time", 1).to_list(1000)
    
    if not trades:
        # Generate demo equity curve
        curve = []
        balance = 100000
        for i in range(50):
            change = balance * (0.003 if i % 4 != 0 else -0.002)
            balance += change
            curve.append({
                "index": i,
                "equity": round(balance, 2),
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=50-i)).isoformat()
            })
        return {"curve": curve}
    
    # Build from actual trades
    curve = []
    balance = 100000
    for i, trade in enumerate(trades):
        balance += trade.get("pnl", 0)
        curve.append({
            "index": i,
            "equity": round(balance, 2),
            "timestamp": trade.get("exit_time")
        })
    
    return {"curve": curve}


# ---------- Trades Endpoints ----------

@api_router.get("/trades")
async def get_trades(
    status: Optional[str] = None,
    strategy: Optional[str] = None,
    limit: int = 50
):
    """Get trade history"""
    query = {}
    if status:
        query["status"] = status
    if strategy:
        query["strategy"] = strategy
    
    trades = await db.trades.find(
        query, {"_id": 0}
    ).sort("entry_time", -1).limit(limit).to_list(limit)
    
    return {"trades": trades, "count": len(trades)}


@api_router.get("/trades/open")
async def get_open_trades():
    """Get all open trades"""
    trades = await db.trades.find(
        {"status": "OPEN"}, {"_id": 0}
    ).to_list(100)
    
    # Update P&L for open trades
    for trade in trades:
        symbol = trade.get("symbol", "EURUSD")
        current_price = market_simulator.current_prices.get(symbol, trade["entry_price"])
        
        if trade["direction"] == "BUY":
            pnl_pips = (current_price - trade["entry_price"]) * 10000
        else:
            pnl_pips = (trade["entry_price"] - current_price) * 10000
        
        trade["current_price"] = round(current_price, 5)
        trade["unrealized_pnl"] = round(pnl_pips * trade["lot_size"] * 10, 2)
    
    return {"trades": trades, "count": len(trades)}


@api_router.post("/trades")
async def create_trade(trade_data: TradeCreate):
    """Create a new trade (manual entry)"""
    # Calculate risk/reward
    if trade_data.direction == "BUY":
        risk = trade_data.entry_price - trade_data.stop_loss
        reward = trade_data.take_profit - trade_data.entry_price
    else:
        risk = trade_data.stop_loss - trade_data.entry_price
        reward = trade_data.entry_price - trade_data.take_profit
    
    if risk <= 0 or reward <= 0:
        raise HTTPException(status_code=400, detail="Invalid SL/TP levels")
    
    risk_reward = reward / risk
    
    # Validate with risk manager
    is_valid, reason = risk_manager.validate_trade(
        trade_data.entry_price,
        trade_data.stop_loss,
        trade_data.take_profit,
        trade_data.lot_size,
        trade_data.direction
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=reason)
    
    # Create trade
    trade = Trade(
        **trade_data.model_dump(),
        risk_reward=round(risk_reward, 2)
    )
    
    trade_dict = trade.model_dump()
    trade_dict['entry_time'] = trade_dict['entry_time'].isoformat()
    
    await db.trades.insert_one(trade_dict)
    
    await create_alert("SUCCESS", "Trade Opened", 
        f"{trade_data.direction} {trade_data.symbol} @ {trade_data.entry_price}")
    
    return {"trade": trade_dict, "validation": reason}


@api_router.post("/trades/{trade_id}/close")
async def close_trade(trade_id: str, exit_price: Optional[float] = None):
    """Close an open trade"""
    trade = await db.trades.find_one({"id": trade_id}, {"_id": 0})
    
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    if trade["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="Trade already closed")
    
    # Get current price if not provided
    if exit_price is None:
        symbol = trade.get("symbol", "EURUSD")
        exit_price = market_simulator.current_prices.get(symbol, trade["entry_price"])
    
    # Calculate P&L
    if trade["direction"] == "BUY":
        pnl_pips = (exit_price - trade["entry_price"]) * 10000
    else:
        pnl_pips = (trade["entry_price"] - exit_price) * 10000
    
    pnl = round(pnl_pips * trade["lot_size"] * 10, 2)
    pnl_percent = round(pnl / risk_manager.current_balance * 100, 2)
    
    update_data = {
        "status": "CLOSED",
        "exit_price": exit_price,
        "exit_time": datetime.now(timezone.utc).isoformat(),
        "pnl": pnl,
        "pnl_percent": pnl_percent
    }
    
    await db.trades.update_one({"id": trade_id}, {"$set": update_data})
    
    # Update account stats
    await update_account_stats()
    
    # Create alert
    alert_type = "SUCCESS" if pnl > 0 else "WARNING"
    await create_alert(alert_type, "Trade Closed",
        f"{trade['direction']} {trade['symbol']} closed @ {exit_price}. P&L: ${pnl}")
    
    return {"success": True, "pnl": pnl, "pnl_percent": pnl_percent}


# ---------- Market Data Endpoints ----------

@api_router.get("/market/quotes")
async def get_market_quotes():
    """Get current market quotes for all pairs"""
    quotes = market_simulator.get_all_quotes()
    return {"quotes": quotes, "timestamp": datetime.now(timezone.utc).isoformat()}


@api_router.get("/market/prices/{symbol}")
async def get_prices(symbol: str, count: int = 100):
    """Get historical prices for a symbol"""
    prices = market_simulator.get_prices(symbol.upper(), count)
    ohlc = market_simulator.get_ohlc(symbol.upper(), min(count, 50))
    current = market_simulator.tick(symbol.upper())
    
    return {
        "symbol": symbol.upper(),
        "prices": prices,
        "ohlc": ohlc,
        "current": current
    }


@api_router.get("/market/indicators/{symbol}")
async def get_indicators(symbol: str):
    """Get technical indicators for a symbol"""
    prices = market_simulator.get_prices(symbol.upper(), 100)
    indicators = trading_engine.get_indicator_values(prices)
    
    return {
        "symbol": symbol.upper(),
        "indicators": indicators,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ---------- Risk Management Endpoints ----------

@api_router.get("/risk/status")
async def get_risk_status():
    """Get current risk status and FTMO limits"""
    await update_account_stats()
    return risk_manager.get_risk_status()


@api_router.get("/risk/validate")
async def validate_trade_risk(
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    lot_size: float,
    direction: str
):
    """Validate a potential trade against risk rules"""
    is_valid, reason = risk_manager.validate_trade(
        entry_price, stop_loss, take_profit, lot_size, direction.upper()
    )
    
    # Calculate position sizing suggestion
    suggested_lot = risk_manager.calculate_position_size(entry_price, stop_loss)
    
    return {
        "valid": is_valid,
        "reason": reason,
        "suggested_lot_size": suggested_lot
    }


# ---------- Bot Control Endpoints ----------

@api_router.post("/bot/start")
async def start_bot():
    """Start the trading bot"""
    settings = await get_or_create_settings()
    
    if settings.get("bot_active"):
        return {"status": "already_running"}
    
    await db.settings.update_one({}, {"$set": {"bot_active": True}})
    bot_state["active"] = True
    
    await create_alert("INFO", "Bot Started", "Trading bot is now active")
    
    return {"status": "started", "timestamp": datetime.now(timezone.utc).isoformat()}


@api_router.post("/bot/stop")
async def stop_bot():
    """Stop the trading bot"""
    await db.settings.update_one({}, {"$set": {"bot_active": False}})
    bot_state["active"] = False
    
    await create_alert("INFO", "Bot Stopped", "Trading bot has been stopped")
    
    return {"status": "stopped", "timestamp": datetime.now(timezone.utc).isoformat()}


@api_router.get("/bot/signals")
async def get_signals():
    """Get current trading signals from strategies"""
    settings = await get_or_create_settings()
    symbols = settings.get("symbols", ["EURUSD"])
    
    all_signals = []
    
    for symbol in symbols:
        prices = market_simulator.get_prices(symbol, 100)
        current_price = market_simulator.current_prices.get(symbol, prices[-1])
        
        # Update trading engine settings
        trading_engine.scalping_enabled = settings.get("scalping_enabled", True)
        trading_engine.intraday_enabled = settings.get("intraday_enabled", True)
        
        signals = trading_engine.analyze_market(prices, current_price)
        
        for signal in signals:
            signal["symbol"] = symbol
            # Validate each signal
            is_valid, reason = risk_manager.validate_trade(
                signal["entry_price"],
                signal["stop_loss"],
                signal["take_profit"],
                settings.get(f"{signal['strategy'].lower()}_lot_size", 0.1),
                signal["direction"]
            )
            signal["valid"] = is_valid
            signal["validation_reason"] = reason
            
        all_signals.extend(signals)
    
    return {
        "signals": all_signals,
        "bot_active": settings.get("bot_active", False),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ---------- Settings Endpoints ----------

@api_router.get("/settings")
async def get_settings():
    """Get trading settings"""
    return await get_or_create_settings()


class SettingsUpdate(BaseModel):
    bot_active: Optional[bool] = None
    scalping_enabled: Optional[bool] = None
    intraday_enabled: Optional[bool] = None
    symbols: Optional[List[str]] = None
    scalping_lot_size: Optional[float] = None
    scalping_tp_pips: Optional[float] = None
    scalping_sl_pips: Optional[float] = None
    intraday_lot_size: Optional[float] = None
    intraday_tp_pips: Optional[float] = None
    intraday_sl_pips: Optional[float] = None


@api_router.put("/settings")
async def update_settings(settings_data: SettingsUpdate):
    """Update trading settings"""
    update_dict = {k: v for k, v in settings_data.model_dump().items() if v is not None}
    update_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.settings.update_one({}, {"$set": update_dict})
    
    # Reinitialize trading engine with new settings
    new_settings = await get_or_create_settings()
    trading_engine.scalping.tp_pips = new_settings.get("scalping_tp_pips", 10)
    trading_engine.scalping.sl_pips = new_settings.get("scalping_sl_pips", 10)
    trading_engine.intraday.tp_pips = new_settings.get("intraday_tp_pips", 30)
    trading_engine.intraday.sl_pips = new_settings.get("intraday_sl_pips", 20)
    
    return {"success": True, "settings": new_settings}


# ---------- Alerts Endpoints ----------

@api_router.get("/alerts")
async def get_alerts(unread_only: bool = False, limit: int = 50):
    """Get alerts/notifications"""
    query = {"read": False} if unread_only else {}
    
    alerts = await db.alerts.find(
        query, {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    return {"alerts": alerts, "count": len(alerts)}


@api_router.post("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str):
    """Mark an alert as read"""
    await db.alerts.update_one({"id": alert_id}, {"$set": {"read": True}})
    return {"success": True}


@api_router.post("/alerts/read-all")
async def mark_all_alerts_read():
    """Mark all alerts as read"""
    await db.alerts.update_many({}, {"$set": {"read": True}})
    return {"success": True}


# ---------- Demo Data ----------

@api_router.post("/demo/generate-trades")
async def generate_demo_trades():
    """Generate demo trades for testing"""
    demo_trades = []
    base_balance = 100000
    balance = base_balance
    
    for i in range(20):
        symbol = "EURUSD"
        direction = "BUY" if i % 2 == 0 else "SELL"
        entry_price = 1.0850 + (i * 0.0005)
        
        is_winner = i % 3 != 0
        
        if direction == "BUY":
            if is_winner:
                exit_price = entry_price + 0.0015
                sl = entry_price - 0.0010
                tp = entry_price + 0.0015
            else:
                exit_price = entry_price - 0.0010
                sl = entry_price - 0.0010
                tp = entry_price + 0.0015
        else:
            if is_winner:
                exit_price = entry_price - 0.0015
                sl = entry_price + 0.0010
                tp = entry_price - 0.0015
            else:
                exit_price = entry_price + 0.0010
                sl = entry_price + 0.0010
                tp = entry_price - 0.0015
        
        lot_size = 0.1 if i % 2 == 0 else 0.05
        pnl_pips = abs(exit_price - entry_price) * 10000 * (1 if is_winner else -1)
        pnl = pnl_pips * lot_size * 10
        balance += pnl
        
        trade = {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "direction": direction,
            "entry_price": round(entry_price, 5),
            "exit_price": round(exit_price, 5),
            "stop_loss": round(sl, 5),
            "take_profit": round(tp, 5),
            "lot_size": lot_size,
            "strategy": "SCALPING" if i % 2 == 0 else "INTRADAY",
            "status": "CLOSED",
            "pnl": round(pnl, 2),
            "pnl_percent": round(pnl / base_balance * 100, 2),
            "risk_reward": 1.5,
            "entry_time": (datetime.now(timezone.utc) - timedelta(hours=20-i)).isoformat(),
            "exit_time": (datetime.now(timezone.utc) - timedelta(hours=19-i)).isoformat()
        }
        
        demo_trades.append(trade)
    
    # Clear existing and insert new
    await db.trades.delete_many({})
    await db.trades.insert_many(demo_trades)
    
    # Update account
    await update_account_stats()
    
    return {"success": True, "trades_created": len(demo_trades)}


# ==================== APP SETUP ====================

# Include router
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("FTMO Trading Bot API starting...")
    
    # Ensure collections exist
    await get_or_create_settings()
    await get_or_create_account()
    
    logger.info("Database initialized")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
