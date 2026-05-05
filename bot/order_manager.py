"""
Order Manager module.
Handles order placement, exit, margin checks, and lot size validation.
Supports both paper trading and live trading via Angel One SmartAPI.
"""

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from logger import get_logger
from database import insert_trade, close_trade, get_setting, get_active_trade, get_all_time_pnl
from instrument_manager import get_instrument_manager

IST = timezone(timedelta(hours=5, minutes=30))
MAX_QTY_PER_ORDER = 1800 # Nifty freeze limit quantity


class OrderManager:
    """Manages order placement and exit for NIFTY options."""

    def __init__(self, smart_api=None):
        self.smart_api = smart_api  # SmartConnect instance
        self.logger = get_logger()
        self.instrument_mgr = get_instrument_manager()
        self._lock = threading.Lock()
        self.data_feed = None
        self.capital = 0

    def set_smart_api(self, smart_api):
        """Set/update the SmartConnect instance."""
        self.smart_api = smart_api

    def update_context(self, data_feed=None, capital: float = 0):
        """Update data feed and capital context for margin checks."""
        if data_feed:
            self.data_feed = data_feed
        if capital > 0:
            self.capital = capital

    def check_margin(self, required_amount: float = 0, log_check: bool = True) -> Dict:
        """
        Check available margin from Angel One.
        Returns margin info dict.
        """
        try:
            if self.smart_api is None:
                # Paper trading — return virtual capital
                if self.data_feed and self.data_feed.playback_file:
                    available = self.capital  # use compounding tracker
                else:
                    initial = float(get_setting("paper_capital") or "100000")
                    pnl = get_all_time_pnl(mode="paper").get("all_time_pnl", 0)
                    available = initial + pnl

                result = {
                    "available": available,
                    "required": required_amount,
                    "sufficient": available >= required_amount,
                    "mode": "paper"
                }
                if log_check:
                    self.logger.margin_check(available, required_amount, result["sufficient"])
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
                if log_check:
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
                # Do not log the initial check to avoid false alarms on the UI if we fallback
                margin_result = self.check_margin(estimated_margin, log_check=False)

                if not margin_result["sufficient"]:
                    # ── Lot-Reduction Fallback ────────────────────────────────────
                    # Required capital > available capital.
                    # Calculate the max lots we can actually afford,
                    # rather than jumping straight to min_lots.
                    min_lots = int(get_setting("min_lots") or "1")
                    lot_size_val = int(get_setting("lot_size") or "65")
                    cost_per_lot = entry_price * lot_size_val
                    available = margin_result["available"]

                    affordable_lots = int(available // cost_per_lot) if cost_per_lot > 0 else 0
                    affordable_lots = max(affordable_lots, 0)  # floor at 0

                    if affordable_lots >= min_lots:
                        fallback_qty = affordable_lots * lot_size_val
                        fallback_margin = entry_price * fallback_qty
                        self.logger.info(
                            f"Margin insufficient for {quantity} units (₹{estimated_margin:.0f}). "
                            f"Scaling down to {affordable_lots} lot(s) ({fallback_qty} units) — "
                            f"requires ₹{fallback_margin:.0f}, available ₹{available:.0f}."
                        )
                        # Log the successful fallback check
                        self.logger.margin_check(available, fallback_margin, True)
                        
                        quantity = fallback_qty
                        estimated_margin = fallback_margin
                    else:
                        min_req = entry_price * min_lots * lot_size_val
                        # Log the true failure
                        self.logger.margin_check(available, min_req, False)
                        self.logger.order_failed(
                            f"Insufficient margin even for {min_lots} lot(s). "
                            f"Available: {available:.2f}, "
                            f"Required (min): {min_req:.2f} (Est. Premium: {entry_price})"
                        )
                        return None
                else:
                    # Initial check passed, log success
                    self.logger.margin_check(margin_result["available"], estimated_margin, True)

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
                    "entry_quality": entry_quality,
                    "capital_used": round(entry_price * quantity, 2)
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
                    "entry_quality": entry_quality,
                    "capital_used": round(entry_price * quantity, 2),
                    "total_capital": margin_result["available"]
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
                    "capital_used": round(entry_price * quantity, 2),
                    "expiry": str(expiry) if expiry else None
                }

            except Exception as e:
                self.logger.error("Order placement failed", e)
                return None

    def _place_live_order(self, symbol: str, token: str,
                          option_type: str, quantity: int,
                          price: float) -> Optional[Dict]:
        """Place live orders via Angel One SmartAPI, slicing if necessary."""
        order_ids = self._execute_live_order_sliced(
            symbol=symbol,
            token=token,
            side="BUY",
            quantity=quantity
        )
        if order_ids:
            return {"order_ids": order_ids, "price": price}
        return None

    def _execute_live_order_sliced(self, symbol: str, token: str, side: str, quantity: int) -> List[str]:
        """Generic helper to execute live orders with slicing and retries."""
        if not self.smart_api:
            return []

        # Use the hard quantity limit (1800 for Nifty)
        max_qty_per_order = MAX_QTY_PER_ORDER
        
        total_qty = quantity
        all_order_ids = []
        
        while total_qty > 0:
            chunk_qty = min(total_qty, max_qty_per_order)
            
            # Retry logic: Try up to 3 times (initial + 2 retries)
            success = False
            for attempt in range(3):
                try:
                    order_params = {
                        "variety": "NORMAL",
                        "tradingsymbol": symbol,
                        "symboltoken": token,
                        "transactiontype": side,
                        "exchange": "NFO",
                        "ordertype": "MARKET",
                        "producttype": "INTRADAY",
                        "duration": "DAY",
                        "quantity": str(chunk_qty),
                    }
                    order_id = self.smart_api.placeOrder(order_params)
                    if order_id:
                        all_order_ids.append(order_id)
                        self.logger.info(f"Live order chunk placed: {order_id} ({side} Qty: {chunk_qty}, Attempt: {attempt+1})")
                        success = True
                        break
                    else:
                        self.logger.warning(f"Order attempt {attempt+1} returned no order_id for qty {chunk_qty}")
                except Exception as e:
                    self.logger.error(f"Order attempt {attempt+1} exception for qty {chunk_qty}: {e}")
                
                if attempt < 2:
                    time.sleep(0.5) # Wait 500ms before retry
            
            if not success:
                self.logger.error(f"FATAL: Failed to execute {side} order for chunk {chunk_qty} after 3 attempts.")
                # We stop here to prevent partially filled large positions from becoming unmanageable
                return all_order_ids 

            total_qty -= chunk_qty
            if total_qty > 0:
                time.sleep(0.3) # 300ms delay between sequential chunks to prevent rate limits
        
        return all_order_ids

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

    def partial_exit(self, trade_id: int, quantity: int, exit_price: float, 
                     reason: str = "partial_target", mode: str = "paper", 
                     timestamp: Optional[datetime] = None) -> float:
        """
        Exits a portion of an active trade.
        Records realized P&L by updating existing trade qty and inserting a closed record.
        """
        try:
            from database import update_trade, get_ist_now
            active = get_active_trade()
            if not active or active["id"] != trade_id:
                self.logger.warning(f"Partial exit failed: Trade {trade_id} not found or not active")
                return 0

            if quantity >= active["quantity"]:
                self.logger.info("Partial quantity >= total. Closing entire trade instead.")
                return self.exit_trade(trade_id, exit_price, reason, mode, timestamp)

            if mode == "live" and self.smart_api:
                # Place partial exit order
                self._place_partial_sell_order(active, quantity, exit_price)

            # Realized P&L for this portion
            realized_pnl = round((exit_price - active["entry_price"]) * quantity, 2)
            
            # 1. Update active trade (decrease quantity, mark partial_booked)
            remaining_qty = active["quantity"] - quantity
            update_trade(trade_id, {
                "quantity": remaining_qty,
                "partial_booked": 1
            })

            # 2. Insert a "Closed" trade record for the partial exit portion to track P&L
            now = timestamp or get_ist_now()
            partial_record = dict(active)
            partial_record["exit_time"] = now.strftime("%H:%M:%S")
            
            # Remove ID so it inserts as new
            if "id" in partial_record: del partial_record["id"]
            partial_record["quantity"] = quantity
            partial_record["status"] = "win" if realized_pnl > 0 else "loss"
            partial_record["exit_price"] = exit_price
            partial_record["pnl"] = realized_pnl
            partial_record["exit_reason"] = reason
            
            insert_trade(partial_record, timestamp=now)

            self.logger.info(f"PARTIAL BOOKED: Sold {quantity} units at {exit_price}. Realized P&L: {realized_pnl}")
            return realized_pnl

        except Exception as e:
            self.logger.error(f"Partial exit for trade {trade_id} failed", e)
            return 0

    def _place_partial_sell_order(self, trade: Dict, quantity: int, price: float):
        """Place a partial exit order via Angel One (Market Sell), slicing if necessary."""
        self._execute_live_order_sliced(
            symbol=trade["trading_symbol"],
            token=trade.get("token", ""),
            side="SELL",
            quantity=quantity
        )

    def _place_exit_order(self, trade: Dict, price: float):
        """Place an exit order via Angel One, slicing if necessary."""
        self._execute_live_order_sliced(
            symbol=trade["trading_symbol"],
            token=trade.get("token", ""),
            side="SELL",
            quantity=trade["quantity"]
        )

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
