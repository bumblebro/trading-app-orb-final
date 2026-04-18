"""
Main Trading Bot Logic.
Orchestrates signal generation, trade management, and risk controls.
Now using ORB + Supertrend + RSI strategy.
"""

import threading
import time
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

from logger import get_logger
from market_calendar import (
    should_bot_run, is_signal_window, is_square_off_time,
    is_trading_day, get_ist_now
)
from data_feed import get_data_feed, DataFeed
from indicators import get_latest_indicators, calculate_orb
from order_manager import get_order_manager, OrderManager
from auth import login_and_get_session
from database import (
    get_active_trade, get_today_trade_count, get_consecutive_losses,
    get_today_pnl, get_setting
)

IST = timezone(timedelta(hours=5, minutes=30))


class TradingBot:
    """
    Automated trading bot for NIFTY 50 Options.
    Strategy: ORB (Opening Range Breakout) + Supertrend + RSI.
    """

    def __init__(self):
        self.logger = get_logger()
        self.data_feed: Optional[DataFeed] = None
        self.order_manager: Optional[OrderManager] = None

        # Bot state
        self._running = False
        self._bot_thread: Optional[threading.Thread] = None
        self._current_signal = "WAIT"
        self._last_signal_time: Optional[datetime] = None
        self._phase = "WATCHING" # WATCHING, ORB_BUILDING, TRADING, CLOSED
        
        # Strategy data
        self._orb_data = {"orb_high": None, "orb_low": None, "orb_range": None, "orb_status": "BUILDING"}
        self._indicators: Dict = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_signal(self) -> str:
        return self._current_signal

    @property
    def indicators(self) -> Dict:
        # Merge ORB data for the UI
        return {**self._indicators, **self._orb_data, "phase": self._phase}

    def start(self):
        """Start the trading bot."""
        if self._running:
            self.logger.warning("Bot is already running")
            return

        self._running = True
        self.logger.bot_status("STARTED")

        # Initialize components
        mode = get_setting("trading_mode") or "paper"
        data_source = get_setting("data_source") or "auto"
        playback_file = get_setting("playback_file") or "bot/data/nifty_sample.csv"
        playback_speed = float(get_setting("playback_speed") or "1.0")
        
        if data_source == "playback" and playback_file and not os.path.isabs(playback_file):
            clean_path = playback_file[4:] if playback_file.startswith("bot/") else playback_file
            bot_dir = os.path.dirname(os.path.abspath(__file__))
            playback_file = os.path.join(bot_dir, clean_path)
        
        feed_args = {}
        if data_source == "playback":
            feed_args["playback_file"] = playback_file
            feed_args["playback_speed"] = playback_speed
        else:
            # For non-playback (Live/Paper), we need API credentials for real prices
            feed_args["api_key"] = get_setting("api_key")
            feed_args["client_id"] = get_setting("client_id")
            
        self.data_feed = get_data_feed(**feed_args)
        
        smart_api = None
        if mode == "live" or (mode == "paper" and data_source != "playback"):
            # We need to login if we aren't in playback mode
            smart_api, feed_token = login_and_get_session()
            if smart_api and feed_token:
                self.data_feed.update_credentials(
                    get_setting("api_key"),
                    get_setting("client_id"),
                    feed_token
                )
            else:
                self.logger.error("Failed to initialize Angel One session. Price feed may not start.")

        self.data_feed.start()
        self.order_manager = get_order_manager()
        if smart_api:
            self.order_manager.set_smart_api(smart_api)

        # Start bot loop in background thread
        self._bot_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._bot_thread.start()
        
        active_trade = get_active_trade()
        if active_trade and mode == "live" and active_trade.get("token") and self.data_feed:
            self.data_feed.subscribe_token(active_trade["token"])

    def stop(self):
        """Stop the trading bot."""
        if not self._running:
            return
        self._running = False
        self.logger.bot_status("STOPPED")
        if self.data_feed:
            self.data_feed.stop()

    def _run_loop(self):
        """Main bot loop — runs every second."""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                self.logger.error("Bot tick error", e)
            time.sleep(1)

    def _tick(self):
        """Single bot tick — called every second."""
        now = get_ist_now()
        if self.data_feed and self.data_feed.playback_file:
            playback_time = self.data_feed.last_tick_time
            if playback_time:
                now = playback_time

        # Market Calendar Guard
        should_run, reason = should_bot_run(now)
        if not should_run:
            self._phase = "CLOSED"
            self._current_signal = "MARKET_CLOSED"
            return

        current_price = self.data_feed.current_price if self.data_feed else 0
        if current_price <= 0:
            return

        # 1. Update Phase and Indicators
        self._update_strategy_state(now)
        
        # 2. Square-off check
        if is_square_off_time(now):
            self._handle_square_off(current_price)
            return

        # 3. Manage Active Trade
        active_trade = get_active_trade()
        if active_trade:
            self._manage_trade(active_trade, current_price)
            return

        # 4. Signal Generation (Only in TRADING phase)
        if self._phase == "TRADING":
            if not self._can_trade():
                self._current_signal = "WAIT"
                return

            signal = self._generate_signal(current_price)
            self._current_signal = signal

            if signal in ("BUY_CE", "BUY_PE"):
                self._execute_trade(signal, current_price, now)
        else:
            # If we are in ORB_BUILDING or WATCHING, we don't look for breakouts
            if self._phase == "ORB_BUILDING":
                self._current_signal = "WAIT"
            elif self._phase == "CLOSED":
                self._current_signal = "SQUARED_OFF"

    def _update_strategy_state(self, now: datetime):
        """Update bot phase, ORB building, and indicators."""
        current_time_str = now.strftime("%H:%M")
        
        # Determine Phase
        if current_time_str < "09:15":
            self._phase = "WATCHING"
        elif "09:15" <= current_time_str < "09:30":
            if self._phase != "ORB_BUILDING":
                self.logger.info("ORB building started")
                self._phase = "ORB_BUILDING"
        elif "09:30" <= current_time_str < "14:30":
            if self._phase == "ORB_BUILDING":
                self._calculate_orb_range()
            self._phase = "TRADING"
        else:
            self._phase = "CLOSED"

        # Update Indicators (using 5-min candles for trend, but 1-min for ORB)
        candles = self.data_feed.get_all_candles() if self.data_feed else []
        if candles:
            settings = {
                "supertrend_period": get_setting("supertrend_period"),
                "supertrend_multiplier": get_setting("supertrend_multiplier"),
                "rsi_period": get_setting("rsi_period")
            }
            self._indicators = get_latest_indicators(candles, settings)

    def _calculate_orb_range(self):
        """Calculate ORB at exactly 9:30 AM."""
        # We need historical 1-minute candles for or precise ORB
        # The data_feed usually provides 5-min candles for the dashboard
        # but the underlying feed might have 1-min raw data if we use playback.
        # In this implementation, we fetch the 1-min candles from the feed
        candles = self.data_feed.get_all_candles(interval="1minute") if self.data_feed else []
        # If the feed doesn't support interval, fallback to whatever candles are there (maybe already 1-min)
        if not candles:
             candles = self.data_feed.get_all_candles()

        orb_data = calculate_orb(candles)
        self._orb_data = orb_data
        
        orb_high = orb_data["orb_high"]
        orb_low = orb_data["orb_low"]
        orb_range = orb_data["orb_range"]

        if orb_high and orb_low:
            self.logger.info(f"ORB calculated: High={orb_high} Low={orb_low} Range={orb_range}")
            
            min_range = float(get_setting("min_orb_range") or "30")
            max_range = float(get_setting("max_orb_range") or "300")
            
            if orb_range < min_range:
                self._orb_data["orb_status"] = "TOO_FLAT"
                self.logger.warning(f"ORB status: TOO_FLAT (range={orb_range}), skipping today")
            elif orb_range > max_range:
                self._orb_data["orb_status"] = "TOO_WIDE"
                self.logger.warning(f"ORB status: TOO_WIDE (range={orb_range}), skipping today")
            else:
                self._orb_data["orb_status"] = "READY"
                self.logger.info("ORB status: READY for trading")
        else:
            self.logger.error("ORB calculation failed: Insufficient data between 9:15-9:30")

    def _generate_signal(self, current_price: float) -> str:
        """ORB Breakout logic."""
        if self._orb_data.get("orb_status") != "READY":
            return "WAIT"

        orb_high = self._orb_data["orb_high"]
        orb_low = self._orb_data["orb_low"]
        st_direction = self._indicators.get("supertrend_direction")
        rsi = self._indicators.get("rsi")
        
        rsi_buy = float(get_setting("rsi_buy_level") or "55")
        rsi_sell = float(get_setting("rsi_sell_level") or "45")

        # BULLISH BREAKOUT
        if (current_price > orb_high and 
            st_direction == "UP" and 
            rsi and rsi > rsi_buy):
            return "BUY_CE"

        # BEARISH BREAKOUT
        if (current_price < orb_low and 
            st_direction == "DOWN" and 
            rsi and rsi < rsi_sell):
            return "BUY_PE"

        return "WAIT"

    def _execute_trade(self, signal: str, current_price: float, now: datetime):
        """Execute a trade with support for Option % based targets/SL and dynamic lot sizing."""
        mode = get_setting("trading_mode") or "paper"
        orb_range = self._orb_data["orb_range"]
        
        # 1. Calculate Quantity based on Max Capital Risk %
        lot_size = int(get_setting("lot_size") or "65")
        max_risk_pct = float(get_setting("max_capital_risk_pct") or "1.0")
        capital = float(get_setting("paper_capital") or "100000")
        
        # Risk amount for the entire trade
        total_risk_allowance = capital * (max_risk_pct / 100)
        
        # Estimated entry premium
        est_entry = round(current_price * 0.015, 2)
        sl_pct = float(get_setting("option_sl_pct") or "25.0")
        
        # Risk per unit
        risk_per_unit = est_entry * (sl_pct / 100)
        
        # Calculated quantity (rounded down to nearest lot size)
        if risk_per_unit > 0:
            raw_qty = total_risk_allowance / risk_per_unit
            quantity = (int(raw_qty) // lot_size) * lot_size
            quantity = max(lot_size, quantity) # At least 1 lot
        else:
            quantity = lot_size

        # 2. Place order
        result = self.order_manager.place_order(signal, current_price, mode, timestamp=now)
        
        if result:
            trade_id = result["trade_id"]
            entry_price = result["entry_price"]
            
            # 3. Calculate Target and SL based on % preferences
            target_pct = float(get_setting("option_target_pct") or "50.0")
            
            # Primary: Option % calculation
            final_target = round(entry_price * (1 + target_pct / 100), 2)
            final_sl = round(entry_price * (1 - sl_pct / 100), 2)
            
            from database import update_trade
            update_trade(trade_id, {
                "target": final_target,
                "stop_loss": final_sl,
                "trailing_sl": final_sl, # Initialize trailing SL at the entry SL
                "quantity": quantity, # Update with dynamic quantity
                "orb_high": self._orb_data["orb_high"],
                "orb_low": self._orb_data["orb_low"],
                "orb_range": self._orb_data["orb_range"],
                "supertrend_at_entry": self._indicators.get("supertrend_direction"),
                "rsi_at_entry": self._indicators.get("rsi")
            })
            
            self.logger.info(f"ORB Trade Entry: {signal} at {entry_price}. Qty: {quantity}, Target: {final_target}, SL: {final_sl}")

    def _manage_trade(self, trade: Dict, current_price: float):
        """Manage trade with Trailing SL and Supertrend Flip rules."""
        simulated_price = self.calculate_option_price(trade, current_price)
        st_direction = self._indicators.get("supertrend_direction")
        trade_type = trade.get("type", "CE")
        
        # 1. Trailing Stop Loss Logic
        trailing_enabled = get_setting("trailing_sl_enabled") == "true"
        trailing_pct = float(get_setting("trailing_sl_pct") or "15.0")
        current_sl = trade.get("trailing_sl") or trade.get("stop_loss")
        
        if trailing_enabled:
            # Calculate potential new SL based on current price
            potential_sl = round(simulated_price * (1 - trailing_pct / 100), 2)
            if potential_sl > current_sl:
                current_sl = potential_sl
                from database import update_trade
                update_trade(trade["id"], {"trailing_sl": current_sl})
                self.logger.info(f"Trailing SL updated to {current_sl} (Price: {simulated_price})")

        # 2. Dual Exit Logic
        
        # 2a. Underlying Index Price Checks (R-Multiples)
        underlying_entry = trade.get("underlying_entry_price")
        orb_range = trade.get("orb_range")
        if underlying_entry and orb_range:
            target_multi = float(get_setting("target_multiplier") or "2.0")
            sl_multi = float(get_setting("sl_multiplier") or "1.0")
            
            if trade_type == "CE":
                index_target = underlying_entry + (orb_range * target_multi)
                index_sl = underlying_entry - (orb_range * sl_multi)
                if current_price >= index_target:
                    self.logger.info(f"Index Target Hit (+{target_multi}R): {current_price} >= {index_target}")
                    self._close_active_trade(trade, simulated_price, "target")
                    return
                if current_price <= index_sl:
                    self.logger.info(f"Index SL Hit (-{sl_multi}R): {current_price} <= {index_sl}")
                    self._close_active_trade(trade, simulated_price, "stoploss")
                    return
            else: # PE
                index_target = underlying_entry - (orb_range * target_multi)
                index_sl = underlying_entry + (orb_range * sl_multi)
                if current_price <= index_target:
                    self.logger.info(f"Index Target Hit (+{target_multi}R): {current_price} <= {index_target}")
                    self._close_active_trade(trade, simulated_price, "target")
                    return
                if current_price >= index_sl:
                    self.logger.info(f"Index SL Hit (-{sl_multi}R): {current_price} >= {index_sl}")
                    self._close_active_trade(trade, simulated_price, "stoploss")
                    return

        # 2b. Option Premium Price Checks (Percentages)
        if simulated_price >= trade["target"]:
            self.logger.info(f"Option Premium Target Hit: {simulated_price} >= {trade['target']}")
            self._close_active_trade(trade, simulated_price, "target")
            return
        if simulated_price <= current_sl:
            self.logger.info(f"Option Premium SL Hit: {simulated_price} <= {current_sl}")
            self._close_active_trade(trade, simulated_price, "stoploss")
            return
        # 3. Supertrend Flip Check
        if (trade_type == "CE" and st_direction == "DOWN") or \
           (trade_type == "PE" and st_direction == "UP"):
            self.logger.info(f"Supertrend flipped to {st_direction} → Early exit triggered")
            self._close_active_trade(trade, simulated_price, "manual") # Using manual as reason for flip
            return

        self._current_signal = f"ACTIVE_{trade_type}"

    def calculate_option_price(self, trade: Dict, current_index_price: float) -> float:
        """Calculate simulated option price based on Delta 0.5."""
        mode = trade.get("mode", "paper")
        is_playback = self.data_feed and self.data_feed.playback_file
        
        entry_option_price = trade.get("entry_price", 0)
        entry_index_price = trade.get("underlying_entry_price")
        trade_type = trade.get("type", "CE")
        token = trade.get("token")

        if mode == "live" and not is_playback and token and self.data_feed:
            live_ltp = self.data_feed.get_token_price(token)
            if live_ltp > 0: return live_ltp

        if (mode == "paper" or is_playback) and entry_index_price and entry_option_price:
            index_diff = current_index_price - entry_index_price
            if trade_type == "CE":
                option_ltp = entry_option_price + (index_diff * 0.5)
            else:
                option_ltp = entry_option_price - (index_diff * 0.5)
            return max(0.05, round(option_ltp, 2))

        return current_index_price

    def _close_active_trade(self, trade: Dict, exit_price: float, reason: str):
        """Exit trade and update state."""
        now = get_ist_now()
        if self.data_feed and self.data_feed.playback_file:
            now = self.data_feed.last_tick_time
            
        self.order_manager.exit_trade(trade["id"], exit_price, reason, trade.get("mode", "paper"), timestamp=now)
        if trade.get("mode") == "live" and trade.get("token") and self.data_feed:
            self.data_feed.unsubscribe_token(trade["token"])
        self._current_signal = "WAIT"

    def _handle_square_off(self, current_price: float):
        """Auto square-off at 3:15 PM."""
        active_trade = get_active_trade()
        if active_trade:
            sim_exit = self.calculate_option_price(active_trade, current_price)
            self._close_active_trade(active_trade, sim_exit, "squareoff")
            self.logger.info("Auto square-off executed at 3:15 PM IST")
        self._phase = "CLOSED"
        self._current_signal = "SQUARED_OFF"

    def _can_trade(self) -> bool:
        """Risk management rules."""
        max_trades = int(get_setting("max_trades_per_day") or "3")
        today_count = get_today_trade_count()
        if today_count >= max_trades: return False
        
        consecutive_losses = get_consecutive_losses()
        if consecutive_losses >= 2: return False
        
        return True

    def get_status(self) -> Dict:
        from database import get_today_pnl, get_active_trade, get_all_time_pnl
        pnl_summary = get_today_pnl()
        mode = get_setting("trading_mode") or "paper"
        all_time_summary = get_all_time_pnl(mode=mode)
        active_trade = get_active_trade()
        price_info = self.data_feed.get_price_info() if self.data_feed else {}
        
        status = {
            "running": self._running,
            "signal": self._current_signal,
            "indicators": self.indicators,
            "price": price_info,
            "today_pnl": pnl_summary.get("total_pnl", 0),
            "today_trades": pnl_summary.get("total_trades", 0),
            "wins": pnl_summary.get("wins", 0),
            "losses": pnl_summary.get("losses", 0),
            "win_rate": pnl_summary.get("win_rate", 0),
            "total_pnl": all_time_summary.get("all_time_pnl", 0),
            "total_trades": all_time_summary.get("all_time_trades", 0),
            "mode": mode,
            "phase": self._phase,
            "orb_status": self._orb_data["orb_status"]
        }
        
        if active_trade and price_info.get("price"):
            simulated_price = self.calculate_option_price(active_trade, price_info["price"])
            active_trade["current_price"] = simulated_price
            active_trade["live_pnl"] = round((simulated_price - active_trade["entry_price"]) * active_trade["quantity"], 2)
            status["active_trade"] = active_trade

        return status

    def manual_exit(self, current_price: float = None) -> Dict:
        active_trade = get_active_trade()
        if not active_trade: return {"success": False, "message": "No active trade"}
        if current_price is None: current_price = self.data_feed.current_price if self.data_feed else 0
        pnl = self.order_manager.exit_trade(active_trade["id"], current_price, "manual", active_trade["mode"])
        return {"success": True, "pnl": pnl, "message": "Manual exit completed"}


_bot = None
def get_bot() -> TradingBot:
    global _bot
    if _bot is None: _bot = TradingBot()
    return _bot
