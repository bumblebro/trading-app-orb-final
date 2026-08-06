"""
Price feed for NIFTY spot.

Two sources share one interface:
  * Angel One SmartWebSocketV2 for live/paper trading, with auto-reconnect.
  * CSV replay for backtesting.

Closed 1-minute candles are published to a bounded queue that the bot drains.
During replay the producer blocks when that queue is full, so a fast replay can
never outrun the strategy and silently skip candles.
"""

from __future__ import annotations

import csv
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable, Deque, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

NIFTY_SPOT_TOKENS = ["26000", "99926000"]
EXCHANGE_TYPE_NSE = 1
EXCHANGE_TYPE_NFO = 2

MAX_CANDLE_HISTORY = 1500
CLOSED_QUEUE_LIMIT = 240
RECONNECT_BASE_DELAY = 5
RECONNECT_MAX_DELAY = 60


class DataFeed:
    def __init__(self, api_key: str = "", client_id: str = "",
                 feed_token: str = "", jwt_token: str = "",
                 playback_file: Optional[str] = None,
                 playback_speed: float = 1.0,
                 playback_start_date: str = "",
                 playback_end_date: str = "",
                 playback_period: str = "all"):
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token
        self.jwt_token = jwt_token
        self.playback_file = playback_file
        self.playback_speed = playback_speed
        self.playback_start_date = playback_start_date
        self.playback_end_date = playback_end_date
        self.playback_period = playback_period

        self._lock = threading.Lock()
        self._current_price = 0.0
        self._prev_price = 0.0
        self._session_open = 0.0
        self._token_prices: Dict[str, float] = {}
        self._last_update: Optional[datetime] = None
        self._tick_count = 0

        self._candles_1min: List[Dict] = []
        self._current_1min: Optional[Dict] = None
        self._candles_5min: List[Dict] = []
        self._current_5min: Optional[Dict] = None

        # Closed 1-minute candles awaiting the strategy.
        self._closed_queue: Deque[Dict] = deque()
        self._queue_cv = threading.Condition()

        self._ws = None
        self._threads: List[threading.Thread] = []
        self._running = False
        self._connected = False
        self._reconnects = 0
        self._playback_finished = False

        self.on_price_update: Optional[Callable] = None
        self._logger = None

    # ------------------------------------------------------------------ basics

    def _log(self):
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
    def is_connected(self) -> bool:
        return self._connected

    @property
    def playback_finished(self) -> bool:
        return self._playback_finished

    @property
    def last_tick_time(self) -> Optional[datetime]:
        with self._lock:
            return self._last_update

    def get_token_price(self, token: str) -> float:
        with self._lock:
            return self._token_prices.get(str(token), 0.0)

    def update_credentials(self, api_key: str, client_id: str,
                           feed_token: str, jwt_token: str = ""):
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token
        self.jwt_token = jwt_token

    def get_price_info(self) -> Dict:
        with self._lock:
            reference = self._session_open or self._prev_price
            change = self._current_price - reference if reference else 0.0
            return {
                "price": round(self._current_price, 2),
                "change": round(change, 2),
                "change_pct": round(change / reference * 100, 2) if reference else 0.0,
                "last_update": self._last_update.isoformat() if self._last_update else None,
                "connected": self._connected,
                "tick_count": self._tick_count,
                "playback": bool(self.playback_file),
            }

    # ---------------------------------------------------------------- lifecycle

    def start(self):
        if self._running:
            return
        self._running = True
        self._playback_finished = False

        if self.playback_file:
            self._spawn(self._replay_csv, "feed-replay")
        elif all([self.api_key, self.client_id, self.feed_token, self.jwt_token]):
            self._spawn(self._websocket_loop, "feed-ws")
        else:
            self._running = False
            log = self._log()
            if log:
                log.error("No credentials and no playback file — feed cannot start")

    def stop(self):
        self._running = False
        self._connected = False
        with self._queue_cv:
            self._queue_cv.notify_all()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _spawn(self, target, name):
        thread = threading.Thread(target=target, daemon=True, name=name)
        thread.start()
        self._threads.append(thread)

    # ------------------------------------------------------------ candle queue

    def drain_closed_candles(self, limit: int = 500) -> List[Dict]:
        """Pop the closed 1-minute candles the strategy has not seen yet."""
        with self._queue_cv:
            out = []
            while self._closed_queue and len(out) < limit:
                out.append(self._closed_queue.popleft())
            if out:
                self._queue_cv.notify_all()
            return out

    def _publish_closed(self, candle: Dict):
        with self._queue_cv:
            if self.playback_file:
                # Backpressure: never let the replay run ahead of the strategy.
                while (self._running and len(self._closed_queue) >= CLOSED_QUEUE_LIMIT):
                    self._queue_cv.wait(timeout=1.0)
            elif len(self._closed_queue) >= CLOSED_QUEUE_LIMIT:
                self._closed_queue.popleft()
            self._closed_queue.append(candle)
            self._queue_cv.notify_all()

    def get_all_candles(self, interval: str = "5minute") -> List[Dict]:
        with self._lock:
            if str(interval) in ("1minute", "60"):
                base, current = self._candles_1min, self._current_1min
            else:
                base, current = self._candles_5min, self._current_5min
            candles = list(base)
            if current:
                candles.append(dict(current))
            return candles

    def seed_history(self, candles: List[Dict], interval: int = 60):
        if not candles:
            return
        ordered = sorted(candles, key=lambda c: c.get("time", 0))
        with self._lock:
            target = self._candles_1min if interval == 60 else self._candles_5min
            target.clear()
            for candle in ordered:
                entry = dict(candle)
                if "time_key" not in entry:
                    stamp = datetime.fromtimestamp(entry["time"], IST)
                    entry["time_key"] = stamp.strftime("%Y-%m-%d %H:%M")
                    entry["time_str"] = stamp.strftime("%H:%M")
                target.append(entry)

            last = target.pop() if target else None
            if interval == 60:
                self._current_1min = last
            else:
                self._current_5min = last

            if last and self._current_price == 0:
                self._current_price = last["close"]

        log = self._log()
        if log:
            log.info(f"Seeded {len(ordered)} candles at {interval}s")

    # ---------------------------------------------------------------- ticks

    def _process_tick(self, price: float, timestamp: Optional[datetime] = None,
                      volume: Optional[int] = None):
        now = timestamp or datetime.now(IST)
        with self._lock:
            self._prev_price = self._current_price
            self._current_price = price
            self._last_update = now
            self._tick_count += 1

        closed = self._roll_candles(price, now, volume)
        for candle in closed:
            self._publish_closed(candle)

        if self.on_price_update:
            self.on_price_update(price)

    def _roll_candles(self, price: float, stamp: datetime,
                      volume: Optional[int]) -> List[Dict]:
        """Update both candle series; return any 1-minute candle that just closed."""
        finished = []
        with self._lock:
            for interval in (60, 300):
                completed = self._update_series(price, stamp, interval, volume)
                if completed and interval == 60:
                    finished.append(completed)
        return finished

    def _update_series(self, price: float, stamp: datetime, interval: int,
                       volume: Optional[int]) -> Optional[Dict]:
        seconds = stamp.hour * 3600 + stamp.minute * 60
        bucket = (seconds // interval) * interval
        start = stamp.replace(hour=bucket // 3600, minute=(bucket % 3600) // 60,
                              second=0, microsecond=0)
        key = start.strftime("%Y-%m-%d %H:%M")

        if interval == 60:
            history, current = self._candles_1min, self._current_1min
        else:
            history, current = self._candles_5min, self._current_5min

        if current and current["time_key"] == key:
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            if volume:
                current["volume"] = max(current.get("volume", 0), volume)
            return None

        completed = dict(current) if current else None
        if completed:
            history.append(completed)
            if len(history) > MAX_CANDLE_HISTORY:
                del history[0]

        fresh = {
            "time": int(start.timestamp()),
            "time_key": key,
            "time_str": start.strftime("%H:%M"),
            "open": price, "high": price, "low": price, "close": price,
            "volume": volume or 0,
        }
        if interval == 60:
            self._current_1min = fresh
        else:
            self._current_5min = fresh
        return completed

    # -------------------------------------------------------------- CSV replay

    def _replay_csv(self):
        log = self._log()
        if not self.playback_file or not os.path.exists(self.playback_file):
            if log:
                log.error(f"Playback file not found: {self.playback_file}")
            return

        start_dt = _parse_date(self.playback_start_date)
        end_dt = _parse_date(self.playback_end_date, end_of_day=True)
        delay = 0.0 if self.playback_speed >= 500 else 1.0 / max(self.playback_speed, 0.01)

        if log:
            log.info(f"Replaying {self.playback_file} at {self.playback_speed}x")
        self._connected = True

        try:
            with open(self.playback_file, "r", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = {name.lower(): name for name in (reader.fieldnames or [])}
                ts_col = columns.get("date") or columns.get("timestamp") or columns.get("time")
                if not ts_col:
                    if log:
                        log.error("Playback CSV has no timestamp column")
                    return

                period_start: Optional[datetime] = None
                for row in reader:
                    if not self._running:
                        break

                    stamp = _parse_timestamp(row.get(ts_col, ""))
                    if stamp is None:
                        continue
                    if start_dt and stamp < start_dt:
                        continue
                    if period_start is None:
                        period_start = stamp
                        end_dt = end_dt or _period_end(period_start, self.playback_period)
                    if end_dt and stamp > end_dt:
                        break

                    try:
                        o = float(row[columns["open"]])
                        h = float(row[columns["high"]])
                        l = float(row[columns["low"]])
                        c = float(row[columns["close"]])
                    except (KeyError, TypeError, ValueError):
                        continue

                    # Replay the bar as open -> high/low -> close so intrabar
                    # stop and target touches are still detected.
                    for tick in (o, h, l, c) if c >= o else (o, l, h, c):
                        self._process_tick(tick, timestamp=stamp)

                    if delay:
                        time.sleep(delay)

            if log:
                log.info("Replay finished")
        except Exception as exc:
            if log:
                log.error(f"Replay error: {exc}")
        finally:
            self._playback_finished = True
            self._connected = False

    # ---------------------------------------------------------------- websocket

    def _websocket_loop(self):
        while self._running:
            try:
                self._connect()
            except Exception as exc:
                log = self._log()
                if log:
                    log.websocket_event("ERROR", str(exc))

            if not self._running:
                break

            self._reconnects += 1
            delay = min(RECONNECT_BASE_DELAY * (2 ** min(self._reconnects - 1, 4)),
                        RECONNECT_MAX_DELAY)
            log = self._log()
            if log:
                log.websocket_event("RECONNECTING",
                                    f"attempt {self._reconnects} in {delay}s")
            time.sleep(delay)

    def _connect(self):
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        auth = self.jwt_token
        if auth and not auth.startswith("Bearer "):
            auth = f"Bearer {auth}"

        self._ws = SmartWebSocketV2(auth, self.api_key, self.client_id, self.feed_token)

        def on_open(_):
            log = self._log()
            if log:
                log.websocket_event("CONNECTED")
            self._connected = True
            self._reconnects = 0
            self._ws.subscribe("nifty_spot", 2,
                               [{"exchangeType": EXCHANGE_TYPE_NSE,
                                 "tokens": NIFTY_SPOT_TOKENS}])

        def on_data(_, message):
            try:
                for msg in (message if isinstance(message, list) else [message]):
                    if not isinstance(msg, dict):
                        continue
                    token = str(msg.get("instrument_token") or msg.get("token") or "")
                    ltp = msg.get("last_traded_price") or msg.get("ltp")
                    if ltp is None:
                        continue
                    ltp = float(ltp)
                    if ltp > 100000:      # Angel reports paise for some feeds
                        ltp /= 100.0
                    if ltp <= 0:
                        continue

                    with self._lock:
                        if token:
                            self._token_prices[token] = ltp
                        day_open = msg.get("open_price_of_the_day") or msg.get("open")
                        if day_open:
                            day_open = float(day_open)
                            self._session_open = day_open / 100.0 if day_open > 100000 else day_open

                    if token in NIFTY_SPOT_TOKENS:
                        self._process_tick(ltp, volume=msg.get("volume_traded_today"))
            except Exception as exc:
                log = self._log()
                if log:
                    log.error(f"Tick handling failed: {exc}")

        def on_error(_, error):
            self._connected = False
            log = self._log()
            if log:
                log.websocket_event("ERROR", str(error))

        def on_close(_):
            self._connected = False

        self._ws.on_open = on_open
        self._ws.on_data = on_data
        self._ws.on_error = on_error
        self._ws.on_close = on_close
        self._ws.connect()

    def subscribe_token(self, token: str, exchange: str = "NFO"):
        if not (self._ws and self._connected and token):
            return
        try:
            ex_type = EXCHANGE_TYPE_NFO if exchange == "NFO" else EXCHANGE_TYPE_NSE
            self._ws.subscribe("position", 1,
                               [{"exchangeType": ex_type, "tokens": [str(token)]}])
        except Exception as exc:
            log = self._log()
            if log:
                log.warning(f"Could not subscribe to {token}: {exc}")

    def unsubscribe_token(self, token: str, exchange: str = "NFO"):
        if not (self._ws and self._connected and token):
            return
        try:
            ex_type = EXCHANGE_TYPE_NFO if exchange == "NFO" else EXCHANGE_TYPE_NSE
            self._ws.unsubscribe("position", 1,
                                 [{"exchangeType": ex_type, "tokens": [str(token)]}])
        except Exception as exc:
            log = self._log()
            if log:
                log.warning(f"Could not unsubscribe from {token}: {exc}")


def _parse_timestamp(raw: str) -> Optional[datetime]:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _parse_date(value: str, end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        stamp = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=IST)
    except ValueError:
        return None
    return stamp.replace(hour=23, minute=59, second=59) if end_of_day else stamp


def _period_end(start: datetime, period: str) -> Optional[datetime]:
    days = {"1 month": 30, "3 months": 91, "6 months": 182, "1 year": 365}.get(period)
    return start + timedelta(days=days) if days else None


_feed: Optional[DataFeed] = None


def get_data_feed(**kwargs) -> DataFeed:
    global _feed
    if _feed is None:
        _feed = DataFeed(**kwargs)
    return _feed


def reset_data_feed():
    """Drop the cached feed so the next start picks up changed settings."""
    global _feed
    if _feed is not None:
        _feed.stop()
    _feed = None
