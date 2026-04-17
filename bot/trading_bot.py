"""
Main Trading Bot Logic.
Orchestrates signal generation, trade management, and risk controls.
"""

import threading
import time
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

from logger import get_logger
from market_calendar import (
    should_bot_run, is_signal_window, is_square_off_time,
    is_trading_day, get_ist_now
)
from data_feed import get_data_feed, DataFeed
from indicators import get_latest_indicators, ema_crossover
from order_manager import get_order_manager, OrderManager
from database import (
    get_active_trade, get_today_trade_count, get_consecutive_losses,
    get_today_pnl, get_setting
)

IST = timezone(timedelta(hours=5, minutes=30))


class TradingBot:
    """
    Automated trading bot for NIFTY 50 Options.
    Generates signals based on EMA crossover + VWAP + RSI.
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

        # Cached indicator values
        self._indicators: Dict = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_signal(self) -> str:
        return self._current_signal

    @property
    def indicators(self) -> Dict:
        return dict(self._indicators)

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
        
        # Resolve playback file path relative to bot root if it's relative
        if data_source == "playback" and playback_file and not os.path.isabs(playback_file):
            # If path starts with 'bot/', remove it since we are likely running from inside /bot
            clean_path = playback_file[4:] if playback_file.startswith("bot/") else playback_file
            bot_dir = os.path.dirname(os.path.abspath(__file__))
            playback_file = os.path.join(bot_dir, clean_path)
        
        use_simulation = (mode == "paper") and (data_source == "simulated" or not get_setting("api_key"))
        
        feed_args = {"use_simulation": use_simulation}
        if data_source == "playback":
            feed_args["playback_file"] = playback_file
            feed_args["playback_speed"] = playback_speed
            
        self.data_feed = get_data_feed(**feed_args)
        self.data_feed.start()

        self.order_manager = get_order_manager()

        # Start bot loop in background thread
        self._bot_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._bot_thread.start()
        
        # If there is an active trade, ensure we are subscribed to its price feed
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
        # Use playback time if available to drive the bot logic
        now = get_ist_now()
        if self.data_feed and self.data_feed.playback_file:
            playback_time = self.data_feed.last_tick_time
            if playback_time:
                now = playback_time

        # Market Calendar Guard
        should_run, reason = should_bot_run(now)
        if not should_run:
            self._current_signal = "MARKET_CLOSED"
            return

        current_price = self.data_feed.current_price if self.data_feed else 0
        if current_price <= 0:
            return

        # Get candle data and calculate indicators
        candles = self.data_feed.get_all_candles() if self.data_feed else []

        if len(candles) >= 2:
            ema_fast_period = int(get_setting("ema_fast") or "9")
            ema_slow_period = int(get_setting("ema_slow") or "21")
            rsi_period = int(get_setting("rsi_period") or "14")

            self._indicators = get_latest_indicators(
                candles, ema_fast_period, ema_slow_period, rsi_period
            )

        # Auto square-off check
        if is_square_off_time(now):
            self._handle_square_off(current_price)
            return

        # Check for active trade — manage it
        active_trade = get_active_trade()
        if active_trade:
            self._manage_trade(active_trade, current_price)
            return

        # Signal generation window check
        if not is_signal_window(now):
            self._current_signal = "WAIT"
            return

        # Risk management checks
        if not self._can_trade():
            self._current_signal = "WAIT"
            return

        # Generate signal
        signal = self._generate_signal(current_price)
        self._current_signal = signal

        # Place order if signal is actionable
        if signal in ("BUY_CE", "BUY_PE"):
            mode = get_setting("trading_mode") or "paper"
            result = self.order_manager.place_order(signal, current_price, mode, timestamp=now)
            if result:
                self.logger.order_placed(
                    f"BUY {result['type']}", result['strike'], result['entry_price'], result['quantity'], mode, timestamp=now
                )
                self.logger.info(f"Trade opened: {result}")
                # Subscribe to live option price if in live mode
                if mode == "live" and result.get("token") and self.data_feed:
                    self.data_feed.subscribe_token(result["token"])

    def _generate_signal(self, current_price: float) -> str:
        """
        Generate trading signal based on EMA crossover + VWAP + RSI.
        """
        if not self._indicators.get("ready"):
            return "WAIT"

        ema_fast = self._indicators.get("ema_fast")
        ema_slow = self._indicators.get("ema_slow")
        vwap = self._indicators.get("vwap")
        rsi = self._indicators.get("rsi")
        crossover = self._indicators.get("crossover")

        if any(v is None for v in [ema_fast, ema_slow, vwap, rsi]):
            return "WAIT"

        rsi_overbought = float(get_setting("rsi_overbought") or "55")
        rsi_oversold = float(get_setting("rsi_oversold") or "45")

        signal = "WAIT"

        # BUY CE: EMA9 crosses above EMA21 + price > VWAP + RSI > 55
        if crossover == "bullish" and current_price > vwap and rsi > rsi_overbought:
            signal = "BUY_CE"

        # BUY PE: EMA9 crosses below EMA21 + price < VWAP + RSI < 45
        elif crossover == "bearish" and current_price < vwap and rsi < rsi_oversold:
            signal = "BUY_PE"

        # Log signal if changed
        if signal != "WAIT":
            self.logger.signal(signal, {
                "price": current_price,
                "ema9": ema_fast,
                "ema21": ema_slow,
                "vwap": vwap,
                "rsi": rsi,
                "crossover": crossover
            }, timestamp=self.data_feed.last_tick_time if self.data_feed else None)

        return signal

    def calculate_option_price(self, trade: Dict, current_index_price: float) -> float:
        """Calculate a realistic simulated option price based on underlying movement."""
        mode = trade.get("mode", "paper")
        is_playback = self.data_feed and self.data_feed.playback_file
        
        entry_option_price = trade.get("entry_price", 0)
        entry_index_price = trade.get("underlying_entry_price")
        trade_type = trade.get("type", "CE")
        token = trade.get("token")

        # 1. If live and not in playback, use real LTP from WebSocket
        if mode == "live" and not is_playback and token and self.data_feed:
            live_ltp = self.data_feed.get_token_price(token)
            if live_ltp > 0:
                return live_ltp

        # 2. If paper or playback, use Delta simulation
        if (mode == "paper" or is_playback) and entry_index_price and entry_option_price:
            index_diff = current_index_price - entry_index_price
            # Delta 0.5 estimate: Option moves 0.5 points for every 1 point move in Index
            if trade_type == "CE":
                option_ltp = entry_option_price + (index_diff * 0.5)
            else: # PE
                option_ltp = entry_option_price - (index_diff * 0.5)
            
            return max(0.05, round(option_ltp, 2))

        # 3. Fallback to index price (should rarely happen for options now)
        return current_index_price

    def _manage_trade(self, trade: Dict, current_price: float):
        """Monitor and manage an active trade with realistic option price simulation."""
        stop_loss = trade.get("stop_loss", 0)
        target = trade.get("target", 0)
        entry_option_price = trade["entry_price"]
        trade_type = trade.get("type", "CE")
        
        # Calculate simulated/real current price
        simulated_price = self.calculate_option_price(trade, current_price)

        # Calculate current P&L
        pnl = (simulated_price - entry_option_price) * trade["quantity"]

        # Check stop loss
        if stop_loss and simulated_price <= stop_loss:
            self._close_active_trade(trade, simulated_price, "stoploss")
            self._current_signal = "WAIT"
            return

        # Check target
        if target and simulated_price >= target:
            self._close_active_trade(trade, simulated_price, "target")
            self._current_signal = "WAIT"
            return

        # Update signal to show active trade
        self._current_signal = f"ACTIVE_{trade_type}"

    def _close_active_trade(self, trade: Dict, exit_price: float, reason: str):
        """Helper to exit trade and handle unsubscription."""
        now = self.data_feed.last_tick_time if self.data_feed else get_ist_now()
        self.order_manager.exit_trade(trade["id"], exit_price, reason, trade.get("mode", "paper"), timestamp=now)
        
        # In live mode, unsubscribe from the option feed
        if trade.get("mode") == "live" and trade.get("token") and self.data_feed:
            self.data_feed.unsubscribe_token(trade["token"])

    def _handle_square_off(self, current_price: float):
        """Handle end-of-day square-off with simulated price."""
        active_trade = get_active_trade()
        if active_trade:
            simulated_exit = self.calculate_option_price(active_trade, current_price)
            self.order_manager.exit_trade(active_trade["id"], simulated_exit, "squareoff", active_trade.get("mode", "paper"))
            self._current_signal = "WAIT"
            self.logger.info("Auto square-off executed at 3:15 PM IST")
        self._current_signal = "SQUARED_OFF"

    def _can_trade(self) -> bool:
        """Check risk management rules before placing a trade."""
        max_trades = int(get_setting("max_trades_per_day") or "3")
        today_count = get_today_trade_count()

        if today_count >= max_trades:
            return False

        consecutive_losses = get_consecutive_losses()
        if consecutive_losses >= 2:
            self.logger.warning("2 consecutive losses — bot paused for the day")
            return False

        return True

    def get_status(self) -> Dict:
        """Get current bot status and today's stats."""
        date_override = None
        if self.data_feed and self.data_feed.playback_file and self.data_feed.last_tick_time:
            date_override = self.data_feed.last_tick_time.strftime("%Y-%m-%d")
            
        pnl_summary = get_today_pnl(date_override=date_override)
        active_trade = get_active_trade()
        price_info = self.data_feed.get_price_info() if self.data_feed else {}

        status = {
            "running": self._running,
            "signal": self._current_signal,
            "indicators": self._indicators,
            "price": price_info,
            "active_trade": active_trade,
            "today_pnl": pnl_summary.get("total_pnl", 0),
            "today_trades": pnl_summary.get("total_trades", 0),
            "wins": pnl_summary.get("wins", 0),
            "losses": pnl_summary.get("losses", 0),
            "win_rate": pnl_summary.get("win_rate", 0),
            "consecutive_losses": get_consecutive_losses(date_override=date_override),
            "mode": get_setting("trading_mode") or "paper",
            "market_status": should_bot_run()[1] if not self._running else "Bot running"
        }

        # Add live P&L to active trade if it exists
        if active_trade and price_info.get("price"):
            simulated_option_price = self.calculate_option_price(active_trade, price_info["price"])
            active_trade["current_price"] = simulated_option_price
            active_trade["live_pnl"] = round(
                (simulated_option_price - active_trade["entry_price"]) * active_trade["quantity"], 2
            )
            status["active_trade"] = active_trade

        return status

    def manual_exit(self, current_price: float = None) -> Dict:
        """Manually exit the active trade."""
        active_trade = get_active_trade()
        if not active_trade:
            return {"success": False, "message": "No active trade to exit"}

        if current_price is None:
            current_price = self.data_feed.current_price if self.data_feed else 0

        mode = active_trade.get("mode", "paper")
        pnl = self.order_manager.exit_trade(active_trade["id"], current_price, "manual", mode)

        return {"success": True, "pnl": pnl, "message": f"Trade exited. P&L: {pnl:+.2f}"}


# Global bot instance
_bot = None

def get_bot() -> TradingBot:
    """Get or create the global TradingBot instance."""
    global _bot
    if _bot is None:
        _bot = TradingBot()
    return _bot
