"""
Live price data feed module.
Connects to Angel One WebSocket for real-time Nifty 50 price data.
Includes auto-reconnect with exponential backoff.
"""

import threading
import time
import json
import csv
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Callable

IST = timezone(timedelta(hours=5, minutes=30))

NIFTY_50_TOKEN = "26000"
EXCHANGE_TYPE_NSE = 1
EXCHANGE_TYPE_NFO = 2


class DataFeed:
    """
    Live price feed with WebSocket connection and auto-reconnect.
    Provides real-time Nifty 50 spot price and builds OHLCV candles across multiple intervals.
    """

    def __init__(self, api_key: str = "", client_id: str = "",
                 feed_token: str = "",
                 playback_file: Optional[str] = None,
                 playback_speed: float = 1.0,
                 playback_start_date: str = "",
                 playback_period: str = "all"):
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token
        self.playback_file = playback_file
        self.playback_speed = playback_speed
        self.playback_start_date = playback_start_date
        self.playback_period = playback_period

        # Price state
        self._lock = threading.Lock()
        self._current_price: float = 0.0
        self._prev_price: float = 0.0
        self._token_prices: Dict[str, float] = {}
        self._last_update: Optional[datetime] = None

        # Candle building
        self._candles_5min: List[Dict] = []
        self._current_candle_5min: Optional[Dict] = None
        self._candles_1min: List[Dict] = []
        self._current_candle_1min: Optional[Dict] = None

        # WebSocket state
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._reconnect_count = 0
        self._max_reconnects = 50
        self._base_reconnect_delay = 5  # seconds

        # Playback state
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
        """Backward compatibility for 5-minute candles property."""
        return self.get_all_candles(interval="5minute")

    def update_credentials(self, api_key: str, client_id: str, feed_token: str):
        """Update API credentials for live feed."""
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token
        
    def start(self):
        """Start the data feed."""
        if self._running:
            return

        self._running = True

        if self.playback_file:
            self._start_playback()
        elif all([self.api_key, self.client_id, self.feed_token]):
            self._start_websocket()
        else:
            logger = self._get_logger()
            if logger:
                logger.error("Insufficient credentials and no playback file provided. Bot cannot start price feed.")
            self._running = False

    def stop(self):
        """Stop the data feed."""
        self._running = False
        self._connected = False

        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _start_playback(self):
        """Start streaming data from a CSV file."""
        if not self.playback_file or not os.path.exists(self.playback_file):
            logger = self._get_logger()
            if logger:
                logger.error(f"Playback file not found: {self.playback_file}")
            return

        logger = self._get_logger()
        if logger:
            logger.info(f"Starting CSV playback from {self.playback_file}")

        self._connected = True
        
        # Pre-calculate start and end times
        start_dt = None
        if self.playback_start_date:
            try:
                start_dt = datetime.strptime(self.playback_start_date, "%Y-%m-%d").replace(tzinfo=IST)
            except ValueError:
                pass
        
        end_dt = None
        # We'll calculate end_dt once we find the first valid row_time >= start_dt

        self._playback_thread = threading.Thread(target=self._play_csv_data, args=(start_dt,), daemon=True)
        self._playback_thread.start()

    def _play_csv_data(self, start_dt: Optional[datetime] = None):
        """Read CSV and emit prices."""
        try:
            end_dt = None
            period_started = False

            with open(self.playback_file, 'r') as f:
                reader = csv.DictReader(f)
                headers = {k.lower(): k for k in reader.fieldnames} if reader.fieldnames else {}
                
                for row in reader:
                    if not self._running:
                        break
                    
                    try:
                        ts_key = next((k for k in headers if 'date' in k or 'time' in k or 'timestamp' in k), None)
                        row_time = None
                        if ts_key:
                            ts_str = row[headers[ts_key]]
                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
                                try:
                                    row_time = datetime.strptime(ts_str, fmt).replace(tzinfo=IST)
                                    break
                                except ValueError:
                                    continue
                        
                        # Date Filtering
                        if row_time:
                            if start_dt and row_time < start_dt:
                                continue
                            
                            # Calculate End Date on the first qualifying row
                            if not period_started:
                                period_started = True
                                if self.playback_period != "all":
                                    days = {
                                        "1 month": 30,
                                        "3 months": 91,
                                        "6 months": 182,
                                        "1 year": 365
                                    }.get(self.playback_period)
                                    if days:
                                        end_dt = row_time + timedelta(days=days)
                            
                            if end_dt and row_time > end_dt:
                                logger = self._get_logger()
                                if logger:
                                    logger.info(f"Playback period ({self.playback_period}) completed at {row_time}")
                                break
                        
                        has_ohlc = all(k in headers for k in ['open', 'high', 'low', 'close'])
                        volume = int(row.get(headers.get('volume', ''), 0))
                        
                        if has_ohlc:
                            o = float(row[headers['open']])
                            h = float(row[headers['high']])
                            l = float(row[headers['low']])
                            c = float(row[headers['close']])
                            for tick in [o, h, l, c]:
                                self._process_tick(tick, volume=volume, override_time=row_time)
                        elif 'price' in headers:
                            self._process_tick(float(row[headers['price']]), volume=volume, override_time=row_time)
                        else:
                            close_key = next((k for k in headers if 'close' in k), None)
                            if close_key:
                                self._process_tick(float(row[headers[close_key]]), volume=volume, override_time=row_time)
                        
                        if self.playback_speed >= 500:
                            pass # No sleep for MAX speed
                        else:
                            time.sleep(1.0 / self.playback_speed)
                        
                    except (ValueError, KeyError):
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

            self._reconnect_count += 1
            delay = min(self._base_reconnect_delay * (2 ** min(self._reconnect_count - 1, 3)), 30)
            logger = self._get_logger()
            if logger:
                logger.websocket_event("RECONNECTING", f"Attempt {self._reconnect_count}/{self._max_reconnects} in {delay}s")
            time.sleep(delay)

    def _connect_websocket(self):
        """Establish WebSocket connection to Angel One."""
        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            self._ws = SmartWebSocketV2(self.feed_token, self.client_id, api_key=self.api_key)

            def on_open(wsapp):
                logger = self._get_logger()
                if logger: logger.websocket_event("CONNECTED")
                self._connected = True
                self._reconnect_count = 0
                self._ws.subscribe(
                    correlation_id="nifty50_feed",
                    mode=3,
                    token_list=[{"exchangeType": EXCHANGE_TYPE_NSE, "tokens": [NIFTY_50_TOKEN]}]
                )

            def on_data(wsapp, message):
                try:
                    token = message.get("instrument_token") or message.get("token")
                    ltp = message.get("last_traded_price", 0) / 100
                    vol = message.get("volume_traded_today", 0)
                    if ltp and ltp > 0:
                        with self._lock:
                            if token: self._token_prices[str(token)] = ltp
                            if str(token) == str(NIFTY_50_TOKEN):
                                self._process_tick(ltp, volume=vol)
                except Exception:
                    pass

            def on_error(wsapp, error):
                self._connected = False
                if self.on_connection_change: self.on_connection_change(False)

            def on_close(wsapp):
                self._connected = False
                if self.on_connection_change: self.on_connection_change(False)

            self._ws.on_open = on_open
            self._ws.on_data = on_data
            self._ws.on_error = on_error
            self._ws.on_close = on_close
            self._ws.connect()
        except Exception as e:
            self._connected = False

    def subscribe_token(self, token: str, exchange: str = EXCHANGE_TYPE_NFO):
        if not self._ws or not self._connected: return
        try:
            from SmartApi.smartWebSocketV2 import EXCHANGE_TYPE_NSE, EXCHANGE_TYPE_NFO
            ex_type = EXCHANGE_TYPE_NFO if exchange == "NFO" else EXCHANGE_TYPE_NSE
            self._ws.subscribe(correlation_id="dynamic", mode=1, token_list=[{"exchangeType": ex_type, "tokens": [str(token)]}])
        except Exception: pass

    def unsubscribe_token(self, token: str, exchange: str = EXCHANGE_TYPE_NFO):
        if not self._ws or not self._connected: return
        try:
            from SmartApi.smartWebSocketV2 import EXCHANGE_TYPE_NSE, EXCHANGE_TYPE_NFO
            ex_type = EXCHANGE_TYPE_NFO if exchange == "NFO" else EXCHANGE_TYPE_NSE
            self._ws.unsubscribe(correlation_id="unsub", mode=1, token_list=[{"exchangeType": ex_type, "tokens": [str(token)]}])
        except Exception: pass

    def _process_tick(self, price: float, volume: Optional[int] = None, override_time: Optional[datetime] = None):
        """Process a price tick."""
        now = override_time or datetime.now(IST)
        with self._lock:
            self._prev_price = self._current_price
            self._current_price = price
            self._last_update = now
        self._update_all_candles(price, now, volume=volume)
        if self.on_price_update: self.on_price_update(price)

    def _update_all_candles(self, price: float, timestamp: datetime, volume: Optional[int] = None):
        self._update_candle_list(price, timestamp, 60, volume)
        self._update_candle_list(price, timestamp, 300, volume)

    def _update_candle_list(self, price: float, timestamp: datetime, interval: int, volume: Optional[int] = None):
        total_seconds = timestamp.hour * 3600 + timestamp.minute * 60
        candle_seconds = (total_seconds // interval) * interval
        candle_time = timestamp.replace(hour=candle_seconds // 3600, minute=(candle_seconds % 3600) // 60, second=0, microsecond=0)
        candle_key = candle_time.strftime("%Y-%m-%d %H:%M")

        with self._lock:
            if interval == 60:
                candles_list, current = self._candles_1min, self._current_candle_1min
            else:
                candles_list, current = self._candles_5min, self._current_candle_5min

            if current and current.get("time_key") == candle_key:
                current["high"] = max(current["high"], price)
                current["low"] = min(current["low"], price)
                current["close"] = price
                if volume is not None and volume > 0:
                    if current.get("volume", 0) > volume and interval == 300:
                         current["volume"] = current.get("volume", 0) + volume
                    else: current["volume"] = volume 
                else: current["volume"] = current.get("volume", 0) + 1
            else:
                if current:
                    candles_list.append(dict(current))
                    if len(candles_list) > 500: del candles_list[0]
                new_candle = {
                    "time": int(candle_time.timestamp()),
                    "time_key": candle_key,
                    "open": price, "high": price, "low": price, "close": price,
                    "volume": 1, "time_str": candle_time.strftime("%H:%M")
                }
                if interval == 60: self._current_candle_1min = new_candle
                else: self._current_candle_5min = new_candle

    def get_all_candles(self, interval: str = "5minute") -> List[Dict]:
        with self._lock:
            if interval == "1minute" or str(interval) == "60":
                base_list, current = self._candles_1min, self._current_candle_1min
            else:
                base_list, current = self._candles_5min, self._current_candle_5min
            result = list(base_list)
            if current: result.append(dict(current))
            return result

    def get_daily_range(self, target_date: str) -> Optional[Dict]:
        """Scan CSV or history for daily High/Low of a specific date."""
        if not self.playback_file or not os.path.exists(self.playback_file):
            return None
        
        try:
            high = float('-inf')
            low = float('inf')
            found = False

            with open(self.playback_file, 'r') as f:
                reader = csv.DictReader(f)
                headers = {k.lower(): k for k in reader.fieldnames} if reader.fieldnames else {}
                ts_key = next((k for k in headers if 'date' in k or 'time' in k or 'timestamp' in k), None)
                
                if not ts_key: return None

                for row in reader:
                    ts_str = row[headers[ts_key]]
                    if not ts_str.startswith(target_date):
                        if found: break # Optimization: past the date
                        continue
                    
                    found = True
                    h_val = float(row[headers.get('high', headers.get('price'))])
                    l_val = float(row[headers.get('low', headers.get('price'))])
                    high = max(high, h_val)
                    low = min(low, l_val)
            
            if found:
                return {"high": high, "low": low, "range": round(high - low, 2)}
        except Exception:
            pass
        return None

    def get_price_info(self) -> Dict:
        with self._lock:
            change = self._current_price - self._prev_price if self._prev_price > 0 else 0
            change_pct = (change / self._prev_price * 100) if self._prev_price > 0 else 0
            return {
                "price": self._current_price, "prev_price": self._prev_price,
                "change": round(change, 2), "change_pct": round(change_pct, 2),
                "last_update": self._last_update.isoformat() if self._last_update else None,
                "connected": self._connected, "simulation": False
            }

_feed = None
def get_data_feed(**kwargs) -> DataFeed:
    global _feed
    if _feed is None: _feed = DataFeed(**kwargs)
    return _feed
