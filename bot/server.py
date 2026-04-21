"""
FastAPI Server for the Trading Bot.
Provides REST API endpoints for the Next.js frontend.
Strategy: ORB + Fibonacci Pullback + MACD Confirmation.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uvicorn

from trading_bot import get_bot
from data_feed import get_data_feed
from database import (
    get_trades, get_active_trade, get_today_pnl,
    save_settings, get_all_settings, init_db
)
from logger import get_logger
from market_calendar import should_bot_run, is_trading_day, get_ist_now

# Initialize
init_db()
logger = get_logger()

app = FastAPI(title="Nifty 50 Trading Bot", version="2.0.0")

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request Models ---

class SettingsRequest(BaseModel):
    settings: Dict[str, str]

class ExitTradeRequest(BaseModel):
    price: Optional[float] = None


# --- Endpoints ---

@app.get("/")
async def root():
    return {"status": "ok", "service": "Nifty 50 Trading Bot", "strategy": "Natural ORB"}


@app.post("/start")
async def start_bot():
    """Start the trading bot."""
    bot = get_bot()
    if bot.is_running:
        return {"status": "already_running", "message": "Bot is already running"}

    # Check if it's a trading day
    should_run, reason = should_bot_run()
    bot.start()
    logger.bot_status("STARTED", f"Market status: {reason}")

    return {
        "status": "started",
        "message": "Bot started successfully",
        "market_status": reason
    }


@app.post("/stop")
async def stop_bot():
    """Stop the trading bot."""
    bot = get_bot()
    if not bot.is_running:
        return {"status": "already_stopped", "message": "Bot is not running"}

    bot.stop()
    return {"status": "stopped", "message": "Bot stopped successfully"}


@app.get("/status")
async def get_status():
    """Get bot status and today's stats."""
    bot = get_bot()
    status = bot.get_status()

    # Add market info
    should_run, market_reason = should_bot_run()
    status["market_open"] = should_run
    status["market_status"] = market_reason
    status["is_trading_day"] = is_trading_day()

    return status


@app.get("/price")
async def get_price():
    """Get current price and indicator values."""
    bot = get_bot()
    feed = bot.data_feed

    if feed:
        price_info = feed.get_price_info()
    else:
        price_info = {
            "price": 0,
            "prev_price": 0,
            "change": 0,
            "change_pct": 0,
            "connected": False,
            "simulation": True
        }

    indicators = bot.indicators

    return {
        **price_info,
        "indicators": {
            "orb_high": indicators.get("orb_high"),
            "orb_low": indicators.get("orb_low"),
            "orb_range": indicators.get("orb_range"),
            "orb_status": indicators.get("orb_status"),
            "vwap": indicators.get("vwap"),
            "phase": indicators.get("phase", "WATCHING"),
            "ready": indicators.get("ready", False),
        }
    }


@app.get("/signal")
async def get_signal():
    """Get current trade signal with strategy checklist."""
    bot = get_bot()
    phase_data = bot.strategy_phase_data
    indicators = bot.indicators

    current_price = bot.data_feed.current_price if bot.data_feed else 0
    orb_high = indicators.get("orb_high")
    orb_low = indicators.get("orb_low")

    # Determine breakout state
    breakout_dir = "NONE"
    orb_breakout = False
    buffer = float(get_all_settings().get("breakout_buffer", "5"))
    if orb_high and current_price > orb_high + buffer:
        breakout_dir = "UP"
        orb_breakout = True
    elif orb_low and current_price < orb_low - buffer:
        breakout_dir = "DOWN"
        orb_breakout = True

    return {
        "signal": bot.current_signal,
        "phase": phase_data.get("phase"),
        "phase_description": phase_data.get("phase_description"),
        "orb_status": indicators.get("orb_status"),
        "orb_high": orb_high,
        "orb_low": orb_low,
        "orb_range": indicators.get("orb_range"),
        "breakout_direction": breakout_dir,
        "breakout_price": phase_data.get("breakout_price"),
        "breakout_time": phase_data.get("breakout_time"),
        "vwap": phase_data.get("vwap"),
        "vwap_confirms": phase_data.get("vwap_confirms", False),
        "timestamp": get_ist_now().isoformat()
    }


@app.get("/orb")
async def get_orb():
    """Get Opening Range Breakout data."""
    bot = get_bot()
    return bot.orb_api_data




@app.get("/strategy-phase")
async def get_strategy_phase():
    """Get current strategy phase and metadata."""
    bot = get_bot()
    return bot.strategy_phase_data


@app.get("/candles")
async def get_candles():
    """Get 5-minute OHLCV candle data for chart."""
    bot = get_bot()
    feed = bot.data_feed

    if feed:
        candles = feed.get_all_candles()
        chart_candles = [
            {
                "time": c["time"],
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"]
            }
            for c in candles
            if "time" in c
        ]

        indicators = bot.indicators
        orb_high = indicators.get("orb_high")
        orb_low = indicators.get("orb_low")

        orb_high_line = []
        orb_low_line = []

        if orb_high and orb_low:
            for c in candles:
                if "time" in c:
                    orb_high_line.append({"time": c["time"], "value": orb_high})
                    orb_low_line.append({"time": c["time"], "value": orb_low})

        # VWAP line data
        vwap_line = []
        vwap_values = []
        if candles:
            from indicators import calculate_vwap
            vwap_values = calculate_vwap(candles)
            for i, c in enumerate(candles):
                if "time" in c and i < len(vwap_values):
                    vwap_line.append({"time": c["time"], "value": vwap_values[i]})

        return {
            "candles": chart_candles,
            "orb_high": orb_high_line,
            "orb_low": orb_low_line,
            "vwap": vwap_line,
        }
    else:
        return {
            "candles": [],
            "orb_high": [],
            "orb_low": [],
            "vwap": [],
        }


@app.get("/trades")
async def list_trades(mode: Optional[str] = None,
                      date_from: Optional[str] = None,
                      date_to: Optional[str] = None,
                      limit: int = 100):
    """Get trade history."""
    trades = get_trades(mode=mode, date_from=date_from, date_to=date_to, limit=limit)
    return {"trades": trades}


@app.get("/trades/active")
async def active_trade():
    """Get current open trade."""
    trade = get_active_trade()
    if trade:
        bot = get_bot()
        current_index_price = bot.data_feed.current_price if bot.data_feed else 0
        if current_index_price > 0:
            simulated_option_price = bot.calculate_option_price(trade, current_index_price)
            trade["current_price"] = simulated_option_price
            trade["live_pnl"] = round(
                (simulated_option_price - trade["entry_price"]) * trade["quantity"], 2
            )
    return {"trade": trade}


@app.post("/exit-trade")
async def exit_trade(req: ExitTradeRequest):
    """Manually exit the active trade."""
    bot = get_bot()
    result = bot.manual_exit(req.price)
    return result


@app.get("/pnl")
async def pnl_summary(mode: Optional[str] = None):
    """Get today's P&L summary."""
    bot = get_bot()
    date_override = None
    if bot.data_feed and bot.data_feed.playback_file and bot.data_feed.last_tick_time:
        date_override = bot.data_feed.last_tick_time.strftime("%Y-%m-%d")

    return get_today_pnl(mode=mode, date_override=date_override)


@app.post("/settings")
async def update_settings(req: SettingsRequest):
    """Save settings."""
    try:
        save_settings(req.settings)
        logger.info(f"Settings updated: {list(req.settings.keys())}")

        # Check if critical settings were changed while bot is running
        bot = get_bot()
        if bot.is_running and ("trading_mode" in req.settings or "pin" in req.settings or "totp_secret" in req.settings):
            logger.warning("Bot is currently running. Please STOP and START the bot for live mode changes and credentials to take effect.")

        return {"status": "saved", "message": "Settings saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/settings")
async def read_settings():
    """Get all settings."""
    settings = get_all_settings()
    # Mask sensitive fields
    masked = dict(settings)
    for key in ["api_key", "pin", "totp_secret"]:
        if masked.get(key):
            masked[key] = "****" + masked[key][-4:] if len(masked[key]) > 4 else "****"
    return {"settings": masked}


@app.get("/logs")
async def get_logs(limit: int = 200, category: Optional[str] = None):
    """Get recent bot logs."""
    logs = logger.get_recent_logs(limit=limit, category=category)
    return {"logs": logs}


@app.get("/margin")
async def get_margin():
    """Get available margin."""
    bot = get_bot()
    if bot.order_manager:
        margin = bot.order_manager.check_margin()
        return margin
    return {"available": 0, "mode": "disconnected"}


if __name__ == "__main__":
    print("🚀 Starting Nifty 50 Trading Bot Server on port 8000...")
    print("📊 Strategy: Natural Opening Range Breakout")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
