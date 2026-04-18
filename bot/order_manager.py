"""
Order Manager module.
Handles order placement, exit, margin checks, and lot size validation.
Supports both paper trading and live trading via Angel One SmartAPI.
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from logger import get_logger
from database import insert_trade, close_trade, get_setting, get_active_trade
from instrument_manager import get_instrument_manager

IST = timezone(timedelta(hours=5, minutes=30))


class OrderManager:
    """Manages order placement and exit for NIFTY options."""

    def __init__(self, smart_api=None):
        self.smart_api = smart_api  # SmartConnect instance
        self.logger = get_logger()
        self.instrument_mgr = get_instrument_manager()
        self._lock = threading.Lock()

    def set_smart_api(self, smart_api):
        """Set/update the SmartConnect instance."""
        self.smart_api = smart_api

    def check_margin(self, required_amount: float = 0) -> Dict:
        """
        Check available margin from Angel One.
        Returns margin info dict.
        """
        try:
            if self.smart_api is None:
                # Paper trading — return virtual capital
                paper_capital = float(get_setting("paper_capital") or "100000")
                result = {
                    "available": paper_capital,
                    "required": required_amount,
                    "sufficient": paper_capital >= required_amount,
                    "mode": "paper"
                }
                self.logger.margin_check(paper_capital, required_amount, result["sufficient"])
                return result

            # Live trading — call Angel One RMS
            margin_data = self.smart_api.rmsLimit()
            if margin_data and margin_data.get("status"):
                data = margin_data.get("data", {})
                available = float(data.get("availablecash", 0))
                result = {
                    "available": available,
                    "required": required_amount,
                    "sufficient": available >= required_amount,
                    "mode": "live"
                }
                self.logger.margin_check(available, required_amount, result["sufficient"])
                return result
            else:
                self.logger.error(f"Margin check failed: {margin_data}")
                return {"available": 0, "required": required_amount, "sufficient": False, "mode": "live"}

        except Exception as e:
            self.logger.error("Margin check error", e)
            return {"available": 0, "required": required_amount, "sufficient": False, "mode": "error"}

    def validate_lot_size(self, quantity: int) -> bool:
        """
        Validate that quantity is a valid multiple of Nifty lot size.
        """
        lot_size = self.instrument_mgr.get_lot_size()
        if quantity <= 0:
            self.logger.warning(f"Invalid quantity: {quantity}")
            return False
        if quantity % lot_size != 0:
            self.logger.warning(
                f"Quantity {quantity} is not a multiple of lot size {lot_size}. "
                f"Must be multiples of {lot_size}."
            )
            return False
        return True

    def place_order(self, signal: str, current_price: float,
                    mode: str = "paper", timestamp: Optional[datetime] = None, 
                    entry_quality: Optional[float] = None,
                    quantity: Optional[int] = None) -> Optional[Dict]:
        """
        Place an order based on signal.
        signal: 'BUY_CE' or 'BUY_PE'
        Returns trade info dict or None if order failed.
        """
        with self._lock:
            try:
                option_type = "CE" if signal == "BUY_CE" else "PE"

                # Get instrument info
                self.instrument_mgr.load_instruments()
                strike = self.instrument_mgr.get_atm_strike(current_price)
                lot_size = self.instrument_mgr.get_lot_size()
                
                if quantity is None:
                    quantity = lot_size
                elif not self.validate_lot_size(quantity):
                    quantity = lot_size # fallback to 1 lot if invalid

                expiry = self.instrument_mgr.get_nearest_expiry()

                option_info = self.instrument_mgr.get_option_info(strike, option_type, expiry)
                trading_symbol = option_info["symbol"] if option_info else f"NIFTY{strike}{option_type}"
                token = option_info["token"] if option_info else None

                # Get strategy parameters
                stop_loss_pct = float(get_setting("stop_loss_pct") or "0.5")
                target_pct = float(get_setting("target_pct") or "1.0")

                # For paper trading/playback with only index data, estimate option premium
                # Standard estimate for ATM weekly options is ~1.5% of the index price
                # If current_price > 2000, we treat it as an index price needing premium estimation
                if mode == "paper" or current_price > 2000:
                    entry_price = round(current_price * 0.015, 2)
                    self.logger.info(f"Using estimated premium for {option_type}: {entry_price}")
                else:
                    entry_price = current_price
                
                stop_loss = round(entry_price * (1 - stop_loss_pct / 100), 2)
                target = round(entry_price * (1 + target_pct / 100), 2)

                # Estimate required margin
                estimated_margin = entry_price * quantity
                margin_result = self.check_margin(estimated_margin)

                if not margin_result["sufficient"]:
                    self.logger.order_failed(
                        f"Insufficient margin. Available: {margin_result['available']:.2f}, "
                        f"Required: {estimated_margin:.2f} (Est. Premium: {entry_price})"
                    )
                    return None

                # Validate lot size
                if not self.validate_lot_size(quantity):
                    self.logger.order_failed(f"Invalid lot size: {quantity}")
                    return None

                # Place the order
                trade_info = {
                    "type": option_type,
                    "strike_price": strike,
                    "trading_symbol": trading_symbol,
                    "entry_price": entry_price,
                    "quantity": quantity,
                    "lot_size": lot_size,
                    "mode": mode,
                    "stop_loss": stop_loss,
                    "target": target,
                    "underlying_entry_price": current_price,
                    "token": token,
                    "entry_quality": entry_quality
                }

                if mode == "live" and self.smart_api:
                    # Live order via Angel One
                    order_result = self._place_live_order(
                        trading_symbol, token, option_type, quantity, entry_price
                    )
                    if not order_result:
                        return None
                    entry_price = order_result.get("price", entry_price)
                else:
                    # Paper trade — simulate fill at current price
                    self.logger.info(f"Paper trade: Simulated fill for {trading_symbol} at {entry_price}")

                # Save trade to database
                trade_data = {
                    "type": option_type,
                    "strike_price": strike,
                    "trading_symbol": trading_symbol,
                    "entry_price": entry_price,
                    "quantity": quantity,
                    "lot_size": lot_size,
                    "mode": mode,
                    "stop_loss": stop_loss,
                    "target": target,
                    "underlying_entry_price": current_price,
                    "token": token,
                    "entry_quality": entry_quality
                }
                trade_id = insert_trade(trade_data, timestamp=timestamp)

                self.logger.order_placed(
                    f"BUY {option_type}",
                    strike, entry_price, quantity, mode
                )

                return {
                    "trade_id": trade_id,
                    "type": option_type,
                    "strike": strike,
                    "symbol": trading_symbol,
                    "entry_price": entry_price,
                    "quantity": quantity,
                    "stop_loss": stop_loss,
                    "target": target,
                    "mode": mode,
                    "expiry": str(expiry) if expiry else None
                }

            except Exception as e:
                self.logger.error("Order placement failed", e)
                return None

    def _place_live_order(self, symbol: str, token: str,
                          option_type: str, quantity: int,
                          price: float) -> Optional[Dict]:
        """Place a live order via Angel One SmartAPI."""
        try:
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": "BUY",
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "quantity": str(quantity),
            }

            order_result = self.smart_api.placeOrder(order_params)
            if order_result:
                self.logger.info(f"Live order placed: {order_result}")
                return {"order_id": order_result, "price": price}
            else:
                self.logger.order_failed("Angel One returned None for order")
                return None

        except Exception as e:
            self.logger.error("Live order placement failed", e)
            return None

    def exit_trade(self, trade_id: int, exit_price: float,
                   reason: str = "manual", mode: str = "paper", timestamp: Optional[datetime] = None) -> float:
        """
        Exit an active trade.
        Returns P&L.
        """
        try:
            active = get_active_trade()
            if not active or active["id"] != trade_id:
                self.logger.warning(f"Trade {trade_id} not found or not active")
                return 0
 
            if mode == "live" and self.smart_api:
                # Place exit order via Angel One
                self._place_exit_order(active, exit_price)
 
            pnl = close_trade(trade_id, exit_price, reason, timestamp=timestamp)
 
            self.logger.order_exit(reason, pnl, {
                "trade_id": trade_id,
                "entry": active["entry_price"],
                "exit": exit_price,
                "type": active["type"]
            }, timestamp=timestamp)
 
            return pnl

        except Exception as e:
            self.logger.error(f"Exit trade {trade_id} failed", e)
            return 0

    def _place_exit_order(self, trade: Dict, price: float):
        """Place an exit order via Angel One."""
        try:
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": trade["trading_symbol"],
                "symboltoken": "",
                "transactiontype": "SELL",
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "quantity": str(trade["quantity"]),
            }
            result = self.smart_api.placeOrder(order_params)
            self.logger.info(f"Exit order placed: {result}")
        except Exception as e:
            self.logger.error("Exit order failed", e)

    def exit_all_positions(self, current_price: float, reason: str = "squareoff"):
        """Exit all open positions (for square-off)."""
        active = get_active_trade()
        if active:
            mode = active.get("mode", "paper")
            self.exit_trade(active["id"], current_price, reason, mode)


# Global instance
_order_manager = None

def get_order_manager(smart_api=None) -> OrderManager:
    """Get or create the global OrderManager instance."""
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager(smart_api)
    return _order_manager
