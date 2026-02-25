"""
Risk Manager for FTMO compliance
Ensures all trades respect FTMO rules:
- Max 1% loss per trade
- Min 1:1 Risk/Reward ratio
- Max 4.5% daily loss
- Max 10% total drawdown
"""
from typing import Optional, Tuple
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        initial_balance: float = 100000.0,
        max_loss_per_trade: float = 0.01,  # 1%
        min_risk_reward: float = 1.0,  # 1:1
        max_daily_loss: float = 0.045,  # 4.5%
        max_total_loss: float = 0.10  # 10%
    ):
        self.initial_balance = initial_balance
        self.max_loss_per_trade = max_loss_per_trade
        self.min_risk_reward = min_risk_reward
        self.max_daily_loss = max_daily_loss
        self.max_total_loss = max_total_loss
        
        # Track current state
        self.current_balance = initial_balance
        self.daily_starting_balance = initial_balance
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.last_reset_date = datetime.now(timezone.utc).date()
        
    def reset_daily_limits(self, current_balance: float):
        """Reset daily tracking at start of new trading day"""
        self.daily_starting_balance = current_balance
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now(timezone.utc).date()
        logger.info(f"Daily limits reset. Starting balance: {current_balance}")
        
    def update_state(self, current_balance: float, daily_pnl: float, total_pnl: float):
        """Update risk manager state from database"""
        self.current_balance = current_balance
        self.daily_pnl = daily_pnl
        self.total_pnl = total_pnl
        
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        symbol: str = "EURUSD"
    ) -> float:
        """
        Calculate maximum position size based on 1% risk rule
        Returns lot size
        """
        # Calculate risk in price units
        risk_pips = abs(entry_price - stop_loss)
        if risk_pips == 0:
            return 0.0
            
        # Maximum risk amount (1% of current balance)
        max_risk_amount = self.current_balance * self.max_loss_per_trade
        
        # For forex, 1 standard lot = 100,000 units
        # Pip value for EUR/USD with 1 lot ≈ $10 per pip
        pip_value_per_lot = 10.0  # Approximate for EURUSD
        
        # Calculate lot size
        lot_size = max_risk_amount / (risk_pips * 10000 * pip_value_per_lot)
        
        # Round to 2 decimal places (standard forex lot precision)
        lot_size = round(lot_size, 2)
        
        # Minimum lot size
        return max(0.01, min(lot_size, 10.0))
        
    def validate_trade(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        lot_size: float,
        direction: str
    ) -> Tuple[bool, str]:
        """
        Validate if a trade respects all FTMO rules
        Returns (is_valid, reason)
        """
        # Calculate risk and reward
        if direction == "BUY":
            risk_pips = entry_price - stop_loss
            reward_pips = take_profit - entry_price
        else:  # SELL
            risk_pips = stop_loss - entry_price
            reward_pips = entry_price - take_profit
            
        # Check positive values
        if risk_pips <= 0:
            return False, "Stop loss must be below entry for BUY, above for SELL"
        if reward_pips <= 0:
            return False, "Take profit must be above entry for BUY, below for SELL"
            
        # Check Risk/Reward ratio (minimum 1:1)
        risk_reward = reward_pips / risk_pips
        if risk_reward < self.min_risk_reward:
            return False, f"Risk/Reward {risk_reward:.2f} is below minimum {self.min_risk_reward}"
            
        # Calculate potential loss
        pip_value = 10.0 * lot_size  # Approximate for EURUSD
        potential_loss = risk_pips * 10000 * pip_value
        potential_loss_percent = potential_loss / self.current_balance
        
        # Check max loss per trade (1%)
        if potential_loss_percent > self.max_loss_per_trade:
            return False, f"Trade risk {potential_loss_percent*100:.2f}% exceeds max {self.max_loss_per_trade*100}%"
            
        # Check daily loss limit
        daily_loss_percent = abs(self.daily_pnl) / self.daily_starting_balance if self.daily_pnl < 0 else 0
        remaining_daily_risk = self.max_daily_loss - daily_loss_percent
        
        if potential_loss_percent > remaining_daily_risk:
            return False, f"Trade would exceed daily loss limit. Remaining: {remaining_daily_risk*100:.2f}%"
            
        # Check total drawdown
        total_loss_percent = abs(self.total_pnl) / self.initial_balance if self.total_pnl < 0 else 0
        remaining_total_risk = self.max_total_loss - total_loss_percent
        
        if potential_loss_percent > remaining_total_risk:
            return False, f"Trade would exceed total drawdown limit. Remaining: {remaining_total_risk*100:.2f}%"
            
        return True, f"Trade valid. RR: {risk_reward:.2f}, Risk: {potential_loss_percent*100:.2f}%"
        
    def get_risk_status(self) -> dict:
        """Get current risk status for dashboard"""
        # Daily loss tracking
        daily_loss = abs(self.daily_pnl) if self.daily_pnl < 0 else 0
        daily_loss_percent = daily_loss / self.daily_starting_balance if self.daily_starting_balance > 0 else 0
        daily_remaining = self.max_daily_loss - daily_loss_percent
        daily_remaining_amount = daily_remaining * self.daily_starting_balance
        
        # Total drawdown tracking
        total_loss = abs(self.total_pnl) if self.total_pnl < 0 else 0
        total_loss_percent = total_loss / self.initial_balance if self.initial_balance > 0 else 0
        total_remaining = self.max_total_loss - total_loss_percent
        total_remaining_amount = total_remaining * self.initial_balance
        
        return {
            "daily_loss_percent": round(daily_loss_percent * 100, 2),
            "daily_loss_limit": self.max_daily_loss * 100,
            "daily_remaining_percent": round(daily_remaining * 100, 2),
            "daily_remaining_amount": round(daily_remaining_amount, 2),
            "daily_status": "SAFE" if daily_loss_percent < 0.03 else "WARNING" if daily_loss_percent < 0.04 else "DANGER",
            
            "total_loss_percent": round(total_loss_percent * 100, 2),
            "total_loss_limit": self.max_total_loss * 100,
            "total_remaining_percent": round(total_remaining * 100, 2),
            "total_remaining_amount": round(total_remaining_amount, 2),
            "total_status": "SAFE" if total_loss_percent < 0.07 else "WARNING" if total_loss_percent < 0.09 else "DANGER",
            
            "can_trade": daily_remaining > 0.005 and total_remaining > 0.005,
            "max_risk_per_trade": self.max_loss_per_trade * 100,
            "min_risk_reward": self.min_risk_reward
        }
