"""
Technical indicators module.
Calculates ORB, VWAP, and RSI for the
ORB + VWAP Confirmation strategy.
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


def calculate_vwap(candles: List[dict]) -> List[float]:
    """
    Calculate Volume Weighted Average Price.
    VWAP = Σ(Typical Price × Volume) / Σ(Volume)
    where Typical Price = (High + Low + Close) / 3.
    Resets at the start of each trading day (based on date in candle data).

    candles: list of dicts with keys: high, low, close, volume (and optionally time_key)
    Returns list of VWAP values (same length as candles).
    """
    if not candles:
        return []

    vwap_values = []
    cumulative_tp_vol = 0.0
    cumulative_vol = 0.0
    current_date = None

    for candle in candles:
        # Detect day change and reset accumulators
        candle_date = candle.get("time_key", "").split(" ")[0] if candle.get("time_key") else None
        if candle_date and candle_date != current_date:
            cumulative_tp_vol = 0.0
            cumulative_vol = 0.0
            current_date = candle_date

        # Typical Price = (High + Low + Close) / 3
        typical_price = (candle["high"] + candle["low"] + candle["close"]) / 3
        volume = candle.get("volume", 1)  # Default volume if not available

        cumulative_tp_vol += typical_price * volume
        cumulative_vol += volume

        if cumulative_vol > 0:
            vwap = cumulative_tp_vol / cumulative_vol
        else:
            vwap = typical_price

        vwap_values.append(round(vwap, 2))

    return vwap_values


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


def calculate_atr(candles: List[dict], period: int = 14) -> List[float]:
    """
    Calculate Average True Range.
    TR = max(High-Low, abs(High-PrevClose), abs(Low-PrevClose))
    ATR = Simple Moving Average of TR.
    """
    if len(candles) < period + 1:
        return [float('nan')] * len(candles)

    tr_values = [candles[0]['high'] - candles[0]['low']]
    for i in range(1, len(candles)):
        h = candles[i]['high']
        l = candles[i]['low']
        pc = candles[i-1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_values.append(tr)

    # Simple ATR using SMA of TR
    atr_values = [float('nan')] * (period - 1)
    for i in range(period - 1, len(tr_values)):
        atr = sum(tr_values[i - period + 1:i + 1]) / period
        atr_values.append(round(atr, 2))

    return atr_values


def get_candle_strength(candles: List[dict], window: int = 3) -> Dict:
    """
    Compare current candle body vs average of previous 'window' bodies.
    Body = abs(Open - Close)
    """
    if len(candles) < window + 1:
        return {"current_body": 0, "avg_body": 0, "strength_pass": False}

    bodies = [abs(c['open'] - c['close']) for c in candles]
    current_body = bodies[-1]
    prev_bodies = bodies[-(window+1):-1]
    avg_prev_body = sum(prev_bodies) / window

    return {
        "current_body": round(current_body, 2),
        "avg_body": round(avg_prev_body, 2),
        "strength_pass": current_body > avg_prev_body
    }


def get_latest_indicators(candles: List[dict]) -> dict:
    """
    Calculate ORB + VWAP indicators for the Natural ORB strategy.
    """
    if not candles:
        return {"orb_status": "BUILDING", "vwap": None, "ready": False}

    orb_results = calculate_orb(candles)

    # Calculate VWAP
    vwap_values = calculate_vwap(candles)
    current_vwap = vwap_values[-1] if vwap_values else None

    # Calculate ATR
    # Use standard 14 period or whatever is in settings
    atr_values = calculate_atr(candles, period=14)
    current_atr = atr_values[-1] if atr_values else None

    # Calculate Candle Strength
    strength_info = get_candle_strength(candles, window=3)

    return {
        "orb_high": orb_results["orb_high"],
        "orb_low": orb_results["orb_low"],
        "orb_range": orb_results["orb_range"],
        "orb_status": orb_results["orb_status"],
        "vwap": current_vwap,
        "atr": current_atr,
        "candle_strength": strength_info,
        "ready": True
    }
