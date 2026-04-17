"""
Technical indicators module.
Calculates EMA, VWAP, and RSI for trading signals.
"""

import numpy as np
from typing import List, Optional


def calculate_ema(prices: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average.
    Returns list of EMA values (same length as prices, with NaN for insufficient data).
    """
    if len(prices) < period:
        return [float('nan')] * len(prices)

    ema_values = [float('nan')] * (period - 1)

    # First EMA = SMA of first 'period' values
    sma = sum(prices[:period]) / period
    ema_values.append(sma)

    # Multiplier
    multiplier = 2 / (period + 1)

    # Calculate subsequent EMA values
    for i in range(period, len(prices)):
        ema = (prices[i] - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)

    return ema_values


def calculate_vwap(ohlcv_data: List[dict]) -> List[float]:
    """
    Calculate Volume Weighted Average Price.
    VWAP resets at the start of each trading day (9:15 AM IST).

    ohlcv_data: list of dicts with keys: open, high, low, close, volume
    Returns list of VWAP values.
    """
    if not ohlcv_data:
        return []

    vwap_values = []
    cumulative_tp_vol = 0.0
    cumulative_vol = 0.0

    for candle in ohlcv_data:
        # Typical Price = (High + Low + Close) / 3
        typical_price = (candle["high"] + candle["low"] + candle["close"]) / 3
        volume = candle.get("volume", 1)  # Default volume if not available

        cumulative_tp_vol += typical_price * volume
        cumulative_vol += volume

        if cumulative_vol > 0:
            vwap = cumulative_tp_vol / cumulative_vol
        else:
            vwap = typical_price

        vwap_values.append(vwap)

    return vwap_values


def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    Calculate Relative Strength Index.
    Returns list of RSI values (same length as prices).
    """
    if len(prices) < period + 1:
        return [float('nan')] * len(prices)

    rsi_values = [float('nan')] * period

    # Calculate price changes
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # First average gain/loss
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))

    # Calculate subsequent RSI values using smoothed averages
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


def find_recent_crossover(ema_fast: List[float], ema_slow: List[float], window: int = 10) -> dict:
    """
    Find the most recent crossover within the specified lookback window.
    Returns dict: {'type': 'bullish'|'bearish'|None, 'bars_ago': int|None}
    """
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return {"type": None, "bars_ago": None}

    # Look back from the latest candle
    for i in range(1, min(window + 1, len(ema_fast))):
        idx = -i
        prev_idx = -i - 1
        
        # Avoid index error at start of list
        if abs(prev_idx) > len(ema_fast):
            break

        prev_f, prev_s = ema_fast[prev_idx], ema_slow[prev_idx]
        curr_f, curr_s = ema_fast[idx], ema_slow[idx]

        if any(np.isnan(x) for x in [prev_f, prev_s, curr_f, curr_s]):
            continue

        # Bullish
        if prev_f <= prev_s and curr_f > curr_s:
            return {"type": "bullish", "bars_ago": i - 1}
        # Bearish
        if prev_f >= prev_s and curr_f < curr_s:
            return {"type": "bearish", "bars_ago": i - 1}

    return {"type": None, "bars_ago": None}


def ema_crossover(ema_fast: List[float], ema_slow: List[float]) -> Optional[str]:
    """
    Check for EMA crossover between the last two data points.
    Returns 'bullish' if fast crosses above slow, 'bearish' if fast crosses below slow, None otherwise.
    """
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None

    # Check last two values for crossover
    prev_fast = ema_fast[-2]
    prev_slow = ema_slow[-2]
    curr_fast = ema_fast[-1]
    curr_slow = ema_slow[-1]

    # Skip if any value is NaN
    if any(np.isnan(x) for x in [prev_fast, prev_slow, curr_fast, curr_slow]):
        return None

    # Bullish crossover: fast was below slow, now above
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return "bullish"

    # Bearish crossover: fast was above slow, now below
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return "bearish"

    return None


def get_latest_indicators(candles: List[dict], ema_fast_period: int = 9,
                          ema_slow_period: int = 21, rsi_period: int = 14) -> dict:
    """
    Calculate all indicators from candle data and return the latest values.
    """
    if not candles or len(candles) < max(ema_fast_period, ema_slow_period, rsi_period) + 1:
        return {
            "ema_fast": None,
            "ema_slow": None,
            "vwap": None,
            "rsi": None,
            "crossover": None,
            "ready": False
        }

    close_prices = [c["close"] for c in candles]

    ema_fast = calculate_ema(close_prices, ema_fast_period)
    ema_slow = calculate_ema(close_prices, ema_slow_period)
    vwap = calculate_vwap(candles)
    rsi = calculate_rsi(close_prices, rsi_period)
    
    # Standard crossover (latest candle)
    crossover = ema_crossover(ema_fast, ema_slow)
    
    # Recent crossover (last 20 candles lookback)
    recent_cross = find_recent_crossover(ema_fast, ema_slow, window=20)

    return {
        "ema_fast": round(ema_fast[-1], 2) if not np.isnan(ema_fast[-1]) else None,
        "ema_slow": round(ema_slow[-1], 2) if not np.isnan(ema_slow[-1]) else None,
        "vwap": round(vwap[-1], 2) if vwap else None,
        "rsi": round(rsi[-1], 2) if not np.isnan(rsi[-1]) else None,
        "rsi_prev": round(rsi[-2], 2) if len(rsi) >= 2 and not np.isnan(rsi[-2]) else None,
        "crossover": crossover,
        "recent_cross_type": recent_cross["type"],
        "recent_cross_bars": recent_cross["bars_ago"],
        "ready": True
    }
