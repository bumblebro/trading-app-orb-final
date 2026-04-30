"""
Technical indicators module.
Calculates ORB, VWAP, and RSI for the
ORB + VWAP Confirmation strategy.
"""

import numpy as np
import math
from typing import List, Optional, Dict, Any


def sanitize_nan(value: Any) -> Any:
    """Convert NaN or Inf to None for JSON compliance."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    elif isinstance(value, dict):
        return {k: sanitize_nan(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [sanitize_nan(v) for v in value]
    return value


def calculate_ema(prices: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average.
    """
    if len(prices) < period:
        return [float('nan')] * len(prices)
    
    ema_values = [float('nan')] * (period - 1)
    
    # First EMA value is SMA
    sma = sum(prices[:period]) / period
    ema_values.append(sma)
    
    multiplier = 2 / (period + 1)
    
    for i in range(period, len(prices)):
        ema = (prices[i] - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)
        
    return ema_values


def calculate_adx(candles: List[dict], period: int = 14) -> List[float]:
    """
    Calculate Average Directional Index (ADX).
    Standard Welles Wilder implementation.
    """
    if len(candles) < period * 2:
        return [float('nan')] * len(candles)

    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    closes = [c['close'] for c in candles]

    # 1. TR, +DM, -DM
    tr_all = []
    dm_plus_all = []
    dm_minus_all = []

    for i in range(1, len(candles)):
        h, l, pc = highs[i], lows[i], closes[i-1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_all.append(tr)

        move_up = h - highs[i-1]
        move_down = lows[i-1] - l

        if move_up > move_down and move_up > 0:
            dm_plus_all.append(move_up)
        else:
            dm_plus_all.append(0)

        if move_down > move_up and move_down > 0:
            dm_minus_all.append(move_down)
        else:
            dm_minus_all.append(0)

    # 2. Smooth TR, DM+, DM- using Wilder's Smoothing
    def wilder_smoothing(data, p):
        smoothed = [float('nan')] * (p - 1)
        # Initial SMA
        smoothed.append(sum(data[:p]))
        for j in range(p, len(data)):
            # Wilder's Smoothing: Current = Prev - (Prev/p) + Current
            val = smoothed[-1] - (smoothed[-1] / p) + data[j]
            smoothed.append(val)
        return smoothed

    tr_smoothed = wilder_smoothing(tr_all, period)
    dm_plus_smoothed = wilder_smoothing(dm_plus_all, period)
    dm_minus_smoothed = wilder_smoothing(dm_minus_all, period)

    adx_values = [float('nan')] * (period * 2 - 1)
    
    dx_all = []
    for i in range(len(tr_smoothed)):
        if tr_smoothed[i] > 0 and not math.isnan(tr_smoothed[i]):
            di_plus = 100 * (dm_plus_smoothed[i] / tr_smoothed[i])
            di_minus = 100 * (dm_minus_smoothed[i] / tr_smoothed[i])
            
            denominator = di_plus + di_minus
            if denominator > 0:
                dx = 100 * abs(di_plus - di_minus) / denominator
            else:
                dx = 0
            dx_all.append(dx)
        else:
            dx_all.append(float('nan'))

    # Final ADX (SMA of DX)
    # Filter out initial NaNs
    start_idx = period - 1
    valid_dx = dx_all[start_idx:]
    
    # First ADX is SMA of first 'period' DX values
    first_adx = sum(valid_dx[:period]) / period
    adx_values.append(first_adx)
    
    # Subsequent ADX values
    for i in range(period, len(valid_dx)):
        current_adx = (adx_values[-1] * (period - 1) + valid_dx[i]) / period
        adx_values.append(current_adx)

    return adx_values


def calculate_supertrend_series(candles: List[dict], period: int = 10, multiplier: float = 3.0) -> Dict[str, List]:
    """
    Calculate Supertrend indicator series.
    Returns: {supertrend: List, direction: List, upper_band: List, lower_band: List}
    """
    if len(candles) < period:
        empty = [float('nan')] * len(candles)
        return {"supertrend": empty, "direction": [0] * len(candles), "upper_band": empty, "lower_band": empty}

    atr_vals = calculate_atr(candles, period)
    hl2 = [(c['high'] + c['low']) / 2 for c in candles]
    
    supertrend = [0.0] * len(candles)
    direction = [1] * len(candles)
    upper_band = [0.0] * len(candles)
    lower_band = [0.0] * len(candles)

    for i in range(len(candles)):
        if i < period: continue
            
        atr = atr_vals[i]
        if math.isnan(atr): continue

        basic_upper = hl2[i] + (multiplier * atr)
        basic_lower = hl2[i] - (multiplier * atr)

        if i > 0:
            if basic_upper < upper_band[i-1] or candles[i-1]['close'] > upper_band[i-1]:
                upper_band[i] = basic_upper
            else:
                upper_band[i] = upper_band[i-1]

            if basic_lower > lower_band[i-1] or candles[i-1]['close'] < lower_band[i-1]:
                lower_band[i] = basic_lower
            else:
                lower_band[i] = lower_band[i-1]
        else:
            upper_band[i] = basic_upper
            lower_band[i] = basic_lower

        if i > 0:
            if direction[i-1] == 1:
                if candles[i]['close'] < lower_band[i]:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]
                else:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
            else:
                if candles[i]['close'] > upper_band[i]:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
                else:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]
        else:
            supertrend[i] = lower_band[i]

    return {
        "supertrend": supertrend,
        "direction": direction,
        "upper_band": upper_band,
        "lower_band": lower_band
    }

def calculate_supertrend(candles: List[dict], period: int = 10, multiplier: float = 3.0) -> Dict:
    """
    Calculate late Supertrend indicator (single value).
    """
    series = calculate_supertrend_series(candles, period, multiplier)
    return {
        "value": round(series["supertrend"][-1], 2) if series["supertrend"][-1] > 0 else None,
        "direction": series["direction"][-1],
        "upper_band": round(series["upper_band"][-1], 2),
        "lower_band": round(series["lower_band"][-1], 2)
    }


def calculate_atr(candles: List[dict], period: int = 14) -> List[float]:
    """
    Calculate Average True Range.
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


def get_latest_indicators(candles: List[dict]) -> dict:
    """
    Calculate Supertrend, EMA, and ADX indicators for the new strategy.
    """
    if not candles:
        return {"ready": False}

    closes = [c['close'] for c in candles]

    # 1. EMA Crossover (Momentum)
    ema_short = calculate_ema(closes, period=9)
    ema_long = calculate_ema(closes, period=21)
    
    # 2. Supertrend (Trend Direction)
    st_data = calculate_supertrend(candles, period=10, multiplier=3.0)
    
    # 3. ADX (Market Choppiness Filter)
    adx_values = calculate_adx(candles, period=14)
    current_adx = adx_values[-1] if adx_values else None

    # Calculate ATR for other volatility checks
    atr_vals = calculate_atr(candles, period=14)
    current_atr = atr_vals[-1] if atr_vals else None

    results = {
        "ema_short": round(ema_short[-1], 2) if not math.isnan(ema_short[-1]) else None,
        "ema_long": round(ema_long[-1], 2) if not math.isnan(ema_long[-1]) else None,
        "supertrend": st_data["value"],
        "supertrend_direction": st_data["direction"], # 1 for Long, -1 for Short
        "adx": round(current_adx, 2) if current_adx is not None and not math.isnan(current_adx) else None,
        "atr": current_atr,
        "ready": True
    }

    return sanitize_nan(results)
