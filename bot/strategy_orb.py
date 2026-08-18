"""
Opening Range Breakout (ORB) strategy engine.

This module is deliberately pure: no database, no network, no globals. The same
instance logic drives the research backtester and the live bot, so simulated and
live behaviour cannot drift apart.

Session outline (all times IST):

  09:15            Session opens, opening range starts building.
  09:15 + N        Opening range is locked (high / low / width).
                   Range width is validated against min/max bands.
  ... until cutoff  Wait for a breakout beyond the range (+ buffer).
                   Entry is CE above the high, PE below the low.
  on entry         Stop and target are placed on index levels.
  in trade         Stop moves to breakeven after a configurable R multiple,
                   then trails. A premium stop caps option-specific decay.
  15:15            Anything still open is squared off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Dict, List, Optional

# Strategy phases surfaced to the UI.
PHASE_PREOPEN = "PREOPEN"
PHASE_BUILDING_RANGE = "BUILDING_RANGE"
PHASE_WAITING_BREAKOUT = "WAITING_BREAKOUT"
PHASE_IN_TRADE = "IN_TRADE"
PHASE_SKIP_DAY = "SKIP_DAY"
PHASE_DONE = "DONE"
PHASE_CLOSED = "CLOSED"

PHASE_DESCRIPTIONS = {
    PHASE_PREOPEN: "Pre-market — waiting for 09:15",
    PHASE_BUILDING_RANGE: "Building the opening range",
    PHASE_WAITING_BREAKOUT: "Range locked — waiting for a breakout",
    PHASE_IN_TRADE: "Trade active — monitoring position",
    PHASE_SKIP_DAY: "No trade today — opening range rejected",
    PHASE_DONE: "Done for today — trade limit or cutoff reached",
    PHASE_CLOSED: "Market session closed",
}

SESSION_OPEN = time(9, 15)


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        hour, minute = value.strip().split(":")
        return time(int(hour), int(minute))
    except (AttributeError, ValueError):
        return fallback


@dataclass
class OrbConfig:
    """Every tunable knob of the strategy. Values are the validated defaults."""

    # --- Opening range ---
    # 60 minutes beat 15/30/45 in both halves of the sample by a wide margin;
    # the textbook 15-minute range is barely break-even after costs.
    or_minutes: int = 60
    # Range width, as a percentage of spot, that makes a day tradeable. Too
    # narrow means noise; too wide means the stop would be uncomfortably far.
    min_or_pct: float = 0.25
    max_or_pct: float = 2.00

    # --- Entry ---
    # "close": a confirmation candle must close beyond the level.
    # "touch": a stop order fills the moment price trades through the level.
    entry_trigger: str = "close"
    confirm_interval_mins: int = 3
    # Breakout must clear the level by this fraction of the range width.
    # Wider buffers look better in-sample and fall apart out-of-sample.
    breakout_buffer_pct: float = 0.05
    entry_cutoff: str = "13:30"

    # --- Risk ---
    # "or_opposite": stop at the far side of the range (full-width risk).
    # "or_fraction": stop a fraction of the range width away from entry.
    sl_mode: str = "or_opposite"
    sl_fraction: float = 0.50
    target_r: float = 2.0
    # Move the stop to entry once the trade is this many R in profit. 0 = off.
    breakeven_after_r: float = 1.0
    # Trail the stop this many R behind the best price reached. 0 = off.
    trail_r: float = 0.0
    # Hard stop on the option premium, as a percentage of the entry premium.
    # 100 disables it, which is the tested default: the index stop already
    # bounds the loss, and every tighter setting cut returns without cutting
    # drawdown. Lower it only if you want a backstop for feed/broker failure.
    option_sl_pct: float = 100.0

    # --- Session limits ---
    max_trades_per_day: int = 1
    allow_reversal: bool = False
    square_off: str = "15:15"

    @property
    def entry_cutoff_time(self) -> time:
        return _parse_hhmm(self.entry_cutoff, time(13, 30))

    @property
    def square_off_time(self) -> time:
        return _parse_hhmm(self.square_off, time(15, 15))

    @classmethod
    def from_settings(cls, get: "callable") -> "OrbConfig":
        """Build a config from a `get(key) -> str` settings accessor."""
        def num(key, default, cast=float):
            raw = get(key)
            if raw is None or str(raw).strip() == "":
                return default
            try:
                return cast(raw)
            except (TypeError, ValueError):
                return default

        def text(key, default):
            raw = get(key)
            return str(raw).strip() if raw not in (None, "") else default

        d = cls()
        return cls(
            or_minutes=num("orb_or_minutes", d.or_minutes, int),
            min_or_pct=num("orb_min_range_pct", d.min_or_pct),
            max_or_pct=num("orb_max_range_pct", d.max_or_pct),
            entry_trigger=text("orb_entry_trigger", d.entry_trigger),
            confirm_interval_mins=num("orb_confirm_interval_mins",
                                      d.confirm_interval_mins, int),
            breakout_buffer_pct=num("orb_breakout_buffer_pct", d.breakout_buffer_pct),
            entry_cutoff=text("orb_entry_cutoff", d.entry_cutoff),
            sl_mode=text("orb_sl_mode", d.sl_mode),
            sl_fraction=num("orb_sl_fraction", d.sl_fraction),
            target_r=num("orb_target_r", d.target_r),
            breakeven_after_r=num("orb_breakeven_after_r", d.breakeven_after_r),
            trail_r=num("orb_trail_r", d.trail_r),
            option_sl_pct=num("option_sl_pct", d.option_sl_pct),
            max_trades_per_day=num("orb_max_trades_per_day",
                                   d.max_trades_per_day, int),
            allow_reversal=text("orb_allow_reversal", "false").lower() == "true",
            square_off=text("square_off_time", d.square_off),
        )


@dataclass
class OpeningRange:
    high: float
    low: float
    start: datetime
    end: datetime
    bar_count: int

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0


@dataclass
class EntrySignal:
    direction: str          # "LONG" | "SHORT"
    option_type: str        # "CE" | "PE"
    index_price: float      # index level the entry is based on
    stop_index: float
    target_index: float
    risk_points: float
    orb_high: float
    orb_low: float
    orb_range: float
    triggered_at: datetime
    reason: str


@dataclass
class ExitSignal:
    reason: str
    index_price: float


@dataclass
class Position:
    """Index-level view of an open trade, independent of option bookkeeping."""

    direction: str
    entry_index: float
    stop_index: float
    target_index: float
    risk_points: float
    entry_option_price: float
    entry_time: datetime
    best_index: float = 0.0
    breakeven_done: bool = False

    def __post_init__(self):
        if not self.best_index:
            self.best_index = self.entry_index

    @property
    def is_long(self) -> bool:
        return self.direction == "LONG"

    def r_multiple(self, index_price: float) -> float:
        if self.risk_points <= 0:
            return 0.0
        move = (index_price - self.entry_index) if self.is_long else (self.entry_index - index_price)
        return move / self.risk_points


class OrbStrategy:
    """Day-scoped ORB state machine driven by closed candles and price updates."""

    def __init__(self, config: Optional[OrbConfig] = None):
        self.config = config or OrbConfig()
        self.reset_day()

    # ------------------------------------------------------------------ state

    def reset_day(self, session_date: Optional[str] = None):
        self.session_date = session_date
        self.opening_range: Optional[OpeningRange] = None
        self.phase = PHASE_PREOPEN
        self.skip_reason: Optional[str] = None
        self.trades_taken = 0
        self.directions_taken: List[str] = []
        self.last_breakout: Optional[Dict] = None
        self._range_bars: List[Dict] = []
        self._confirm_bucket: List[Dict] = []
        self._confirm_bucket_key: Optional[str] = None

    @property
    def phase_description(self) -> str:
        if self.phase == PHASE_SKIP_DAY and self.skip_reason:
            return f"No trade today — {self.skip_reason}"
        return PHASE_DESCRIPTIONS.get(self.phase, self.phase)

    def snapshot(self) -> Dict:
        """Serialisable view of strategy state for the API/UI."""
        orb = self.opening_range
        return {
            "phase": self.phase,
            "phase_description": self.phase_description,
            "orb_high": round(orb.high, 2) if orb else None,
            "orb_low": round(orb.low, 2) if orb else None,
            "orb_range": round(orb.width, 2) if orb else None,
            "orb_range_pct": round(orb.width / orb.mid * 100, 3) if orb and orb.mid else None,
            "orb_locked_at": orb.end.strftime("%H:%M") if orb else None,
            "min_or_pct": self.config.min_or_pct,
            "max_or_pct": self.config.max_or_pct,
            "skip_reason": self.skip_reason,
            "trades_taken": self.trades_taken,
            "max_trades": self.config.max_trades_per_day,
            "entry_cutoff": self.config.entry_cutoff,
            "or_minutes": self.config.or_minutes,
            "last_breakout": self.last_breakout,
        }

    # ------------------------------------------------------------ range build

    def _session_bounds(self, bar_time: datetime):
        start = bar_time.replace(hour=SESSION_OPEN.hour, minute=SESSION_OPEN.minute,
                                 second=0, microsecond=0)
        return start, start + _minutes(self.config.or_minutes)

    def _lock_range(self, range_end: datetime):
        bars = self._range_bars
        if not bars:
            self.phase = PHASE_SKIP_DAY
            self.skip_reason = "no opening range data"
            return

        high = max(b["high"] for b in bars)
        low = min(b["low"] for b in bars)
        self.opening_range = OpeningRange(
            high=high, low=low,
            start=bars[0]["time"], end=range_end,
            bar_count=len(bars),
        )

        mid = self.opening_range.mid
        width_pct = (high - low) / mid * 100 if mid else 0.0
        cfg = self.config

        if width_pct < cfg.min_or_pct:
            self.phase = PHASE_SKIP_DAY
            self.skip_reason = f"range too narrow ({width_pct:.2f}% < {cfg.min_or_pct}%)"
        elif width_pct > cfg.max_or_pct:
            self.phase = PHASE_SKIP_DAY
            self.skip_reason = f"range too wide ({width_pct:.2f}% > {cfg.max_or_pct}%)"
        else:
            self.phase = PHASE_WAITING_BREAKOUT

    # ----------------------------------------------------------------- entries

    def on_candle(self, candle: Dict, in_trade: bool = False) -> Optional[EntrySignal]:
        """
        Feed one *closed* 1-minute candle.

        Returns an EntrySignal when a breakout is confirmed, otherwise None.
        `candle` needs: time (datetime), open, high, low, close.
        """
        bar_time: datetime = candle["time"]
        session_start, range_end = self._session_bounds(bar_time)

        if bar_time < session_start:
            self.phase = PHASE_PREOPEN
            return None

        # Accumulate the opening range, then lock it once the window has passed.
        if bar_time < range_end:
            self.phase = PHASE_BUILDING_RANGE
            self._range_bars.append(candle)
            return None

        if self.opening_range is None:
            self._lock_range(range_end)

        if self.phase in (PHASE_SKIP_DAY, PHASE_DONE, PHASE_CLOSED):
            return None
        if in_trade:
            # Keep the confirmation timeframe aligned so a post-exit re-entry
            # does not evaluate a half-built candle.
            self._push_confirmation_bar(candle)
            self.phase = PHASE_IN_TRADE
            return None
        if self.trades_taken >= self.config.max_trades_per_day:
            self.phase = PHASE_DONE
            return None

        bar_end = bar_time + _minutes(1)
        if bar_end.time() > self.config.entry_cutoff_time:
            self.phase = PHASE_DONE
            return None

        self.phase = PHASE_WAITING_BREAKOUT
        return self._check_breakout(candle)

    def _check_breakout(self, candle: Dict) -> Optional[EntrySignal]:
        cfg = self.config
        orb = self.opening_range
        if orb is None:
            return None

        buffer_pts = orb.width * cfg.breakout_buffer_pct
        long_level = orb.high + buffer_pts
        short_level = orb.low - buffer_pts

        if cfg.entry_trigger == "touch":
            # A resting stop order fills at the level itself.
            bar = self._touch_candidate(candle, long_level, short_level)
        else:
            bar = self._close_candidate(candle, long_level, short_level)

        if bar is None:
            return None

        direction, fill_index = bar
        if direction in self.directions_taken and not cfg.allow_reversal:
            return None

        stop_index = self._stop_for(direction, fill_index, orb)
        risk = abs(fill_index - stop_index)
        if risk <= 0:
            return None

        target_index = (fill_index + cfg.target_r * risk) if direction == "LONG" \
            else (fill_index - cfg.target_r * risk)

        self.last_breakout = {
            "direction": direction,
            "price": round(fill_index, 2),
            "time": candle["time"].strftime("%H:%M"),
        }

        return EntrySignal(
            direction=direction,
            option_type="CE" if direction == "LONG" else "PE",
            index_price=fill_index,
            stop_index=stop_index,
            target_index=target_index,
            risk_points=risk,
            orb_high=orb.high,
            orb_low=orb.low,
            orb_range=orb.width,
            triggered_at=candle["time"],
            reason=f"{direction} breakout of {cfg.or_minutes}m range",
        )

    def _touch_candidate(self, candle: Dict, long_level: float, short_level: float):
        # If a bar straddles both levels, treat it as noise rather than guessing
        # which side traded first.
        hit_long = candle["high"] >= long_level
        hit_short = candle["low"] <= short_level
        if hit_long and hit_short:
            return None
        if hit_long:
            return "LONG", long_level
        if hit_short:
            return "SHORT", short_level
        return None

    def _close_candidate(self, candle: Dict, long_level: float, short_level: float):
        """Confirm on the close of an aggregated confirmation candle."""
        agg = self._push_confirmation_bar(candle)
        if agg is None:
            return None
        if agg["close"] > long_level:
            return "LONG", agg["close"]
        if agg["close"] < short_level:
            return "SHORT", agg["close"]
        return None

    def _push_confirmation_bar(self, candle: Dict) -> Optional[Dict]:
        """
        Aggregate 1-minute candles into the confirmation timeframe.
        Returns the aggregated bar only when it is complete.
        """
        interval = max(1, self.config.confirm_interval_mins)
        if interval == 1:
            return candle

        bar_time: datetime = candle["time"]
        minutes = bar_time.hour * 60 + bar_time.minute
        bucket = minutes // interval
        key = f"{bar_time:%Y-%m-%d}#{bucket}"

        if key != self._confirm_bucket_key:
            self._confirm_bucket_key = key
            self._confirm_bucket = []
        self._confirm_bucket.append(candle)

        # The bucket is complete when this candle is its last minute.
        if (minutes + 1) % interval != 0:
            return None

        bars = self._confirm_bucket
        return {
            "time": bars[0]["time"],
            "open": bars[0]["open"],
            "high": max(b["high"] for b in bars),
            "low": min(b["low"] for b in bars),
            "close": bars[-1]["close"],
        }

    def _stop_for(self, direction: str, entry: float, orb: OpeningRange) -> float:
        cfg = self.config
        if cfg.sl_mode == "or_opposite":
            return orb.low if direction == "LONG" else orb.high
        distance = orb.width * cfg.sl_fraction
        return entry - distance if direction == "LONG" else entry + distance

    def register_entry(self, signal: EntrySignal):
        self.trades_taken += 1
        self.directions_taken.append(signal.direction)
        self.phase = PHASE_IN_TRADE

    def register_exit(self):
        if self.trades_taken >= self.config.max_trades_per_day:
            self.phase = PHASE_DONE
        else:
            self.phase = PHASE_WAITING_BREAKOUT

    # ------------------------------------------------------------------ exits

    def check_exit(self, position: Position, index_price: float, now: datetime,
                   option_price: Optional[float] = None,
                   bar_high: Optional[float] = None,
                   bar_low: Optional[float] = None) -> Optional[ExitSignal]:
        """
        Evaluate exit conditions for an open position.

        `bar_high`/`bar_low` let the backtester detect intrabar touches; live
        callers pass ticks and can omit them. When a bar could have hit both the
        stop and the target, the stop is assumed to have come first.
        """
        cfg = self.config
        high = bar_high if bar_high is not None else index_price
        low = bar_low if bar_low is not None else index_price

        if now.time() >= cfg.square_off_time:
            return ExitSignal("squareoff", index_price)

        self._update_trailing(position, high, low)

        if position.is_long:
            if low <= position.stop_index:
                return ExitSignal(self._stop_reason(position), position.stop_index)
            if high >= position.target_index:
                return ExitSignal("target", position.target_index)
        else:
            if high >= position.stop_index:
                return ExitSignal(self._stop_reason(position), position.stop_index)
            if low <= position.target_index:
                return ExitSignal("target", position.target_index)

        # Premium stop: protects against decay/IV crush that the index cannot show.
        if option_price is not None and position.entry_option_price > 0 and cfg.option_sl_pct > 0:
            floor_price = position.entry_option_price * (1 - cfg.option_sl_pct / 100.0)
            if option_price <= floor_price:
                return ExitSignal("premium_sl", index_price)

        return None

    def _stop_reason(self, position: Position) -> str:
        return "breakeven_stop" if position.breakeven_done else "stoploss"

    def _update_trailing(self, position: Position, high: float, low: float):
        cfg = self.config
        favourable = high if position.is_long else low
        if position.is_long:
            position.best_index = max(position.best_index, favourable)
        else:
            position.best_index = min(position.best_index, favourable)

        best_r = position.r_multiple(position.best_index)

        if cfg.breakeven_after_r > 0 and not position.breakeven_done and best_r >= cfg.breakeven_after_r:
            position.stop_index = position.entry_index
            position.breakeven_done = True

        if cfg.trail_r > 0 and best_r > cfg.trail_r:
            offset = cfg.trail_r * position.risk_points
            trailed = (position.best_index - offset) if position.is_long \
                else (position.best_index + offset)
            if position.is_long:
                position.stop_index = max(position.stop_index, trailed)
            else:
                position.stop_index = min(position.stop_index, trailed)


def _minutes(count: int):
    from datetime import timedelta
    return timedelta(minutes=count)
