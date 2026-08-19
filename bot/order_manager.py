"""
Order placement and exit for NIFTY options.

Paper mode books a simulated fill at the theoretical premium. Live mode routes
LIMIT orders through Angel One SmartAPI (MARKET is blocked for algo APIs since
Apr 2026), slicing above the exchange freeze quantity, and then *verifies* the
fill from the order book instead of assuming the requested price. If part of a
sliced entry fails, the filled portion is sold back immediately rather than
left as an unintended position. Live exits escalate: normal pad → 1.5x →
force LIMIT (~8% of LTP) → last-resort MARKET (Angel MPP).
"""

from __future__ import annotations

import math
import re
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
FILL_POLL_ATTEMPTS = 8
FILL_POLL_DELAY_SEC = 0.5
# NIFTY option tick; used to round LIMIT prices.
OPTION_TICK = 0.05
# Adaptive pads: scale with premium + lots; entry/exit caps differ (exits need room).
# 1-lot ~₹55 → entry ~₹0.20–0.25, exit ~₹0.50–0.55.
ENTRY_PAD_MIN = 0.20
ENTRY_PAD_PCT = 0.004          # 0.4% of LTP
ENTRY_PAD_PER_EXTRA_LOT = 0.05
ENTRY_PAD_CAP_PCT = 0.03       # entry never exceeds 3% of LTP
EXIT_PAD_MIN = 0.50
EXIT_PAD_PCT = 0.010           # 1.0% of LTP
EXIT_PAD_PER_EXTRA_LOT = 0.10
EXIT_PAD_CAP_PCT = 0.06        # normal/1.5x exit attempts
FORCE_EXIT_PAD_PCT = 0.08      # tier-3 "must exit" LIMIT (ignore lot formula)
_LPP_PRICE_RE = re.compile(r"<\s*([0-9]+(?:\.[0-9]+)?)\s*>")


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
                          "sufficient": available >= required, "mode": "paper",
                          "ok": True}
            else:
                response = self.smart_api.rmsLimit() or {}
                data = response.get("data") or {}
                # Stale/expired sessions often return status=false or empty data.
                # Do not treat that as a real ₹0 balance.
                raw = data.get("availablecash")
                if raw is None or raw == "":
                    raw = data.get("net")
                api_ok = bool(response.get("status")) and raw is not None and raw != ""
                if not api_ok:
                    message = response.get("message") or "RMS limit unavailable"
                    self.logger.warning(f"Angel RMS failed: {message}")
                    return {"available": 0, "required": required,
                            "sufficient": False, "mode": "error", "ok": False,
                            "message": message}
                available = float(raw)
                result = {"available": available, "required": required,
                          "sufficient": available >= required, "mode": "live",
                          "ok": True}

            if log_check:
                self.logger.margin_check(result["available"], required, result["sufficient"])
            return result
        except Exception as exc:
            self.logger.error("Margin check failed", exc)
            return {"available": 0, "required": required, "sufficient": False,
                    "mode": "error", "ok": False}

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
                estimated_entry = round(float(entry_price), 2)

                required = entry_price * quantity
                margin = self.check_margin(required, mode=mode, log_check=False)
                quantity = self._fit_to_margin(quantity, entry_price, lot_size, margin)
                if quantity <= 0:
                    return None

                order_ids: List[str] = []
                if mode == "live":
                    # Slip baseline = live option LTP just before the order
                    # (not BS), so pad/fill quality is measured correctly.
                    pre_ltp = self._fetch_ltp(contract["symbol"], contract.get("token"))
                    if pre_ltp > 0:
                        estimated_entry = round(pre_ltp, 2)
                    filled = self._enter_live(contract, quantity,
                                              hint_price=estimated_entry)
                    if filled is None:
                        return None
                    order_ids, avg_price, filled_qty = filled
                    entry_price = avg_price
                    quantity = filled_qty
                else:
                    self.logger.info(f"Paper fill: {contract['symbol']} "
                                     f"@ Rs {entry_price} x{quantity}")

                # Long options: entry slip > 0 means we paid above the pre-order mark.
                entry_slip = round((float(entry_price) - estimated_entry) * quantity, 2)

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
                    "estimated_entry_price": estimated_entry,
                    "entry_slippage": entry_slip,
                    "entry_order_ids": ",".join(order_ids) if order_ids else None,
                    **(trade_context or {}),
                }, timestamp=timestamp)

                if mode == "live" and abs(entry_slip) >= 0.01:
                    self.logger.info(
                        f"Entry slip Rs {entry_slip:+,.2f} "
                        f"(est {estimated_entry} → fill {entry_price})"
                    )

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

    def _enter_live(self, contract: Dict, quantity: int,
                    hint_price: float = 0.0
                    ) -> Optional[Tuple[List[str], float, int]]:
        """
        Place the buy, then confirm what actually filled.
        Returns (order_ids, average_fill_price, filled_quantity).
        """
        order_ids, placed_qty = self._execute_sliced(
            contract["symbol"], contract["token"], "BUY", quantity,
            hint_price=hint_price,
        )
        if not order_ids:
            self.logger.order_failed("Entry rejected — no order was accepted")
            return None

        avg_price, filled_qty = self._confirm_fills(order_ids)

        # Don't leave a DAY LIMIT resting for hours — cancel anything still open.
        if filled_qty < quantity:
            self._cancel_orders(order_ids)
            avg_price, filled_qty = self._confirm_fills(order_ids, attempts=3)

        if filled_qty <= 0:
            self.logger.order_failed(
                "Entry missed — limit not filled in time; pending orders cancelled"
            )
            return None

        if filled_qty < quantity:
            # A slice failed mid-way. Do not carry an unintended position.
            self.logger.error(
                f"Partial entry: {filled_qty}/{quantity} filled. "
                f"Unwinding the filled portion immediately.")
            self._execute_sliced(contract["symbol"], contract["token"], "SELL",
                                 filled_qty, hint_price=avg_price or hint_price)
            return None

        if avg_price <= 0:
            self.logger.warning("Fill price unavailable from the order book; "
                                "the trade will be marked at the last traded price")
            avg_price = self._last_price(contract["token"])
            if avg_price <= 0:
                self.logger.order_failed("Cannot determine the entry fill price")
                self._execute_sliced(contract["symbol"], contract["token"], "SELL",
                                     filled_qty, hint_price=hint_price)
                return None

        return order_ids, round(avg_price, 2), filled_qty

    def _last_price(self, token: Optional[str]) -> float:
        if token and self.data_feed:
            return self.data_feed.get_token_price(token)
        return 0.0

    def _fetch_ltp(self, symbol: str, token: Optional[str]) -> float:
        """Prefer websocket LTP; fall back to Angel ltpData REST."""
        last = self._last_price(token)
        if last > 0:
            return last
        if not (self.smart_api and symbol and token):
            return 0.0
        try:
            resp = self.smart_api.ltpData("NFO", symbol, str(token)) or {}
            if not resp.get("status"):
                self.logger.warning(f"ltpData failed for {symbol}: {resp}")
                return 0.0
            data = resp.get("data") or {}
            for key in ("ltp", "Ltp", "lastPrice", "lasttradeprice"):
                if data.get(key) is not None:
                    return float(data[key])
        except Exception as exc:
            self.logger.warning(f"ltpData raised for {symbol}: {exc}")
        return 0.0

    def _limit_pad(self, side: str, ref: float, quantity: int,
                   pad_mult: float = 1.0, force_exit: bool = False) -> float:
        """
        Rupee cushion around LTP.
        Scales with premium and lots; entry/exit caps differ.
        force_exit: tier-3 pad = FORCE_EXIT_PAD_PCT of LTP (must-get-flat).
        """
        if force_exit and side == "SELL":
            pad = max(EXIT_PAD_MIN, ref * FORCE_EXIT_PAD_PCT)
            ticks = max(1, int(math.ceil(pad / OPTION_TICK - 1e-9)))
            return round(ticks * OPTION_TICK, 2)

        lot_size = int(get_setting("lot_size") or "65")
        lots = max(float(quantity) / max(lot_size, 1), 1.0)
        extra_lots = max(lots - 1.0, 0.0)

        if side == "BUY":
            pad = max(ENTRY_PAD_MIN, ref * ENTRY_PAD_PCT)
            pad += extra_lots * ENTRY_PAD_PER_EXTRA_LOT
            cap_pct = ENTRY_PAD_CAP_PCT
            floor = ENTRY_PAD_MIN
        else:
            pad = max(EXIT_PAD_MIN, ref * EXIT_PAD_PCT)
            pad += extra_lots * EXIT_PAD_PER_EXTRA_LOT
            cap_pct = EXIT_PAD_CAP_PCT
            floor = EXIT_PAD_MIN

        pad *= max(pad_mult, 1.0)
        pad = min(pad, max(ref * cap_pct, floor))
        ticks = max(1, int(math.ceil(pad / OPTION_TICK - 1e-9)))
        return round(ticks * OPTION_TICK, 2)

    def _limit_price(self, side: str, symbol: str, token: Optional[str],
                     hint_price: float = 0.0, quantity: int = 0,
                     pad_mult: float = 1.0, force_exit: bool = False
                     ) -> Optional[float]:
        """Build a marketable LIMIT from live LTP (estimate only as last resort)."""
        ref = self._fetch_ltp(symbol, token)
        source = "ltp"
        if ref <= 0:
            ref = float(hint_price or 0)
            source = "estimate"
        if ref <= 0:
            return None

        pad = self._limit_pad(
            side, ref, quantity or int(get_setting("lot_size") or "65"),
            pad_mult=pad_mult, force_exit=force_exit,
        )
        if side == "BUY":
            raw = ref + pad
            stepped = math.ceil(raw / OPTION_TICK) * OPTION_TICK
        else:
            raw = ref - pad
            stepped = math.floor(raw / OPTION_TICK) * OPTION_TICK
        price = max(round(stepped, 2), OPTION_TICK)
        tag = "FORCE " if force_exit else ""
        self.logger.info(
            f"{tag}LIMIT {side} {symbol}: ref={ref:.2f} ({source}) pad={pad:.2f} "
            f"qty={quantity} -> {price:.2f}"
        )
        return price

    @staticmethod
    def _parse_lpp_bound(message: str) -> Optional[float]:
        if not message:
            return None
        match = _LPP_PRICE_RE.search(message)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _execute_sliced(self, symbol: str, token: str, side: str,
                        quantity: int, hint_price: float = 0.0,
                        pad_mult: float = 1.0, force_exit: bool = False,
                        use_market: bool = False
                        ) -> Tuple[List[str], int]:
        """Place LIMIT (or last-resort MARKET) orders, splitting across freeze."""
        if not self.smart_api:
            return [], 0

        order_ids: List[str] = []
        remaining = quantity
        placed = 0

        while remaining > 0:
            chunk = min(remaining, MAX_QTY_PER_ORDER)
            order_id = self._place_chunk(
                symbol, token, side, chunk,
                hint_price=hint_price, pad_mult=pad_mult,
                force_exit=force_exit, use_market=use_market,
            )
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
                     quantity: int, hint_price: float = 0.0,
                     pad_mult: float = 1.0, force_exit: bool = False,
                     use_market: bool = False) -> Optional[str]:
        # Prefer LIMIT. MARKET is last-resort only — Angel converts via MPP.
        limit_price: Optional[float] = None
        if not use_market:
            limit_price = self._limit_price(
                side, symbol, token, hint_price=hint_price,
                quantity=quantity, pad_mult=pad_mult, force_exit=force_exit,
            )
            if limit_price is None:
                self.logger.error(
                    f"Cannot place {side} LIMIT for {symbol}: no LTP/estimate price")
                return None

        for attempt in range(1, ORDER_RETRIES + 1):
            if use_market:
                params = {
                    "variety": "NORMAL",
                    "tradingsymbol": symbol,
                    "symboltoken": str(token) if token is not None else "",
                    "transactiontype": side,
                    "exchange": "NFO",
                    "ordertype": "MARKET",
                    "producttype": "INTRADAY",
                    "duration": "DAY",
                    "price": "0",
                    "squareoff": "0",
                    "stoploss": "0",
                    "quantity": str(quantity),
                }
                price_label = "MARKET"
            else:
                params = {
                    "variety": "NORMAL",
                    "tradingsymbol": symbol,
                    "symboltoken": str(token) if token is not None else "",
                    "transactiontype": side,
                    "exchange": "NFO",
                    "ordertype": "LIMIT",
                    "producttype": "INTRADAY",
                    "duration": "DAY",
                    "price": str(limit_price),
                    "squareoff": "0",
                    "stoploss": "0",
                    "quantity": str(quantity),
                }
                price_label = str(limit_price)
            try:
                # Full response so Angel's message/errorcode reaches our logs.
                place = getattr(self.smart_api, "placeOrderFullResponse", None)
                response = place(dict(params)) if callable(place) else None
                order_id = None
                if response is None and not callable(place):
                    order_id = self.smart_api.placeOrder(dict(params))
                    if not order_id:
                        self.logger.warning(
                            f"{side} attempt {attempt} returned no order id "
                            f"for {symbol} @ {price_label}"
                        )
                elif isinstance(response, dict):
                    data = response.get("data") or {}
                    if response.get("status") and isinstance(data, dict):
                        order_id = data.get("orderid")
                    if not order_id:
                        message = str(response.get("message") or "")
                        self.logger.error(
                            f"{side} attempt {attempt} rejected for {symbol} "
                            f"@ {price_label}: {response}"
                        )
                        # Exchange Limit Price Protection — retry inside the band.
                        if (not use_market and limit_price is not None
                                and response.get("errorcode") == "AB1007"):
                            bound = self._parse_lpp_bound(message)
                            if bound and bound > 0:
                                if side == "BUY":
                                    limit_price = max(
                                        round(math.floor(bound / OPTION_TICK) * OPTION_TICK, 2),
                                        OPTION_TICK,
                                    )
                                else:
                                    limit_price = max(
                                        round(math.ceil(bound / OPTION_TICK) * OPTION_TICK, 2),
                                        OPTION_TICK,
                                    )
                                self.logger.info(
                                    f"Retrying inside LPP band @ {limit_price}"
                                )
                                continue
                else:
                    self.logger.error(
                        f"{side} attempt {attempt} unexpected response: {response!r}"
                    )

                if order_id:
                    self.logger.info(
                        f"{side} {quantity} {symbol} {price_label} -> order {order_id}"
                    )
                    return str(order_id)
            except Exception as exc:
                self.logger.error(f"{side} attempt {attempt} raised: {exc}")
            if attempt < ORDER_RETRIES:
                time.sleep(RETRY_DELAY_SEC)
        return None

    def _attempt_live_exit(self, symbol: str, token: Optional[str], quantity: int,
                           hint_price: float = 0.0, pad_mult: float = 1.0,
                           force_exit: bool = False, use_market: bool = False
                           ) -> Tuple[List[str], float, int]:
        """Place sell, wait for fill, cancel leftovers. Returns (ids, avg, filled)."""
        order_ids, _ = self._execute_sliced(
            symbol, token, "SELL", quantity, hint_price=hint_price,
            pad_mult=pad_mult, force_exit=force_exit, use_market=use_market,
        )
        if not order_ids:
            return [], 0.0, 0

        avg, filled = self._confirm_fills(order_ids)
        if filled < quantity:
            self._cancel_orders(order_ids)
            avg, filled = self._confirm_fills(order_ids, attempts=3)
        return order_ids, avg, filled

    def _cancel_orders(self, order_ids: List[str]) -> None:
        """Cancel resting LIMIT orders so they cannot fill hours later unmanaged."""
        if not self.smart_api or not order_ids:
            return
        for order_id in order_ids:
            try:
                resp = self.smart_api.cancelOrder(str(order_id), "NORMAL")
                self.logger.info(f"Cancelled order {order_id}: {resp}")
            except Exception as exc:
                self.logger.warning(f"Cancel failed for order {order_id}: {exc}")

    def _confirm_fills(self, order_ids: List[str],
                       attempts: int = FILL_POLL_ATTEMPTS) -> Tuple[float, int]:
        """
        Poll the order book until the given orders reach a terminal state.
        Returns (quantity-weighted average fill price, total filled quantity).
        On timeout, returns whatever quantity has filled so far (may be 0).
        """
        wanted = set(str(oid) for oid in order_ids)
        best_qty = 0
        best_notional = 0.0

        for attempt in range(attempts):
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

                if filled > 0 and avg > 0:
                    total_qty += filled
                    notional += avg * filled

                if status not in ("complete", "rejected", "cancelled"):
                    pending = True

            if total_qty > best_qty:
                best_qty = total_qty
                best_notional = notional

            if not pending:
                if total_qty > 0 and notional > 0:
                    return notional / total_qty, total_qty
                return 0.0, 0

            if attempt < attempts - 1:
                time.sleep(FILL_POLL_DELAY_SEC)

        self.logger.warning("Timed out waiting for fill confirmation")
        if best_qty > 0 and best_notional > 0:
            return best_notional / best_qty, best_qty
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
            # Mark before live fill — used to measure exit slippage.
            estimated_exit = round(float(exit_price), 2) if exit_price else None
            if mode == "live" and self.smart_api:
                symbol = trade["trading_symbol"]
                token = trade.get("token")
                qty = int(trade["quantity"])
                hint = estimated_exit or 0.0
                filled = 0
                notional = 0.0
                all_order_ids: List[str] = []

                def _accumulate(ids: List[str], avg: float, got: int) -> None:
                    nonlocal filled, notional, all_order_ids
                    if ids:
                        all_order_ids.extend(ids)
                    if got > 0 and avg > 0:
                        notional += avg * got
                        filled += got

                remaining = qty

                # Tier 1: normal adaptive exit pad.
                ids, avg, got = self._attempt_live_exit(
                    symbol, token, remaining, hint_price=hint,
                )
                _accumulate(ids, avg, got)
                remaining = qty - filled

                # Tier 2: wider pad (1.5x), still under EXIT_PAD_CAP_PCT.
                if remaining > 0:
                    self.logger.warning(
                        f"Exit LIMIT missed for trade {trade_id}; "
                        f"retrying {remaining} with 1.5x pad"
                    )
                    ids, avg, got = self._attempt_live_exit(
                        symbol, token, remaining, hint_price=hint, pad_mult=1.5,
                    )
                    _accumulate(ids, avg, got)
                    remaining = qty - filled

                # Tier 3: must-exit LIMIT at FORCE_EXIT_PAD_PCT of LTP.
                if remaining > 0:
                    self.logger.warning(
                        f"Exit still open for trade {trade_id}; "
                        f"FORCE LIMIT {remaining} at {FORCE_EXIT_PAD_PCT:.0%} of LTP"
                    )
                    ids, avg, got = self._attempt_live_exit(
                        symbol, token, remaining, hint_price=hint, force_exit=True,
                    )
                    _accumulate(ids, avg, got)
                    remaining = qty - filled

                # Tier 4: MARKET (Angel MPP) — last resort to get flat.
                if remaining > 0:
                    self.logger.warning(
                        f"FORCE LIMIT missed for trade {trade_id}; "
                        f"last-resort MARKET {remaining} (Angel MPP)"
                    )
                    ids, avg, got = self._attempt_live_exit(
                        symbol, token, remaining, hint_price=hint, use_market=True,
                    )
                    _accumulate(ids, avg, got)
                    remaining = qty - filled

                exit_order_ids = all_order_ids

                if remaining > 0:
                    self.logger.error(
                        f"ALERT EXIT INCOMPLETE trade {trade_id}: sold {filled} of "
                        f"{qty}. All exit tiers failed — MANUAL SQUARE-OFF NOW. "
                        f"Position still open at broker."
                    )
                    try:
                        from notify import notify_exit_incomplete
                        notify_exit_incomplete(
                            trade_id, filled, qty, symbol=symbol or "",
                        )
                    except Exception:
                        pass
                    return 0.0

                if filled > 0 and notional > 0:
                    exit_price = round(notional / filled, 2)

            pnl = close_trade(trade_id, exit_price, reason, timestamp=timestamp,
                              underlying_exit_price=underlying_price,
                              exit_order_ids=",".join(exit_order_ids) or None,
                              estimated_exit_price=estimated_exit)

            if mode == "live" and estimated_exit and estimated_exit > 0:
                exit_slip = round((estimated_exit - float(exit_price)) * trade["quantity"], 2)
                if abs(exit_slip) >= 0.01:
                    self.logger.info(
                        f"Exit slip Rs {exit_slip:+,.2f} "
                        f"(est {estimated_exit} → fill {exit_price})"
                    )

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
