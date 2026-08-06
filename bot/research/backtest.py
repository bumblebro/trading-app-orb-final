"""
Research backtester for the ORB strategy.

Drives the exact `OrbStrategy` engine the live bot uses, over 1-minute NIFTY
index history, and prices the option leg with Black-Scholes so that theta decay
and moneyness are reflected in the P&L.

Usage:
    python research/backtest.py --run                  # single run, default config
    python research/backtest.py --sweep quick          # parameter search
    python research/backtest.py --run --from 2019-01-01 --to 2026-04-08

Modelling caveats (the index feed carries no option data):
  * Premiums are theoretical, using realised-volatility-based IV.
  * Weekly expiries are assumed; NIFTY weeklies only existed from Feb 2019, so
    the default analysis window starts there.
  * Fills assume the stop is hit before the target when a bar spans both.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import math
import os
import pickle
import sys
import time as _time
from array import array
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from charges import calculate_charges  # noqa: E402
from option_pricing import (  # noqa: E402
    atm_strike, black_scholes, next_weekly_expiry, realised_volatility,
    time_to_expiry_years,
)
from strategy_orb import (  # noqa: E402
    PHASE_DONE, PHASE_SKIP_DAY, OrbConfig, OrbStrategy, Position,
)

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_CSV = os.path.join(BOT_DIR, "data", "nifty_sample.csv")
CACHE_PATH = os.path.join(BOT_DIR, "data", ".nifty_1min.cache")
CACHE_VERSION = 2

# NIFTY weekly options launched in Feb 2019; earlier premiums would be fiction.
ANALYSIS_START = "2019-01-01"

MINUTE_OFFSETS = [timedelta(minutes=m) for m in range(24 * 60)]


# --------------------------------------------------------------------- loading

@dataclass
class DayData:
    """
    One session's bars.

    OHLC is held in `array` buffers rather than Python lists: the sweep forks
    worker processes, and millions of individual float objects would defeat
    copy-on-write as soon as refcounting touched them.
    """

    date: str
    base: datetime              # midnight IST of this session
    minutes: "array"            # minute-of-day per bar (unsigned short)
    opens: "array"
    highs: "array"
    lows: "array"
    closes: "array"

    @property
    def close(self) -> float:
        return self.closes[-1]


def _new_day(date_str: str) -> DayData:
    return DayData(
        date=date_str,
        base=datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]),
                      tzinfo=IST),
        minutes=array("H"), opens=array("d"), highs=array("d"),
        lows=array("d"), closes=array("d"),
    )


def load_days(csv_path: str = DEFAULT_CSV, use_cache: bool = True) -> List[DayData]:
    if use_cache and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "rb") as fh:
                payload = pickle.load(fh)
            if payload.get("version") == CACHE_VERSION and payload.get("source") == csv_path:
                return payload["days"]
        except Exception:
            pass

    days: List[DayData] = []
    current: Optional[DayData] = None

    with open(csv_path, "r", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        idx = {name.strip().lower(): i for i, name in enumerate(header)}
        i_ts, i_o = idx["date"], idx["open"]
        i_h, i_l, i_c = idx["high"], idx["low"], idx["close"]

        for row in reader:
            try:
                ts = row[i_ts]
                date_str = ts[:10]
                hh = int(ts[11:13])
                mm = int(ts[14:16])
            except (IndexError, ValueError):
                continue

            if current is None or current.date != date_str:
                if current is not None and len(current.minutes) >= 30:
                    days.append(current)
                current = _new_day(date_str)

            try:
                o, h, l, c = float(row[i_o]), float(row[i_h]), float(row[i_l]), float(row[i_c])
            except (IndexError, ValueError):
                continue
            if c <= 0:
                continue

            current.minutes.append(hh * 60 + mm)
            current.opens.append(o)
            current.highs.append(h)
            current.lows.append(l)
            current.closes.append(c)

    if current is not None and len(current.minutes) >= 30:
        days.append(current)

    try:
        with open(CACHE_PATH, "wb") as fh:
            pickle.dump({"version": CACHE_VERSION, "source": csv_path, "days": days},
                        fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass

    return days


# ------------------------------------------------------------------ simulation

@dataclass
class SimParams:
    lot_size: int = 75
    lots: int = 1
    # Market orders on ATM weekly options cross a bid-ask of roughly 1% of
    # premium per side. Optimistic fills flatter the strategy badly: the edge
    # here survives 1% but is gone by 3%, so the default stays pessimistic.
    slippage_pct: float = 0.010
    min_slippage_pts: float = 1.00
    iv_lookback: int = 20


@dataclass
class TradeRecord:
    date: str
    direction: str
    option_type: str
    entry_time: str
    exit_time: str
    entry_index: float
    exit_index: float
    entry_premium: float
    exit_premium: float
    quantity: int
    gross_pnl: float
    charges: float
    net_pnl: float
    exit_reason: str
    orb_range: float
    risk_points: float
    r_multiple: float


def _bar_dict(day: DayData, i: int) -> Dict:
    return {
        "time": day.base + MINUTE_OFFSETS[day.minutes[i]],
        "open": day.opens[i],
        "high": day.highs[i],
        "low": day.lows[i],
        "close": day.closes[i],
    }


def _apply_slippage(premium: float, params: SimParams, side: str) -> float:
    slip = max(premium * params.slippage_pct, params.min_slippage_pts)
    return round(premium + slip, 2) if side == "buy" else round(max(0.05, premium - slip), 2)


def simulate(days: List[DayData], config: OrbConfig,
             params: Optional[SimParams] = None,
             date_from: Optional[str] = None,
             date_to: Optional[str] = None) -> List[TradeRecord]:
    """Run the strategy across every session and return the executed trades."""
    params = params or SimParams()
    strategy = OrbStrategy(config)
    quantity = params.lot_size * params.lots

    trades: List[TradeRecord] = []
    daily_closes: List[float] = []
    square_off = config.square_off_time
    square_off_min = square_off.hour * 60 + square_off.minute

    for day in days:
        # The IV estimate only uses sessions strictly before the current one.
        iv = realised_volatility(daily_closes, params.iv_lookback) if daily_closes else 0.15
        daily_closes.append(day.close)
        if len(daily_closes) > params.iv_lookback + 5:
            daily_closes.pop(0)

        if date_from and day.date < date_from:
            continue
        if date_to and day.date > date_to:
            break

        strategy.reset_day(day.date)
        position: Optional[Position] = None
        strike = 0.0
        expiry: Optional[datetime] = None
        entry_record: Dict = {}

        n = len(day.minutes)
        for i in range(n):
            minute = day.minutes[i]
            close = day.closes[i]
            bar_time = day.base + MINUTE_OFFSETS[minute]

            if position is not None:
                quote = black_scholes(close, strike,
                                      time_to_expiry_years(bar_time, expiry),
                                      iv, position_option_type(position))
                exit_signal = strategy.check_exit(
                    position, close, bar_time,
                    option_price=quote.price,
                    bar_high=day.highs[i], bar_low=day.lows[i],
                )
                if exit_signal is not None:
                    exit_index = exit_signal.index_price
                    exit_quote = black_scholes(
                        exit_index, strike, time_to_expiry_years(bar_time, expiry),
                        iv, position_option_type(position))
                    exit_premium = _apply_slippage(exit_quote.price, params, "sell")

                    gross = round((exit_premium - position.entry_option_price) * quantity, 2)
                    fees = calculate_charges(position.entry_option_price,
                                             exit_premium, quantity)["total_charges"]
                    trades.append(TradeRecord(
                        date=day.date,
                        direction=position.direction,
                        option_type=position_option_type(position),
                        entry_time=entry_record["time"],
                        exit_time=bar_time.strftime("%H:%M"),
                        entry_index=round(position.entry_index, 2),
                        exit_index=round(exit_index, 2),
                        entry_premium=position.entry_option_price,
                        exit_premium=exit_premium,
                        quantity=quantity,
                        gross_pnl=gross,
                        charges=fees,
                        net_pnl=round(gross - fees, 2),
                        exit_reason=exit_signal.reason,
                        orb_range=entry_record["orb_range"],
                        risk_points=round(position.risk_points, 2),
                        r_multiple=round(position.r_multiple(exit_index), 3),
                    ))
                    position = None
                    strategy.register_exit()
                continue

            if minute >= square_off_min:
                break
            # Once the day is rejected or its trade budget is spent there is
            # nothing left to evaluate, so skip the remaining bars.
            if strategy.phase in (PHASE_SKIP_DAY, PHASE_DONE):
                break

            signal = strategy.on_candle(_bar_dict(day, i), in_trade=False)
            if signal is None:
                continue

            expiry = next_weekly_expiry(bar_time)
            strike = atm_strike(signal.index_price)
            entry_quote = black_scholes(
                signal.index_price, strike,
                time_to_expiry_years(bar_time, expiry), iv, signal.option_type)
            entry_premium = _apply_slippage(entry_quote.price, params, "buy")

            position = Position(
                direction=signal.direction,
                entry_index=signal.index_price,
                stop_index=signal.stop_index,
                target_index=signal.target_index,
                risk_points=signal.risk_points,
                entry_option_price=entry_premium,
                entry_time=bar_time,
            )
            entry_record = {
                "time": bar_time.strftime("%H:%M"),
                "orb_range": round(signal.orb_range, 2),
            }
            strategy.register_entry(signal)

        # Anything still open when the session ends is closed at the last print.
        if position is not None:
            last_time = day.base + MINUTE_OFFSETS[day.minutes[n - 1]]
            exit_index = day.closes[n - 1]
            exit_quote = black_scholes(exit_index, strike,
                                       time_to_expiry_years(last_time, expiry),
                                       iv, position_option_type(position))
            exit_premium = _apply_slippage(exit_quote.price, params, "sell")
            gross = round((exit_premium - position.entry_option_price) * quantity, 2)
            fees = calculate_charges(position.entry_option_price, exit_premium,
                                     quantity)["total_charges"]
            trades.append(TradeRecord(
                date=day.date, direction=position.direction,
                option_type=position_option_type(position),
                entry_time=entry_record["time"], exit_time=last_time.strftime("%H:%M"),
                entry_index=round(position.entry_index, 2), exit_index=round(exit_index, 2),
                entry_premium=position.entry_option_price, exit_premium=exit_premium,
                quantity=quantity, gross_pnl=gross, charges=fees,
                net_pnl=round(gross - fees, 2), exit_reason="squareoff",
                orb_range=entry_record["orb_range"],
                risk_points=round(position.risk_points, 2),
                r_multiple=round(position.r_multiple(exit_index), 3),
            ))

    return trades


def position_option_type(position: Position) -> str:
    return "CE" if position.is_long else "PE"


# --------------------------------------------------------------------- metrics

def summarise(trades: List[TradeRecord], label: str = "") -> Dict:
    if not trades:
        return {"label": label, "trades": 0, "net_pnl": 0.0, "win_rate": 0.0,
                "profit_factor": 0.0, "expectancy": 0.0, "max_drawdown": 0.0,
                "avg_r": 0.0, "sharpe": 0.0, "best_day": 0.0, "worst_day": 0.0}

    pnls = [t.net_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    by_day: Dict[str, float] = {}
    for t in trades:
        by_day[t.date] = by_day.get(t.date, 0.0) + t.net_pnl
    day_pnls = list(by_day.values())
    mean_day = sum(day_pnls) / len(day_pnls)
    if len(day_pnls) > 1:
        var = sum((d - mean_day) ** 2 for d in day_pnls) / (len(day_pnls) - 1)
        sd = math.sqrt(var)
        sharpe = (mean_day / sd * math.sqrt(252)) if sd > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "label": label,
        "trades": len(trades),
        "trading_days": len(by_day),
        "net_pnl": round(sum(pnls), 2),
        "win_rate": round(len(wins) / len(pnls) * 100, 1),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else float("inf"),
        "expectancy": round(sum(pnls) / len(pnls), 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "max_drawdown": round(max_dd, 2),
        "avg_r": round(sum(t.r_multiple for t in trades) / len(trades), 3),
        "sharpe": round(sharpe, 2),
        "best_day": round(max(day_pnls), 2),
        "worst_day": round(min(day_pnls), 2),
    }


def yearly_breakdown(trades: List[TradeRecord]) -> List[Dict]:
    buckets: Dict[str, List[TradeRecord]] = {}
    for t in trades:
        buckets.setdefault(t.date[:4], []).append(t)
    rows = []
    for year in sorted(buckets):
        s = summarise(buckets[year], year)
        rows.append({"year": year, "trades": s["trades"], "net_pnl": s["net_pnl"],
                     "win_rate": s["win_rate"], "profit_factor": s["profit_factor"],
                     "max_drawdown": s["max_drawdown"]})
    return rows


def exit_breakdown(trades: List[TradeRecord]) -> List[Dict]:
    buckets: Dict[str, List[float]] = {}
    for t in trades:
        buckets.setdefault(t.exit_reason, []).append(t.net_pnl)
    rows = []
    for reason, pnls in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        rows.append({"reason": reason, "count": len(pnls),
                     "net_pnl": round(sum(pnls), 2),
                     "avg": round(sum(pnls) / len(pnls), 2)})
    return rows


# ----------------------------------------------------------------------- sweeps

def _sweep_space(name: str) -> List[Dict]:
    if name == "quick":
        space = {
            "or_minutes": [15, 30, 45],
            "entry_trigger": ["close", "touch"],
            "sl_mode": ["or_fraction", "or_opposite"],
            "target_r": [1.5, 2.0, 3.0],
        }
    elif name == "full":
        space = {
            "or_minutes": [15, 30, 45, 60],
            "entry_trigger": ["close", "touch"],
            "confirm_interval_mins": [1, 5],
            "breakout_buffer_pct": [0.0, 0.05, 0.15],
            "sl_mode": ["or_fraction", "or_opposite"],
            "sl_fraction": [0.35, 0.5, 0.75],
            "target_r": [1.5, 2.0, 3.0],
            "breakeven_after_r": [0.0, 1.0],
        }
    elif name == "risk":
        space = {
            "target_r": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
            "breakeven_after_r": [0.0, 0.75, 1.0, 1.5],
            "trail_r": [0.0, 1.0, 1.5],
            "option_sl_pct": [25.0, 35.0, 50.0],
        }
    elif name == "filters":
        space = {
            "min_or_pct": [0.0, 0.15, 0.25, 0.35],
            "max_or_pct": [0.75, 1.0, 1.5, 5.0],
            "entry_cutoff": ["11:00", "12:00", "13:30", "15:00"],
            "breakout_buffer_pct": [0.0, 0.05, 0.15, 0.30],
        }
    elif name == "structure":
        space = {
            "or_minutes": [15, 30, 45, 60],
            "entry_trigger": ["close", "touch"],
            "confirm_interval_mins": [1, 3, 5],
        }
    elif name == "exits":
        # Explores how far to let winners run and whether stop management helps.
        space = {
            "target_r": [2.0, 3.0, 4.0, 5.0, 6.0],
            "breakeven_after_r": [0.0, 1.0, 1.5, 2.0],
            "trail_r": [0.0, 1.0, 2.0],
            "option_sl_pct": [25.0, 35.0, 50.0, 100.0],
        }
    else:
        raise SystemExit(f"unknown sweep space: {name}")

    keys = list(space)
    combos: List[Dict] = [{}]
    for key in keys:
        combos = [dict(c, **{key: v}) for c in combos for v in space[key]]
    return combos


_WORKER_STATE: Dict = {}


def _init_worker(days, base, params, date_from, date_to, is_end, oos_start):
    _WORKER_STATE.update(days=days, base=base, params=params, date_from=date_from,
                         date_to=date_to, is_end=is_end, oos_start=oos_start)


def _evaluate_combo(overrides: Dict) -> Dict:
    st = _WORKER_STATE
    config = replace(st["base"], **overrides)
    # One pass over the whole window; the in/out-of-sample split is a filter on
    # the resulting trades, which is equivalent because sessions are independent
    # and the volatility estimate always warms up from the start of history.
    trades = simulate(st["days"], config, st["params"], st["date_from"], st["date_to"])
    is_trades = [t for t in trades if t.date <= st["is_end"]]
    oos_trades = [t for t in trades if t.date >= st["oos_start"]]
    return {
        "params": overrides,
        "is": summarise(is_trades, "IS"),
        "oos": summarise(oos_trades, "OOS"),
        "all": summarise(trades, "ALL"),
    }


def run_sweep(days: List[DayData], base: OrbConfig, space: str,
              is_end: str, oos_start: str, params: SimParams,
              date_from: str, date_to: str, workers: int = 0) -> List[Dict]:
    combos = _sweep_space(space)
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"Sweeping {len(combos)} combinations on {workers} workers "
          f"(in-sample {date_from}..{is_end}, out-of-sample {oos_start}..{date_to})",
          flush=True)

    started = _time.time()
    results: List[Dict] = []
    init_args = (days, base, params, date_from, date_to, is_end, oos_start)

    if workers == 1:
        _init_worker(*init_args)
        iterator = (_evaluate_combo(c) for c in combos)
    else:
        import multiprocessing as mp
        # fork lets workers share the parsed history without re-reading it;
        # freezing the GC keeps collection from dirtying those shared pages.
        gc.freeze()
        gc.disable()
        ctx = mp.get_context("fork")
        pool = ctx.Pool(workers, initializer=_init_worker, initargs=init_args)
        iterator = pool.imap_unordered(_evaluate_combo, combos, chunksize=1)

    for n, result in enumerate(iterator, 1):
        results.append(result)
        if n % 10 == 0 or n == len(combos):
            rate = (_time.time() - started) / n
            print(f"  {n}/{len(combos)} done ({rate:.1f}s/combo, "
                  f"~{rate * (len(combos) - n) / 60:.1f} min left)", flush=True)

    if workers > 1:
        pool.close()
        pool.join()

    results.sort(key=lambda r: r["is"]["net_pnl"], reverse=True)
    return results


# -------------------------------------------------------------------------- cli

def _print_report(trades: List[TradeRecord], config: OrbConfig, title: str):
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")
    print("Config: " + json.dumps({
        "or_minutes": config.or_minutes, "entry_trigger": config.entry_trigger,
        "confirm_interval_mins": config.confirm_interval_mins,
        "breakout_buffer_pct": config.breakout_buffer_pct,
        "min_or_pct": config.min_or_pct, "max_or_pct": config.max_or_pct,
        "sl_mode": config.sl_mode, "sl_fraction": config.sl_fraction,
        "target_r": config.target_r, "breakeven_after_r": config.breakeven_after_r,
        "trail_r": config.trail_r, "option_sl_pct": config.option_sl_pct,
        "entry_cutoff": config.entry_cutoff,
        "max_trades_per_day": config.max_trades_per_day,
    }))

    stats = summarise(trades, "ALL")
    print(f"\nTrades {stats['trades']}  |  Trading days {stats['trading_days']}")
    print(f"Net P&L Rs {stats['net_pnl']:,.0f}  |  Win rate {stats['win_rate']}%  "
          f"|  Profit factor {stats['profit_factor']}")
    print(f"Expectancy Rs {stats['expectancy']:,.0f}/trade  |  Avg R {stats['avg_r']}  "
          f"|  Sharpe {stats['sharpe']}")
    print(f"Avg win Rs {stats['avg_win']:,.0f}  |  Avg loss Rs {stats['avg_loss']:,.0f}  "
          f"|  Max DD Rs {stats['max_drawdown']:,.0f}")

    print("\nBy year:")
    print(f"  {'year':<6}{'trades':>8}{'net P&L':>14}{'win%':>8}{'PF':>8}{'maxDD':>14}")
    for row in yearly_breakdown(trades):
        print(f"  {row['year']:<6}{row['trades']:>8}{row['net_pnl']:>14,.0f}"
              f"{row['win_rate']:>8}{row['profit_factor']:>8}{row['max_drawdown']:>14,.0f}")

    print("\nBy exit reason:")
    for row in exit_breakdown(trades):
        print(f"  {row['reason']:<18}{row['count']:>6}{row['net_pnl']:>14,.0f}"
              f"{row['avg']:>12,.0f} avg")


def main():
    ap = argparse.ArgumentParser(description="ORB strategy backtester")
    ap.add_argument("--run", action="store_true", help="single backtest run")
    ap.add_argument("--sweep", metavar="SPACE",
                    help="parameter sweep: quick | full | risk | filters")
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--from", dest="date_from", default=ANALYSIS_START)
    ap.add_argument("--to", dest="date_to", default="2026-12-31")
    ap.add_argument("--is-end", default="2023-12-31", help="in-sample end date")
    ap.add_argument("--oos-start", default="2024-01-01", help="out-of-sample start")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out", help="write sweep results as JSON")
    ap.add_argument("--config", help="JSON dict of OrbConfig overrides")
    ap.add_argument("--lots", type=int, default=1)
    ap.add_argument("--lot-size", type=int, default=65)
    ap.add_argument("--trades-csv", help="write executed trades to CSV")
    ap.add_argument("--workers", type=int, default=0, help="0 = auto")
    args = ap.parse_args()

    t0 = _time.time()
    days = load_days(args.csv)
    print(f"Loaded {len(days)} sessions ({days[0].date} .. {days[-1].date}) "
          f"in {_time.time() - t0:.1f}s", flush=True)

    base = OrbConfig()
    if args.config:
        base = replace(base, **json.loads(args.config))
    params = SimParams(lot_size=args.lot_size, lots=args.lots)

    if args.sweep:
        results = run_sweep(days, base, args.sweep, args.is_end, args.oos_start,
                            params, args.date_from, args.date_to, args.workers)
        print(f"\nTop {args.top} by in-sample net P&L "
              f"(OOS shown for honesty, not used for ranking):\n")
        header = (f"{'#':<4}{'IS net':>12}{'IS PF':>8}{'IS win%':>9}{'IS n':>7}"
                  f"{'OOS net':>12}{'OOS PF':>8}{'OOS n':>7}  params")
        print(header)
        for i, r in enumerate(results[:args.top], 1):
            print(f"{i:<4}{r['is']['net_pnl']:>12,.0f}{r['is']['profit_factor']:>8}"
                  f"{r['is']['win_rate']:>9}{r['is']['trades']:>7}"
                  f"{r['oos']['net_pnl']:>12,.0f}{r['oos']['profit_factor']:>8}"
                  f"{r['oos']['trades']:>7}  {json.dumps(r['params'])}")
        if args.out:
            with open(args.out, "w") as fh:
                json.dump(results, fh, indent=2)
            print(f"\nFull results written to {args.out}")
        return

    if args.run or True:
        trades = simulate(days, base, params, args.date_from, args.date_to)
        _print_report(trades, base, f"ORB backtest {args.date_from} .. {args.date_to}")

        is_trades = [t for t in trades if t.date <= args.is_end]
        oos_trades = [t for t in trades if t.date >= args.oos_start]
        print("\nIn-sample vs out-of-sample:")
        for stats in (summarise(is_trades, f"IS  {args.date_from}..{args.is_end}"),
                      summarise(oos_trades, f"OOS {args.oos_start}..{args.date_to}")):
            print(f"  {stats['label']:<28} n={stats['trades']:<5} "
                  f"net=Rs {stats['net_pnl']:>12,.0f}  PF={stats['profit_factor']:<7} "
                  f"win={stats['win_rate']}%  DD=Rs {stats['max_drawdown']:,.0f}")

        if args.trades_csv:
            with open(args.trades_csv, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["date", "direction", "type", "entry_time", "exit_time",
                                 "entry_index", "exit_index", "entry_premium",
                                 "exit_premium", "qty", "gross_pnl", "charges",
                                 "net_pnl", "exit_reason", "orb_range", "risk_pts", "r"])
                for t in trades:
                    writer.writerow([t.date, t.direction, t.option_type, t.entry_time,
                                     t.exit_time, t.entry_index, t.exit_index,
                                     t.entry_premium, t.exit_premium, t.quantity,
                                     t.gross_pnl, t.charges, t.net_pnl, t.exit_reason,
                                     t.orb_range, t.risk_points, t.r_multiple])
            print(f"\nTrades written to {args.trades_csv}")


if __name__ == "__main__":
    main()
