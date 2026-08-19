"""
ORB trading bot runtime.

Owns the session loop, risk limits and order lifecycle. All strategy decisions
are delegated to `strategy_orb.OrbStrategy`, the same engine the research
backtester drives, so live behaviour matches the backtest.

Signals are evaluated only on *closed* 1-minute candles. Exits are checked both
on closed candles (using the bar high/low) and on every live tick, so a stop is
never missed between bars.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from auth import login_and_get_session
from data_feed import DataFeed, get_data_feed
from database import (
    close_trade, get_active_trade, get_all_settings, get_all_time_pnl,
    get_first_trade_date, get_setting, get_today_pnl, get_today_trade_count,
    insert_signal_log, insert_trade, update_trade,
)
from logger import get_logger
from market_calendar import get_ist_now, is_trading_day, should_bot_run
from option_pricing import (
    atm_strike, black_scholes, next_weekly_expiry, realised_volatility,
    time_to_expiry_years,
)
from order_manager import OrderManager, get_order_manager
from strategy_orb import (
    PHASE_CLOSED, PHASE_DONE, PHASE_IN_TRADE, PHASE_PREOPEN, OrbConfig,
    OrbStrategy, Position,
)

IST = timezone(timedelta(hours=5, minutes=30))

PHASE_DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
NIFTY_SPOT_TOKENS = ("99926000", "26000")


class TradingBot:
    """Runs the ORB strategy against a live, paper or replayed price feed."""

    def __init__(self):
        self.logger = get_logger()
        self.data_feed: Optional[DataFeed] = None
        self.order_manager: Optional[OrderManager] = None
        self.strategy = OrbStrategy(OrbConfig())

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        self._session_date: Optional[str] = None
        self._last_candle_key: Optional[str] = None
        self._last_close = 0.0
        self._kill_switch_tripped = False

        # Option pricing context for the open position.
        self._daily_closes: List[float] = []
        self._iv = 0.14
        self._position: Optional[Position] = None
        self._strike: float = 0.0
        self._expiry: Optional[datetime] = None

        self.capital = 0.0
        self.capital_history: List[float] = []
        self._first_trade_date: Optional[str] = None

        # Broker / feed connection state for the dashboard.
        self._data_source = get_setting("data_source") or "playback"
        self._broker_status = "stopped"  # stopped|playback|connected|failed
        self._broker_message = "Bot stopped"
        self._available_cash_cache: Optional[float] = None
        self._available_cash_cached_at = 0.0
        self._last_session_refresh_at = 0.0

    # --------------------------------------------------------------- lifecycle

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_signal(self) -> str:
        with self._lock:
            return self._describe_signal()

    @property
    def mode(self) -> str:
        return get_setting("trading_mode") or "paper"

    @property
    def is_playback(self) -> bool:
        return bool(self.data_feed and self.data_feed.playback_file)

    def _now(self) -> datetime:
        """Current time, following the replay clock when backtesting."""
        if self.is_playback and self.data_feed and self.data_feed.last_tick_time:
            return self.data_feed.last_tick_time
        return get_ist_now()

    def reload_config(self):
        self.strategy.config = OrbConfig.from_settings(get_setting)

    def start(self):
        if self._running:
            self.logger.warning("Bot is already running")
            return

        # Ensure a previous soft-stop released any Angel WS slots.
        if self.data_feed:
            try:
                self.data_feed.stop()
            except Exception:
                pass
            self.data_feed = None

        self.reload_config()
        mode = self.mode
        data_source = get_setting("data_source") or "playback"
        self._data_source = data_source
        self._kill_switch_tripped = False
        # Force a fresh session on every start so a pre-open CLOSED phase
        # cannot stick around after a soft restart once the market is open.
        self._session_date = None
        self._position = None
        self._strike = 0
        self.strategy.reset_day()

        self.data_feed = self._build_feed(mode, data_source)
        smart_api = self._maybe_login(mode, data_source)

        self.order_manager = get_order_manager()
        if smart_api:
            self.order_manager.set_smart_api(smart_api)

        initial_capital = float(get_setting("initial_capital") or "500000")
        self.capital = initial_capital + get_all_time_pnl(mode=mode).get("all_time_pnl", 0)
        self._first_trade_date = get_first_trade_date(mode=mode)
        self.order_manager.update_context(data_feed=self.data_feed, capital=self.capital)

        # Replay today's closed bars into the strategy *before* the live feed
        # starts, so a late start still builds the real 09:15 opening range.
        self._catch_up_strategy_from_history()

        self.data_feed.start()
        self._restore_open_position()
        if self.mode == "live" and self._position is None:
            adopted = self.adopt_broker_position()
            if adopted.get("status") == "recovered":
                self.logger.info(
                    f"Adopted broker position after clear/restart: {adopted.get('symbol')}"
                )

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="orb-bot")
        self._thread.start()
        self.logger.bot_status("STARTED", f"mode={mode} source={data_source}")

    def stop(self):
        was_running = self._running
        self._running = False
        if self.data_feed:
            self.data_feed.stop()
        self._broker_status = "stopped"
        self._broker_message = "Bot stopped"
        self._available_cash_cache = None
        self._available_cash_cached_at = 0.0
        self._last_session_refresh_at = 0.0
        if was_running:
            self.logger.bot_status("STOPPED")

    def _build_feed(self, mode: str, data_source: str) -> DataFeed:
        from data_feed import reset_data_feed
        import os

        # A stale singleton would keep replaying the previous settings.
        reset_data_feed()

        if data_source == "playback":
            path = get_setting("playback_file") or "bot/data/nifty_sample.csv"
            if not os.path.isabs(path):
                relative = path[4:] if path.startswith("bot/") else path
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)
            return get_data_feed(
                playback_file=path,
                playback_speed=float(get_setting("playback_speed") or "500"),
                playback_start_date=get_setting("playback_start_date") or "",
                playback_end_date=get_setting("playback_end_date") or "",
                playback_period=get_setting("playback_period") or "all",
            )

        return get_data_feed(api_key=get_setting("api_key"),
                             client_id=get_setting("client_id"))

    def _maybe_login(self, mode: str, data_source: str):
        if data_source == "playback":
            self._broker_status = "playback"
            self._broker_message = "Using CSV playback — Angel One not used"
            return None

        smart_api, feed_token = login_and_get_session()
        if not (smart_api and feed_token):
            self._broker_status = "failed"
            self._broker_message = "Angel One login failed — check credentials / TOTP"
            self.logger.error("Angel One login failed — cannot start a live feed")
            if mode == "live":
                raise RuntimeError("Live mode requires a working broker session")
            return None

        self.data_feed.update_credentials(get_setting("api_key"), get_setting("client_id"),
                                          feed_token, smart_api.access_token)
        self._seed_history(smart_api)
        self._broker_status = "connected"
        self._broker_message = "Angel One session active"
        return smart_api

    def _seed_history(self, smart_api):
        """Pull recent 1-minute candles so the opening range survives a restart."""
        now = get_ist_now()
        params_base = {
            "exchange": "NSE",
            "interval": "ONE_MINUTE",
            "fromdate": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
            "todate": now.strftime("%Y-%m-%d %H:%M"),
        }
        for token in NIFTY_SPOT_TOKENS:
            try:
                response = smart_api.getCandleData({**params_base, "symboltoken": token})
            except Exception as exc:
                self.logger.warning(f"History fetch failed for token {token}: {exc}")
                continue

            rows = (response or {}).get("data") or []
            candles = []
            for row in rows:
                parsed = _parse_history_row(row)
                if parsed:
                    candles.append(parsed)
            if candles:
                self.data_feed.seed_history(candles, interval=60)
                self.logger.info(f"Seeded {len(candles)} 1-minute candles from token {token}")
                return
        self.logger.error("Could not seed historical candles from any NIFTY token")

    def _catch_up_strategy_from_history(self):
        """
        Feed today's already-closed 1-min bars into the strategy after a late start.

        Historical breakout signals are ignored — we only rebuild range / phase.
        Live breakouts after catch-up can still trigger entries.
        """
        if not self.data_feed or self.is_playback:
            return

        session = get_ist_now().strftime("%Y-%m-%d")
        closed = [
            c for c in self.data_feed.closed_1min_candles()
            if (c.get("time_key") or "").startswith(session)
        ]
        if not closed:
            return

        with self._lock:
            for candle in closed:
                bar = {
                    "time": _candle_time(candle),
                    "open": candle["open"], "high": candle["high"],
                    "low": candle["low"], "close": candle["close"],
                }
                now = bar["time"]
                self._last_candle_key = candle.get("time_key")
                self._last_close = bar["close"]
                self._handle_day_rollover(now, bar["close"])

                should_run, _ = should_bot_run(now)
                if not should_run:
                    self.strategy.phase = PHASE_CLOSED
                    continue

                # Rebuild state only — do not place orders on past signals.
                self.strategy.on_candle(bar, in_trade=False)

        self.logger.info(
            f"Caught up strategy from {len(closed)} closed bars "
            f"(phase={self.strategy.phase})"
        )

    # --------------------------------------------------------------- main loop

    def _run_loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as exc:
                self.logger.error("Bot tick error", exc)

            if self.is_playback and self.data_feed.playback_speed >= 500:
                time.sleep(0.001)
            else:
                time.sleep(1)

    def _tick(self):
        with self._lock:
            if not self.data_feed:
                return

            # Small batches so /status and other callers can take the lock
            # during fast CSV replay (full sample is ~1M rows @ 500x).
            for candle in self.data_feed.drain_closed_candles(limit=40):
                self._on_closed_candle(candle)

            if not self.is_playback:
                self._on_live_tick()

    def _on_closed_candle(self, candle: Dict):
        bar = {
            "time": _candle_time(candle),
            "open": candle["open"], "high": candle["high"],
            "low": candle["low"], "close": candle["close"],
        }
        now = bar["time"]
        self._last_candle_key = candle.get("time_key")
        self._last_close = bar["close"]

        self._handle_day_rollover(now, bar["close"])

        should_run, _ = should_bot_run(now)
        if not should_run:
            if self._position is not None:
                self._flatten("session_end", bar["close"], now)
            self.strategy.phase = PHASE_CLOSED
            return

        if self._kill_switch_active(bar["close"], now):
            return

        if self._position is not None:
            self._evaluate_exit(bar["close"], now,
                                bar_high=bar["high"], bar_low=bar["low"])
            if self._position is not None:
                self.strategy.on_candle(bar, in_trade=True)
            return

        signal = self.strategy.on_candle(bar, in_trade=False)
        if signal is not None:
            self._enter(signal, now)

    def _on_live_tick(self):
        """Between candles, keep watching stops and the session boundary."""
        now = get_ist_now()
        price = self.data_feed.current_price
        if price <= 0:
            return

        self._handle_day_rollover(now, price)

        should_run, _ = should_bot_run(now)
        if not should_run:
            if self._position is not None:
                self._flatten("session_end", price, now)
            self.strategy.phase = PHASE_CLOSED
            return

        if self._kill_switch_active(price, now):
            return

        if self._position is not None:
            self._evaluate_exit(price, now)

    def _handle_day_rollover(self, now: datetime, last_price: float):
        session_date = now.strftime("%Y-%m-%d")
        if self._session_date == session_date:
            return

        if self._session_date is not None and self._last_close > 0:
            # Carry the previous close into the volatility estimate.
            self._daily_closes.append(self._last_close)
            if len(self._daily_closes) > 40:
                self._daily_closes.pop(0)
            self.logger.info(f"New session {session_date} — strategy state reset")

        self._session_date = session_date
        self._last_candle_key = None
        self._kill_switch_tripped = False
        self.strategy.reset_day(session_date)
        self._iv = (realised_volatility(self._daily_closes)
                    if len(self._daily_closes) >= 5
                    else float(get_setting("assumed_iv") or "0.14"))

    def _kill_switch_active(self, price: float, now: datetime) -> bool:
        max_loss = float(get_setting("max_daily_loss") or "10000")
        if max_loss <= 0:
            return False

        pnl = get_today_pnl(mode=self.mode,
                            date_override=now.strftime("%Y-%m-%d"))["total_pnl"]
        if pnl > -max_loss:
            return False

        if self._position is not None:
            self.logger.warning(f"Daily loss limit hit (Rs {pnl:,.0f}) — flattening now")
            self._flatten("kill_switch", price, now)

        if not self._kill_switch_tripped:
            self.logger.warning(f"Daily loss limit reached (Rs {pnl:,.0f} <= "
                                f"-Rs {max_loss:,.0f}); no further trades today")
            self._kill_switch_tripped = True

        self.strategy.phase = PHASE_DAILY_LOSS_LIMIT
        return True

    def _describe_signal(self) -> str:
        if self._kill_switch_tripped:
            return "KILL_SWITCH"
        if self._position is not None:
            return f"IN_TRADE_{'CE' if self._position.is_long else 'PE'}"
        return self.strategy.phase

    # ------------------------------------------------------------------ trades

    def _enter(self, signal, now: datetime):
        mode = self.mode
        index_price = signal.index_price
        self._expiry = next_weekly_expiry(now)
        self._strike = atm_strike(index_price)

        estimated_premium = self._theoretical_premium(index_price, signal.option_type, now)
        quantity = self._position_size(estimated_premium)
        if quantity <= 0:
            self.logger.warning("Position sizing returned zero quantity — skipping entry")
            return

        result = self.order_manager.place_order(
            option_type=signal.option_type,
            index_price=index_price,
            quantity=quantity,
            mode=mode,
            estimated_premium=estimated_premium,
            timestamp=now,
            strike=self._strike,
        )
        if not result:
            self.logger.warning("Entry aborted — order was not placed")
            return

        entry_premium = result["entry_price"]
        premium_stop = round(entry_premium * (1 - self.strategy.config.option_sl_pct / 100.0), 2)

        update_trade(result["trade_id"], {
            "direction": signal.direction,
            "orb_high": round(signal.orb_high, 2),
            "orb_low": round(signal.orb_low, 2),
            "orb_range": round(signal.orb_range, 2),
            "stop_index": round(signal.stop_index, 2),
            "target_index": round(signal.target_index, 2),
            "risk_points": round(signal.risk_points, 2),
            "stop_loss": premium_stop,
        })

        self._position = Position(
            direction=signal.direction,
            entry_index=index_price,
            stop_index=signal.stop_index,
            target_index=signal.target_index,
            risk_points=signal.risk_points,
            entry_option_price=entry_premium,
            entry_time=now,
        )
        self.strategy.register_entry(signal)

        insert_signal_log({
            "price": index_price, "orb_high": signal.orb_high,
            "orb_low": signal.orb_low, "orb_range": signal.orb_range,
            "phase": PHASE_IN_TRADE, "signal": f"BUY_{signal.option_type}",
        }, timestamp=now)

        self.logger.info(
            f"ORB ENTRY {signal.direction} {signal.option_type} {self._strike} "
            f"@ Rs {entry_premium} x{quantity} | index {index_price:.2f} "
            f"stop {signal.stop_index:.2f} target {signal.target_index:.2f} "
            f"risk {signal.risk_points:.1f}pts"
        )

        if mode == "live" and result.get("token") and self.data_feed:
            self.data_feed.subscribe_token(result["token"])

    def _evaluate_exit(self, index_price: float, now: datetime,
                       bar_high: float = None, bar_low: float = None):
        position = self._position
        if position is None:
            return

        option_price = self._current_option_price(index_price, now)
        signal = self.strategy.check_exit(
            position, index_price, now,
            option_price=option_price, bar_high=bar_high, bar_low=bar_low,
        )
        if signal is None:
            return

        # Re-price at the level the stop or target actually triggered on.
        exit_price = self._current_option_price(signal.index_price, now)
        self._close(signal.reason, exit_price, signal.index_price, now)

    def _flatten(self, reason: str, index_price: float, now: datetime):
        if self._position is None:
            return
        exit_price = self._current_option_price(index_price, now)
        self._close(reason, exit_price, index_price, now)

    def _close(self, reason: str, option_price: float, index_price: float, now: datetime):
        trade = get_active_trade(mode=self.mode)
        if trade is None:
            self._position = None
            return

        pnl = self.order_manager.exit_trade(
            trade_id=trade["id"], exit_price=option_price, reason=reason,
            mode=trade.get("mode", "paper"), timestamp=now,
            underlying_price=index_price,
        )

        self.capital += pnl
        self.capital_history.append(round(self.capital, 2))
        self.order_manager.update_context(capital=self.capital)

        if trade.get("mode") == "live" and trade.get("token") and self.data_feed:
            self.data_feed.unsubscribe_token(trade["token"])

        self._position = None
        self.strategy.register_exit()
        self.logger.info(f"ORB EXIT [{reason}] @ Rs {option_price} | "
                         f"index {index_price:.2f} | net P&L Rs {pnl:,.2f}")

    def manual_exit(self, price: Optional[float] = None) -> Dict:
        with self._lock:
            trade = get_active_trade(mode=self.mode)
            if not trade:
                return {"status": "error", "message": "No active trade"}

            now = self._now()
            index_price = self.data_feed.current_price if self.data_feed else 0
            option_price = price if price is not None else \
                self._current_option_price(index_price, now)
            if not option_price or option_price <= 0:
                return {"status": "error", "message": "No market price available"}

            self._close("manual", option_price, index_price, now)
            return {"status": "success", "message": f"Exited at Rs {option_price}"}

    # ------------------------------------------------------------ option maths

    def _theoretical_premium(self, index_price: float, option_type: str,
                             now: datetime) -> float:
        quote = black_scholes(index_price, self._strike or atm_strike(index_price),
                              time_to_expiry_years(now, self._expiry),
                              self._iv, option_type)
        return quote.price

    def _current_option_price(self, index_price: float, now: datetime) -> float:
        """Live LTP when available, otherwise a Black-Scholes mark."""
        position = self._position
        option_type = "CE" if (position and position.is_long) else "PE"

        if self.mode == "live" and not self.is_playback and self.data_feed:
            trade = get_active_trade(mode="live")
            if trade and trade.get("token"):
                ltp = self.data_feed.get_token_price(trade["token"])
                # Guard: if an old tick was cached in paise, rescale once.
                entry = float(trade.get("entry_price") or 0)
                if ltp > 0 and entry > 0 and ltp > max(entry * 20, 500):
                    ltp = ltp / 100.0
                if ltp <= 0 and self.order_manager:
                    # WS may not have the option token yet — use Angel REST LTP.
                    ltp = self.order_manager._fetch_ltp(
                        trade.get("trading_symbol") or "", trade.get("token"),
                    )
                if ltp > 0:
                    return ltp

        return self._theoretical_premium(index_price, option_type, now)

    def _refresh_broker_session(self) -> bool:
        """Re-login when Angel RMS/session goes stale. Rate-limited to 2 min."""
        now = time.time()
        if now - self._last_session_refresh_at < 120:
            return False
        self._last_session_refresh_at = now
        try:
            smart_api, feed_token = login_and_get_session()
            if not (smart_api and feed_token):
                self.logger.warning("Angel session refresh failed")
                return False
            if self.order_manager:
                self.order_manager.set_smart_api(smart_api)
            if self.data_feed:
                self.data_feed.update_credentials(
                    get_setting("api_key"), get_setting("client_id"),
                    feed_token, smart_api.access_token,
                )
            self._broker_status = "connected"
            self._broker_message = "Angel One session refreshed"
            self.logger.info("Angel One session refreshed after RMS failure")
            return True
        except Exception as exc:
            self.logger.warning(f"Angel session refresh error: {exc}")
            return False

    def _broker_available_cash(self) -> Optional[float]:
        """Angel available cash, cached briefly to avoid hammering rmsLimit."""
        if not (self._running and self.order_manager and self.order_manager.smart_api):
            return self._available_cash_cache
        now = time.time()
        if (self._available_cash_cache is not None
                and now - self._available_cash_cached_at < 15):
            return self._available_cash_cache
        try:
            margin = self.order_manager.check_margin(mode="live", log_check=False)
            if not margin.get("ok", True) or margin.get("mode") == "error":
                if self._refresh_broker_session():
                    margin = self.order_manager.check_margin(mode="live", log_check=False)
            if not margin.get("ok", True) or margin.get("mode") == "error":
                # Keep last good value instead of flashing ₹0 on API blips.
                return self._available_cash_cache
            available = float(margin.get("available") or 0)
            self._available_cash_cache = available
            self._available_cash_cached_at = now
            return available
        except Exception:
            return self._available_cash_cache

    # ------------------------------------------------------------------ sizing

    def _available_capital(self) -> float:
        if self.is_playback:
            return max(self.capital, 0)
        if self.mode == "paper":
            base = float(get_setting("paper_capital") or "500000")
            return base + get_all_time_pnl(mode="paper").get("all_time_pnl", 0)
        # Prefer a fresh RMS read; fall back to last good cash so a blip
        # does not size the next live order as zero.
        if self.order_manager:
            margin = self.order_manager.check_margin(mode="live", log_check=False)
            if margin.get("ok", True) and margin.get("mode") != "error":
                available = float(margin.get("available") or 0)
                self._available_cash_cache = available
                self._available_cash_cached_at = time.time()
                return available
            if self._refresh_broker_session():
                margin = self.order_manager.check_margin(mode="live", log_check=False)
                if margin.get("ok", True) and margin.get("mode") != "error":
                    available = float(margin.get("available") or 0)
                    self._available_cash_cache = available
                    self._available_cash_cached_at = time.time()
                    return available
        if self._available_cash_cache is not None:
            return self._available_cash_cache
        return 0

    def _position_size(self, premium: float) -> int:
        """
        Size on the option's real worst case: the premium stop.

        A long option's loss is bounded by the premium paid, and in practice by
        the premium stop, which is a far more reliable risk measure than the
        index stop multiplied by an assumed delta.
        """
        lot_size = int(get_setting("lot_size") or "75")
        min_lots = int(get_setting("min_lots") or "1")
        max_lots = int(get_setting("max_lots") or "10")
        capital = self._available_capital()

        if premium <= 0 or capital <= 0:
            return 0

        if (get_setting("position_sizing_mode") or "fixed_lots") == "fixed_lots":
            lots = int(get_setting("fixed_lots") or "1")
        else:
            risk_pct = float(get_setting("risk_percent_per_trade") or "2.0")
            stop_pct = max(self.strategy.config.option_sl_pct, 1.0) / 100.0
            risk_per_unit = premium * stop_pct
            lots = int((capital * risk_pct / 100.0) / max(risk_per_unit * lot_size, 1e-9))

        # Never commit more than a set share of capital to one trade's premium.
        cap_pct = float(get_setting("max_capital_per_trade_pct") or "15.0") / 100.0
        affordable = int((capital * cap_pct) / max(premium * lot_size, 1e-9))
        lots = min(lots, affordable, max_lots)
        lots = max(lots, 0 if affordable < min_lots else min_lots)

        return lots * lot_size

    # ------------------------------------------------------------- persistence

    def _restore_open_position(self):
        trade = get_active_trade(mode=self.mode)
        if not trade:
            return

        direction = trade.get("direction") or ("LONG" if trade["type"] == "CE" else "SHORT")
        self._position = Position(
            direction=direction,
            entry_index=trade.get("underlying_entry_price") or 0.0,
            stop_index=trade.get("stop_index") or 0.0,
            target_index=trade.get("target_index") or 0.0,
            risk_points=trade.get("risk_points") or 0.0,
            entry_option_price=trade["entry_price"],
            entry_time=self._now(),
        )
        self._strike = trade.get("strike_price") or 0
        self._expiry = next_weekly_expiry(self._now())
        self.strategy.phase = PHASE_IN_TRADE
        if self.strategy.trades_taken < 1:
            self.strategy.trades_taken = 1
            self.strategy.directions_taken.append(direction)
        self.logger.info(f"Recovered open trade #{trade['id']} "
                         f"({trade['type']} {trade['strike_price']}) — resuming management")

        if self.mode == "live" and trade.get("token") and self.data_feed:
            self.data_feed.subscribe_token(trade["token"])

    def adopt_broker_position(self) -> Dict:
        """
        Re-create a DB open trade from Angel's live NFO position.

        Used when Clear history wiped the row but the broker position remains.
        Rebuilds stop/target from today's OR if available.
        """
        if get_active_trade(mode=self.mode):
            return {"status": "ok", "message": "Active trade already in DB"}

        if self.mode != "live" or not self.order_manager or not self.order_manager.smart_api:
            return {"status": "error", "message": "Live Angel session required"}

        try:
            resp = self.order_manager.smart_api.position() or {}
        except Exception as exc:
            self.logger.error("Broker position fetch failed", exc)
            return {"status": "error", "message": f"position() failed: {exc}"}

        rows = resp.get("data") or []
        if not isinstance(rows, list):
            return {"status": "error", "message": "Unexpected position payload"}

        longs = []
        for row in rows:
            try:
                if str(row.get("exchange", "")).upper() not in ("NFO", "NFO"):
                    continue
                net = int(float(row.get("netqty") or row.get("netQty") or 0))
            except (TypeError, ValueError):
                continue
            if net <= 0:
                continue
            symbol = str(row.get("tradingsymbol") or row.get("tradingSymbol") or "")
            if not symbol.upper().startswith("NIFTY"):
                continue
            longs.append((net, row))

        if not longs:
            return {"status": "empty", "message": "No open NIFTY option long at Angel"}

        # One strategy slot — take the largest NIFTY long.
        net, row = max(longs, key=lambda item: item[0])
        symbol = str(row.get("tradingsymbol") or row.get("tradingSymbol") or "")
        token = str(row.get("symboltoken") or row.get("symbolToken") or "")
        avg = float(
            row.get("buyavgprice")
            or row.get("avgnetprice")
            or row.get("averageprice")
            or 0
        )
        strike = int(float(row.get("strikeprice") or row.get("strikePrice") or 0))
        if strike <= 0:
            # NIFTY25AUG2624050PE → strike before CE/PE
            digits = "".join(ch if ch.isdigit() else " " for ch in symbol)
            parts = [p for p in digits.split() if len(p) >= 4]
            strike = int(parts[-1]) if parts else 0

        option_type = "CE" if symbol.upper().endswith("CE") else "PE"
        direction = "LONG" if option_type == "CE" else "SHORT"
        lot_size = int(get_setting("lot_size") or "65")
        quantity = net

        snap = self.strategy.snapshot()
        orb_high = snap.get("orb_high")
        orb_low = snap.get("orb_low")
        orb_range = snap.get("orb_range")
        index_price = float(self.data_feed.current_price or 0) if self.data_feed else 0.0
        if index_price <= 0:
            index_price = float((orb_high or 0) + (orb_low or 0)) / 2.0 if orb_high and orb_low else 0.0

        cfg = self.strategy.config
        stop_index = target_index = risk_points = 0.0
        if orb_high and orb_low and index_price > 0:
            if direction == "SHORT":
                stop_index = float(orb_high)
                risk_points = abs(index_price - stop_index)
                target_index = index_price - cfg.target_r * risk_points
            else:
                stop_index = float(orb_low)
                risk_points = abs(index_price - stop_index)
                target_index = index_price + cfg.target_r * risk_points

        if avg <= 0:
            return {"status": "error", "message": f"No avg price on broker position {symbol}"}

        trade_id = insert_trade({
            "type": option_type,
            "direction": direction,
            "strike_price": strike,
            "trading_symbol": symbol,
            "token": token or None,
            "entry_price": round(avg, 2),
            "quantity": quantity,
            "lot_size": lot_size,
            "mode": "live",
            "orb_high": orb_high,
            "orb_low": orb_low,
            "orb_range": orb_range,
            "underlying_entry_price": round(index_price, 2) if index_price else None,
            "stop_index": round(stop_index, 2) if stop_index else None,
            "target_index": round(target_index, 2) if target_index else None,
            "risk_points": round(risk_points, 2) if risk_points else None,
            "capital_used": round(avg * quantity, 2),
            "estimated_entry_price": round(avg, 2),
            "entry_slippage": 0.0,
        })

        self._restore_open_position()
        self.logger.info(
            f"ADOPTED broker position as trade #{trade_id}: {symbol} "
            f"@ {avg} x{quantity} stop={stop_index:.2f} target={target_index:.2f}"
        )
        return {
            "status": "recovered",
            "trade_id": trade_id,
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": round(avg, 2),
            "stop_index": round(stop_index, 2) if stop_index else None,
            "target_index": round(target_index, 2) if target_index else None,
        }

    # --------------------------------------------------------------- reporting

    @property
    def strategy_state(self) -> Dict:
        # Snapshot under the tick lock: a half-applied entry or exit would
        # otherwise surface as a position and signal that disagree.
        with self._lock:
            state = self.strategy.snapshot()
            state["signal"] = self._describe_signal()
            position = self._position
            if position:
                state["position"] = {
                    "direction": position.direction,
                    "entry_index": round(position.entry_index, 2),
                    "stop_index": round(position.stop_index, 2),
                    "target_index": round(position.target_index, 2),
                    "risk_points": round(position.risk_points, 2),
                    "breakeven_done": position.breakeven_done,
                }
            return state

    def get_status(self) -> Dict:
        try:
            mode = self.mode
            now = self._now()
            date_override = now.strftime("%Y-%m-%d") if self.is_playback else None

            today = get_today_pnl(mode=mode, date_override=date_override)
            all_time = get_all_time_pnl(mode=mode)
            price_info = self.data_feed.get_price_info() if self.data_feed else {}
            should_run, market_reason = should_bot_run(now)

            strategy_state = self.strategy_state
            feed_connected = bool(self.data_feed and self.data_feed.is_connected)
            creds_ok = all(
                (get_setting(k) or "").strip()
                for k in ("api_key", "client_id", "pin", "totp_secret")
            )
            data_source = self._data_source if self._running else (
                get_setting("data_source") or "playback"
            )
            status = {
                "running": self._running,
                "mode": mode,
                "signal": strategy_state["signal"],
                "strategy": strategy_state,
                "price": price_info,
                "today_pnl": today["total_pnl"],
                "today_trades": today["total_trades"],
                "wins": today["wins"],
                "losses": today["losses"],
                "win_rate": today["win_rate"],
                "total_pnl": all_time["all_time_pnl"],
                "total_trades": all_time["all_time_trades"],
                "all_time_win_rate": all_time["all_time_win_rate"],
                "total_charges": all_time["all_time_charges"],
                "capital": round(self.capital, 2),
                "initial_capital": float(get_setting("initial_capital") or "500000"),
                "market_open": should_run,
                "market_status": market_reason,
                "is_trading_day": is_trading_day(now.date()),
                "is_playback": self.is_playback,
                "session_date": self._session_date,
                "data_source": data_source,
                "broker": {
                    "name": "Angel One",
                    "status": self._broker_status if self._running else "stopped",
                    "message": (
                        self._broker_message if self._running
                        else ("Credentials saved" if creds_ok
                              else "Credentials missing — add them in Settings")
                    ),
                    "connected": self._running and self._broker_status == "connected",
                    "feed_connected": feed_connected,
                    "credentials_configured": creds_ok,
                    "available_cash": self._broker_available_cash(),
                },
            }

            trade = get_active_trade(mode=mode)
            if trade:
                index_price = price_info.get("price") or 0
                if index_price > 0:
                    current = self._current_option_price(index_price, now)
                    trade["current_price"] = current
                    trade["live_pnl"] = round((current - trade["entry_price"])
                                              * trade["quantity"], 2)
                status["active_trade"] = trade

            return status
        except Exception as exc:
            self.logger.error(f"Error building status: {exc}")
            return {"running": self._running, "error": str(exc),
                    "mode": self.mode, "signal": "ERROR"}


def _candle_time(candle: Dict) -> datetime:
    key = candle.get("time_key")
    if key:
        return datetime.strptime(key, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    return datetime.fromtimestamp(candle["time"], IST)


def _parse_history_row(row) -> Optional[Dict]:
    try:
        raw = row[0]
        if "T" in raw:
            stamp = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=IST)
        else:
            stamp = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M").replace(tzinfo=IST)
        return {
            "time": int(stamp.timestamp()),
            "time_key": stamp.strftime("%Y-%m-%d %H:%M"),
            "time_str": stamp.strftime("%H:%M"),
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": int(row[5]) if len(row) > 5 else 0,
        }
    except (IndexError, TypeError, ValueError):
        return None


_bot: Optional[TradingBot] = None


def get_bot() -> TradingBot:
    global _bot
    if _bot is None:
        _bot = TradingBot()
    return _bot
