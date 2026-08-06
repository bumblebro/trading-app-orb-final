"""
Order placement and exit for NIFTY options.

Paper mode books a simulated fill at the theoretical premium. Live mode routes
market orders through Angel One SmartAPI, slicing above the exchange freeze
quantity, and then *verifies* the fill from the order book instead of assuming
the requested price. If part of a sliced entry fails, the filled portion is
sold back immediately rather than left as an unintended position.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from database import (
    calculate_charges, close_trade, get_active_trade, get_all_time_pnl,
    get_setting, insert_trade,
)
from instrument_manager import get_instrument_manager
from logger import get_logger

# NSE freeze limit for NIFTY options; larger orders must be sliced.
MAX_QTY_PER_ORDER = 1800
ORDER_RETRIES = 3
RETRY_DELAY_SEC = 0.5
SLICE_DELAY_SEC = 0.3
FILL_POLL_ATTEMPTS = 6
FILL_POLL_DELAY_SEC = 0.5


class OrderManager:
    def __init__(self, smart_api=None):
        self.smart_api = smart_api
        self.logger = get_logger()
        self.instruments = get_instrument_manager()
        self._lock = threading.Lock()
        self.data_feed = None
        self.capital = 0.0

    def set_smart_api(self, smart_api):
        self.smart_api = smart_api

    def update_context(self, data_feed=None, capital: float = None):
        if data_feed is not None:
            self.data_feed = data_feed
        if capital is not None:
            self.capital = capital

    # ------------------------------------------------------------------ margin

    def check_margin(self, required: float = 0, mode: str = "paper",
                     log_check: bool = True) -> Dict:
        try:
            if mode != "live" or self.smart_api is None:
                if self.data_feed is not None and getattr(self.data_feed, "playback_file", None):
                    available = self.capital
                else:
                    base = float(get_setting("paper_capital") or "500000")
                    available = base + get_all_time_pnl(mode="paper").get("all_time_pnl", 0)
                result = {"available": available, "required": required,
                          "sufficient": available >= required, "mode": "paper"}
            else:
                data = (self.smart_api.rmsLimit() or {}).get("data") or {}
                available = float(data.get("availablecash", 0) or 0)
                result = {"available": available, "required": required,
                          "sufficient": available >= required, "mode": "live"}

            if log_check:
                self.logger.margin_check(result["available"], required, result["sufficient"])
            return result
        except Exception as exc:
            self.logger.error("Margin check failed", exc)
            return {"available": 0, "required": required, "sufficient": False, "mode": "error"}

    # ------------------------------------------------------------------- entry

    def place_order(self, option_type: str, index_price: float, quantity: int,
                    mode: str = "paper", estimated_premium: float = 0,
                    timestamp: Optional[datetime] = None,
                    strike: Optional[int] = None,
                    trade_context: Optional[Dict] = None) -> Optional[Dict]:
        """Buy an ATM option. Returns trade details, or None if nothing was filled."""
        with self._lock:
            try:
                if quantity <= 0:
                    self.logger.order_failed("Refusing to place a zero-quantity order")
                    return None

                contract = self._resolve_contract(index_price, option_type, strike)
                lot_size = contract["lot_size"]
                if quantity % lot_size != 0:
                    quantity = max(lot_size, (quantity // lot_size) * lot_size)

                entry_price = estimated_premium if estimated_premium > 0 else \
                    round(index_price * 0.015, 2)

                required = entry_price * quantity
                margin = self.check_margin(required, mode=mode, log_check=False)
                quantity = self._fit_to_margin(quantity, entry_price, lot_size, margin)
                if quantity <= 0:
                    return None

                order_ids: List[str] = []
                if mode == "live":
                    filled = self._enter_live(contract, quantity)
                    if filled is None:
                        return None
                    order_ids, avg_price, filled_qty = filled
                    entry_price = avg_price
                    quantity = filled_qty
                else:
                    self.logger.info(f"Paper fill: {contract['symbol']} "
                                     f"@ Rs {entry_price} x{quantity}")

                trade_id = insert_trade({
                    "type": option_type,
                    "strike_price": contract["strike"],
                    "trading_symbol": contract["symbol"],
                    "token": contract["token"],
                    "entry_price": entry_price,
                    "quantity": quantity,
                    "lot_size": lot_size,
                    "mode": mode,
                    "underlying_entry_price": index_price,
                    "capital_used": round(entry_price * quantity, 2),
                    "total_capital": margin.get("available"),
                    "entry_order_ids": ",".join(order_ids) if order_ids else None,
                    **(trade_context or {}),
                }, timestamp=timestamp)

                self.logger.order_placed(f"BUY {option_type}", contract["strike"],
                                         entry_price, quantity, mode, timestamp=timestamp)

                return {"trade_id": trade_id, "entry_price": entry_price,
                        "quantity": quantity, "token": contract["token"],
                        "symbol": contract["symbol"], "strike": contract["strike"]}

            except Exception as exc:
                self.logger.error("Order placement failed", exc)
                return None

    def _resolve_contract(self, index_price: float, option_type: str,
                          strike: Optional[int]) -> Dict:
        self.instruments.load_instruments()
        strike = int(strike or self.instruments.get_atm_strike(index_price))
        expiry = self.instruments.get_nearest_expiry()
        info = self.instruments.get_option_info(strike, option_type, expiry)

        if info:
            return {"strike": strike, "symbol": info["symbol"], "token": info["token"],
                    "lot_size": info.get("lot_size") or self.instruments.get_lot_size()}

        # Fall back to configured values so paper/backtest runs still work when
        # the instrument master is unavailable.
        return {
            "strike": strike,
            "symbol": f"NIFTY{strike}{option_type}",
            "token": None,
            "lot_size": int(get_setting("lot_size") or "75"),
        }

    def _fit_to_margin(self, quantity: int, price: float, lot_size: int,
                       margin: Dict) -> int:
        required = price * quantity
        if margin["available"] >= required:
            self.logger.margin_check(margin["available"], required, True)
            return quantity

        cost_per_lot = price * lot_size
        affordable_lots = int(margin["available"] // cost_per_lot) if cost_per_lot > 0 else 0
        min_lots = int(get_setting("min_lots") or "1")

        if affordable_lots < min_lots:
            self.logger.margin_check(margin["available"], cost_per_lot * min_lots, False)
            self.logger.order_failed(
                f"Insufficient margin: need Rs {cost_per_lot * min_lots:,.0f} for "
                f"{min_lots} lot(s), have Rs {margin['available']:,.0f}")
            return 0

        reduced = affordable_lots * lot_size
        self.logger.info(f"Margin trim: {quantity} -> {reduced} units "
                         f"(Rs {margin['available']:,.0f} available)")
        self.logger.margin_check(margin["available"], price * reduced, True)
        return reduced

    def _enter_live(self, contract: Dict, quantity: int
                    ) -> Optional[Tuple[List[str], float, int]]:
        """
        Place the buy, then confirm what actually filled.
        Returns (order_ids, average_fill_price, filled_quantity).
        """
        order_ids, placed_qty = self._execute_sliced(contract["symbol"], contract["token"],
                                                     "BUY", quantity)
        if not order_ids:
            self.logger.order_failed("Entry rejected — no order was accepted")
            return None

        avg_price, filled_qty = self._confirm_fills(order_ids)

        if filled_qty <= 0:
            self.logger.order_failed("Entry orders accepted but nothing filled")
            return None

        if placed_qty < quantity:
            # A slice failed mid-way. Do not carry an unintended position.
            self.logger.error(
                f"Partial entry: {filled_qty}/{quantity} filled. "
                f"Unwinding the filled portion immediately.")
            self._execute_sliced(contract["symbol"], contract["token"], "SELL", filled_qty)
            return None

        if avg_price <= 0:
            self.logger.warning("Fill price unavailable from the order book; "
                                "the trade will be marked at the last traded price")
            avg_price = self._last_price(contract["token"])
            if avg_price <= 0:
                self.logger.order_failed("Cannot determine the entry fill price")
                self._execute_sliced(contract["symbol"], contract["token"], "SELL", filled_qty)
                return None

        return order_ids, round(avg_price, 2), filled_qty

    def _last_price(self, token: Optional[str]) -> float:
        if token and self.data_feed:
            return self.data_feed.get_token_price(token)
        return 0.0

    def _execute_sliced(self, symbol: str, token: str, side: str,
                        quantity: int) -> Tuple[List[str], int]:
        """Place a market order, splitting it across the freeze limit."""
        if not self.smart_api:
            return [], 0

        order_ids: List[str] = []
        remaining = quantity
        placed = 0

        while remaining > 0:
            chunk = min(remaining, MAX_QTY_PER_ORDER)
            order_id = self._place_chunk(symbol, token, side, chunk)
            if order_id is None:
                self.logger.error(f"{side} slice of {chunk} failed after "
                                  f"{ORDER_RETRIES} attempts; stopping")
                break

            order_ids.append(order_id)
            placed += chunk
            remaining -= chunk
            if remaining > 0:
                time.sleep(SLICE_DELAY_SEC)

        return order_ids, placed

    def _place_chunk(self, symbol: str, token: str, side: str,
                     quantity: int) -> Optional[str]:
        params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": side,
            "exchange": "NFO",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": str(quantity),
        }
        for attempt in range(1, ORDER_RETRIES + 1):
            try:
                order_id = self.smart_api.placeOrder(params)
                if order_id:
                    self.logger.info(f"{side} {quantity} {symbol} -> order {order_id}")
                    return str(order_id)
                self.logger.warning(f"{side} attempt {attempt} returned no order id")
            except Exception as exc:
                self.logger.error(f"{side} attempt {attempt} raised: {exc}")
            if attempt < ORDER_RETRIES:
                time.sleep(RETRY_DELAY_SEC)
        return None

    def _confirm_fills(self, order_ids: List[str]) -> Tuple[float, int]:
        """
        Poll the order book until the given orders reach a terminal state.
        Returns (quantity-weighted average fill price, total filled quantity).
        """
        wanted = set(order_ids)
        for attempt in range(FILL_POLL_ATTEMPTS):
            try:
                book = (self.smart_api.orderBook() or {}).get("data") or []
            except Exception as exc:
                self.logger.warning(f"Order book poll failed: {exc}")
                book = []

            total_qty = 0
            notional = 0.0
            pending = False

            for row in book:
                if str(row.get("orderid")) not in wanted:
                    continue
                status = str(row.get("status", "")).lower()
                filled = int(float(row.get("filledshares") or 0))
                avg = float(row.get("averageprice") or 0)

                if status in ("complete", "rejected", "cancelled"):
                    if filled > 0 and avg > 0:
                        total_qty += filled
                        notional += avg * filled
                else:
                    pending = True

            if not pending and total_qty > 0:
                return notional / total_qty, total_qty
            if attempt < FILL_POLL_ATTEMPTS - 1:
                time.sleep(FILL_POLL_DELAY_SEC)

        self.logger.warning("Timed out waiting for fill confirmation")
        return 0.0, 0

    # -------------------------------------------------------------------- exit

    def exit_trade(self, trade_id: int, exit_price: float, reason: str = "manual",
                   mode: str = "paper", timestamp: Optional[datetime] = None,
                   underlying_price: Optional[float] = None) -> float:
        """Close a trade and book the P&L. Returns net P&L."""
        try:
            trade = get_active_trade()
            if not trade or trade["id"] != trade_id:
                self.logger.warning(f"Trade {trade_id} is not open; nothing to exit")
                return 0.0

            exit_order_ids: List[str] = []
            if mode == "live" and self.smart_api:
                exit_order_ids, placed = self._execute_sliced(
                    trade["trading_symbol"], trade.get("token"), "SELL", trade["quantity"])
                if placed < trade["quantity"]:
                    # The book is now out of sync with reality; make it loud.
                    self.logger.error(
                        f"EXIT INCOMPLETE for trade {trade_id}: sold {placed} of "
                        f"{trade['quantity']}. Manual intervention required.")
                if exit_order_ids:
                    avg, filled = self._confirm_fills(exit_order_ids)
                    if avg > 0:
                        exit_price = round(avg, 2)

            pnl = close_trade(trade_id, exit_price, reason, timestamp=timestamp,
                              underlying_exit_price=underlying_price,
                              exit_order_ids=",".join(exit_order_ids) or None)

            self.logger.order_exit(reason, pnl, {
                "trade_id": trade_id, "entry": trade["entry_price"],
                "exit": exit_price, "type": trade["type"],
            }, timestamp=timestamp)
            return pnl

        except Exception as exc:
            self.logger.error(f"Exit failed for trade {trade_id}", exc)
            return 0.0


_order_manager: Optional[OrderManager] = None


def get_order_manager(smart_api=None) -> OrderManager:
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager(smart_api)
    return _order_manager
