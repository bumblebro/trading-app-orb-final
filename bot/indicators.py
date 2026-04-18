"""
Technical indicators module.
Calculates ORB, Fibonacci levels, MACD, and RSI for the
ORB + Fibonacci Pullback + MACD Confirmation strategy.
"""

import numpy as np
from typing import List, Optional, Dict


def calculate_orb(candles: List[dict], start_time: str = "09:15", end_time: str = "09:30") -> dict:
    """
    Calculate the Opening Range Breakout levels for the CURRENT day.
    Finds the high and low between the specified start and end time (IST) 
    only for the most recent date in the candles list.

    candles: List of 1-minute OHLCV dicts.
    Returns: {orb_high, orb_low, orb_range, orb_status}
    """
    if not candles:
        return {"orb_high": None, "orb_low": None, "orb_range": None, "orb_status": "BUILDING"}

    # Identify the latest date in the list to avoid mixing multi-day data
    dates = [c.get("time_key", "").split(" ")[0] for c in candles if c.get("time_key")]
    if not dates:
        return {"orb_high": None, "orb_low": None, "orb_range": None, "orb_status": "BUILDING"}
    
    latest_date = max(dates)

    # Filter candles within the window for the latest date only
    window_candles = []
    for c in candles:
        time_key = c.get("time_key", "")
        if not time_key or not time_key.startswith(latest_date):
            continue
            
        time_part = c.get("time_str", "")
        if start_time <= time_part < end_time:
            window_candles.append(c)

    if not window_candles:
        return {"orb_high": None, "orb_low": None, "orb_range": None, "orb_status": "BUILDING"}

    highs = [c["high"] for c in window_candles]
    lows = [c["low"] for c in window_candles]

    orb_high = max(highs)
    orb_low = min(lows)
    orb_range = round(orb_high - orb_low, 2)

    return {
        "orb_high": orb_high,
        "orb_low": orb_low,
        "orb_range": orb_range,
        "orb_status": "READY"
    }


def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    Calculate Relative Strength Index.
    Returns list of RSI values (same length as prices).
    Used as optional confirmation filter.
    """
    if len(prices) < period + 1:
        return [float('nan')] * len(prices)

    rsi_values = [float('nan')] * period

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))

    for i in range(period, len(deltas)):
        gain = max(deltas[i], 0)
        loss = abs(min(deltas[i], 0))

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


def get_latest_indicators(candles: List[dict]) -> dict:
    """
    Calculate only ORB indicators for the Natural ORB strategy.
    """
    if not candles:
        return {"orb_status": "BUILDING", "ready": False}

    orb_results = calculate_orb(candles)
    
    return {
        "orb_high": orb_results["orb_high"],
        "orb_low": orb_results["orb_low"],
        "orb_range": orb_results["orb_range"],
        "orb_status": orb_results["orb_status"],
        "ready": True
    }
