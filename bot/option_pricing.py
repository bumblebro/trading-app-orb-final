"""
ATM option pricing for NIFTY index options.

The bot only receives index (spot) data from the feed. To simulate paper trades
and to mark positions to market when an option LTP is unavailable, premiums are
modelled with Black-Scholes rather than a flat delta, so that time decay and
moneyness both affect the simulated P&L.

Live trading always prefers the real option LTP; this module is the fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

RISK_FREE_RATE = 0.065
STRIKE_STEP = 50
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

# Bounds for the volatility estimate, annualised.
MIN_IV = 0.08
MAX_IV = 0.75
# Realised vol systematically understates option IV; scale it up modestly.
IV_PREMIUM_MULTIPLIER = 1.15

MINUTES_PER_YEAR = 365 * 24 * 60


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def atm_strike(spot: float, step: int = STRIKE_STEP) -> int:
    return int(round(spot / step) * step)


def weekly_expiry_weekday(when: datetime) -> int:
    """
    Python weekday index of the NIFTY weekly expiry in force on a given date.
    NSE moved the weekly expiry from Thursday to Tuesday in September 2025.
    """
    return 1 if (when.year, when.month) >= (2025, 9) else 3


def next_weekly_expiry(now: datetime, weekday: Optional[int] = None) -> datetime:
    """Expiry moment (market close) of the nearest weekly contract."""
    if weekday is None:
        weekday = weekly_expiry_weekday(now)
    days_ahead = (weekday - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE,
        second=0, microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def time_to_expiry_years(now: datetime, expiry: Optional[datetime] = None) -> float:
    if expiry is None:
        expiry = next_weekly_expiry(now)
    minutes = (expiry - now).total_seconds() / 60.0
    # Never return exactly zero: a zero-T Black-Scholes call is undefined.
    return max(minutes, 1.0) / MINUTES_PER_YEAR


def realised_volatility(daily_closes: List[float], lookback: int = 20) -> float:
    """Annualised close-to-close volatility, clamped to a sane option-IV range."""
    if len(daily_closes) < 3:
        return 0.15

    window = daily_closes[-(lookback + 1):]
    returns = [
        math.log(window[i] / window[i - 1])
        for i in range(1, len(window))
        if window[i] > 0 and window[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.15

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    annualised = math.sqrt(variance) * math.sqrt(252)
    return _clamp(annualised * IV_PREMIUM_MULTIPLIER, MIN_IV, MAX_IV)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class OptionQuote:
    price: float
    delta: float
    intrinsic: float


def black_scholes(spot: float, strike: float, t_years: float, iv: float,
                  option_type: str, rate: float = RISK_FREE_RATE) -> OptionQuote:
    """Price a European option and return its delta alongside."""
    is_call = option_type.upper() == "CE"
    intrinsic = max(0.0, spot - strike) if is_call else max(0.0, strike - spot)

    if spot <= 0 or strike <= 0 or t_years <= 0 or iv <= 0:
        return OptionQuote(price=intrinsic, delta=1.0 if intrinsic > 0 else 0.0,
                           intrinsic=intrinsic)

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * t_years) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    discount = math.exp(-rate * t_years)

    if is_call:
        price = spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
        delta = norm_cdf(d1)
    else:
        price = strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)
        delta = norm_cdf(d1) - 1.0

    # Options cannot trade below intrinsic value or at a negative price.
    price = max(price, intrinsic, 0.05)
    return OptionQuote(price=round(price, 2), delta=delta, intrinsic=intrinsic)


def price_atm_option(spot: float, option_type: str, now: datetime,
                     iv: float, strike: Optional[float] = None,
                     expiry: Optional[datetime] = None) -> OptionQuote:
    """Convenience wrapper: price the ATM contract for the current spot."""
    k = strike if strike is not None else atm_strike(spot)
    t = time_to_expiry_years(now, expiry)
    return black_scholes(spot, k, t, iv, option_type)
