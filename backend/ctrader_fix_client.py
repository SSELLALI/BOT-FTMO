"""
cTrader FIX API Client
Connects to cTrader/FTMO via FIX Protocol
"""
import socket
import ssl
import time
import threading
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, List
import hashlib

logger = logging.getLogger(__name__)


class FIXMessage:
    """FIX Protocol Message Builder/Parser"""
    
    SOH = '\x01'  # FIX delimiter
    
    # Common FIX tags
    TAGS = {
        8: "BeginString",
        9: "BodyLength",
        35: "MsgType",
        49: "SenderCompID",
        56: "TargetCompID",
        34: "MsgSeqNum",
        52: "SendingTime",
        50: "SenderSubID",
        57: "TargetSubID",
        98: "EncryptMethod",
        108: "HeartBtInt",
        553: "Username",
        554: "Password",
        10: "CheckSum",
        # Market Data
        262: "MDReqID",
        263: "SubscriptionRequestType",
        264: "MarketDepth",
        265: "MDUpdateType",
        267: "NoMDEntryTypes",
        269: "MDEntryType",
        146: "NoRelatedSym",
        55: "Symbol",
        # Order
        11: "ClOrdID",
        38: "OrderQty",
        40: "OrdType",
        44: "Price",
        54: "Side",
        59: "TimeInForce",
        60: "TransactTime",
    }
    
    # Message types
    MSG_TYPES = {
        "A": "Logon",
        "0": "Heartbeat",
        "1": "TestRequest",
        "2": "ResendRequest",
        "3": "Reject",
        "4": "SequenceReset",
        "5": "Logout",
        "V": "MarketDataRequest",
        "W": "MarketDataSnapshotFullRefresh",
        "X": "MarketDataIncrementalRefresh",
        "D": "NewOrderSingle",
        "8": "ExecutionReport",
        "j": "BusinessMessageReject",
    }
    
    def __init__(self, msg_type: str = None):
        self.fields: Dict[int, str] = {}
        if msg_type:
            self.fields[35] = msg_type
    
    def set(self, tag: int, value) -> 'FIXMessage':
        self.fields[tag] = str(value)
        return self
    
    def get(self, tag: int) -> Optional[str]:
        return self.fields.get(tag)
    
    def build(self, sender_comp_id: str, target_comp_id: str, seq_num: int, 
              sender_sub_id: str = None) -> bytes:
        """Build FIX message with proper header and checksum"""
        
        # Body fields (excluding 8, 9, 10)
        body_fields = []
        
        # Add required header fields
        body_fields.append(f"35={self.fields.get(35, '0')}")
        body_fields.append(f"49={sender_comp_id}")
        body_fields.append(f"56={target_comp_id}")
        body_fields.append(f"34={seq_num}")
        body_fields.append(f"52={datetime.now(timezone.utc).strftime('%Y%m%d-%H:%M:%S.%f')[:-3]}")
        
        if sender_sub_id:
            body_fields.append(f"50={sender_sub_id}")
        
        # Add other fields
        for tag, value in self.fields.items():
            if tag not in [8, 9, 10, 35, 49, 56, 34, 52, 50]:
                body_fields.append(f"{tag}={value}")
        
        body = self.SOH.join(body_fields) + self.SOH
        
        # Calculate body length
        body_length = len(body)
        
        # Build full message
        header = f"8=FIX.4.4{self.SOH}9={body_length}{self.SOH}"
        message_without_checksum = header + body
        
        # Calculate checksum
        checksum = sum(ord(c) for c in message_without_checksum) % 256
        full_message = message_without_checksum + f"10={checksum:03d}{self.SOH}"
        
        return full_message.encode('ascii')
    
    @classmethod
    def parse(cls, data: bytes) -> 'FIXMessage':
        """Parse FIX message from bytes"""
        msg = cls()
        try:
            text = data.decode('ascii')
            pairs = text.split(cls.SOH)
            for pair in pairs:
                if '=' in pair:
                    tag, value = pair.split('=', 1)
                    msg.fields[int(tag)] = value
        except Exception as e:
            logger.error(f"Failed to parse FIX message: {e}")
        return msg


class CTraderFIXClient:
    """
    cTrader FIX API Client
    Handles connection, authentication, and trading operations
    """
    
    def __init__(
        self,
        host: str,
        port: int,
        sender_comp_id: str,
        target_comp_id: str,
        password: str,
        sender_sub_id: str = None,
        use_ssl: bool = True
    ):
        self.host = host
        self.port = port
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.password = password
        self.sender_sub_id = sender_sub_id
        self.use_ssl = use_ssl
        
        self.socket: Optional[socket.socket] = None
        self.ssl_socket: Optional[ssl.SSLSocket] = None
        self.connected = False
        self.logged_in = False
        self.seq_num = 1
        
        self.heartbeat_interval = 30
        self.last_heartbeat = time.time()
        
        self.callbacks: Dict[str, Callable] = {}
        self.market_data: Dict[str, Dict] = {}
        
        self._reader_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._running = False
    
    def connect(self) -> bool:
        """Establish connection to cTrader FIX server"""
        try:
            logger.info(f"Connecting to {self.host}:{self.port}...")
            
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(30)
            
            if self.use_ssl:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.ssl_socket = context.wrap_socket(self.socket, server_hostname=self.host)
                self.ssl_socket.connect((self.host, self.port))
            else:
                self.socket.connect((self.host, self.port))
            
            self.connected = True
            logger.info("Socket connected successfully")
            
            # Start reader thread
            self._running = True
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()
            
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.connected = False
            return False
    
    def login(self) -> bool:
        """Send logon message"""
        if not self.connected:
            logger.error("Not connected")
            return False
        
        try:
            logon = FIXMessage("A")  # Logon message type
            logon.set(98, 0)  # EncryptMethod = None
            logon.set(108, self.heartbeat_interval)  # HeartBtInt
            logon.set(141, "Y")  # ResetSeqNumFlag - required by cTrader
            logon.set(553, self.sender_comp_id.split('.')[-1])  # Username (account number)
            logon.set(554, self.password)  # Password
            
            self._send(logon)
            
            # Wait for logon response (up to 10 seconds)
            for _ in range(20):
                time.sleep(0.5)
                if self.logged_in:
                    break
            
            if self.logged_in:
                # Start heartbeat thread
                self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
                self._heartbeat_thread.start()
                logger.info("Login successful")
                return True
            else:
                logger.error("Login failed - no confirmation received")
                return False
                
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False
    
    def logout(self):
        """Send logout message and disconnect"""
        if self.logged_in:
            try:
                logout = FIXMessage("5")  # Logout
                self._send(logout)
                time.sleep(1)
            except:
                pass
        
        self._running = False
        self.logged_in = False
        self.connected = False
        
        if self.ssl_socket:
            try:
                self.ssl_socket.close()
            except:
                pass
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
    
    def subscribe_market_data(self, symbols: List[str]):
        """Subscribe to market data for symbols"""
        if not self.logged_in:
            logger.error("Not logged in")
            return
        
        for symbol in symbols:
            md_req = FIXMessage("V")  # MarketDataRequest
            md_req.set(262, f"MD_{symbol}_{int(time.time())}")  # MDReqID
            md_req.set(263, 1)  # SubscriptionRequestType = Snapshot + Updates
            md_req.set(264, 1)  # MarketDepth = Top of Book
            md_req.set(265, 0)  # MDUpdateType = Full Refresh
            md_req.set(267, 2)  # NoMDEntryTypes
            md_req.set(269, 0)  # MDEntryType = Bid
            md_req.set(269, 1)  # MDEntryType = Offer
            md_req.set(146, 1)  # NoRelatedSym
            md_req.set(55, symbol)  # Symbol
            
            self._send(md_req)
            logger.info(f"Subscribed to {symbol}")
    
    def place_order(
        self,
        symbol: str,
        side: str,  # "BUY" or "SELL"
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None
    ) -> Optional[str]:
        """Place a new order"""
        if not self.logged_in:
            logger.error("Not logged in")
            return None
        
        order = FIXMessage("D")  # NewOrderSingle
        cl_ord_id = f"ORD_{int(time.time() * 1000)}"
        
        order.set(11, cl_ord_id)  # ClOrdID
        order.set(55, symbol)  # Symbol
        order.set(54, 1 if side == "BUY" else 2)  # Side: 1=Buy, 2=Sell
        order.set(38, quantity)  # OrderQty
        order.set(40, 1 if order_type == "MARKET" else 2)  # OrdType: 1=Market, 2=Limit
        order.set(59, 1)  # TimeInForce: 1=GTC
        order.set(60, datetime.now(timezone.utc).strftime('%Y%m%d-%H:%M:%S'))  # TransactTime
        
        if price and order_type == "LIMIT":
            order.set(44, price)  # Price
        
        self._send(order)
        logger.info(f"Order placed: {side} {quantity} {symbol}")
        
        return cl_ord_id
    
    def _send(self, message: FIXMessage):
        """Send FIX message"""
        data = message.build(
            self.sender_comp_id,
            self.target_comp_id,
            self.seq_num,
            self.sender_sub_id
        )
        
        sock = self.ssl_socket if self.use_ssl else self.socket
        sock.send(data)
        
        self.seq_num += 1
        logger.debug(f"Sent: {data.decode('ascii')[:100]}...")
    
    def _read_loop(self):
        """Background thread to read incoming messages"""
        sock = self.ssl_socket if self.use_ssl else self.socket
        buffer = b""
        
        while self._running:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                
                buffer += data
                
                # Parse complete messages
                while b"10=" in buffer and b"\x01" in buffer[buffer.find(b"10="):]:
                    # Find end of message (after checksum)
                    checksum_pos = buffer.find(b"10=")
                    end_pos = buffer.find(b"\x01", checksum_pos + 3) + 1
                    
                    if end_pos > 0:
                        message_data = buffer[:end_pos]
                        buffer = buffer[end_pos:]
                        
                        self._handle_message(FIXMessage.parse(message_data))
                    else:
                        break
                        
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Read error: {e}")
                break
    
    def _handle_message(self, msg: FIXMessage):
        """Handle incoming FIX message"""
        msg_type = msg.get(35)
        
        if msg_type == "A":  # Logon response
            self.logged_in = True
            logger.info("Logon confirmed")
            
        elif msg_type == "5":  # Logout
            self.logged_in = False
            logger.info("Logged out")
            
        elif msg_type == "0":  # Heartbeat
            self.last_heartbeat = time.time()
            
        elif msg_type == "1":  # Test Request
            # Respond with heartbeat
            heartbeat = FIXMessage("0")
            heartbeat.set(112, msg.get(112) or "")  # TestReqID
            self._send(heartbeat)
            
        elif msg_type == "W":  # Market Data Snapshot
            symbol = msg.get(55)
            if symbol:
                self.market_data[symbol] = {
                    "bid": float(msg.get(270) or 0),
                    "ask": float(msg.get(270) or 0),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                if "market_data" in self.callbacks:
                    self.callbacks["market_data"](symbol, self.market_data[symbol])
                    
        elif msg_type == "8":  # Execution Report
            if "execution" in self.callbacks:
                self.callbacks["execution"](msg)
                
        elif msg_type == "3":  # Reject
            logger.warning(f"Message rejected: {msg.get(58)}")
            
        elif msg_type == "j":  # Business Reject
            logger.warning(f"Business reject: {msg.get(58)}")
    
    def _heartbeat_loop(self):
        """Send periodic heartbeats"""
        while self._running and self.logged_in:
            time.sleep(self.heartbeat_interval - 5)
            if self._running and self.logged_in:
                heartbeat = FIXMessage("0")
                self._send(heartbeat)
    
    def on_market_data(self, callback: Callable):
        """Register market data callback"""
        self.callbacks["market_data"] = callback
    
    def on_execution(self, callback: Callable):
        """Register execution report callback"""
        self.callbacks["execution"] = callback


# Connection configuration for FTMO
FTMO_CONFIG = {
    "host": "live-uk-eqx-01.p.c-trader.com",
    "port": 5211,  # SSL port
    "sender_comp_id": "live.ftmo.17061677",
    "target_comp_id": "cServer",
    "sender_sub_id": "QUOTE",
    "password": "",  # To be configured
    "use_ssl": True
}


def create_ftmo_client(password: str) -> CTraderFIXClient:
    """Create a configured FTMO FIX client"""
    return CTraderFIXClient(
        host=FTMO_CONFIG["host"],
        port=FTMO_CONFIG["port"],
        sender_comp_id=FTMO_CONFIG["sender_comp_id"],
        target_comp_id=FTMO_CONFIG["target_comp_id"],
        password=password,
        sender_sub_id=FTMO_CONFIG["sender_sub_id"],
        use_ssl=FTMO_CONFIG["use_ssl"]
    )
