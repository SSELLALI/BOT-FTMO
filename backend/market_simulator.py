"""
Market Data Simulator for demo/testing purposes
Generates realistic forex price movements
"""
import numpy as np
from typing import List, Dict
from datetime import datetime, timezone
import random


class MarketSimulator:
    """Simulates realistic forex market data"""
    
    # Realistic base prices for major pairs (Jan 2026)
    BASE_PRICES = {
        "EURUSD": 1.0850,
        "GBPUSD": 1.2650,
        "USDJPY": 148.50,
        "USDCHF": 0.8820,
        "AUDUSD": 0.6280,
        "USDCAD": 1.3550,
        "NZDUSD": 0.5720
    }
    
    # Volatility (daily) for each pair
    VOLATILITY = {
        "EURUSD": 0.0008,
        "GBPUSD": 0.0012,
        "USDJPY": 0.008,
        "USDCHF": 0.0007,
        "AUDUSD": 0.0010,
        "USDCAD": 0.0008,
        "NZDUSD": 0.0011
    }
    
    # Spreads (in pips)
    SPREADS = {
        "EURUSD": 0.8,
        "GBPUSD": 1.2,
        "USDJPY": 1.0,
        "USDCHF": 1.5,
        "AUDUSD": 1.1,
        "USDCAD": 1.3,
        "NZDUSD": 1.8
    }
    
    def __init__(self):
        self.prices: Dict[str, List[float]] = {}
        self.current_prices: Dict[str, float] = {}
        self._initialize_prices()
        
    def _initialize_prices(self):
        """Initialize price history for all pairs"""
        for symbol, base_price in self.BASE_PRICES.items():
            # Generate 200 historical prices using random walk
            volatility = self.VOLATILITY.get(symbol, 0.0008)
            prices = [base_price]
            
            for _ in range(199):
                change = np.random.normal(0, volatility)
                new_price = prices[-1] * (1 + change)
                prices.append(new_price)
            
            self.prices[symbol] = prices
            self.current_prices[symbol] = prices[-1]
    
    def tick(self, symbol: str = "EURUSD") -> Dict:
        """Generate a new price tick"""
        if symbol not in self.prices:
            symbol = "EURUSD"
        
        volatility = self.VOLATILITY.get(symbol, 0.0008)
        spread_pips = self.SPREADS.get(symbol, 1.0)
        
        # Generate new price
        current = self.current_prices[symbol]
        
        # Add some trend bias randomly
        trend_bias = random.choice([-0.00001, 0, 0, 0, 0.00001])
        change = np.random.normal(trend_bias, volatility / 10)  # Smaller for tick
        
        new_price = current * (1 + change)
        
        # Update history
        self.prices[symbol].append(new_price)
        if len(self.prices[symbol]) > 500:
            self.prices[symbol] = self.prices[symbol][-500:]
        
        self.current_prices[symbol] = new_price
        
        # Calculate bid/ask
        pip_value = 0.0001 if "JPY" not in symbol else 0.01
        half_spread = (spread_pips / 2) * pip_value
        
        return {
            "symbol": symbol,
            "bid": round(new_price - half_spread, 5),
            "ask": round(new_price + half_spread, 5),
            "mid": round(new_price, 5),
            "spread": spread_pips,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    def get_prices(self, symbol: str = "EURUSD", count: int = 100) -> List[float]:
        """Get historical prices"""
        if symbol not in self.prices:
            symbol = "EURUSD"
        return self.prices[symbol][-count:]
    
    def get_ohlc(self, symbol: str = "EURUSD", periods: int = 50) -> List[Dict]:
        """Generate OHLC candles from price history"""
        prices = self.get_prices(symbol, periods * 4)
        
        ohlc = []
        for i in range(0, len(prices) - 3, 4):
            chunk = prices[i:i+4]
            ohlc.append({
                "open": round(chunk[0], 5),
                "high": round(max(chunk), 5),
                "low": round(min(chunk), 5),
                "close": round(chunk[-1], 5),
                "volume": random.randint(1000, 5000)
            })
        
        return ohlc[-periods:] if len(ohlc) > periods else ohlc
    
    def get_all_quotes(self) -> List[Dict]:
        """Get quotes for all major pairs"""
        quotes = []
        for symbol in self.BASE_PRICES.keys():
            tick = self.tick(symbol)
            quotes.append(tick)
        return quotes


# Global simulator instance
market_simulator = MarketSimulator()
