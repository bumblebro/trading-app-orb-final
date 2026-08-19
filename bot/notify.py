"""
Free personal WhatsApp alerts via CallMeBot.

Setup (one-time on your phone):
  1. Add +34 694 29 84 96 as a contact
  2. WhatsApp them: I allow callmebot to send me messages
  3. Save the APIKEY they reply with into Settings

Only for personal use. Official WhatsApp Business API is paid.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from database import get_setting
from logger import get_logger

_CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
_TIMEOUT_SEC = 12


def _enabled() -> bool:
    return (get_setting("whatsapp_enabled") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _phone() -> str:
    raw = (get_setting("whatsapp_phone") or "").strip().replace(" ", "").replace("-", "")
    if raw.startswith("+"):
        raw = raw[1:]
    return raw


def _apikey() -> str:
    return (get_setting("whatsapp_apikey") or "").strip()


def send_whatsapp(message: str, *, force: bool = False) -> dict:
    """
    Send a WhatsApp text via CallMeBot. Non-blocking callers should use notify().
    Returns {ok, message/detail}.
    """
    log = get_logger()
    if not force and not _enabled():
        return {"ok": False, "message": "WhatsApp alerts disabled"}

    phone = _phone()
    apikey = _apikey()
    if not phone or not apikey:
        return {"ok": False, "message": "Set whatsapp_phone and whatsapp_apikey in Settings"}

    text = (message or "").strip()
    if not text:
        return {"ok": False, "message": "Empty message"}

    query = urllib.parse.urlencode({
        "phone": phone,
        "text": text,
        "apikey": apikey,
        "source": "nifty-orb",
    })
    url = f"{_CALLMEBOT_URL}?{query}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:300]
            ok = 200 <= resp.status < 300
            if ok:
                log.info(f"WhatsApp sent ({len(text)} chars)")
            else:
                log.warning(f"WhatsApp HTTP {resp.status}: {body}")
            return {"ok": ok, "message": body or f"HTTP {resp.status}"}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        log.warning(f"WhatsApp HTTPError {exc.code}: {detail}")
        return {"ok": False, "message": detail or str(exc)}
    except Exception as exc:
        log.warning(f"WhatsApp send failed: {exc}")
        return {"ok": False, "message": str(exc)}


def notify(message: str) -> None:
    """Fire-and-forget WhatsApp (daemon thread). Never raises to callers."""
    if not _enabled():
        return

    def _run():
        try:
            send_whatsapp(message)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="whatsapp-notify").start()


def notify_entry(option_type: str, strike, entry_price: float, qty: int,
                 index_price: float = 0, stop: float = 0, target: float = 0) -> None:
    lines = [
        f"*ORB ENTRY* {option_type} {strike}",
        f"Fill Rs {entry_price:.2f} x{qty}",
    ]
    if index_price:
        lines.append(f"Index {index_price:.2f}")
    if stop:
        lines.append(f"Stop {stop:.2f}")
    if target:
        lines.append(f"Target {target:.2f}")
    notify("\n".join(lines))


def notify_exit(reason: str, option_price: float, pnl: float,
                index_price: float = 0) -> None:
    sign = "+" if pnl >= 0 else ""
    lines = [
        f"*ORB EXIT* [{reason}]",
        f"@ Rs {option_price:.2f}",
        f"Net P&L Rs {sign}{pnl:,.2f}",
    ]
    if index_price:
        lines.append(f"Index {index_price:.2f}")
    notify("\n".join(lines))


def notify_exit_incomplete(trade_id: int, filled: int, qty: int,
                           symbol: str = "") -> None:
    notify(
        "*ALERT EXIT INCOMPLETE*\n"
        f"Trade #{trade_id} {symbol}\n"
        f"Sold {filled} of {qty}\n"
        "MANUAL SQUARE-OFF NOW",
    )


def notify_kill_switch(today_pnl: float) -> None:
    notify(f"*KILL SWITCH*\nDaily loss limit hit\nToday P&L Rs {today_pnl:,.2f}")


def notify_adopted(symbol: str, entry_price: float, qty: int) -> None:
    notify(
        f"*RECOVERED POSITION*\n{symbol}\n"
        f"@ Rs {entry_price:.2f} x{qty}\nResuming management"
    )


def notify_test() -> dict:
    """Synchronous test used by the Settings UI."""
    return send_whatsapp(
        "*ORB bot test*\nWhatsApp alerts are working.",
        force=True,
    )
