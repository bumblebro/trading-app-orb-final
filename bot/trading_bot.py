"""
Main Trading Bot Logic.
Orchestrates signal generation, trade management, and risk controls.
Strategy: ORB + Fibonacci Pullback + MACD Confirmation.
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
from indicators import (
    get_latest_indicators, calculate_orb
)
from order_manager import get_order_manager, OrderManager
from auth import login_and_get_session
from database import (
    get_active_trade, get_today_trade_count, get_consecutive_losses,
    get_today_pnl, get_setting, update_trade
)

IST = timezone(timedelta(hours=5, minutes=30))

# Strategy phases
PHASE_WATCHING = "WATCHING"
PHASE_BUILDING_ORB = "BUILDING_ORB"
PHASE_WAITING_BREAKOUT = "WAITING_BREAKOUT"
PHASE_ORDER_PLACED = "ORDER_PLACED"
PHASE_IN_TRADE = "IN_TRADE"
PHASE_SKIP_TODAY = "SKIP_TODAY"
PHASE_MAX_TRADES_DONE = "MAX_TRADES_DONE"
PHASE_CLOSED = "CLOSED"

PHASE_DESCRIPTIONS = {
    PHASE_WATCHING: "Pre-market — waiting for 9:15 AM",
    PHASE_BUILDING_ORB: "Building Opening Range (9:15-9:30)",
    PHASE_WAITING_BREAKOUT: "Watching for ORB Breakout",
    PHASE_ORDER_PLACED: "Order placed — entering trade",
    PHASE_IN_TRADE: "Trade active — monitoring position",
    PHASE_SKIP_TODAY: "Skipping today — ORB range invalid",
    PHASE_MAX_TRADES_DONE: "Max trades reached for today",
    PHASE_CLOSED: "Market session closed",
}


class TradingBot:
    """
    Automated trading bot for NIFTY 50 Options.
    Strategy: ORB (Opening Range Breakout) + Fibonacci Pullback + MACD Confirmation.
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

        # Strategy phase state
        self._strategy_phase = PHASE_WATCHING
        self._phase_description = PHASE_DESCRIPTIONS[PHASE_WATCHING]

        # ORB data
        self._orb_data = {"orb_high": None, "orb_low": None, "orb_range": None, "orb_status": "BUILDING"}

        # Breakout tracking
        self._breakout_direction: Optional[str] = None  # "LONG" or "SHORT"
        self._breakout_price: Optional[float] = None
        self._breakout_time: Optional[datetime] = None

        self._breakout_attempts = 0

        # Indicators Tracking
        self._indicators: Dict = {}

        # Reset tracking
        self._last_tick_date: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_signal(self) -> str:
        return self._current_signal

    @property
    def indicators(self) -> Dict:
        """Merge all indicator data for the UI."""
        return {
            **self._indicators,
            **self._orb_data,
            "phase": self._strategy_phase,
        }

    @property
    def strategy_phase_data(self) -> Dict:
        """Full strategy phase info for the /strategy-phase endpoint."""
        return {
            "phase": self._strategy_phase,
            "phase_description": self._phase_description,
            "breakout_direction": self._breakout_direction,
            "breakout_price": self._breakout_price,
            "breakout_time": self._breakout_time.isoformat() if self._breakout_time else None,
        }

    @property
    def orb_api_data(self) -> Dict:
        """ORB data for the /orb endpoint."""
        skip_reason = None
        is_valid = self._orb_data.get("orb_status") == "READY"
        if self._orb_data.get("orb_status") == "TOO_FLAT":
            skip_reason = "ORB range too small"
        elif self._orb_data.get("orb_status") == "TOO_WIDE":
            skip_reason = "ORB range too wide"
        return {
            "orb_high": self._orb_data.get("orb_high"),
            "orb_low": self._orb_data.get("orb_low"),
            "orb_range": self._orb_data.get("orb_range"),
            "is_valid": is_valid,
            "skip_reason": skip_reason,
        }


    def _get_current_time(self) -> datetime:
        """Get current time, respecting playback mode."""
        now = get_ist_now()
        if self.data_feed and self.data_feed.playback_file:
            playback_time = self.data_feed.last_tick_time
            if playback_time:
                now = playback_time
        return now

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
            feed_args["api_key"] = get_setting("api_key")
            feed_args["client_id"] = get_setting("client_id")

        self.data_feed = get_data_feed(**feed_args)

        smart_api = None
        if mode == "live" or (mode == "paper" and data_source != "playback"):
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

        # Reset strategy state for new session
        self._reset_strategy_state()

        # Startup Recovery: Check for open trades from today
        self._restore_state()

        # Start bot loop in background thread
        self._bot_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._bot_thread.start()

        active_trade = get_active_trade()
        if active_trade and mode == "live" and active_trade.get("token") and self.data_feed:
            self.data_feed.subscribe_token(active_trade["token"])

    def _restore_state(self):
        """Check database for active trades and restore bot state."""
        try:
            active_trade = get_active_trade()
            if active_trade:
                self.logger.info(f"Recovery: Found active trade {active_trade['id']} ({active_trade['type']})")
                
                # Restore phase
                self._strategy_phase = PHASE_IN_TRADE
                self._phase_description = PHASE_DESCRIPTIONS[PHASE_IN_TRADE]
                
                # Restore breakout info
                self._breakout_direction = "LONG" if "CE" in active_trade["type"] else "SHORT"
                self._breakout_price = active_trade.get("breakout_price")
                self._breakout_time = None # We don't have this in DB but it's okay for Phase 6
                
                # Restore ORB
                self._orb_data = {
                    "orb_high": active_trade.get("orb_high"),
                    "orb_low": active_trade.get("orb_low"),
                    "orb_range": (active_trade["orb_high"] - active_trade["orb_low"]) if active_trade.get("orb_high") and active_trade.get("orb_low") else 0,
                    "orb_status": "READY"
                }

                self.logger.info("Bot state restored. Resuming trade monitoring.")
            else:
                # No active trade, reset breakout attempts for today
                self._breakout_attempts = 0
        except Exception as e:
            self.logger.error(f"Error during state restoration: {e}")

    def stop(self):
        """Stop the trading bot."""
        if not self._running:
            return
        self._running = False
        self.logger.bot_status("STOPPED")
        if self.data_feed:
            self.data_feed.stop()

    def _reset_strategy_state(self):
        """Reset all strategy state for a new trading day."""
        # Strategy Phase & Status
        self._strategy_phase = PHASE_WATCHING
        self._phase_description = PHASE_DESCRIPTIONS[PHASE_WATCHING]
        self._current_signal = "WAIT"

        # Strategy Data
        self._orb_data = {"orb_high": None, "orb_low": None, "orb_range": None, "orb_status": "BUILDING"}
        self._breakout_direction = None # "LONG" or "SHORT"
        self._breakout_price = None
        self._breakout_time = None
        self._breakout_attempts = 0 # Track attempts per day (max 2)

        # Indicators tracking
        self._indicators = {}

    def _set_phase(self, phase: str):
        """Update strategy phase with logging."""
        if self._strategy_phase != phase:
            self._strategy_phase = phase
            self._phase_description = PHASE_DESCRIPTIONS.get(phase, phase)
            self.logger.info(f"Strategy phase → {phase}: {self._phase_description}")

    def _run_loop(self):
        """Main bot loop — runs every second."""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                self.logger.error("Bot tick error", e)
            
            # Synchronize sleep with playback speed in backtest mode
            if self.data_feed and self.data_feed.playback_file:
                speed = self.data_feed.playback_speed
                if speed >= 500:
                    pass # MAX speed, no sleep
                else:
                    time.sleep(1.0 / speed)
            else:
                time.sleep(1)

    def _tick(self):
        """Single bot tick — called every second."""
        now = self._get_current_time()

        # Simple New Day Reset
        current_date = now.strftime("%Y-%m-%d")
        if self._last_tick_date and self._last_tick_date != current_date:
            self.logger.info(f"New day detected ({current_date}). Resetting strategy state.")
            self._reset_strategy_state()
            self._breakout_attempts = 0
        self._last_tick_date = current_date

        # Market Calendar Guard
        should_run, reason = should_bot_run(now)
        if not should_run:
            self._set_phase(PHASE_CLOSED)
            self._current_signal = "MARKET_CLOSED"
            return

        current_price = self.data_feed.current_price if self.data_feed else 0
        if current_price <= 0:
            return

        current_time_str = now.strftime("%H:%M")

        # Update indicators continuously
        self._update_indicators()

        # 1. Square-off check
        if is_square_off_time(now):
            self._handle_square_off(current_price)
            return

        # 2. If there's an active trade, manage it
        active_trade = get_active_trade()
        if active_trade:
            self._set_phase(PHASE_IN_TRADE)
            self._manage_trade(active_trade, current_price)
            return

        # 3. Phase-based strategy logic
        if current_time_str < "09:15":
            self._set_phase(PHASE_WATCHING)
            self._current_signal = "WAIT"

        elif "09:15" <= current_time_str < "09:30":
            # PHASE 1: Building ORB
            self._set_phase(PHASE_BUILDING_ORB)
            self._build_orb(now)
            self._current_signal = "WAIT"

        elif current_time_str >= "09:30":
            # Finalize ORB if just transitioning
            if self._orb_data.get("orb_status") == "BUILDING":
                self._finalize_orb()

            # Check if we should skip today
            if self._strategy_phase == PHASE_SKIP_TODAY:
                self._current_signal = "WAIT"
                return

            # Check risk limits
            if not self._can_trade():
                self._set_phase(PHASE_MAX_TRADES_DONE)
                self._current_signal = "WAIT"
                return

            # Check signal cutoff
            cutoff = get_setting("signal_cutoff_time") or "14:30"
            if current_time_str >= cutoff:
                self._current_signal = "WAIT"
                return

            # Run the multi-phase strategy
            self._run_strategy(current_price, now)

    def _build_orb(self, now: datetime):
        """PHASE 1: Track ORB during 9:15-9:30."""
        candles = self.data_feed.get_all_candles(interval="1minute") if self.data_feed else []
        if not candles:
            candles = self.data_feed.get_all_candles() if self.data_feed else []

        orb_data = calculate_orb(candles)
        # During building, keep updating live
        if self._orb_data.get("orb_status") == "BUILDING":
            self._orb_data = orb_data
            self._orb_data["orb_status"] = "BUILDING"

    def _finalize_orb(self):
        """Finalize ORB at 9:30 and validate range."""
        candles = self.data_feed.get_all_candles(interval="1minute") if self.data_feed else []
        if not candles:
            candles = self.data_feed.get_all_candles() if self.data_feed else []

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
                self.logger.warning(f"ORB range too small ({orb_range} pts), skipping today")
                self._set_phase(PHASE_SKIP_TODAY)
            elif orb_range > max_range:
                self._orb_data["orb_status"] = "TOO_WIDE"
                self.logger.warning(f"ORB range too wide ({orb_range} pts), skipping today")
                self._set_phase(PHASE_SKIP_TODAY)
            else:
                self._orb_data["orb_status"] = "READY"
                self.logger.info("ORB status: READY for trading")
                self._set_phase(PHASE_WAITING_BREAKOUT)
        else:
            self.logger.error("ORB calculation failed: Insufficient data between 9:15-9:30")
            self._set_phase(PHASE_SKIP_TODAY)

    def _run_strategy(self, current_price: float, now: datetime):
        """Run the multi-phase ORB strategy."""

        orb_high = self._orb_data.get("orb_high")
        orb_low = self._orb_data.get("orb_low")

        if not orb_high or not orb_low:
            return

        buffer = float(get_setting("breakout_buffer") or "5")

        # ----------------------------------------
        # PHASE 2: Detect Breakout
        # ----------------------------------------
        if self._strategy_phase == PHASE_WAITING_BREAKOUT:
            # Risk Guard: Max 2 attempts per day
            if self._breakout_attempts >= 2:
                self._current_signal = "WAIT (Max Trades reached)"
                return

            # RE-ENTRY RULE: If we already took one trade, 
            # we only allow a second one if price comes back INSIDE the ORB first
            # (To avoid flicker re-entries)
            if self._breakout_attempts == 1:
                # If price is still above high or below low, we wait
                if current_price > orb_high or current_price < orb_low:
                    self._current_signal = "WAIT (Price must return to ORB)"
                    return

            if current_price > orb_high + buffer:
                self._breakout_direction = "LONG"
                self._breakout_price = current_price
                self._breakout_time = now
                self._breakout_attempts += 1
                self._set_phase(PHASE_ORDER_PLACED)
                self.logger.info(f"BREAKOUT UP at {current_price} (ORB High {orb_high} + buffer {buffer}) - Attempt {self._breakout_attempts}")
                
                signal = "BUY_CE"
                self._current_signal = signal
                self._execute_trade(signal, current_price, now)
                return

            elif current_price < orb_low - buffer:
                self._breakout_direction = "SHORT"
                self._breakout_price = current_price
                self._breakout_time = now
                self._breakout_attempts += 1
                self._set_phase(PHASE_ORDER_PLACED)
                self.logger.info(f"BREAKOUT DOWN at {current_price} (ORB Low {orb_low} - buffer {buffer}) - Attempt {self._breakout_attempts}")
                
                signal = "BUY_PE"
                self._current_signal = signal
                self._execute_trade(signal, current_price, now)
                return

            self._current_signal = "WAIT"
            return

        # Fallback
        self._current_signal = "WAIT"

    def _update_indicators(self):
        """Calculate Opening Range indicators only."""
        feed = self.data_feed
        if feed:
            candles = feed.get_all_candles()
            self._indicators = get_latest_indicators(candles)

    def _execute_trade(self, signal: str, current_price: float, now: datetime):
        """Execute a trade with targets and SL."""
        mode = get_setting("trading_mode") or "paper"

        # 1. ORB Range Guard (Secondary Safety)
        orb_range = self._orb_data.get("orb_range", 0)
        max_range = float(get_setting("max_orb_range") or "150")
        
        if orb_range > max_range:
            self.logger.warning(f"ORB range too wide ({orb_range} pts), skipping trade")
            self._set_phase(PHASE_SKIP_TODAY)
            return

        # 2. Position Sizing
        lot_size = int(get_setting("lot_size") or "65")
        
        position_size_mode = get_setting("position_size_mode") or "fixed"
        
        if position_size_mode == "fixed":
            fixed_lots = int(get_setting("fixed_lots") or "2")
            quantity = fixed_lots * lot_size
        else:
            # Calculate Quantity based on Max Capital Risk %
            max_risk_pct = float(get_setting("max_capital_risk_pct") or "1.0")
            capital = float(get_setting("paper_capital") or "100000")

            total_risk_allowance = capital * (max_risk_pct / 100)

            # Estimated entry premium
            est_entry = round(current_price * 0.015, 2)
            # Default fallback SL for qty calculation only 
            sl_pct_est = 40.0 

            # Risk per unit
            risk_per_unit = est_entry * (sl_pct_est / 100)

            # Calculated quantity (rounded down to nearest lot size)
            if risk_per_unit > 0:
                raw_qty = total_risk_allowance / risk_per_unit
                quantity = (int(raw_qty) // lot_size) * lot_size
                quantity = max(lot_size, quantity)
            else:
                quantity = lot_size

        # 3. Place order
        result = self.order_manager.place_order(signal, current_price, mode, timestamp=now, quantity=quantity)

        if result:
            # IMMEDIATELY update phase to prevent LOOP if DB update fails later
            self._set_phase(PHASE_IN_TRADE)
            
            trade_id = result["trade_id"]
            entry_price = result["entry_price"]

            # 4. Dynamic Range-Based Target and SL
            delta = float(get_setting("atm_delta") or "0.5")
            
            # SL = Entry - (Range * Delta * 0.8)
            # Target = Entry + (Range * Delta * 1.5)
            final_target = round(entry_price + (orb_range * delta * 1.5), 2)
            final_sl = round(entry_price - (orb_range * delta * 0.8), 2)

            update_trade(trade_id, {
                "target": final_target,
                "stop_loss": final_sl,
                "trailing_sl": final_sl,
                "quantity": quantity,
                "orb_high": self._orb_data["orb_high"],
                "orb_low": self._orb_data["orb_low"],
                "orb_range": self._orb_data["orb_range"],
                "breakout_price": self._breakout_price,
                "trailing_sl_used": 1 if get_setting("trailing_sl_enabled") == "true" else 0,
            })

            self.logger.info(
                f"Natural ORB Entry: {signal} at {entry_price}. "
                f"Qty: {quantity}, Target: {final_target}, SL: {final_sl}. "
                f"Breakout: {self._breakout_price}"
            )

    def _manage_trade(self, trade: Dict, current_price: float):
        """PHASE 6: Manage active trade with Trailing SL."""
        simulated_price = self.calculate_option_price(trade, current_price)
        trade_type = trade.get("type", "CE")

        # 1. Trailing Stop Loss Logic
        trailing_enabled = get_setting("trailing_sl_enabled") == "true"
        trailing_pct = float(get_setting("trailing_sl_pct") or "15.0")
        current_sl = trade.get("trailing_sl") or trade.get("stop_loss")

        if trailing_enabled:
            potential_sl = round(simulated_price * (1 - trailing_pct / 100), 2)
            if potential_sl > current_sl:
                current_sl = potential_sl
                from database import update_trade
                update_trade(trade["id"], {
                    "trailing_sl": current_sl,
                    "trailing_sl_final": current_sl,
                })
                self.logger.info(f"Trailing SL updated to {current_sl} (Price: {simulated_price})")

        # 2. Exit checks

        # 2a. Stop loss hit
        if simulated_price <= current_sl:
            self.logger.info(f"Stop loss hit: {simulated_price} <= {current_sl}")
            self._close_active_trade(trade, simulated_price, "stoploss")
            return

        # 2b. Target hit
        if simulated_price >= trade["target"]:
            self.logger.info(f"Target hit: {simulated_price} >= {trade['target']}")
            self._close_active_trade(trade, simulated_price, "target")
            return

        # 2c. Time checks — no new logic needed here, just track state
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
            if live_ltp > 0:
                return live_ltp

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
        now = self._get_current_time()
        self.order_manager.exit_trade(trade["id"], exit_price, reason, trade.get("mode", "paper"), timestamp=now)
        if trade.get("mode") == "live" and trade.get("token") and self.data_feed:
            self.data_feed.unsubscribe_token(trade["token"])
        self._current_signal = "WAIT"

        # Reset to look for next breakout (if still within trading hours)
        self._breakout_direction = None
        self._breakout_price = None
        self._breakout_time = None
        self._set_phase(PHASE_WAITING_BREAKOUT)

    def _handle_square_off(self, current_price: float):
        """Auto square-off at 3:15 PM."""
        active_trade = get_active_trade()
        if active_trade:
            sim_exit = self.calculate_option_price(active_trade, current_price)
            self._close_active_trade(active_trade, sim_exit, "squareoff")
            self.logger.info("Auto square-off executed at 3:15 PM IST")
        self._set_phase(PHASE_CLOSED)
        self._current_signal = "SQUARED_OFF"

    def _can_trade(self) -> bool:
        """PHASE 7: Risk management rules."""
        max_trades = int(get_setting("max_trades_per_day") or "3")
        today_count = get_today_trade_count()
        if today_count >= max_trades:
            return False

        consecutive_losses = get_consecutive_losses()
        if consecutive_losses >= 2:
            return False

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
            "all_time_win_rate": all_time_summary.get("all_time_win_rate", 0),
            "mode": mode,
            "phase": self._strategy_phase,
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
        if not active_trade:
            return {"success": False, "message": "No active trade"}
        if current_price is None:
            current_price = self.data_feed.current_price if self.data_feed else 0
        pnl = self.order_manager.exit_trade(active_trade["id"], current_price, "manual", active_trade["mode"])
        return {"success": True, "pnl": pnl, "message": "Manual exit completed"}


_bot = None
def get_bot() -> TradingBot:
    global _bot
    if _bot is None:
        _bot = TradingBot()
    return _bot
