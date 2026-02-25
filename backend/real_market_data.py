"""
Real Market Data Provider
Fetches real forex prices from multiple sources
Falls back to simulation if APIs unavailable
"""
import aiohttp
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone
import logging
import random

logger = logging.getLogger(__name__)


class RealMarketDataProvider:
    """
    Fetches real forex market data from free APIs
    Supports multiple providers with fallback
    """
    
    # Free API endpoints (no auth required for basic access)
    PROVIDERS = {
        "frankfurter": {
            "url": "https://api.frankfurter.app/latest",
            "params": {"from": "USD", "to": "EUR,GBP,JPY,CHF,AUD,CAD,NZD"},
            "type": "rates"
        },
        "exchangerate": {
            "url": "https://open.er-api.com/v6/latest/USD",
            "type": "rates"
        }
    }
    
    # Forex pair mappings
    PAIRS = {
        "EURUSD": ("EUR", "USD", False),  # (base, quote, inverted)
        "GBPUSD": ("GBP", "USD", False),
        "USDJPY": ("USD", "JPY", True),
        "USDCHF": ("USD", "CHF", True),
        "AUDUSD": ("AUD", "USD", False),
        "USDCAD": ("USD", "CAD", True),
        "NZDUSD": ("NZD", "USD", False)
    }
    
    # Realistic base prices (fallback)
    FALLBACK_PRICES = {
        "EURUSD": 1.0850,
        "GBPUSD": 1.2650,
        "USDJPY": 148.50,
        "USDCHF": 0.8820,
        "AUDUSD": 0.6280,
        "USDCAD": 1.3550,
        "NZDUSD": 0.5720
    }
    
    # Spreads in pips
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
        self.last_rates: Dict[str, float] = {}
        self.last_update: Optional[datetime] = None
        self.price_history: Dict[str, List[float]] = {pair: [] for pair in self.PAIRS}
        self._initialize_history()
        
    def _initialize_history(self):
        """Initialize price history with realistic data"""
        for pair, base_price in self.FALLBACK_PRICES.items():
            volatility = 0.0008 if "JPY" not in pair else 0.008
            prices = [base_price]
            for _ in range(199):
                change = random.gauss(0, volatility)
                new_price = prices[-1] * (1 + change)
                prices.append(new_price)
            self.price_history[pair] = prices
            self.last_rates[pair] = prices[-1]
    
    async def fetch_rates(self) -> Dict[str, float]:
        """Fetch real rates from APIs"""
        
        # Try Frankfurter API first (free, no key needed)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.frankfurter.app/latest",
                    params={"from": "USD"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        rates = data.get("rates", {})
                        
                        # Convert to forex pairs
                        forex_rates = {}
                        
                        if "EUR" in rates:
                            forex_rates["EURUSD"] = round(1 / rates["EUR"], 5)
                        if "GBP" in rates:
                            forex_rates["GBPUSD"] = round(1 / rates["GBP"], 5)
                        if "JPY" in rates:
                            forex_rates["USDJPY"] = round(rates["JPY"], 3)
                        if "CHF" in rates:
                            forex_rates["USDCHF"] = round(rates["CHF"], 5)
                        if "AUD" in rates:
                            forex_rates["AUDUSD"] = round(1 / rates["AUD"], 5)
                        if "CAD" in rates:
                            forex_rates["USDCAD"] = round(rates["CAD"], 5)
                        if "NZD" in rates:
                            forex_rates["NZDUSD"] = round(1 / rates["NZD"], 5)
                        
                        if forex_rates:
                            self.last_rates.update(forex_rates)
                            self.last_update = datetime.now(timezone.utc)
                            logger.info(f"Fetched real rates: {forex_rates}")
                            return forex_rates
                            
        except Exception as e:
            logger.warning(f"Frankfurter API failed: {e}")
        
        # Try Open Exchange Rates API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://open.er-api.com/v6/latest/USD",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        rates = data.get("rates", {})
                        
                        forex_rates = {}
                        if "EUR" in rates:
                            forex_rates["EURUSD"] = round(1 / rates["EUR"], 5)
                        if "GBP" in rates:
                            forex_rates["GBPUSD"] = round(1 / rates["GBP"], 5)
                        if "JPY" in rates:
                            forex_rates["USDJPY"] = round(rates["JPY"], 3)
                        if "CHF" in rates:
                            forex_rates["USDCHF"] = round(rates["CHF"], 5)
                        if "AUD" in rates:
                            forex_rates["AUDUSD"] = round(1 / rates["AUD"], 5)
                        if "CAD" in rates:
                            forex_rates["USDCAD"] = round(rates["CAD"], 5)
                        if "NZD" in rates:
                            forex_rates["NZDUSD"] = round(1 / rates["NZD"], 5)
                        
                        if forex_rates:
                            self.last_rates.update(forex_rates)
                            self.last_update = datetime.now(timezone.utc)
                            return forex_rates
                            
        except Exception as e:
            logger.warning(f"Open ER API failed: {e}")
        
        # Return last known rates or fallback
        return self.last_rates if self.last_rates else self.FALLBACK_PRICES
    
    def simulate_tick(self, symbol: str, base_rate: Optional[float] = None) -> Dict:
        """
        Simulate a realistic price tick based on real base rate
        Adds micro-movements for realistic trading simulation
        """
        if symbol not in self.PAIRS:
            symbol = "EURUSD"
        
        # Use real rate as base, or last known
        base = base_rate or self.last_rates.get(symbol, self.FALLBACK_PRICES[symbol])
        
        # Add micro-volatility for tick simulation
        is_jpy = "JPY" in symbol
        volatility = 0.00008 if not is_jpy else 0.008
        
        # Random walk with mean reversion
        current = self.price_history[symbol][-1] if self.price_history[symbol] else base
        
        # Mean reversion factor
        mean_reversion = (base - current) * 0.01
        
        # Random component
        random_change = random.gauss(0, volatility)
        
        # New price
        new_price = current + mean_reversion + (current * random_change)
        
        # Update history
        self.price_history[symbol].append(new_price)
        if len(self.price_history[symbol]) > 500:
            self.price_history[symbol] = self.price_history[symbol][-500:]
        
        self.last_rates[symbol] = new_price
        
        # Calculate bid/ask with spread
        spread_pips = self.SPREADS.get(symbol, 1.0)
        pip_value = 0.0001 if not is_jpy else 0.01
        half_spread = (spread_pips / 2) * pip_value
        
        return {
            "symbol": symbol,
            "bid": round(new_price - half_spread, 5 if not is_jpy else 3),
            "ask": round(new_price + half_spread, 5 if not is_jpy else 3),
            "mid": round(new_price, 5 if not is_jpy else 3),
            "spread": spread_pips,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "real" if self.last_update else "simulated"
        }
    
    def get_all_quotes(self) -> List[Dict]:
        """Get quotes for all pairs"""
        quotes = []
        for symbol in self.PAIRS:
            quote = self.simulate_tick(symbol)
            quotes.append(quote)
        return quotes
    
    def get_price_history(self, symbol: str, count: int = 100) -> List[float]:
        """Get price history for a symbol"""
        if symbol not in self.price_history:
            symbol = "EURUSD"
        return self.price_history[symbol][-count:]


# Global instance
real_market_data = RealMarketDataProvider()
