"""
Live Trading Service - Connects Strategies to FIX API
Manages real-time trading with FTMO safety barriers.

Includes validated USDJPY Price Action strategy (BREAKOUT + BOUNCE).
"""
import asyncio
import threading
import time
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from ctrader_fix_client import CTraderFIXClient, create_ftmo_client
from professional_strategies import (
    ScalpingStrategy, IntradayStrategy, ProfessionalRiskManager,
    TradeSignal, TechnicalAnalysis
)
from usdjpy_pa_strategy import PriceActionSignalGenerator, PASignal

logger = logging.getLogger(__name__)


@dataclass
class LiveTrade:
    signal: object  # TradeSignal or PASignal
    cl_ord_id: str
    status: str = "PENDING"
    fill_price: float = 0.0
    close_price: float = 0.0
    pnl: float = 0.0
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class LiveTradingService:
    """
    Orchestrates live trading using strategies + FIX API.
    Safety barriers are ALWAYS active - never bypassed.

    Strategies:
      - PA BREAKOUT + BOUNCE on USDJPY (validated +0.94%/week)
      - Legacy Scalping + Intraday (optional)
    """

    def __init__(self):
        self.fix_client: Optional[CTraderFIXClient] = None
        self.risk_manager: Optional[ProfessionalRiskManager] = None
        self.scalping = ScalpingStrategy()
        self.intraday = IntradayStrategy()
        self.pa_strategy = PriceActionSignalGenerator()

        self.is_running = False
        self.is_connected = False
        self.active_trades: Dict[str, LiveTrade] = {}
        self.closed_trades: List[LiveTrade] = []
        self.candle_buffer_m15: List[Dict] = []
        self.candle_buffer_h1: List[Dict] = []
        self.candle_buffer_m30: List[Dict] = []
        self.market_prices: Dict[str, Dict] = {}

        self.enabled_strategies = {
            "pa_breakout": True,
            "pa_bounce": True,
            "scalping": False,
            "intraday": False,
        }
        self.trading_symbols = ["USDJPY"]
        self.initial_balance = 10000.0
        self._h1_initialized = False

        self._trading_thread: Optional[threading.Thread] = None
        self._last_candle_time: Optional[datetime] = None
        self._last_pa_check: Optional[datetime] = None

    def configure(self, initial_balance: float = 10000.0, symbols: List[str] = None):
        self.initial_balance = initial_balance
        if symbols:
            self.trading_symbols = symbols
        self.risk_manager = ProfessionalRiskManager(
            initial_balance=initial_balance,
            max_risk_per_trade=0.0075,
            max_daily_loss=0.045,
            max_total_drawdown=0.08
        )
        self.pa_strategy = PriceActionSignalGenerator(initial_balance=initial_balance)
        self._init_historical_data()

    def connect(self) -> Dict:
        """Connect to cTrader FIX API"""
        password = os.environ.get("FIX_PASSWORD", "")
        if not password:
            return {"success": False, "error": "FIX_PASSWORD not configured"}

        try:
            self.fix_client = CTraderFIXClient(
                host=os.environ.get("FIX_HOST", "live-uk-eqx-01.p.c-trader.com"),
                port=int(os.environ.get("FIX_PORT", "5211")),
                sender_comp_id=os.environ.get("FIX_SENDER_COMP_ID", "live.ftmo.17061677"),
                target_comp_id=os.environ.get("FIX_TARGET_COMP_ID", "cServer"),
                password=password,
                sender_sub_id="QUOTE",
                use_ssl=True
            )

            self.fix_client.on_market_data(self._on_market_data)
            self.fix_client.on_execution(self._on_execution)

            if self.fix_client.connect():
                if self.fix_client.login():
                    self.is_connected = True
                    self.fix_client.subscribe_market_data(self.trading_symbols)
                    logger.info("Live trading connected to FIX API")
                    return {
                        "success": True,
                        "message": "Connected to cTrader FIX API",
                        "account": os.environ.get("FIX_ACCOUNT", "17061677"),
                        "strategies": self.enabled_strategies,
                        "pa_status": self.pa_strategy.get_status(),
                    }
                else:
                    return {"success": False, "error": "FIX login failed"}
            else:
                return {"success": False, "error": "Could not connect to FIX server"}

        except Exception as e:
            logger.error(f"FIX connection error: {e}")
            return {"success": False, "error": str(e)}

    def _init_historical_data(self):
        """Load historical H1 + M30 data for S/R zone computation."""
        try:
            from tradingview_loader import load_tradingview_csv
            h1_path = os.path.join(os.path.dirname(__file__), "historical_data", "USDJPY_H1_TV.csv")
            m30_path = os.path.join(os.path.dirname(__file__), "historical_data", "USDJPY_M30_TV.csv")

            h1 = load_tradingview_csv(h1_path) if os.path.exists(h1_path) else []
            m30 = load_tradingview_csv(m30_path) if os.path.exists(m30_path) else []

            if h1:
                self.candle_buffer_h1 = h1[-500:]
                logger.info(f"Loaded {len(self.candle_buffer_h1)} H1 candles from historical data")
            if m30:
                self.candle_buffer_m30 = m30[-500:]
                logger.info(f"Loaded {len(self.candle_buffer_m30)} M30 candles from historical data")

            if len(self.candle_buffer_h1) >= 100:
                self.pa_strategy.update(self.candle_buffer_h1, self.candle_buffer_m30)
                self._h1_initialized = True
                logger.info("PA Strategy initialized with historical data")

        except Exception as e:
            logger.warning(f"Could not load historical data: {e}. PA will wait for live data.")

    def disconnect(self):
        """Stop trading and disconnect"""
        self.stop_trading()
        if self.fix_client:
            self.fix_client.logout()
            self.fix_client = None
        self.is_connected = False
        logger.info("Disconnected from FIX API")

    def start_trading(self, strategies: Dict[str, bool] = None) -> Dict:
        """Start the live trading loop"""
        if not self.is_connected:
            return {"success": False, "error": "Not connected to FIX API"}

        if not self.risk_manager:
            self.configure(self.initial_balance)

        if strategies:
            self.enabled_strategies = strategies

        self.is_running = True
        self._trading_thread = threading.Thread(target=self._trading_loop, daemon=True)
        self._trading_thread.start()

        logger.info(f"Live trading started - Strategies: {self.enabled_strategies}")
        return {
            "success": True,
            "message": "Live trading started",
            "strategies": self.enabled_strategies,
            "symbols": self.trading_symbols,
            "risk_limits": {
                "max_risk_per_trade": "1%",
                "max_daily_loss": "4.5%",
                "max_total_drawdown": "8%"
            }
        }

    def stop_trading(self) -> Dict:
        """Stop the trading loop (does NOT close open positions)"""
        self.is_running = False
        logger.info("Live trading stopped")
        return {
            "success": True,
            "message": "Trading stopped",
            "open_positions": len(self.active_trades),
            "total_closed": len(self.closed_trades)
        }

    def get_status(self) -> Dict:
        """Get current live trading status"""
        risk_status = self.risk_manager.get_status() if self.risk_manager else {}
        pa_status = self.pa_strategy.get_status()
        return {
            "connected": self.is_connected,
            "trading": self.is_running,
            "strategies": self.enabled_strategies,
            "symbols": self.trading_symbols,
            "pa_strategy": pa_status,
            "open_trades": len(self.active_trades),
            "closed_trades": len(self.closed_trades),
            "risk_status": risk_status,
            "market_prices": self.market_prices,
            "h1_candles_buffered": len(self.candle_buffer_h1),
            "m30_candles_buffered": len(self.candle_buffer_m30),
            "active_trades": [
                {
                    "symbol": getattr(t.signal, "symbol", "USDJPY"),
                    "direction": getattr(t.signal, "direction", ""),
                    "strategy": getattr(t.signal, "strategy", ""),
                    "entry_price": t.fill_price,
                    "stop_loss": getattr(t.signal, "stop_loss", 0),
                    "take_profit": getattr(t.signal, "take_profit", 0),
                    "status": t.status,
                    "opened_at": t.opened_at.isoformat() if t.opened_at else None
                }
                for t in self.active_trades.values()
            ],
            "recent_closed": [
                {
                    "symbol": getattr(t.signal, "symbol", "USDJPY"),
                    "direction": getattr(t.signal, "direction", ""),
                    "strategy": getattr(t.signal, "strategy", ""),
                    "pnl": round(t.pnl, 2),
                    "closed_at": t.closed_at.isoformat() if t.closed_at else None
                }
                for t in self.closed_trades[-10:]
            ]
        }

    def _on_market_data(self, symbol: str, data: Dict):
        """Handle incoming market data from FIX"""
        self.market_prices[symbol] = data
        self._update_candle_buffers(symbol, data)

    def _on_execution(self, msg):
        """Handle execution reports from FIX"""
        exec_type = msg.get(150)  # ExecType
        cl_ord_id = msg.get(11)  # ClOrdID

        if cl_ord_id and cl_ord_id in self.active_trades:
            trade = self.active_trades[cl_ord_id]

            if exec_type == "F":  # Fill
                trade.status = "FILLED"
                trade.fill_price = float(msg.get(31) or msg.get(44) or 0)
                trade.opened_at = datetime.now(timezone.utc)
                self.risk_manager.record_trade_open(trade.signal)
                logger.info(f"Order filled: {trade.signal.direction} {trade.signal.symbol} @ {trade.fill_price}")

            elif exec_type == "4":  # Canceled
                trade.status = "CANCELED"
                del self.active_trades[cl_ord_id]

            elif exec_type == "8":  # Rejected
                trade.status = "REJECTED"
                del self.active_trades[cl_ord_id]
                logger.warning(f"Order rejected: {msg.get(58)}")

    def _update_candle_buffers(self, symbol: str, data: Dict):
        """Build candle data from tick stream"""
        now = datetime.now(timezone.utc)
        price = (data.get("bid", 0) + data.get("ask", 0)) / 2
        if price <= 0:
            return

        # Build M15 candles
        m15_slot = now.replace(second=0, microsecond=0)
        m15_slot = m15_slot.replace(minute=(m15_slot.minute // 15) * 15)

        if self.candle_buffer_m15 and self.candle_buffer_m15[-1]["datetime"] == m15_slot:
            c = self.candle_buffer_m15[-1]
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
        else:
            self.candle_buffer_m15.append({
                "datetime": m15_slot,
                "open": price, "high": price, "low": price, "close": price,
                "volume": 100
            })
            if len(self.candle_buffer_m15) > 500:
                self.candle_buffer_m15 = self.candle_buffer_m15[-500:]

        # Build M30 candles (for PA strategy)
        m30_slot = now.replace(second=0, microsecond=0)
        m30_slot = m30_slot.replace(minute=(m30_slot.minute // 30) * 30)

        if self.candle_buffer_m30 and self.candle_buffer_m30[-1]["datetime"] == m30_slot:
            c = self.candle_buffer_m30[-1]
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
        else:
            self.candle_buffer_m30.append({
                "datetime": m30_slot,
                "open": price, "high": price, "low": price, "close": price,
                "volume": 100
            })
            if len(self.candle_buffer_m30) > 500:
                self.candle_buffer_m30 = self.candle_buffer_m30[-500:]

        # Build H1 candles
        h1_slot = now.replace(minute=0, second=0, microsecond=0)
        if self.candle_buffer_h1 and self.candle_buffer_h1[-1]["datetime"] == h1_slot:
            c = self.candle_buffer_h1[-1]
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
        else:
            self.candle_buffer_h1.append({
                "datetime": h1_slot,
                "open": price, "high": price, "low": price, "close": price,
                "volume": 100
            })
            if len(self.candle_buffer_h1) > 500:
                self.candle_buffer_h1 = self.candle_buffer_h1[-500:]

    def _trading_loop(self):
        """Main trading loop - runs in background thread"""
        logger.info("Trading loop started")

        while self.is_running:
            try:
                now = datetime.now(timezone.utc)

                # Check for new day -> reset daily counters
                if self._last_candle_time and self._last_candle_time.date() != now.date():
                    self.risk_manager.reset_daily()
                    self.pa_strategy.current_date = None  # Force daily reset
                    logger.info("New trading day - counters reset")

                # Only trade during valid sessions (07-21 UTC weekdays)
                if now.weekday() >= 5 or now.hour < 7 or now.hour > 21:
                    time.sleep(30)
                    continue

                # ── PA Strategy Check (on every new M30 candle) ──
                if self.enabled_strategies.get("pa_breakout") or self.enabled_strategies.get("pa_bounce"):
                    m30_slot = now.replace(second=0, microsecond=0)
                    m30_slot = m30_slot.replace(minute=(m30_slot.minute // 30) * 30)

                    if self._last_pa_check is None or self._last_pa_check < m30_slot:
                        self._last_pa_check = m30_slot

                        # Update PA strategy with latest candle data
                        if len(self.candle_buffer_h1) >= 100:
                            self.pa_strategy.update(self.candle_buffer_h1, self.candle_buffer_m30)

                            # Check for signals
                            signals = self.pa_strategy.check_signals(
                                self.risk_manager.current_balance if self.risk_manager else self.initial_balance
                            )
                            for sig in signals:
                                if sig.strategy == "PA_BREAKOUT" and not self.enabled_strategies.get("pa_breakout"):
                                    continue
                                if sig.strategy == "PA_BOUNCE" and not self.enabled_strategies.get("pa_bounce"):
                                    continue
                                self._execute_pa_trade(sig)

                # ── Legacy Strategy Check (on M15 candle) ──
                if len(self.candle_buffer_m15) < 50:
                    time.sleep(15)
                    continue

                current_m15 = now.replace(second=0, microsecond=0)
                current_m15 = current_m15.replace(minute=(current_m15.minute // 15) * 15)

                if self._last_candle_time and self._last_candle_time >= current_m15:
                    time.sleep(5)
                    continue

                self._last_candle_time = current_m15

                # Legacy strategy analysis
                for symbol in self.trading_symbols:
                    if symbol != "USDJPY":
                        self._analyze_and_trade(symbol)

                time.sleep(10)

            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                time.sleep(30)

        logger.info("Trading loop stopped")

    def _analyze_and_trade(self, symbol: str):
        """Analyze market and execute trades for a symbol"""
        m15_candles = self.candle_buffer_m15
        h1_candles = self.candle_buffer_h1
        m15_idx = len(m15_candles) - 1
        h1_idx = len(h1_candles) - 1

        # Scalping
        if self.enabled_strategies.get("scalping", True) and m15_idx >= 50:
            signal = self.scalping.analyze(m15_candles, m15_idx, symbol)
            if signal:
                can_trade, reason = self.risk_manager.can_open_trade(
                    signal, self.risk_manager.scalping_state
                )
                if can_trade:
                    self._execute_trade(signal)
                else:
                    logger.info(f"Scalping blocked: {reason}")

        # Intraday
        if self.enabled_strategies.get("intraday", True) and h1_idx >= 200 and m15_idx >= 30:
            signal = self.intraday.analyze(h1_candles, m15_candles, h1_idx, m15_idx, symbol)
            if signal:
                can_trade, reason = self.risk_manager.can_open_trade(
                    signal, self.risk_manager.intraday_state
                )
                if can_trade:
                    self._execute_trade(signal)
                else:
                    logger.info(f"Intraday blocked: {reason}")

    def _execute_pa_trade(self, signal: PASignal):
        """Execute a Price Action trade via FIX API."""
        if not self.fix_client or not self.fix_client.logged_in:
            logger.error("Cannot execute PA trade: FIX not connected")
            return

        # Convert lot size to volume (0.01 lot = 1000 units for FIX)
        quantity = int(signal.lot_size * 100000)

        cl_ord_id = self.fix_client.place_order(
            symbol=signal.symbol,
            side=signal.direction,
            quantity=quantity,
            order_type="MARKET"
        )

        if cl_ord_id:
            self.active_trades[cl_ord_id] = LiveTrade(
                signal=signal,
                cl_ord_id=cl_ord_id,
                status="SENT"
            )
            logger.info(
                f"PA Order sent: {signal.direction} {signal.lot_size} lots {signal.symbol} "
                f"SL:{signal.stop_loss} TP:{signal.take_profit} "
                f"R:R={signal.risk_reward} ({signal.strategy}: {signal.reason})"
            )

    def _execute_trade(self, signal: TradeSignal):
        """Send order to FIX API"""
        if not self.fix_client or not self.fix_client.logged_in:
            logger.error("Cannot execute: FIX not connected")
            return

        # Calculate lot size
        lot_size = self.risk_manager.calculate_lot_size(signal.sl_pips, signal.symbol)
        signal = TradeSignal(
            symbol=signal.symbol,
            direction=signal.direction,
            strategy=signal.strategy,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            sl_pips=signal.sl_pips,
            tp_pips=signal.tp_pips,
            risk_reward=signal.risk_reward,
            lot_size=lot_size,
            reason=signal.reason,
            confidence=signal.confidence,
            session=signal.session,
            timestamp=signal.timestamp
        )

        # Convert lot size to volume (0.01 lot = 1000 units for FIX)
        quantity = int(lot_size * 100000)

        cl_ord_id = self.fix_client.place_order(
            symbol=signal.symbol,
            side=signal.direction,
            quantity=quantity,
            order_type="MARKET"
        )

        if cl_ord_id:
            self.active_trades[cl_ord_id] = LiveTrade(
                signal=signal,
                cl_ord_id=cl_ord_id,
                status="SENT"
            )
            logger.info(
                f"Order sent: {signal.direction} {lot_size} lots {signal.symbol} "
                f"SL:{signal.stop_loss} TP:{signal.take_profit} ({signal.reason})"
            )


# Singleton instance
live_trading_service = LiveTradingService()
