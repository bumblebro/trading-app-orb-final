"""
Main Trading Bot Logic.
Orchestrates signal generation, trade management, and risk controls.
Strategy: Supertrend + EMA Crossover + ADX Filter.
"""


import threading
import time
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

from logger import get_logger
from market_calendar import (
    should_bot_run, is_signal_window, is_square_off_time,
    is_trading_day, get_ist_now
)
from data_feed import get_data_feed, DataFeed
from indicators import (
    get_latest_indicators
)
from order_manager import get_order_manager, OrderManager
from auth import login_and_get_session
from database import (
    get_active_trade, get_today_trade_count, get_consecutive_losses,
    get_today_pnl, get_all_time_pnl, get_setting, update_trade, insert_signal_log
)

IST = timezone(timedelta(hours=5, minutes=30))

# Strategy phases
PHASE_WATCHING = "WATCHING"
PHASE_WAITING_FOR_ALIGNMENT = "WAITING_FOR_ALIGNMENT"
PHASE_IN_TRADE = "IN_TRADE"
PHASE_MAX_TRADES_DONE = "MAX_TRADES_DONE"
PHASE_DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
PHASE_CLOSED = "CLOSED"

PHASE_DESCRIPTIONS = {
    PHASE_WATCHING: "Pre-market — waiting for 9:15 AM",
    PHASE_WAITING_FOR_ALIGNMENT: "Waiting for Supertrend & EMA Alignment",
    PHASE_IN_TRADE: "Trade active — monitoring position",
    PHASE_MAX_TRADES_DONE: "Max trades reached for today",
    PHASE_DAILY_LOSS_LIMIT: "Daily loss limit reached",
    PHASE_CLOSED: "Market session closed",
}


class TradingBot:
    """
    Automated trading bot for NIFTY 50 Options.
    Strategy: Supertrend + EMA Crossover + ADX Filter.
    """

    def __init__(self):
        self.logger = get_logger()
        self.data_feed: Optional[DataFeed] = None
        self.order_manager: Optional[OrderManager] = None
        
        # Cooldown state
        self._last_exit_time = None
        self._last_exit_reason = None

        # Bot state
        self._running = False
        self._bot_thread: Optional[threading.Thread] = None
        self._current_signal = "WAIT"
        self._last_signal_time: Optional[datetime] = None

        # Strategy phase state
        self._strategy_phase = PHASE_WATCHING
        self._phase_description = PHASE_DESCRIPTIONS[PHASE_WATCHING]

        # Indicators Tracking
        self._indicators: Dict = {}
        self._prev_indicators: Dict = {}

        # Trade Tracking
        self._last_5min_timestamp: Optional[str] = None

        # Reset tracking
        self._last_tick_date: Optional[str] = None

        # Auto-Compounding
        self.todays_lots = 0
        self.capital = 100000.0
        self.capital_history = []
        self.compounding_baseline_capital = 100000.0
        self._effective_backtest_start: Optional[str] = None
        self._first_ever_trade_date: Optional[str] = None

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
            "phase": self._strategy_phase,
        }

    @property
    def strategy_phase_data(self) -> Dict:
        """Full strategy phase info for the /strategy-phase endpoint."""
        return {
            "phase": self._strategy_phase,
            "phase_description": self._phase_description,
            "ema_short": self._indicators.get("ema_short"),
            "ema_long": self._indicators.get("ema_long"),
            "supertrend": self._indicators.get("supertrend"),
            "adx": self._indicators.get("adx"),
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
            
            start_date = get_setting("playback_start_date") or ""
            if not start_date:
                from database import get_last_trade_date
                last_trade_date = get_last_trade_date(mode=mode)
                if last_trade_date:
                    try:
                        last_dt = datetime.strptime(last_trade_date, "%Y-%m-%d")
                        start_date = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                        self.logger.info(f"Auto-resuming backtest from {start_date} (Last trade was {last_trade_date})")
                    except Exception:
                        pass
            
            self._effective_backtest_start = start_date
            feed_args["playback_start_date"] = start_date
            feed_args["playback_end_date"] = get_setting("playback_end_date") or ""
            feed_args["playback_period"] = get_setting("playback_period") or "all"
        else:
            self._effective_backtest_start = None
            feed_args["api_key"] = get_setting("api_key")
            feed_args["client_id"] = get_setting("client_id")

        self.data_feed = get_data_feed(**feed_args)

        # Restore Capital and Duration Metrics from Database
        from database import get_first_trade_date, get_all_time_pnl, get_fixed_lot_pnl
        self._first_ever_trade_date = get_first_trade_date(mode=mode)
        
        initial_cap = float(get_setting("initial_capital") or "100000")
        pnl_stats = get_all_time_pnl(mode=mode)
        self.capital = initial_cap + pnl_stats.get("all_time_pnl", 0)
        
        # Restore compounding baseline (fixed lots)
        f_lots = int(get_setting("fixed_lots") or "2")
        l_size = int(get_setting("lot_size") or "65")
        baseline_pnl = get_fixed_lot_pnl(mode=mode, fixed_lots=f_lots, lot_size=l_size)
        self.compounding_baseline_capital = initial_cap + baseline_pnl

        smart_api = None
        if mode == "live" or (mode == "paper" and data_source != "playback"):
            smart_api, feed_token = login_and_get_session()
            if smart_api and feed_token:
                self.data_feed.update_credentials(
                    get_setting("api_key"),
                    get_setting("client_id"),
                    feed_token,
                    smart_api.access_token
                )
                
                # Fetch history to seed indicators and chart
                try:
                    self.logger.info("Fetching historical candles to seed indicators...")
                    from datetime import datetime, timedelta
                    now_ist = datetime.now(IST)
                    # Get last 3 days to ensure we have enough data even after weekends
                    from_ist = now_ist - timedelta(days=3) 
                    
                    # Try both potential tokens for Nifty 50 Spot
                    tokens_to_try = ["99926000", "26000"]
                    hist_candles = []
                    
                    for token in tokens_to_try:
                        params = {
                            "exchange": "NSE",
                            "symboltoken": token,
                            "interval": "FIVE_MINUTE",
                            "fromdate": from_ist.strftime("%Y-%m-%d %H:%M"),
                            "todate": now_ist.strftime("%Y-%m-%d %H:%M")
                        }
                        self.logger.info(f"Trying history fetch for token {token}...")
                        hist_data = smart_api.getCandleData(params)
                        
                        if hist_data and hist_data.get("status"):
                            rows = hist_data.get("data", [])
                            if rows and len(rows) > 0:
                                for row in rows:
                                    try:
                                        ts_str = row[0]
                                        if 'T' in ts_str:
                                            ts_str = ts_str.replace("+0530", "+05:30")
                                            if ts_str.endswith("+05:30"):
                                                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")
                                            else:
                                                ts = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=IST)
                                        else:
                                            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
                                            
                                        hist_candles.append({
                                            "time": int(ts.timestamp()),
                                            "open": float(row[1]),
                                            "high": float(row[2]),
                                            "low": float(row[3]),
                                            "close": float(row[4]),
                                            "volume": int(row[5])
                                        })
                                    except Exception: continue
                                
                                if hist_candles:
                                    self.logger.info(f"Successfully fetched {len(hist_candles)} candles using token {token}")
                                    break # Success, don't try other tokens
                            else:
                                self.logger.warning(f"Token {token} returned empty history: {hist_data.get('message')}")
                        else:
                            msg = hist_data.get("message") if hist_data else "No response"
                            self.logger.warning(f"History API failed for token {token}: {msg}")
                            
                    if hist_candles:
                        self.data_feed.seed_history(hist_candles, interval=300)
                        self._update_indicators()
                        self.logger.info("Indicators initialized from historical data.")
                    else:
                        self.logger.error("Could not fetch historical data from any known Nifty 50 token.")
                        
                except Exception as e:
                    self.logger.error(f"Error during historical data fetch: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())
            else:
                self.logger.error("Failed to initialize Angel One session. Price feed may not start.")

        self.data_feed.start()
        self.order_manager = get_order_manager()
        if smart_api:
            self.order_manager.set_smart_api(smart_api)
        
        # Sync context for margin checks
        self.order_manager.update_context(data_feed=self.data_feed, capital=self.capital)

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
                self._strategy_phase = PHASE_IN_TRADE
                self._phase_description = PHASE_DESCRIPTIONS[PHASE_IN_TRADE]
                self.logger.info("Bot state restored. Resuming trade monitoring.")
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
        self._strategy_phase = PHASE_WATCHING
        self._phase_description = PHASE_DESCRIPTIONS[PHASE_WATCHING]
        self._current_signal = "WAIT"
        self._indicators = {}
        self._prev_indicators = {}
        self._last_5min_timestamp = None
        self.todays_lots = 0 

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
        current_time_str = now.strftime("%H:%M")
        current_price = self.data_feed.current_price if self.data_feed else 0

        # 1. Day Reset Check
        current_date = now.strftime("%Y-%m-%d")
        if self._last_tick_date and self._last_tick_date != current_date:
            self.logger.info(f"New day detected ({current_date}). Resetting strategy state.")
            self._reset_strategy_state()
            self._pre_market_setup(now)
        self._last_tick_date = current_date

        # Market Calendar Guard
        should_run, reason = should_bot_run(now)
        if not should_run:
            self._set_phase(PHASE_CLOSED)
            self._current_signal = "MARKET_CLOSED"
            return
        

        if current_price <= 0 and current_time_str >= "09:15":
            return

        # 2. Daily Loss Kill Switch
        max_loss = float(get_setting("max_daily_loss") or "10000")
        pnl_summary = get_today_pnl()
        if pnl_summary["total_pnl"] <= -max_loss:
            self._set_phase(PHASE_DAILY_LOSS_LIMIT)
            self._current_signal = "KILL_SWITCH_ACTIVE"
            return

        # Update indicators continuously
        self._update_indicators()

        # 3. Square-off check
        if is_square_off_time(now):
            self._handle_square_off(current_price)
            return

        # 4. If there's an active trade, manage it
        active_trade = get_active_trade()
        if active_trade:
            self._set_phase(PHASE_IN_TRADE)
            self._manage_trade(active_trade, current_price, now)
            return

        # 5. Phase-based strategy logic
        if current_time_str < "09:15":
            self._set_phase(PHASE_WATCHING)
            self._current_signal = "WAIT"
        elif current_time_str >= "09:15":
            if self._strategy_phase == PHASE_WATCHING:
                self._set_phase(PHASE_WAITING_FOR_ALIGNMENT)
            
            # Cooldown check: 5 minutes after signal_flip
            if self._last_exit_time and self._last_exit_reason == "signal_flip":
                cooldown_remaining = 300 - (now - self._last_exit_time).total_seconds()
                if cooldown_remaining > 0:
                    self._current_signal = f"COOLDOWN ({int(cooldown_remaining)}s)"
                    return
            
            # Risk check: Max trades
            max_trades = int(get_setting("max_trades_per_day") or "2")
            trades_today = get_today_trade_count(date_override=now.strftime("%Y-%m-%d"))
            if trades_today >= max_trades:
                if self._strategy_phase != PHASE_MAX_TRADES_DONE:
                    self.logger.info(f"Max trades reached for today ({trades_today}/{max_trades}). Skipping signal.")
                self._set_phase(PHASE_MAX_TRADES_DONE)
                self._current_signal = "MAX_TRADES_DONE"
                return

            self._run_strategy(current_price, now)

    def _run_strategy(self, current_price: float, now: datetime):
        """Supertrend + EMA Crossover + ADX Strategy."""
        if not self._indicators.get("ready"):
            return

        st_dir = self._indicators.get("supertrend_direction")
        ema_short = self._indicators.get("ema_short")
        ema_long = self._indicators.get("ema_long")
        adx = self._indicators.get("adx")
        
        prev_ema_short = self._prev_indicators.get("ema_short")
        prev_ema_long = self._prev_indicators.get("ema_long")

        signal = "WAIT"
        skip_reason = None

        # 1. EMA Crossover check
        bullish_cross = False
        bearish_cross = False
        if prev_ema_short is not None and prev_ema_long is not None:
            if ema_short > ema_long and prev_ema_short <= prev_ema_long:
                bullish_cross = True
            elif ema_short < ema_long and prev_ema_short >= prev_ema_long:
                bearish_cross = True

        # 2. ADX Filter
        adx_threshold = float(get_setting("adx_threshold") or "25")
        is_trending = adx is not None and adx >= adx_threshold

        if bullish_cross:
            if st_dir == 1:
                if is_trending:
                    signal = "BUY_CE"
                else:
                    skip_reason = f"ADX {adx} < {adx_threshold} (Choppy)"
            else:
                skip_reason = "Supertrend Bearish (Red)"
        elif bearish_cross:
            if st_dir == -1:
                if is_trending:
                    signal = "BUY_PE"
                else:
                    skip_reason = f"ADX {adx} < {adx_threshold} (Choppy)"
            else:
                skip_reason = "Supertrend Bullish (Green)"

        # Log to signal_logs
        if bullish_cross or bearish_cross or skip_reason:
            insert_signal_log({
                "price": current_price,
                "supertrend": self._indicators.get("supertrend"),
                "supertrend_direction": st_dir,
                "ema_short": ema_short,
                "ema_long": ema_long,
                "adx_threshold": float(get_setting("adx_threshold") or "25"),
                "signal": signal if signal != "WAIT" else None,
                "skip_reason": skip_reason
            }, timestamp=now)

        if signal != "WAIT":
            self.logger.info(f"STRATEGY SIGNAL: {signal} at {current_price} (ADX: {adx})")
            self._execute_trade(signal, current_price, now)

    def _update_indicators(self):
        """Update indicators and keep track of previous values for crossover."""
        feed = self.data_feed
        if feed:
            # Shift current to previous
            if self._indicators:
                self._prev_indicators = self._indicators.copy()
            
            # Use 5-minute candles for the indicator engine
            candles = feed.get_all_candles(interval="5minute")
            self._indicators = get_latest_indicators(candles)

    def calculate_dynamic_lots(self, sl_distance_option: float = 0) -> int:
        """
        Calculate lots based on true risk-based sizing using SL distance.
        lots = Risk Amount / (SL Distance * Lot Size)
        """
        try:
            mode = get_setting("trading_mode") or "paper"
            risk_pct = float(get_setting("risk_percent_per_trade") or "5.0")
            min_lots = int(get_setting("min_lots") or "1")
            lot_size = int(get_setting("lot_size") or "65")
            
            # 1. Determine Balance
            if self.data_feed and self.data_feed.playback_file:
                balance = self.capital
            elif mode == "paper":
                initial_paper = float(get_setting("paper_capital") or "100000")
                pnl_data = get_all_time_pnl(mode="paper")
                balance = initial_paper + pnl_data.get("all_time_pnl", 0)
            else:
                margin_info = self.order_manager.check_margin()
                balance = margin_info.get("available", 0)

            if balance <= 0: return min_lots

            # 2. Max Lots Safeguard
            max_lots_setting = (get_setting("max_lots") or "").strip()
            if not max_lots_setting or max_lots_setting == "10":
                max_lots = max(10, int(balance / 10000)) # Default 1 lot per 10k
            else:
                max_lots = int(max_lots_setting)

            # 3. Risk-Based Calculation
            risk_amount = balance * (risk_pct / 100.0)
            
            if sl_distance_option > 0:
                # True risk-based: how many lots before max loss is hit
                lots = int(risk_amount / (sl_distance_option * lot_size))
                calc_type = "risk-based"
            else:
                # Fallback: use capital usage (5% of capital / estimated premium)
                current_price = self.data_feed.current_price if (self.data_feed and self.data_feed.current_price > 0) else 20000
                est_premium = current_price * 0.015
                lots = int(risk_amount / (est_premium * lot_size))
                calc_type = "premium-fallback"
                
            final_lots = max(min_lots, min(lots, max_lots))
            
            self.logger.info(
                f"Lots Calc ({calc_type}): balance={balance:.0f}, risk={risk_amount:.0f}, "
                f"sl_dist={sl_distance_option:.1f}, final={final_lots}"
            )
            return final_lots
            
        except Exception as e:
            self.logger.error("Error calculating dynamic lots", e)
            return int(get_setting("min_lots") or "1")

    def _pre_market_setup(self, now: datetime):
        """Prepare for the day, lock lots if auto-compounding is enabled."""
        mode = get_setting("position_sizing_mode")
        if mode == "auto_compound":
            self.todays_lots = self.calculate_dynamic_lots()
            self.logger.info(f"Daily Lots Locked: {self.todays_lots} (Mode: auto_compound)")
        else:
            self.todays_lots = int(get_setting("fixed_lots") or "2")
            self.logger.info(f"Daily Lots Locked: {self.todays_lots} (Mode: fixed_lots)")

    def _execute_trade(self, signal: str, current_price: float, now: datetime):
        """Execute a trade with 1:2 RR Target and Supertrend SL."""
        mode = get_setting("trading_mode") or "paper"
        lot_size = int(get_setting("lot_size") or "65")
        
        # 1. SL Distance calculation
        st_value = self._indicators.get("supertrend") or current_price
        sl_distance = abs(current_price - st_value)
        sl_pts_option = sl_distance * 0.5 # Assuming Delta 0.5
        
        # Fetch hard ceiling from settings
        hard_limit = float(get_setting("max_sl_distance_pts") or "50")
        
        if sl_distance > hard_limit:
            self.logger.info(f"Signal skipped: SL distance {sl_distance:.1f} pts exceeds max {hard_limit} pts")
            return

        # 2. Determine Quantity
        pos_mode = get_setting("position_sizing_mode")
        if pos_mode == "auto_compound":
            # True risk-based: calibrate lots to SL distance
            lots = self.calculate_dynamic_lots(sl_distance_option=sl_pts_option)
        else:
            lots = int(get_setting("fixed_lots") or "2")

        quantity = lots * lot_size

        # 3. Place order
        result = self.order_manager.place_order(signal, current_price, mode, timestamp=now, quantity=quantity)

        if result:
            self._set_phase(PHASE_IN_TRADE)
            trade_id = result["trade_id"]
            entry_price = result["entry_price"]
            
            # 2. Risk Management Calculation (at Entry)
            # st_value and sl_distance already calculated above
            
            # Convert to Option SL (assuming Delta 0.5)
            sl_pts_option = sl_distance * 0.5
            initial_sl = round(entry_price - sl_pts_option, 2)
            
            # Target 1:2 RR
            target_pts_option = sl_pts_option * 2
            target_price = round(entry_price + target_pts_option, 2)

            update_trade(trade_id, {
                "target": target_price,
                "stop_loss": initial_sl,
                "trailing_sl": initial_sl,
                "quantity": quantity,
                "supertrend_at_entry": st_value,
                "adx_at_entry": self._indicators.get("adx"),
                "ema_short_at_entry": self._indicators.get("ema_short"),
                "ema_long_at_entry": self._indicators.get("ema_long"),
                "underlying_entry_price": current_price,
                "initial_risk_pts": sl_pts_option,
            })

            self.logger.info(
                f"Supertrend Entry: {signal} at {entry_price}. "
                f"Qty: {quantity}, Target: {target_price}, SL: {initial_sl}. "
                f"Index Entry: {current_price}, Supertrend: {st_value}"
            )

    def _manage_trade(self, trade: Dict, current_index_price: float, now: datetime):
        """Manage active trade with Signal Exit and Candle-Close Supertrend SL trailing."""
        simulated_price = self.calculate_option_price(trade, current_index_price)
        trade_type = trade.get("type", "CE")
        current_sl = trade.get("trailing_sl") or trade.get("stop_loss") or 0
        
        # 1. Signal-based Exit (Immediate Exit on Repaint/Direction Flip)
        st_dir = self._indicators.get("supertrend_direction")
        ema_short = self._indicators.get("ema_short")
        ema_long = self._indicators.get("ema_long")

        signal_exit = False
        exit_reason = "signal"

        if trade_type == "CE":
            if st_dir == -1 or (ema_short is not None and ema_long is not None and ema_short < ema_long):
                signal_exit = True
                exit_reason = "signal_flip"
        else: # PE
            if st_dir == 1 or (ema_short is not None and ema_long is not None and ema_short > ema_long):
                signal_exit = True
                exit_reason = "signal_flip"

        if signal_exit:
            # FIX: Only trigger signal_flip exit if current P&L is negative or less than 0.5x the initial risk.
            # If trade is profitable, let trailing SL or target exit instead to avoid 'tiny winners'.
            pnl_per_unit = simulated_price - trade["entry_price"]
            initial_risk_per_unit = trade.get("initial_risk_pts") or 0
            
            if pnl_per_unit < (initial_risk_per_unit * 0.5):
                self.logger.info(f"SIGNAL EXIT: {exit_reason} (P&L: {pnl_per_unit:.2f}, Risk: {initial_risk_per_unit:.2f})")
                self._close_active_trade(trade, simulated_price, exit_reason)
                return
            else:
                self.logger.info(f"SIGNAL FLIP IGNORED: Profitable trade (P&L: {pnl_per_unit:.1f}). Letting Trailing SL work.")

        # 2. Candle-Close Trailing SL Update (Every 5 minutes)
        candles_5m = self.data_feed.get_all_candles(interval="5minute") if self.data_feed else []
        if len(candles_5m) >= 2:
            last_closed_candle = candles_5m[-2]
            last_candle_time = last_closed_candle.get("time_key")
            
            # Only update SL on confirmed candle close
            if self._last_5min_timestamp != last_candle_time:
                self._last_5min_timestamp = last_candle_time
                
                # Get current Supertrend line value
                st_value = self._indicators.get("supertrend")
                if st_value:
                    # Trailing should only move in favor of the trade
                    new_sl_index = st_value
                    new_sl_option = self.calculate_option_price(trade, new_sl_index)
                    
                    if new_sl_option > current_sl:
                        self.logger.info(f"SUPERTREND TRAIL: Moving SL to {new_sl_option} (Index ST: {new_sl_index})")
                        update_trade(trade["id"], {"trailing_sl": new_sl_option})
                        current_sl = new_sl_option

        # 3. Target/SL Hits
        if simulated_price <= current_sl:
            self.logger.info(f"Stop loss hit: {simulated_price} <= {current_sl}")
            self._close_active_trade(trade, simulated_price, "stoploss")
            return

        if simulated_price >= trade["target"]:
            self.logger.info(f"Target hit: {simulated_price} >= {trade['target']}")
            self._close_active_trade(trade, simulated_price, "target")
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
        pnl = self.order_manager.exit_trade(trade["id"], exit_price, reason, trade.get("mode", "paper"), timestamp=now)
        
        # Update capital for backtest compounding tracking
        if self.data_feed and self.data_feed.playback_file:
            self.capital += pnl
            self.capital_history.append(self.capital)
            # Sync with order manager for next margin check
            if self.order_manager:
                self.order_manager.update_context(capital=self.capital)
            
            # Track fixed lot baseline for "Compounding Advantage" metric
            lot_size = int(get_setting("lot_size") or "65")
            fixed_lots_val = int(get_setting("fixed_lots") or "2")
            entry_price = trade.get("entry_price", 0)
            fixed_pnl = (exit_price - entry_price) * (fixed_lots_val * lot_size)
            self.compounding_baseline_capital += fixed_pnl

        # Track exit for cooldown
        self._last_exit_time = now
        self._last_exit_reason = reason

        # Log capital update
        if trade.get("mode") == "paper" or (self.data_feed and self.data_feed.playback_file):
            initial = float(get_setting("paper_capital") or "100000") if trade.get("mode") == "paper" else float(get_setting("initial_capital") or "100000")
            total_pnl = get_all_time_pnl(mode=trade.get("mode")).get("all_time_pnl", 0)
            self.logger.info(f"Updated capital: \u20b9{initial + total_pnl} (Initial: \u20b9{initial} + PnL: \u20b9{total_pnl})")

        if trade.get("mode") == "live" and trade.get("token") and self.data_feed:
            self.data_feed.unsubscribe_token(trade["token"])
        self._current_signal = "WAIT"

        # Reset to look for next entry
        self._set_phase(PHASE_WAITING_FOR_ALIGNMENT)

    def _handle_square_off(self, current_price: float):
        """Auto square-off at 3:15 PM."""
        active_trade = get_active_trade()
        if active_trade:
            sim_exit = self.calculate_option_price(active_trade, current_price)
            self._close_active_trade(active_trade, sim_exit, "squareoff")
            self.logger.info("Auto square-off executed at 3:15 PM IST")
        self._set_phase(PHASE_CLOSED)
        self._current_signal = "SQUARED_OFF"

    def get_status(self) -> Dict:
        try:
            from database import get_today_pnl, get_active_trade, get_all_time_pnl
            mode = get_setting("trading_mode") or "paper"
            
            # If in backtest mode, filter all stats by current backtest date
            date_to = None
            if self.data_feed and self.data_feed.playback_file:
                date_to = self._get_current_time().strftime("%Y-%m-%d")
                
            pnl_summary = get_today_pnl(mode=mode, date_override=date_to)
            all_time_summary = get_all_time_pnl(mode=mode, date_to=date_to)
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
                "total_wins": all_time_summary.get("wins", 0),
                "total_losses": all_time_summary.get("losses", 0),
                "all_time_win_rate": all_time_summary.get("all_time_win_rate", 0),
                "mode": mode,
                "phase": self._strategy_phase,
                # Compounding stats
                "backtest_capital": self.capital,
                "capital_history": self.capital_history,
                "compounding_advantage": self.capital - self.compounding_baseline_capital,
                "backtest_start": self._first_ever_trade_date or self._effective_backtest_start or get_setting("playback_start_date") or "2015-10-01",
                "backtest_current": self._get_current_time().strftime("%Y-%m-%d") if self.data_feed and self.data_feed.playback_file else None,
                "backtest_duration": "",
                "initial_capital": float(get_setting("initial_capital") or "100000")
            }

            if active_trade and price_info.get("price"):
                simulated_price = self.calculate_option_price(active_trade, price_info["price"])
                active_trade["current_price"] = simulated_price
                active_trade["live_pnl"] = round((simulated_price - active_trade["entry_price"]) * active_trade["quantity"], 2)
                status["active_trade"] = active_trade

            return status
        except Exception as e:
            self.logger.error(f"Error getting bot status: {e}")
            return {
                "running": self._running,
                "error": str(e),
                "mode": "paper",
                "phase": self._strategy_phase,
                "signal": self._current_signal
            }


    def manual_exit(self, exit_price: Optional[float] = None) -> Dict:
        """Manually exit the active trade."""
        try:
            active = get_active_trade()
            if not active:
                return {"status": "error", "message": "No active trade found"}
            
            # Use current price if no exit price provided
            price = exit_price
            if price is None:
                current_price = self.data_feed.current_price if self.data_feed else 0
                if current_price <= 0:
                    return {"status": "error", "message": "Market price not available"}
                price = self.calculate_option_price(active, current_price)
            
            self._close_active_trade(active, price, "manual")
            return {"status": "success", "message": f"Trade exited manually at {price}"}
        except Exception as e:
            self.logger.error(f"Manual exit failed: {e}")
            return {"status": "error", "message": str(e)}


_bot = None
def get_bot() -> TradingBot:
    global _bot
    if _bot is None:
        _bot = TradingBot()
    return _bot

