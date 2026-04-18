"""
Technical indicators module.
Calculates ORB, Supertrend, and RSI for trading signals.
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict


def calculate_orb(candles: List[dict], start_time: str = "09:15", end_time: str = "09:30") -> dict:
    """
    Calculate the Opening Range Breakout levels.
    Finds the high and low between the specified start and end time (IST).
    
    candles: List of 1-minute OHLCV dicts.
    Returns: {orb_high, orb_low, orb_range, orb_status}
    """
    if not candles:
        return {"orb_high": None, "orb_low": None, "orb_range": None, "orb_status": "BUILDING"}

    # Filter candles within the window
    window_candles = []
    for c in candles:
        # Assuming c['time'] is 'HH:MM' or contains it
        # DataFeed format for time is typically 'HH:MM:SS'
        time_part = c.get("time_str", "") or ""
        if not time_part:
            # Fallback to parsing from datetime if available
            pass 
        
        # Simplified for now: assuming candles are 1-min and sorted
        # We find candles where time >= start_time and time < end_time
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


def calculate_supertrend(ohlcv_data: List[dict], period: int = 7, multiplier: float = 3.0) -> List[dict]:
    """
    Calculate Supertrend indicator using ATR.
    Returns a list of dicts: {'value': float, 'direction': 'UP'|'DOWN'}
    """
    if len(ohlcv_data) < period:
        return [{"value": None, "direction": "NEUTRAL"}] * len(ohlcv_data)

    df = pd.DataFrame(ohlcv_data)
    
    # ATR calculation
    high_low = df['high'] - df['low']
    high_pc = (df['high'] - df['close'].shift()).abs()
    low_pc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    # Basic Upper and Lower Bands
    hl2 = (df['high'] + df['low']) / 2
    final_ub = hl2 + (multiplier * atr)
    final_lb = hl2 - (multiplier * atr)

    # Supertrend logic
    supertrend = [0.0] * len(df)
    direction = [1] * len(df) # 1 for UP, -1 for DOWN

    for i in range(1, len(df)):
        # Final Upper Band
        if final_ub[i] < final_ub[i-1] or df['close'][i-1] > final_ub[i-1]:
            final_ub.at[i] = final_ub[i]
        else:
            final_ub.at[i] = final_ub[i-1]

        # Final Lower Band
        if final_lb[i] > final_lb[i-1] or df['close'][i-1] < final_lb[i-1]:
            final_lb.at[i] = final_lb[i]
        else:
            final_lb.at[i] = final_lb[i-1]

        # Trend direction
        if df['close'][i] > final_ub[i-1]:
            direction[i] = 1
        elif df['close'][i] < final_lb[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and final_lb[i] < final_lb[i-1]:
                final_lb.at[i] = final_lb[i-1]
            if direction[i] == -1 and final_ub[i] > final_ub[i-1]:
                final_ub.at[i] = final_ub[i-1]

        # Supertrend value
        if direction[i] == 1:
            supertrend[i] = final_lb[i]
        else:
            supertrend[i] = final_ub[i]

    results = []
    for i in range(len(df)):
        results.append({
            "value": round(supertrend[i], 2) if supertrend[i] != 0 else None,
            "direction": "UP" if direction[i] == 1 else "DOWN"
        })
    
    return results


def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    Calculate Relative Strength Index.
    Returns list of RSI values (same length as prices).
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


def get_latest_indicators(candles: List[dict], settings: dict) -> dict:
    """
    Calculate all indicators for the ORB + Supertrend + RSI strategy.
    """
    if not candles:
        return {"ready": False}

    # Extract parameters from settings
    st_period = int(settings.get("supertrend_period", 7))
    st_multiplier = float(settings.get("supertrend_multiplier", 3.0))
    rsi_period = int(settings.get("rsi_period", 14))

    # We need 1-min candles for ORB, and can use them for Supertrend/RSI too
    # Assuming 'candles' passed here are the ones used for strategy checks (typically 5-min or 1-min)
    close_prices = [c["close"] for c in candles]
    
    supertrend_data = calculate_supertrend(candles, st_period, st_multiplier)
    rsi_data = calculate_rsi(close_prices, rsi_period)
    
    latest_st = supertrend_data[-1]
    latest_rsi = rsi_data[-1]

    return {
        "supertrend_value": latest_st["value"],
        "supertrend_direction": latest_st["direction"],
        "rsi": round(latest_rsi, 2) if not np.isnan(latest_rsi) else None,
        "ready": len(candles) >= max(st_period, rsi_period)
    }
