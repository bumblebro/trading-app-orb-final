"""
Live price data feed module.
Connects to Angel One WebSocket for real-time Nifty 50 price data.
Includes auto-reconnect with exponential backoff.
"""

import threading
import time
import json
import random
import math
import os
import csv
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Callable

IST = timezone(timedelta(hours=5, minutes=30))

NIFTY_50_TOKEN = "26000"
EXCHANGE_TYPE_NSE = 1
EXCHANGE_TYPE_NFO = 2

# Simulated price for development without API credentials
SIMULATED_BASE_PRICE = 22500.0


class DataFeed:
    """
    Live price feed with WebSocket connection and auto-reconnect.
    Provides real-time Nifty 50 spot price and builds 5-minute OHLCV candles.
    """

    def __init__(self, api_key: str = "", client_id: str = "",
                 feed_token: str = "", use_simulation: bool = True,
                 playback_file: Optional[str] = None,
                 playback_speed: float = 1.0):
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token
        self.use_simulation = use_simulation
        self.playback_file = playback_file
        self.playback_speed = playback_speed

        # Price state
        self._lock = threading.Lock()
        self._current_price: float = 0.0
        self._prev_price: float = 0.0
        self._token_prices: Dict[str, float] = {}
        self._last_update: Optional[datetime] = None

        # Candle building
        self._candles: List[Dict] = []
        self._current_candle: Optional[Dict] = None
        self._candle_interval = 300  # 5 minutes in seconds

        # WebSocket state
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._reconnect_count = 0
        self._max_reconnects = 50
        self._base_reconnect_delay = 5  # seconds

        # Simulation/Playback state
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_price = SIMULATED_BASE_PRICE
        self._playback_thread: Optional[threading.Thread] = None

        # Callbacks
        self.on_price_update: Optional[Callable] = None
        self.on_connection_change: Optional[Callable] = None

        # Logger (lazy import)
        self._logger = None

    def _get_logger(self):
        if self._logger is None:
            try:
                from logger import get_logger
                self._logger = get_logger()
            except ImportError:
                pass
        return self._logger

    @property
    def current_price(self) -> float:
        with self._lock:
            return self._current_price

    @property
    def prev_price(self) -> float:
        with self._lock:
            return self._prev_price

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_tick_time(self) -> Optional[datetime]:
        with self._lock:
            return self._last_update

    def get_token_price(self, token: str) -> float:
        """Get the latest price for a specific instrument token."""
        with self._lock:
            return self._token_prices.get(token, 0.0)

    @property
    def candles(self) -> List[Dict]:
        with self._lock:
            return list(self._candles)

    def start(self):
        """Start the data feed."""
        if self._running:
            return

        self._running = True

        if self.playback_file:
            self._start_playback()
        elif self.use_simulation or not all([self.api_key, self.client_id, self.feed_token]):
            self._seed_simulation_history()
            self._start_simulation()
        else:
            # History will be fetched inside connection loop
            self._start_websocket()

    def stop(self):
        """Stop the data feed."""
        self._running = False
        self._connected = False

        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _seed_simulation_history(self, count: int = 50):
        """Pre-populate simulation with historical-looking candles."""
        logger = self._get_logger()
        if logger:
            logger.info(f"Seeding simulation with {count} historical candles")
            
        now = datetime.now(IST)
        base_time = now - timedelta(seconds=count * self._candle_interval)
        
        sim_price = SIMULATED_BASE_PRICE
        temp_candles = []
        
        for i in range(count):
            candle_time = base_time + timedelta(seconds=i * self._candle_interval)
            
            # Generate a slightly trending random candle
            open_p = round(sim_price + random.gauss(0, 2), 2)
            high_p = round(open_p + abs(random.gauss(0, 5)), 2)
            low_p = round(open_p - abs(random.gauss(0, 5)), 2)
            close_p = round(open_p + random.gauss(0, 3), 2)
            
            sim_price = close_p
            
            candle = {
                "time": int(candle_time.timestamp()),
                "time_key": candle_time.strftime("%Y-%m-%d %H:%M"),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": random.randint(100, 1000)
            }
            temp_candles.append(candle)
            
        with self._lock:
            self._candles = temp_candles
            self._current_price = sim_price
            self._prev_price = sim_price
            self._sim_price = sim_price

    def _start_simulation(self):
        """Start simulated price feed for development/paper trading."""
        logger = self._get_logger()
        if logger:
            logger.info("Starting simulated live price updates")

        self._connected = True
        self._sim_thread = threading.Thread(target=self._simulate_prices, daemon=True)
        self._sim_thread.start()

    def _simulate_prices(self):
        """Generate simulated Nifty 50 prices."""
        self._sim_price = SIMULATED_BASE_PRICE
        tick_count = 0

        while self._running:
            # Simulate realistic price movement
            change = random.gauss(0, 5)  # Mean 0, StdDev 5 points
            trend = math.sin(tick_count / 100) * 2  # Slight oscillation
            self._sim_price += change + trend
            self._sim_price = max(self._sim_price, SIMULATED_BASE_PRICE - 500)
            self._sim_price = min(self._sim_price, SIMULATED_BASE_PRICE + 500)

            self._process_tick(round(self._sim_price, 2))
            tick_count += 1
            time.sleep(1)

    def _start_playback(self):
        """Start streaming data from a CSV file."""
        import os
        if not self.playback_file or not os.path.exists(self.playback_file):
            logger = self._get_logger()
            if logger:
                logger.error(f"Playback file not found: {self.playback_file}")
            return

        logger = self._get_logger()
        if logger:
            logger.info(f"Starting CSV playback from {self.playback_file}")

        self._connected = True
        self._playback_thread = threading.Thread(target=self._play_csv_data, daemon=True)
        self._playback_thread.start()

    def _play_csv_data(self):
        """Read CSV and emit prices, supporting OHLCV formats and historical timestamps."""
        try:
            with open(self.playback_file, 'r') as f:
                reader = csv.DictReader(f)
                
                # Normalize field names (case-insensitive)
                headers = {k.lower(): k for k in reader.fieldnames} if reader.fieldnames else {}
                
                for row in reader:
                    if not self._running:
                        break
                    
                    try:
                        # Extract timestamp for "Time Travel" mode
                        ts_key = next((k for k in headers if 'date' in k or 'time' in k or 'timestamp' in k), None)
                        row_time = None
                        if ts_key:
                            ts_str = row[headers[ts_key]]
                            try:
                                # Try common formats
                                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
                                    try:
                                        row_time = datetime.strptime(ts_str, fmt).replace(tzinfo=IST)
                                        break
                                    except ValueError:
                                        continue
                            except Exception:
                                pass

                        # Detect format: OHLCV or simple price
                        has_ohlc = all(k in headers for k in ['open', 'high', 'low', 'close'])
                        volume = int(row.get(headers.get('volume', ''), 0))
                        
                        if has_ohlc:
                            # Playback 4 ticks for realistic HI/LO capture
                            o = float(row[headers['open']])
                            h = float(row[headers['high']])
                            l = float(row[headers['low']])
                            c = float(row[headers['close']])
                            
                            ticks = [o, h, l, c]
                            for tick in ticks:
                                self._process_tick(tick, volume=volume, override_time=row_time)
                        elif 'price' in headers:
                            price = float(row[headers['price']])
                            self._process_tick(price, volume=volume, override_time=row_time)
                        else:
                            # Try common Close column
                            close_key = next((k for k in headers if 'close' in k), None)
                            if close_key:
                                self._process_tick(float(row[headers[close_key]]), volume=volume, override_time=row_time)
                            else:
                                continue
                        
                        # Apply speed-adjusted sleep
                        time.sleep(max(0.01, 1.0 / self.playback_speed))
                        
                    except (ValueError, KeyError, ZeroDivisionError):
                        continue
                        
            logger = self._get_logger()
            if logger:
                logger.info("CSV playback completed")
            self._connected = False
        except Exception as e:
            logger = self._get_logger()
            if logger:
                logger.error(f"Playback error: {e}")

    def _start_websocket(self):
        """Start real Angel One WebSocket connection."""
        self._ws_thread = threading.Thread(target=self._ws_connect_loop, daemon=True)
        self._ws_thread.start()

    def _ws_connect_loop(self):
        """WebSocket connection loop with auto-reconnect."""
        while self._running and self._reconnect_count < self._max_reconnects:
            try:
                self._connect_websocket()
            except Exception as e:
                logger = self._get_logger()
                if logger:
                    logger.websocket_event("ERROR", str(e))

            if not self._running:
                break

            # Auto-reconnect with exponential backoff
            self._reconnect_count += 1
            delay = min(
                self._base_reconnect_delay * (2 ** min(self._reconnect_count - 1, 3)),
                30  # Cap at 30 seconds
            )

            logger = self._get_logger()
            if logger:
                logger.websocket_event(
                    "RECONNECTING",
                    f"Attempt {self._reconnect_count}/{self._max_reconnects} in {delay}s"
                )

            time.sleep(delay)

        if self._reconnect_count >= self._max_reconnects:
            logger = self._get_logger()
            if logger:
                logger.error(f"WebSocket max reconnects ({self._max_reconnects}) reached. Stopping feed.")

    def _connect_websocket(self):
        """Establish WebSocket connection to Angel One."""
        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            self._ws = SmartWebSocketV2(
                self.feed_token,
                self.client_id,
                api_key=self.api_key
            )

            def on_open(wsapp):
                logger = self._get_logger()
                if logger:
                    logger.websocket_event("CONNECTED")
                self._connected = True
                self._reconnect_count = 0  # Reset on successful connect

                # Subscribe to Nifty 50
                self._ws.subscribe(
                    correlation_id="nifty50_feed",
                    mode=3,  # SnapQuote for full data
                    token_list=[{"exchangeType": EXCHANGE_TYPE_NSE, "tokens": [NIFTY_50_TOKEN]}]
                )
                if logger:
                    logger.websocket_event("SUBSCRIBED", "Nifty 50 (token 26000)")

                if self.on_connection_change:
                    self.on_connection_change(True)

            def on_data(wsapp, message):
                try:
                    token = message.get("instrument_token") or message.get("token")
                    ltp = message.get("last_traded_price", 0) / 100  # Price comes in paisa
                    vol = message.get("volume_traded_today", 0)
                    
                    if not ltp or ltp <= 0:
                        return
                        
                    with self._lock:
                        if token:
                            self._token_prices[str(token)] = ltp
                            
                        # If it's the Nifty Index, drive the main bot logic (candles/indicators)
                        if str(token) == str(NIFTY_50_TOKEN):
                            self._process_tick(ltp, volume=vol)
                        elif not token: # Fallback if token is missing
                            self._process_tick(ltp, volume=vol)
                            
                except Exception as e:
                    logger = self._get_logger()
                    if logger:
                        logger.error("Error processing tick", e)

            def on_error(wsapp, error):
                logger = self._get_logger()
                if logger:
                    logger.websocket_event("ERROR", str(error))
                self._connected = False
                if self.on_connection_change:
                    self.on_connection_change(False)

            def on_close(wsapp):
                logger = self._get_logger()
                if logger:
                    logger.websocket_event("DISCONNECTED")
                self._connected = False
                if self.on_connection_change:
                    self.on_connection_change(False)

            self._ws.on_open = on_open
            self._ws.on_data = on_data
            self._ws.on_error = on_error
            self._ws.on_close = on_close

            self._ws.connect()
            
            # Fetch historical data to warm up indicators
            if self.on_connection_change:
                self.on_connection_change(True)
            
            # Attempt to fetch history in background
            threading.Thread(target=self.fetch_historical_data, daemon=True).start()

        except Exception as e:
            logger = self._get_logger()
            if logger:
                logger.error(f"WebSocket connection error: {e}")
            self._connected = False
            if self.on_connection_change:
                self.on_connection_change(False)

    def subscribe_token(self, token: str, exchange: str = EXCHANGE_TYPE_NFO):
        """Dynamically subscribe to a new instrument token."""
        if not self._ws or not self._connected:
            return
            
        try:
            from SmartApi.smartWebSocketV2 import EXCHANGE_TYPE_NSE, EXCHANGE_TYPE_NFO
            # Convert str exchange to int if needed
            ex_type = EXCHANGE_TYPE_NFO if exchange == "NFO" else EXCHANGE_TYPE_NSE
            
            self._ws.subscribe(
                correlation_id="dynamic_sub",
                mode=1, # LTP mode
                token_list=[{"exchangeType": ex_type, "tokens": [str(token)]}]
            )
            logger = self._get_logger()
            if logger:
                logger.info(f"Dynamically subscribed to token: {token}")
        except Exception as e:
            logger = self._get_logger()
            if logger:
                logger.error(f"Failed to subscribe to token {token}: {e}")

    def unsubscribe_token(self, token: str, exchange: str = EXCHANGE_TYPE_NFO):
        """Dynamically unsubscribe from an instrument token."""
        if not self._ws or not self._connected:
            return
            
        try:
            from SmartApi.smartWebSocketV2 import EXCHANGE_TYPE_NSE, EXCHANGE_TYPE_NFO
            ex_type = EXCHANGE_TYPE_NFO if exchange == "NFO" else EXCHANGE_TYPE_NSE
            
            self._ws.unsubscribe(
                correlation_id="dynamic_unsub",
                mode=1,
                token_list=[{"exchangeType": ex_type, "tokens": [str(token)]}]
            )
        except Exception:
            pass

        except ImportError:
            logger = self._get_logger()
            if logger:
                logger.warning("SmartAPI not installed. Falling back to simulation.")
            self._start_simulation()
            raise Exception("SmartAPI not available")

    def _process_tick(self, price: float, volume: Optional[int] = None, override_time: Optional[datetime] = None):
        """Process a price tick — update current price and build candles."""
        now = override_time or datetime.now(IST)

        with self._lock:
            self._prev_price = self._current_price
            self._current_price = price
            self._last_update = now

        # Build candles
        self._update_candle(price, now, volume=volume)

        # Notify callback
        if self.on_price_update:
            self.on_price_update(price)

    def fetch_historical_data(self):
        """Fetch today's historical 5-minute candles to warm up indicators."""
        if self.use_simulation or not self._connected:
            return
            
        logger = self._get_logger()
        try:
            # We need a reference to smart_api which might be set via bot later
            # For now, let's assume we can fetch if self._ws has initialized but 
            # SmartWebSocketV2 doesn't provide history. We need SmartConnect.
            pass # Implementation depends on SmartConnect availability
        except Exception as e:
            if logger:
                logger.error("Failed to fetch historical data", e)

    def _update_candle(self, price: float, timestamp: datetime, volume: Optional[int] = None):
        """Update or create 5-minute candle with volume support."""
        # Calculate candle timestamp (floored to 5-minute interval)
        total_seconds = timestamp.hour * 3600 + timestamp.minute * 60
        candle_seconds = (total_seconds // self._candle_interval) * self._candle_interval
        candle_time = timestamp.replace(
            hour=candle_seconds // 3600,
            minute=(candle_seconds % 3600) // 60,
            second=0,
            microsecond=0
        )
        candle_key = candle_time.strftime("%Y-%m-%d %H:%M")

        with self._lock:
            if self._current_candle and self._current_candle.get("time_key") == candle_key:
                # Update existing candle
                self._current_candle["high"] = max(self._current_candle["high"], price)
                self._current_candle["low"] = min(self._current_candle["low"], price)
                self._current_candle["close"] = price
                
                if volume is not None and volume > 0:
                    # In playback mode we might already have absolute volume
                    # If simulating, we just increment. 
                    # For real live data, SmartAPI returns daily traded volume, 
                    # so we'd need to subtract from prev. 
                    self._current_candle["volume"] = volume 
                else:
                    self._current_candle["volume"] = self._current_candle.get("volume", 0) + 1
            else:
                # Close previous candle
                if self._current_candle:
                    self._candles.append(dict(self._current_candle))
                    # Keep max 500 candles in memory
                    if len(self._candles) > 500:
                        self._candles = self._candles[-500:]

                # Start new candle
                self._current_candle = {
                    "time": int(candle_time.timestamp()),
                    "time_key": candle_key,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1
                }

    def get_all_candles(self) -> List[Dict]:
        """Get all completed candles plus the current one."""
        with self._lock:
            result = list(self._candles)
            if self._current_candle:
                result.append(dict(self._current_candle))
            return result

    def get_price_info(self) -> Dict:
        """Get current price information."""
        with self._lock:
            change = self._current_price - self._prev_price if self._prev_price > 0 else 0
            change_pct = (change / self._prev_price * 100) if self._prev_price > 0 else 0
            return {
                "price": self._current_price,
                "prev_price": self._prev_price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "last_update": self._last_update.isoformat() if self._last_update else None,
                "connected": self._connected,
                "simulation": self.use_simulation
            }


# Global instance
_feed = None

def get_data_feed(**kwargs) -> DataFeed:
    """Get or create the global DataFeed instance."""
    global _feed
    if _feed is None:
        _feed = DataFeed(**kwargs)
    return _feed
