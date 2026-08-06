"""
Behavioural tests for the ORB engine.

These lock in the rules that decide real money: when a breakout counts, where the
stop sits, and when the day is abandoned. Run with:

    python3 -m pytest bot/tests -q
"""

import os
import sys
from datetime import datetime, time, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_orb import (  # noqa: E402
    PHASE_BUILDING_RANGE, PHASE_DONE, PHASE_IN_TRADE, PHASE_PREOPEN,
    PHASE_SKIP_DAY, PHASE_WAITING_BREAKOUT, OrbConfig, OrbStrategy, Position,
)

IST = timezone(timedelta(hours=5, minutes=30))
DAY = datetime(2025, 6, 10, tzinfo=IST)


def at(hour: int, minute: int) -> datetime:
    return DAY.replace(hour=hour, minute=minute)


def bar(hour, minute, open_, high, low, close):
    return {"time": at(hour, minute), "open": open_, "high": high,
            "low": low, "close": close}


def flat_range(strategy: OrbStrategy, high: float, low: float, minutes: int = 15):
    """Feed `minutes` of range bars that print exactly `high` and `low`."""
    for i in range(minutes):
        h = high if i == 0 else (high + low) / 2
        l = low if i == 0 else (high + low) / 2
        strategy.on_candle(bar(9, 15 + i, low, h, l, (high + low) / 2))


def cfg(**overrides) -> OrbConfig:
    base = dict(or_minutes=15, min_or_pct=0.0, max_or_pct=10.0,
                entry_trigger="close", confirm_interval_mins=1,
                breakout_buffer_pct=0.0, sl_mode="or_opposite",
                target_r=2.0, breakeven_after_r=0.0, trail_r=0.0,
                option_sl_pct=0.0, max_trades_per_day=1)
    base.update(overrides)
    return OrbConfig(**base)


# ------------------------------------------------------------- range building

def test_range_is_locked_from_the_first_n_minutes_only():
    s = OrbStrategy(cfg())
    flat_range(s, high=25100, low=25000)

    assert s.phase == PHASE_BUILDING_RANGE
    assert s.opening_range is None

    # The 09:30 bar falls outside the window and triggers the lock.
    s.on_candle(bar(9, 30, 25050, 25400, 25050, 25060))

    assert s.opening_range.high == 25100
    assert s.opening_range.low == 25000
    assert s.opening_range.bar_count == 15
    assert s.phase == PHASE_WAITING_BREAKOUT


def test_bars_before_the_open_are_ignored():
    s = OrbStrategy(cfg())
    s.on_candle(bar(9, 0, 25000, 25010, 24990, 25000))
    assert s.phase == PHASE_PREOPEN
    assert s.opening_range is None


def test_narrow_range_skips_the_day():
    s = OrbStrategy(cfg(min_or_pct=0.15))
    flat_range(s, high=25010, low=25000)  # 0.04% wide
    s.on_candle(bar(9, 30, 25005, 25200, 25005, 25200))

    assert s.phase == PHASE_SKIP_DAY
    assert "too narrow" in s.skip_reason


def test_wide_range_skips_the_day():
    s = OrbStrategy(cfg(max_or_pct=1.0))
    flat_range(s, high=25500, low=25000)  # ~1.98% wide
    s.on_candle(bar(9, 30, 25200, 25900, 25200, 25900))

    assert s.phase == PHASE_SKIP_DAY
    assert "too wide" in s.skip_reason


def test_skipped_day_never_produces_a_signal():
    s = OrbStrategy(cfg(min_or_pct=0.15))
    flat_range(s, high=25010, low=25000)
    for minute in range(30, 60):
        assert s.on_candle(bar(9, minute, 25005, 26000, 25005, 26000)) is None


# -------------------------------------------------------------------- entries

def test_close_beyond_the_high_goes_long():
    s = OrbStrategy(cfg())
    flat_range(s, high=25100, low=25000)

    assert s.on_candle(bar(9, 30, 25050, 25090, 25040, 25080)) is None
    signal = s.on_candle(bar(9, 31, 25080, 25130, 25080, 25120))

    assert signal is not None
    assert signal.direction == "LONG"
    assert signal.option_type == "CE"
    assert signal.index_price == 25120
    assert signal.stop_index == 25000            # opposite side of the range
    assert signal.risk_points == pytest.approx(120)
    assert signal.target_index == pytest.approx(25120 + 2 * 120)


def test_close_below_the_low_goes_short():
    s = OrbStrategy(cfg())
    flat_range(s, high=25100, low=25000)
    signal = s.on_candle(bar(9, 30, 25020, 25020, 24950, 24960))

    assert signal.direction == "SHORT"
    assert signal.option_type == "PE"
    assert signal.stop_index == 25100
    assert signal.target_index == pytest.approx(24960 - 2 * 140)


def test_a_wick_through_the_level_is_not_a_close_entry():
    s = OrbStrategy(cfg(entry_trigger="close"))
    flat_range(s, high=25100, low=25000)
    # Trades up to 25180 but closes back inside the range.
    assert s.on_candle(bar(9, 30, 25050, 25180, 25040, 25090)) is None
    assert s.phase == PHASE_WAITING_BREAKOUT


def test_touch_trigger_fills_at_the_level_on_a_wick():
    s = OrbStrategy(cfg(entry_trigger="touch"))
    flat_range(s, high=25100, low=25000)
    signal = s.on_candle(bar(9, 30, 25050, 25180, 25040, 25090))

    assert signal.direction == "LONG"
    assert signal.index_price == 25100  # filled at the level, not the close


def test_touch_trigger_ignores_bars_that_straddle_both_levels():
    s = OrbStrategy(cfg(entry_trigger="touch"))
    flat_range(s, high=25100, low=25000)
    assert s.on_candle(bar(9, 30, 25050, 25150, 24950, 25050)) is None


def test_buffer_requires_the_level_to_be_cleared():
    s = OrbStrategy(cfg(breakout_buffer_pct=0.20))  # 20% of a 100pt range = 20pts
    flat_range(s, high=25100, low=25000)

    assert s.on_candle(bar(9, 30, 25050, 25115, 25050, 25110)) is None  # +10, short
    signal = s.on_candle(bar(9, 31, 25110, 25130, 25110, 25125))        # +25, clears
    assert signal.direction == "LONG"


def test_confirmation_candle_only_evaluates_on_a_complete_bucket():
    s = OrbStrategy(cfg(confirm_interval_mins=5))
    flat_range(s, high=25100, low=25000)

    # 09:30-09:33 close above the high but the 5-minute bar is incomplete.
    for minute in range(30, 34):
        assert s.on_candle(bar(9, minute, 25120, 25130, 25110, 25125)) is None

    signal = s.on_candle(bar(9, 34, 25125, 25140, 25120, 25135))
    assert signal is not None
    assert signal.index_price == 25135  # the aggregated bar's close


def test_no_entry_after_the_cutoff():
    s = OrbStrategy(cfg(entry_cutoff="13:30"))
    flat_range(s, high=25100, low=25000)

    assert s.on_candle(bar(13, 30, 25120, 25200, 25120, 25190)) is None
    assert s.phase == PHASE_DONE


def test_cutoff_boundary_bar_is_still_tradeable():
    s = OrbStrategy(cfg(entry_cutoff="13:30"))
    flat_range(s, high=25100, low=25000)
    # The 13:29 candle closes at 13:30, exactly on the cutoff.
    assert s.on_candle(bar(13, 29, 25120, 25200, 25120, 25190)) is not None


def test_trade_limit_ends_the_day():
    s = OrbStrategy(cfg(max_trades_per_day=1))
    flat_range(s, high=25100, low=25000)
    signal = s.on_candle(bar(9, 30, 25050, 25150, 25050, 25140))
    s.register_entry(signal)
    s.register_exit()

    assert s.phase == PHASE_DONE
    assert s.on_candle(bar(10, 0, 25150, 25300, 25150, 25290)) is None


def test_second_trade_in_the_same_direction_is_blocked_without_reversal():
    s = OrbStrategy(cfg(max_trades_per_day=2, allow_reversal=False))
    flat_range(s, high=25100, low=25000)
    first = s.on_candle(bar(9, 30, 25050, 25150, 25050, 25140))
    s.register_entry(first)
    s.register_exit()

    assert s.on_candle(bar(10, 0, 25150, 25300, 25150, 25290)) is None
    # The other side is still allowed.
    assert s.on_candle(bar(10, 5, 24990, 24990, 24900, 24910)) is not None


def test_reversal_allows_the_same_side_again():
    s = OrbStrategy(cfg(max_trades_per_day=2, allow_reversal=True))
    flat_range(s, high=25100, low=25000)
    first = s.on_candle(bar(9, 30, 25050, 25150, 25050, 25140))
    s.register_entry(first)
    s.register_exit()

    assert s.on_candle(bar(10, 0, 25150, 25300, 25150, 25290)) is not None


def test_confirmation_bucket_stays_aligned_while_in_a_trade():
    """A candle consumed mid-trade must not leave a half-built confirmation bar."""
    s = OrbStrategy(cfg(confirm_interval_mins=5, max_trades_per_day=2))
    flat_range(s, high=25100, low=25000)

    for minute in range(30, 35):
        s.on_candle(bar(9, minute, 25050, 25060, 25040, 25050), in_trade=True)

    assert s.phase == PHASE_IN_TRADE
    assert s._confirm_bucket_key is not None


def test_fraction_stop_mode_sizes_risk_off_the_range_width():
    s = OrbStrategy(cfg(sl_mode="or_fraction", sl_fraction=0.5))
    flat_range(s, high=25100, low=25000)
    signal = s.on_candle(bar(9, 30, 25050, 25150, 25050, 25140))

    assert signal.stop_index == pytest.approx(25140 - 50)
    assert signal.risk_points == pytest.approx(50)


# ---------------------------------------------------------------------- exits

def position(direction="LONG", entry=25120, stop=25000, target=25360,
             option_price=100.0) -> Position:
    return Position(
        direction=direction, entry_index=entry, stop_index=stop,
        target_index=target, risk_points=abs(entry - stop),
        entry_option_price=option_price, entry_time=at(9, 31),
    )


def test_long_stop_hit_intrabar():
    s = OrbStrategy(cfg())
    exit_signal = s.check_exit(position(), 25050, at(11, 0),
                               bar_high=25060, bar_low=24990)
    assert exit_signal.reason == "stoploss"
    assert exit_signal.index_price == 25000  # filled at the stop, not the close


def test_long_target_hit_intrabar():
    s = OrbStrategy(cfg())
    exit_signal = s.check_exit(position(), 25300, at(11, 0),
                               bar_high=25400, bar_low=25280)
    assert exit_signal.reason == "target"
    assert exit_signal.index_price == 25360


def test_stop_wins_when_a_bar_could_have_hit_both():
    s = OrbStrategy(cfg())
    exit_signal = s.check_exit(position(), 25200, at(11, 0),
                               bar_high=25400, bar_low=24990)
    assert exit_signal.reason == "stoploss"


def test_short_stop_and_target():
    s = OrbStrategy(cfg())
    short = position(direction="SHORT", entry=24960, stop=25100, target=24680)

    assert s.check_exit(short, 25000, at(11, 0),
                        bar_high=25110, bar_low=24990).reason == "stoploss"
    assert s.check_exit(short, 24700, at(11, 0),
                        bar_high=24720, bar_low=24670).reason == "target"


def test_breakeven_moves_the_stop_and_renames_the_exit():
    s = OrbStrategy(cfg(breakeven_after_r=1.0))
    pos = position()

    assert s.check_exit(pos, 25250, at(11, 0), bar_high=25250, bar_low=25200) is None
    assert pos.breakeven_done is True
    assert pos.stop_index == pos.entry_index

    exit_signal = s.check_exit(pos, 25100, at(11, 5), bar_high=25130, bar_low=25100)
    assert exit_signal.reason == "breakeven_stop"
    assert exit_signal.index_price == pos.entry_index


def test_trailing_stop_only_ratchets_forward():
    s = OrbStrategy(cfg(trail_r=1.0))
    pos = position()

    s.check_exit(pos, 25400, at(11, 0), bar_high=25400, bar_low=25300)
    trailed = pos.stop_index
    assert trailed == pytest.approx(25400 - 120)

    # A pullback must not loosen the stop.
    s.check_exit(pos, 25300, at(11, 5), bar_high=25310, bar_low=25290)
    assert pos.stop_index == pytest.approx(trailed)


def test_premium_stop_fires_on_option_decay_alone():
    s = OrbStrategy(cfg(option_sl_pct=35.0))
    pos = position(option_price=100.0)

    assert s.check_exit(pos, 25120, at(11, 0), option_price=70.0) is None
    assert s.check_exit(pos, 25120, at(11, 0), option_price=64.0).reason == "premium_sl"


def test_squareoff_beats_every_other_exit():
    s = OrbStrategy(cfg())
    exit_signal = s.check_exit(position(), 25400, at(15, 15),
                               bar_high=25400, bar_low=24000)
    assert exit_signal.reason == "squareoff"


def test_reset_day_clears_all_state():
    s = OrbStrategy(cfg())
    flat_range(s, high=25100, low=25000)
    signal = s.on_candle(bar(9, 30, 25050, 25150, 25050, 25140))
    s.register_entry(signal)

    s.reset_day("2025-06-11")
    assert s.opening_range is None
    assert s.trades_taken == 0
    assert s.directions_taken == []
    assert s.phase == PHASE_PREOPEN
    assert s.skip_reason is None


# ------------------------------------------------------------------- config

def test_config_reads_settings_and_falls_back_on_junk():
    stored = {
        "orb_or_minutes": "30",
        "orb_target_r": "2.5",
        "orb_sl_mode": "or_fraction",
        "orb_allow_reversal": "true",
        "orb_min_range_pct": "",              # blank -> default
        "orb_max_range_pct": "not-a-number",  # junk -> default
    }
    config = OrbConfig.from_settings(lambda key: stored.get(key))
    defaults = OrbConfig()

    assert config.or_minutes == 30
    assert config.target_r == 2.5
    assert config.sl_mode == "or_fraction"
    assert config.allow_reversal is True
    assert config.min_or_pct == defaults.min_or_pct
    assert config.max_or_pct == defaults.max_or_pct
    assert config.entry_cutoff_time == time(13, 30)


def test_defaults_match_the_validated_backtest_configuration():
    """Guards against a stray edit silently changing what the bot trades."""
    d = OrbConfig()
    assert (d.or_minutes, d.entry_trigger, d.confirm_interval_mins) == (60, "close", 3)
    assert (d.min_or_pct, d.max_or_pct, d.breakout_buffer_pct) == (0.25, 2.00, 0.05)
    assert (d.sl_mode, d.target_r, d.breakeven_after_r, d.trail_r) == \
        ("or_opposite", 2.0, 1.0, 0.0)
    assert d.max_trades_per_day == 1 and d.allow_reversal is False
    assert d.entry_cutoff == "13:30" and d.square_off == "15:15"


def test_database_defaults_agree_with_the_strategy_defaults():
    """The settings table must not quietly disagree with OrbConfig."""
    from database import DEFAULT_SETTINGS

    config = OrbConfig.from_settings(DEFAULT_SETTINGS.get)
    assert config == OrbConfig()
