"""Tests for the option pricing model and the transaction cost model."""

import math
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from charges import calculate_charges  # noqa: E402
from option_pricing import (  # noqa: E402
    RISK_FREE_RATE, atm_strike, black_scholes, next_weekly_expiry,
    price_atm_option, realised_volatility, time_to_expiry_years,
    weekly_expiry_weekday,
)

IST = timezone(timedelta(hours=5, minutes=30))


def ist(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# ------------------------------------------------------------------- strikes

@pytest.mark.parametrize("spot", [25012, 25026, 25049, 24975, 23333])
def test_atm_strike_rounds_to_the_nearest_fifty(spot):
    assert atm_strike(spot) % 50 == 0
    assert abs(atm_strike(spot) - spot) <= 25


# -------------------------------------------------------------------- expiry

def test_expiry_weekday_switches_to_tuesday_in_september_2025():
    assert weekly_expiry_weekday(ist(2025, 8, 20)) == 3   # Thursday
    assert weekly_expiry_weekday(ist(2025, 9, 3)) == 1    # Tuesday
    assert weekly_expiry_weekday(ist(2026, 1, 5)) == 1


def test_next_weekly_expiry_lands_on_the_expiry_weekday_at_close():
    expiry = next_weekly_expiry(ist(2025, 6, 10))  # a Tuesday, pre-Sep rules
    assert expiry.weekday() == 3
    assert (expiry.hour, expiry.minute) == (15, 30)
    assert expiry > ist(2025, 6, 10)


def test_expiry_day_after_close_rolls_to_next_week():
    thursday_after_close = ist(2025, 6, 12, 15, 45)
    expiry = next_weekly_expiry(thursday_after_close)
    assert (expiry - thursday_after_close).days >= 6


def test_instrument_nearest_expiry_matches_pricing_weekday_rule():
    from datetime import date
    from instrument_manager import InstrumentManager

    im = InstrumentManager()
    # Pre-Sep 2025: Thursday weekly
    assert im.get_nearest_expiry(date(2025, 6, 10)) == date(2025, 6, 12)
    # Post-Sep 2025: Tuesday weekly (2026-08-06 is a Thursday)
    assert im.get_nearest_expiry(date(2026, 8, 6)) == date(2026, 8, 11)


def test_time_to_expiry_never_returns_zero():
    expiry = ist(2025, 6, 12, 15, 30)
    assert time_to_expiry_years(expiry, expiry) > 0


# ------------------------------------------------------------ black-scholes

def test_atm_call_and_put_satisfy_put_call_parity():
    now = ist(2025, 6, 10)
    spot = strike = 25000
    call = price_atm_option(spot, "CE", now, iv=0.15, strike=strike)
    put = price_atm_option(spot, "PE", now, iv=0.15, strike=strike)

    t = time_to_expiry_years(now)
    expected = spot - strike * math.exp(-RISK_FREE_RATE * t)
    assert call.price - put.price == pytest.approx(expected, abs=0.05)


def test_deep_itm_call_is_worth_at_least_its_intrinsic():
    quote = black_scholes(25500, 25000, 3 / 365, 0.15, "CE")
    assert quote.price >= 500
    assert quote.delta > 0.9


def test_deep_otm_option_decays_towards_the_floor():
    quote = black_scholes(25000, 26000, 1 / 365, 0.15, "CE")
    assert quote.price < 5
    assert quote.price >= 0.05


def test_premium_shrinks_as_expiry_approaches():
    far = black_scholes(25000, 25000, 5 / 365, 0.15, "CE").price
    near = black_scholes(25000, 25000, 1 / 365, 0.15, "CE").price
    assert near < far


def test_higher_volatility_means_a_richer_option():
    low = black_scholes(25000, 25000, 3 / 365, 0.10, "CE").price
    high = black_scholes(25000, 25000, 3 / 365, 0.30, "CE").price
    assert high > low


def test_put_delta_is_negative_and_call_delta_positive():
    assert black_scholes(25000, 25000, 3 / 365, 0.15, "PE").delta < 0
    assert black_scholes(25000, 25000, 3 / 365, 0.15, "CE").delta > 0


def test_degenerate_inputs_fall_back_to_intrinsic():
    assert black_scholes(25500, 25000, 0, 0.15, "CE").price == 500
    assert black_scholes(25000, 25000, 3 / 365, 0, "CE").price == 0


# --------------------------------------------------------------- volatility

def test_realised_volatility_is_clamped_to_the_option_iv_band():
    flat = realised_volatility([25000.0] * 25)
    assert flat >= 0.08

    wild = realised_volatility([25000 * (1.05 if i % 2 else 0.95) for i in range(25)])
    assert wild <= 0.75


def test_short_history_uses_a_neutral_default():
    assert realised_volatility([25000.0, 25100.0]) == 0.15


# ------------------------------------------------------------------ charges

def test_charges_scale_with_turnover_and_stay_realistic():
    small = calculate_charges(100.0, 120.0, 75)
    large = calculate_charges(100.0, 120.0, 750)

    assert large["total_charges"] > small["total_charges"]
    # Costs must never swallow a normal winning trade.
    assert small["total_charges"] < 100


def test_stt_is_charged_on_the_sell_side_only():
    losing = calculate_charges(100.0, 50.0, 75)
    winning = calculate_charges(100.0, 150.0, 75)
    assert winning["stt"] > losing["stt"]


def test_total_is_the_sum_of_its_parts():
    charges = calculate_charges(100.0, 120.0, 375)
    components = (charges["brokerage"] + charges["stt"] + charges["exc_charges"]
                  + charges["gst"])
    assert charges["total_charges"] >= components
    assert charges["total_charges"] > 0
