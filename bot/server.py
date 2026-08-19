"""
FastAPI server for the ORB trading bot.

Security notes:
  * Set BOT_API_TOKEN to require a bearer token on every state-changing route.
    Live trading refuses to start without it.
  * GET /settings never returns broker credentials in plaintext.
  * CORS defaults to localhost; set BOT_CORS_ORIGINS for anything else.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Dict, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import (
    SECRET_KEYS, clear_trade_data, get_active_trade, get_all_settings,
    get_equity_curve, get_exit_reason_breakdown, get_setting, get_today_pnl,
    get_yearly_pnl,
    get_trades, init_db, save_settings,
)
from indicators import sanitize_nan, session_opening_range
from logger import get_logger
from market_calendar import get_ist_now, is_trading_day, should_bot_run
from trading_bot import get_bot

init_db()
logger = get_logger()

API_TOKEN = os.getenv("BOT_API_TOKEN", "").strip()
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("BOT_CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app = FastAPI(title="NIFTY ORB Trading Bot", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def require_token(authorization: Optional[str] = Header(None),
                  x_api_key: Optional[str] = Header(None)):
    """Guard for state-changing routes. A no-op when no token is configured."""
    if not API_TOKEN:
        return
    supplied = x_api_key or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if supplied.strip() != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or missing API token")


Protected = [Depends(require_token)]


class SettingsRequest(BaseModel):
    settings: Dict[str, str]


class ExitTradeRequest(BaseModel):
    price: Optional[float] = None


# ------------------------------------------------------------------- general

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "NIFTY ORB Trading Bot",
        "strategy": "Opening Range Breakout",
        "auth_required": bool(API_TOKEN),
    }


@app.post("/start", dependencies=Protected)
async def start_bot():
    bot = get_bot()
    if bot.is_running:
        return {"status": "already_running"}

    if bot.mode == "live" and not API_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="Live trading requires BOT_API_TOKEN to be set on the server",
        )

    try:
        # bot.start() is sync and can do I/O — keep the event loop free.
        await asyncio.to_thread(bot.start)
    except Exception as exc:
        logger.error("Bot failed to start", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    _, market_reason = should_bot_run()
    return {"status": "started", "market_status": market_reason}


@app.post("/stop", dependencies=Protected)
async def stop_bot():
    bot = get_bot()
    if not bot.is_running:
        return {"status": "already_stopped"}
    await asyncio.to_thread(bot.stop)
    return {"status": "stopped"}


@app.get("/status")
async def status_endpoint():
    return sanitize_nan(await asyncio.to_thread(get_bot().get_status))


@app.get("/price")
async def price():
    def _price():
        bot = get_bot()
        info = bot.data_feed.get_price_info() if bot.data_feed else {
            "price": 0, "change": 0, "change_pct": 0, "connected": False,
        }
        return sanitize_nan({**info, "strategy": bot.strategy_state})

    return await asyncio.to_thread(_price)


@app.get("/orb")
async def orb_state():
    """Current opening range, phase and any pending breakout levels."""
    return sanitize_nan(await asyncio.to_thread(lambda: get_bot().strategy_state))


@app.get("/candles")
async def candles():
    """1-minute candles for the current session plus the opening range band."""
    def _candles():
        bot = get_bot()
        or_minutes = bot.strategy.config.or_minutes
        if not bot.data_feed:
            return {"candles": [], "orb": None, "or_minutes": or_minutes}

        raw = bot.data_feed.get_all_candles(interval="1minute")
        session_date = bot._session_date
        if session_date:
            raw = [c for c in raw if (c.get("time_key") or "").startswith(session_date)]

        payload = [
            {"time": c["time"], "open": c["open"], "high": c["high"],
             "low": c["low"], "close": c["close"]}
            for c in raw if "time" in c
        ]
        return sanitize_nan({
            "candles": payload,
            "orb": session_opening_range(raw, or_minutes, session_date),
            "or_minutes": or_minutes,
        })

    return await asyncio.to_thread(_candles)


# -------------------------------------------------------------------- trades

@app.get("/trades")
async def trades(mode: Optional[str] = None, date_from: Optional[str] = None,
                 date_to: Optional[str] = None, limit: int = 100):
    from database import get_all_time_pnl

    bot = get_bot()
    now = bot._now()
    as_of = now.strftime("%Y-%m-%d")
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    year_start = now.replace(month=1, day=1).strftime("%Y-%m-%d")

    summary = get_all_time_pnl(mode=mode, date_from=date_from, date_to=date_to)
    month = get_all_time_pnl(mode=mode, date_from=month_start, date_to=as_of)
    year = get_all_time_pnl(mode=mode, date_from=year_start, date_to=as_of)
    summary.update({
        "month_pnl": month["all_time_pnl"],
        "month_trades": month["all_time_trades"],
        "month_label": now.strftime("%b %Y"),
        "year_pnl": year["all_time_pnl"],
        "year_trades": year["all_time_trades"],
        "year_label": str(now.year),
    })

    return sanitize_nan({
        "trades": get_trades(mode=mode, date_from=date_from, date_to=date_to, limit=limit),
        "summary": summary,
    })


@app.get("/trades/active")
async def active_trade():
    bot = get_bot()
    trade = get_active_trade(mode=bot.mode)
    if trade and bot.data_feed:
        index_price = bot.data_feed.current_price
        if index_price > 0:
            current = bot._current_option_price(index_price, bot._now())
            trade["current_price"] = current
            trade["live_pnl"] = round((current - trade["entry_price"]) * trade["quantity"], 2)
    return sanitize_nan({"trade": trade})


@app.post("/exit-trade", dependencies=Protected)
async def exit_trade(req: ExitTradeRequest):
    return get_bot().manual_exit(req.price)


@app.post("/recover-position", dependencies=Protected)
async def recover_position():
    """Re-adopt an open Angel NFO long into the DB after Clear history."""
    bot = get_bot()
    if not bot.is_running:
        raise HTTPException(status_code=409, detail="Start the bot first")
    result = await asyncio.to_thread(bot.adopt_broker_position)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message") or "Recover failed")
    return result


@app.get("/pnl")
async def pnl(mode: Optional[str] = None):
    bot = get_bot()
    override = bot._now().strftime("%Y-%m-%d") if bot.is_playback else None
    return get_today_pnl(mode=mode or bot.mode, date_override=override)


@app.get("/analytics")
async def analytics(mode: Optional[str] = None):
    """Equity curve and exit-reason mix — what the results page renders."""
    bot = get_bot()
    target_mode = mode or bot.mode
    return sanitize_nan({
        "equity_curve": get_equity_curve(mode=target_mode),
        "exit_reasons": get_exit_reason_breakdown(mode=target_mode),
        "yearly_pnl": get_yearly_pnl(mode=target_mode),
    })


# ------------------------------------------------------------------ settings

@app.get("/settings")
async def read_settings():
    """Broker credentials come back masked; they are never sent to the client."""
    return {"settings": get_all_settings(redact_secrets=True),
            "secret_keys": sorted(SECRET_KEYS)}


@app.post("/settings", dependencies=Protected)
async def write_settings(req: SettingsRequest):
    # A masked value means "unchanged" — do not overwrite the real secret.
    incoming = {k: v for k, v in req.settings.items()
                if not (k in SECRET_KEYS and set(v or "") == {"*"})}
    try:
        save_settings(incoming)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    bot = get_bot()
    if bot.is_running:
        bot.reload_config()
        logger.info("Settings changed while running; strategy config reloaded. "
                    "Restart the bot for credential or data-source changes.")

    logged = [k for k in incoming if k not in SECRET_KEYS]
    logger.info(f"Settings updated: {logged}")
    return {"status": "saved"}


@app.post("/clear-data", dependencies=Protected)
async def clear_data():
    bot = get_bot()
    if bot.is_running:
        raise HTTPException(status_code=409, detail="Stop the bot before clearing data")
    open_trade = get_active_trade()
    if open_trade:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot clear history while trade #{open_trade['id']} "
                f"({open_trade.get('trading_symbol')}) is still open. "
                f"Square off / exit first — clearing would orphan the broker position."
            ),
        )
    try:
        if not clear_trade_data():
            raise HTTPException(status_code=500, detail="Failed to clear data")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Reset tracked capital so the dashboard matches a fresh history.
    initial = float(get_setting("initial_capital") or "500000")
    bot.capital = initial
    bot.capital_history = []
    bot._first_trade_date = None
    bot._position = None
    return {"status": "cleared"}


# ---------------------------------------------------------------------- ops

@app.get("/logs")
async def logs(limit: int = 200, category: Optional[str] = None):
    return {"logs": logger.get_recent_logs(limit=limit, category=category)}


@app.get("/margin")
async def margin():
    bot = get_bot()
    if bot.order_manager:
        return bot.order_manager.check_margin(mode=bot.mode, log_check=False)
    return {"available": 0, "mode": "disconnected"}


@app.get("/health")
async def health():
    bot = get_bot()
    now = get_ist_now()
    should_run, reason = should_bot_run(now)
    return {
        "running": bot.is_running,
        "feed_connected": bool(bot.data_feed and bot.data_feed.is_connected),
        "market_open": should_run,
        "market_status": reason,
        "trading_day": is_trading_day(now.date()),
        "time": now.isoformat(),
    }


if __name__ == "__main__":
    if not API_TOKEN:
        print("WARNING: BOT_API_TOKEN is not set — control endpoints are unauthenticated "
              "and live trading is disabled.")
    print(f"CORS origins: {CORS_ORIGINS}")
    print("Starting NIFTY ORB bot API on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
