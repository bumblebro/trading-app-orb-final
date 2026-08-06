"""
Chart and serialisation helpers.

The ORB strategy needs no trend indicators: the opening range itself is the
signal. This module only provides what the API layer needs to draw the chart
and to emit JSON safely.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def sanitize_nan(value: Any) -> Any:
    """Replace NaN/Inf with None so the payload stays valid JSON."""
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {k: sanitize_nan(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_nan(v) for v in value]
    return value


def session_opening_range(candles: List[Dict], or_minutes: int = 15,
                          session_date: Optional[str] = None) -> Optional[Dict]:
    """
    High/low of the first `or_minutes` of the most recent session in `candles`.

    Candles must carry `time_key` formatted as "YYYY-MM-DD HH:MM".
    """
    if not candles:
        return None

    if session_date is None:
        last_key = candles[-1].get("time_key") or ""
        session_date = last_key[:10]
    if not session_date:
        return None

    start_minutes = 9 * 60 + 15
    end_minutes = start_minutes + or_minutes

    high, low, count = float("-inf"), float("inf"), 0
    for candle in candles:
        key = candle.get("time_key") or ""
        if not key.startswith(session_date):
            continue
        try:
            minutes = int(key[11:13]) * 60 + int(key[14:16])
        except (ValueError, IndexError):
            continue
        if start_minutes <= minutes < end_minutes:
            high = max(high, candle["high"])
            low = min(low, candle["low"])
            count += 1

    if count == 0:
        return None

    return {
        "high": round(high, 2),
        "low": round(low, 2),
        "range": round(high - low, 2),
        "bars": count,
        "date": session_date,
    }
