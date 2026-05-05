"""
FastAPI Server for the Trading Bot.
Provides REST API endpoints for the Next.js frontend.
Strategy: Supertrend + EMA Crossover + ADX Filter.
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
from indicators import sanitize_nan

# Initialize
init_db()
logger = get_logger()

app = FastAPI(title="Nifty 50 Trading Bot", version="2.0.0")

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow production frontend to connect
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
    return {"status": "ok", "service": "Nifty 50 Trading Bot", "strategy": "Supertrend + EMA"}


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

    return sanitize_nan({
        **price_info,
        "indicators": {
            "ema_short": indicators.get("ema_short"),
            "ema_long": indicators.get("ema_long"),
            "supertrend": indicators.get("supertrend"),
            "supertrend_direction": indicators.get("supertrend_direction"),
            "adx": indicators.get("adx"),
            "phase": indicators.get("phase", "WATCHING"),
            "ready": indicators.get("ready", False),
        }
    })


@app.get("/signal")
async def get_signal():
    """Get current trade signal with strategy confluence data."""
    bot = get_bot()
    phase_data = bot.strategy_phase_data
    indicators = bot.indicators

    return sanitize_nan({
        "signal": bot.current_signal,
        "phase": phase_data.get("phase"),
        "phase_description": phase_data.get("phase_description"),
        "ema_short": indicators.get("ema_short"),
        "ema_long": indicators.get("ema_long"),
        "supertrend": indicators.get("supertrend"),
        "supertrend_direction": indicators.get("supertrend_direction"),
        "adx": indicators.get("adx"),
        "timestamp": get_ist_now().isoformat()
    })


@app.get("/orb")
async def get_orb():
    """Deprecated: Formerly Opening Range Breakout data."""
    return {"status": "deprecated", "message": "Strategy migrated to Supertrend"}




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
        candles = feed.get_all_candles(interval="5minute")
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

        # Calculate indicators for the entire history for chart lines
        from indicators import calculate_ema, calculate_supertrend
        
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        # EMA Lines
        ema9 = calculate_ema(closes, 9)
        ema21 = calculate_ema(closes, 21)
        
        # Supertrend Line
        from indicators import calculate_supertrend_series
        st_data = calculate_supertrend_series(candles, 10, 3)
        st_line = st_data["supertrend"]
        st_dir = st_data["direction"]

        ema9_series = []
        ema21_series = []
        st_series = []

        import math
        for i, c in enumerate(candles):
            if "time" in c:
                if i < len(ema9) and not math.isnan(ema9[i]):
                    ema9_series.append({"time": c["time"], "value": ema9[i]})
                if i < len(ema21) and not math.isnan(ema21[i]):
                    ema21_series.append({"time": c["time"], "value": ema21[i]})
                if i < len(st_line) and not math.isnan(st_line[i]):
                    st_series.append({
                        "time": c["time"], 
                        "value": st_line[i],
                        "color": "#10b981" if st_dir[i] == 1 else "#ef4444"
                    })

        return sanitize_nan({
            "candles": chart_candles,
            "ema9": ema9_series,
            "ema21": ema21_series,
            "supertrend": st_series,
        })
    else:
        return {
            "candles": [],
            "ema9": [],
            "ema21": [],
            "supertrend": [],
        }


@app.get("/trades")
async def trades(mode: str = None, date_from: str = None, date_to: str = None, limit: int = 100):
    from database import get_trades, get_all_time_pnl, get_yearly_summary
    trades = get_trades(mode=mode, date_from=date_from, date_to=date_to, limit=limit)
    summary = get_all_time_pnl(mode=mode, date_from=date_from, date_to=date_to)
    yearly_summary = get_yearly_summary(mode=mode, date_from=date_from, date_to=date_to)
    return {"trades": trades, "summary": summary, "yearly_summary": yearly_summary}



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


@app.get("/logs/margin-failures")
async def get_margin_failures(limit: int = 100):
    """Get logs where margin check failed."""
    logs = logger.get_margin_failures(limit=limit)
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
    print("📊 Strategy: Supertrend + EMA Crossover")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
