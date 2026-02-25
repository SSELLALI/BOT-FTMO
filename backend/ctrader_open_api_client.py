"""
cTrader Open API Client
Alternative to FIX protocol - easier to set up
Uses the official Spotware Open API
"""
import asyncio
import aiohttp
import logging
from typing import Optional, Callable, Dict, List
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ProtoOAPayloadType(Enum):
    """Open API message types"""
    PROTO_OA_APPLICATION_AUTH_REQ = 2100
    PROTO_OA_APPLICATION_AUTH_RES = 2101
    PROTO_OA_ACCOUNT_AUTH_REQ = 2102
    PROTO_OA_ACCOUNT_AUTH_RES = 2103
    PROTO_OA_VERSION_REQ = 2104
    PROTO_OA_VERSION_RES = 2105
    PROTO_OA_TRADER_REQ = 2121
    PROTO_OA_TRADER_RES = 2122
    PROTO_OA_SUBSCRIBE_SPOTS_REQ = 2126
    PROTO_OA_SUBSCRIBE_SPOTS_RES = 2127
    PROTO_OA_SPOT_EVENT = 2131
    PROTO_OA_NEW_ORDER_REQ = 2106
    PROTO_OA_EXECUTION_EVENT = 2126
    PROTO_OA_CLOSE_POSITION_REQ = 2111
    PROTO_OA_SYMBOL_BY_ID_REQ = 2114
    PROTO_OA_SYMBOL_BY_ID_RES = 2115


@dataclass
class OpenAPIConfig:
    """Configuration for cTrader Open API"""
    client_id: str
    client_secret: str
    access_token: str
    account_id: int
    is_live: bool = False


class CTraderOpenAPIClient:
    """
    cTrader Open API Client
    
    To use this client, you need:
    1. Register an application at https://openapi.ctrader.com
    2. Get Client ID and Client Secret
    3. Authenticate user and get Access Token
    4. Get Account ID from the account list
    """
    
    # API endpoints
    DEMO_HOST = "demo.ctraderapi.com"
    LIVE_HOST = "live.ctraderapi.com"
    PORT = 5035
    
    # OAuth endpoints
    AUTH_URL = "https://openapi.ctrader.com/apps/auth"
    TOKEN_URL = "https://openapi.ctrader.com/apps/token"
    
    def __init__(self, config: Optional[OpenAPIConfig] = None):
        self.config = config
        self.connected = False
        self.authenticated = False
        
        self.callbacks: Dict[str, Callable] = {}
        self.symbols: Dict[int, dict] = {}
        self.positions: Dict[int, dict] = {}
        self.pending_orders: Dict[str, dict] = {}
        
        self._reader = None
        self._writer = None
        self._running = False
        
    @classmethod
    def get_auth_url(cls, client_id: str, redirect_uri: str, scope: str = "trading") -> str:
        """
        Generate OAuth authorization URL
        User should visit this URL to authorize the application
        """
        return (
            f"{cls.AUTH_URL}?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"scope={scope}"
        )
    
    @classmethod
    async def exchange_code_for_token(
        cls,
        client_id: str,
        client_secret: str,
        auth_code: str,
        redirect_uri: str
    ) -> Optional[dict]:
        """Exchange authorization code for access token"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    cls.TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": auth_code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri
                    }
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Token exchange failed: {await response.text()}")
                        return None
        except Exception as e:
            logger.error(f"Token exchange error: {e}")
            return None
    
    async def connect(self) -> bool:
        """Connect to cTrader Open API server"""
        if not self.config:
            logger.error("No configuration provided")
            return False
        
        host = self.LIVE_HOST if self.config.is_live else self.DEMO_HOST
        
        try:
            logger.info(f"Connecting to {host}:{self.PORT}...")
            
            self._reader, self._writer = await asyncio.open_connection(
                host, self.PORT, ssl=True
            )
            
            self.connected = True
            self._running = True
            
            # Start message reader
            asyncio.create_task(self._read_messages())
            
            logger.info("Connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    async def authenticate(self) -> bool:
        """Authenticate application and account"""
        if not self.connected:
            return False
        
        # Application authentication
        app_auth = self._build_message(
            ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_REQ,
            {
                "clientId": self.config.client_id,
                "clientSecret": self.config.client_secret
            }
        )
        await self._send(app_auth)
        
        # Wait for response
        await asyncio.sleep(1)
        
        if not self.authenticated:
            # Account authentication
            account_auth = self._build_message(
                ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_REQ,
                {
                    "ctidTraderAccountId": self.config.account_id,
                    "accessToken": self.config.access_token
                }
            )
            await self._send(account_auth)
            await asyncio.sleep(1)
        
        return self.authenticated
    
    async def subscribe_spots(self, symbol_ids: List[int]):
        """Subscribe to spot prices for symbols"""
        if not self.authenticated:
            return
        
        msg = self._build_message(
            ProtoOAPayloadType.PROTO_OA_SUBSCRIBE_SPOTS_REQ,
            {
                "ctidTraderAccountId": self.config.account_id,
                "symbolId": symbol_ids
            }
        )
        await self._send(msg)
    
    async def place_market_order(
        self,
        symbol_id: int,
        side: str,  # "BUY" or "SELL"
        volume: int,  # In cents (0.01 lot = 1000)
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Optional[str]:
        """Place a market order"""
        if not self.authenticated:
            return None
        
        order_data = {
            "ctidTraderAccountId": self.config.account_id,
            "symbolId": symbol_id,
            "orderType": 1,  # Market
            "tradeSide": 1 if side == "BUY" else 2,
            "volume": volume
        }
        
        if stop_loss:
            order_data["stopLoss"] = int(stop_loss * 100000)  # Convert to price units
        if take_profit:
            order_data["takeProfit"] = int(take_profit * 100000)
        
        msg = self._build_message(
            ProtoOAPayloadType.PROTO_OA_NEW_ORDER_REQ,
            order_data
        )
        await self._send(msg)
        
        # Return a client order ID
        return f"ORDER_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    
    async def close_position(self, position_id: int, volume: Optional[int] = None):
        """Close an open position"""
        if not self.authenticated:
            return
        
        msg = self._build_message(
            ProtoOAPayloadType.PROTO_OA_CLOSE_POSITION_REQ,
            {
                "ctidTraderAccountId": self.config.account_id,
                "positionId": position_id,
                "volume": volume  # None = close full position
            }
        )
        await self._send(msg)
    
    async def disconnect(self):
        """Disconnect from server"""
        self._running = False
        self.authenticated = False
        self.connected = False
        
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
    
    def _build_message(self, msg_type: ProtoOAPayloadType, payload: dict) -> bytes:
        """Build a protobuf message (simplified JSON for demo)"""
        # In production, use proper protobuf serialization
        import json
        msg = {
            "payloadType": msg_type.value,
            "payload": payload
        }
        return json.dumps(msg).encode('utf-8') + b'\n'
    
    async def _send(self, data: bytes):
        """Send message to server"""
        if self._writer:
            self._writer.write(data)
            await self._writer.drain()
    
    async def _read_messages(self):
        """Read incoming messages"""
        while self._running:
            try:
                data = await self._reader.readline()
                if data:
                    self._handle_message(data)
            except Exception as e:
                if self._running:
                    logger.error(f"Read error: {e}")
                break
    
    def _handle_message(self, data: bytes):
        """Handle incoming message"""
        import json
        try:
            msg = json.loads(data.decode('utf-8'))
            payload_type = msg.get("payloadType")
            payload = msg.get("payload", {})
            
            if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES.value:
                logger.info("Application authenticated")
                
            elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES.value:
                self.authenticated = True
                logger.info("Account authenticated")
                
            elif payload_type == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT.value:
                if "spot" in self.callbacks:
                    self.callbacks["spot"](payload)
                    
            elif payload_type == ProtoOAPayloadType.PROTO_OA_EXECUTION_EVENT.value:
                if "execution" in self.callbacks:
                    self.callbacks["execution"](payload)
                    
        except Exception as e:
            logger.error(f"Message parse error: {e}")
    
    def on_spot(self, callback: Callable):
        """Register spot price callback"""
        self.callbacks["spot"] = callback
    
    def on_execution(self, callback: Callable):
        """Register execution callback"""
        self.callbacks["execution"] = callback


# Instructions for getting Open API credentials
OPEN_API_SETUP_GUIDE = """
## Guide de configuration cTrader Open API

### Étape 1: Créer une application
1. Allez sur https://openapi.ctrader.com
2. Connectez-vous avec votre compte cTrader ID
3. Cliquez sur "Create New App"
4. Remplissez:
   - App Name: "FTMO Trading Bot"
   - Redirect URI: http://localhost:5000/callback
5. Notez le Client ID et Client Secret

### Étape 2: Autoriser l'accès
1. Visitez l'URL d'autorisation (générée par le bot)
2. Connectez-vous avec votre compte FTMO/cTrader
3. Autorisez l'application
4. Copiez le code d'autorisation de l'URL de redirection

### Étape 3: Obtenir le token
Le bot échangera automatiquement le code contre un access token

### Étape 4: Configurer le bot
Fournissez:
- Client ID
- Client Secret
- Account ID (visible dans cTrader)
"""


def print_setup_guide():
    """Print the setup guide"""
    print(OPEN_API_SETUP_GUIDE)
