"""
SQLite persistence for trades, settings and signal logs.

Schema is ORB-specific. A database written by the previous Supertrend/EMA
strategy is detected on startup and moved aside to `trades_legacy` rather than
being deleted, so its history stays available for inspection but does not
pollute ORB statistics.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from charges import calculate_charges  # re-exported for callers

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.db")
IST = timezone(timedelta(hours=5, minutes=30))

# Every reason the bot is allowed to close a position with. Kept in sync with
# strategy_orb / trading_bot; the CHECK constraint enforces it.
EXIT_REASONS = (
    "target",
    "stoploss",
    "breakeven_stop",
    "premium_sl",
    "squareoff",
    "manual",
    "kill_switch",
    "session_end",
)

_EXIT_REASON_SQL = ", ".join(f"'{r}'" for r in EXIT_REASONS)

TRADES_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('CE', 'PE')),
    direction TEXT CHECK(direction IN ('LONG', 'SHORT')),
    strike_price INTEGER NOT NULL,
    trading_symbol TEXT,
    token TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity INTEGER NOT NULL,
    lot_size INTEGER NOT NULL DEFAULT 75,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'win', 'loss')),
    exit_reason TEXT CHECK(exit_reason IS NULL OR exit_reason IN ({_EXIT_REASON_SQL})),
    mode TEXT NOT NULL DEFAULT 'paper' CHECK(mode IN ('paper', 'live')),

    -- Index-level ORB context
    orb_high REAL,
    orb_low REAL,
    orb_range REAL,
    underlying_entry_price REAL,
    underlying_exit_price REAL,
    stop_index REAL,
    target_index REAL,
    risk_points REAL,

    -- Option-level risk levels
    stop_loss REAL,
    target REAL,

    -- Accounting
    pnl REAL DEFAULT 0,
    net_pnl REAL DEFAULT 0,
    brokerage REAL DEFAULT 0,
    stt REAL DEFAULT 0,
    exc_charges REAL DEFAULT 0,
    gst REAL DEFAULT 0,
    capital_used REAL,
    total_capital REAL,

    -- Fill vs estimate (live). Paper usually has slip ~0.
    estimated_entry_price REAL,
    estimated_exit_price REAL,
    entry_slippage REAL,
    exit_slippage REAL,

    entry_order_ids TEXT,
    exit_order_ids TEXT,
    exit_time TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

# Added after first ship; created via ALTER on existing DBs.
_TRADE_COLUMN_MIGRATIONS = (
    ("estimated_entry_price", "REAL"),
    ("estimated_exit_price", "REAL"),
    ("entry_slippage", "REAL"),
    ("exit_slippage", "REAL"),
)

SIGNAL_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    price REAL,
    orb_high REAL,
    orb_low REAL,
    orb_range REAL,
    phase TEXT,
    signal TEXT,
    skip_reason TEXT
)
"""

# Columns that only ever existed in the retired Supertrend strategy.
LEGACY_COLUMNS = {"supertrend_at_entry", "adx_at_entry", "ema_short_at_entry"}


def get_ist_now() -> datetime:
    return datetime.now(IST)


def get_connection(db_path: str = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.OperationalError:
        pass
    return conn


def _drop_retired_settings(conn):
    """
    Remove tuning left over from the retired strategy so the ORB defaults apply.
    Broker credentials and capital settings are keys of DEFAULT_SETTINGS and survive.
    """
    try:
        stored = {r["key"] for r in conn.execute("SELECT key FROM settings")}
    except sqlite3.OperationalError:
        return

    retired = stored - set(DEFAULT_SETTINGS)
    # These exist under both strategies but carry values tuned for the old one.
    retired |= {"option_sl_pct", "square_off_time", "fixed_lots",
                "position_sizing_mode", "playback_speed"}

    for key in retired:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def _table_columns(conn, table: str) -> set:
    try:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def init_db(db_path: str = None):
    """Create tables, archiving an incompatible legacy trades table if present."""
    conn = get_connection(db_path)
    try:
        existing = _table_columns(conn, "trades")
        if existing and (existing & LEGACY_COLUMNS):
            suffix = get_ist_now().strftime("%Y%m%d%H%M%S")
            conn.execute(f"ALTER TABLE trades RENAME TO trades_legacy_{suffix}")
            conn.execute("DROP TABLE IF EXISTS signal_logs")
            _drop_retired_settings(conn)
            conn.commit()

        conn.execute(TRADES_SCHEMA)
        conn.execute(SIGNAL_LOG_SCHEMA)
        _ensure_trade_columns(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT,
                category TEXT,
                message TEXT,
                details TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(mode)")
        conn.commit()
    finally:
        conn.close()


def _ensure_trade_columns(conn):
    """Add new trade columns on older databases without rebuilding the table."""
    existing = _table_columns(conn, "trades")
    for name, col_type in _TRADE_COLUMN_MIGRATIONS:
        if name not in existing:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {col_type}")


# ------------------------------------------------------------------- trades

_INSERT_FIELDS = (
    "date", "time", "type", "direction", "strike_price", "trading_symbol", "token",
    "entry_price", "quantity", "lot_size", "status", "mode",
    "orb_high", "orb_low", "orb_range", "underlying_entry_price",
    "stop_index", "target_index", "risk_points", "stop_loss", "target",
    "capital_used", "total_capital",
    "estimated_entry_price", "entry_slippage",
    "entry_order_ids",
)


def insert_trade(trade: Dict[str, Any], timestamp: datetime = None, db_path: str = None) -> int:
    now = timestamp or get_ist_now()
    values = dict(trade)
    values.setdefault("date", now.strftime("%Y-%m-%d"))
    values.setdefault("time", now.strftime("%H:%M:%S"))
    values.setdefault("status", "open")
    values.setdefault("mode", "paper")

    columns = ", ".join(_INSERT_FIELDS)
    placeholders = ", ".join("?" for _ in _INSERT_FIELDS)

    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            f"INSERT INTO trades ({columns}) VALUES ({placeholders})",
            [values.get(f) for f in _INSERT_FIELDS],
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_trade(trade_id: int, updates: Dict[str, Any], db_path: str = None):
    if not updates:
        return
    conn = get_connection(db_path)
    try:
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE trades SET {sets} WHERE id = ?",
                     list(updates.values()) + [trade_id])
        conn.commit()
    finally:
        conn.close()


def close_trade(trade_id: int, exit_price: float, exit_reason: str,
                timestamp: datetime = None, underlying_exit_price: float = None,
                exit_order_ids: str = None, estimated_exit_price: float = None,
                db_path: str = None) -> float:
    """Close a trade, booking charges. Returns net P&L."""
    if exit_reason not in EXIT_REASONS:
        raise ValueError(f"unknown exit_reason {exit_reason!r}; "
                         f"expected one of {EXIT_REASONS}")

    conn = get_connection(db_path)
    try:
        trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if trade is None:
            return 0.0

        gross_pnl = round((exit_price - trade["entry_price"]) * trade["quantity"], 2)
        fees = calculate_charges(trade["entry_price"], exit_price, trade["quantity"])
        net_pnl = round(gross_pnl - fees["total_charges"], 2)
        now = timestamp or get_ist_now()

        # Long options: exit slip > 0 means we sold below the pre-order mark.
        est_exit = estimated_exit_price
        exit_slip = None
        if est_exit is not None and est_exit > 0:
            exit_slip = round((float(est_exit) - float(exit_price)) * trade["quantity"], 2)

        conn.execute("""
            UPDATE trades SET
                exit_price = ?, underlying_exit_price = ?, pnl = ?, net_pnl = ?,
                brokerage = ?, stt = ?, exc_charges = ?, gst = ?,
                status = ?, exit_reason = ?, exit_time = ?, exit_order_ids = ?,
                estimated_exit_price = ?, exit_slippage = ?
            WHERE id = ?
        """, (
            exit_price, underlying_exit_price, gross_pnl, net_pnl,
            fees["brokerage"], fees["stt"], fees["exc_charges"], fees["gst"],
            "win" if net_pnl > 0 else "loss", exit_reason,
            now.strftime("%H:%M:%S"), exit_order_ids,
            est_exit, exit_slip, trade_id,
        ))
        conn.commit()
        return net_pnl
    finally:
        conn.close()


def get_active_trade(mode: str = None, db_path: str = None) -> Optional[Dict]:
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM trades WHERE status = 'open'"
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY id DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_trades(mode: str = None, date_from: str = None, date_to: str = None,
               limit: int = 100, db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM trades WHERE 1=1"
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        query += " ORDER BY date DESC, id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(query, params)]
    finally:
        conn.close()


def get_today_trades(mode: str = None, date_override: str = None, db_path: str = None) -> List[Dict]:
    target = date_override or get_ist_now().strftime("%Y-%m-%d")
    return get_trades(mode=mode, date_from=target, date_to=target, limit=100, db_path=db_path)


def get_today_pnl(mode: str = None, date_override: str = None, db_path: str = None) -> Dict:
    trades = get_today_trades(mode=mode, date_override=date_override, db_path=db_path)
    closed = [t for t in trades if t["status"] != "open"]
    total = sum(t["net_pnl"] if t["net_pnl"] is not None else (t["pnl"] or 0) for t in closed)
    wins = sum(1 for t in closed if t["status"] == "win")
    losses = sum(1 for t in closed if t["status"] == "loss")
    return {
        "total_pnl": round(total, 2),
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "open_trades": sum(1 for t in trades if t["status"] == "open"),
    }


def get_all_time_pnl(mode: str = None, date_from: str = None, date_to: str = None,
                     db_path: str = None) -> Dict:
    conn = get_connection(db_path)
    try:
        query = """
            SELECT SUM(pnl) AS gross_pnl,
                   SUM(COALESCE(net_pnl, pnl)) AS net_pnl,
                   SUM(COALESCE(brokerage,0) + COALESCE(stt,0)
                       + COALESCE(exc_charges,0) + COALESCE(gst,0)) AS total_charges,
                   COUNT(*) AS total_trades,
                   SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) AS losses
            FROM trades WHERE status != 'open'
        """
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        row = conn.execute(query, params).fetchone()
    finally:
        conn.close()

    trades = row["total_trades"] or 0
    wins = row["wins"] or 0
    return {
        "all_time_pnl": round(row["net_pnl"] or 0, 2),
        "all_time_gross_pnl": round(row["gross_pnl"] or 0, 2),
        "all_time_charges": round(row["total_charges"] or 0, 2),
        "all_time_trades": trades,
        "all_time_win_rate": round(wins / trades * 100, 1) if trades else 0.0,
        "wins": wins,
        "losses": row["losses"] or 0,
    }


def get_equity_curve(mode: str = None, limit: int = 500, db_path: str = None) -> List[Dict]:
    """Cumulative net P&L per trading day, oldest first."""
    conn = get_connection(db_path)
    try:
        query = """
            SELECT date, SUM(COALESCE(net_pnl, pnl)) AS pnl, COUNT(*) AS trades
            FROM trades WHERE status != 'open'
        """
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " GROUP BY date ORDER BY date ASC LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in conn.execute(query, params)]
    finally:
        conn.close()

    cumulative = 0.0
    for row in rows:
        cumulative += row["pnl"] or 0
        row["cumulative_pnl"] = round(cumulative, 2)
        row["pnl"] = round(row["pnl"] or 0, 2)
    return rows


def get_exit_reason_breakdown(mode: str = None, db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    try:
        query = """
            SELECT exit_reason, COUNT(*) AS count,
                   SUM(COALESCE(net_pnl, pnl)) AS net_pnl
            FROM trades WHERE status != 'open'
        """
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " GROUP BY exit_reason ORDER BY count DESC"
        return [
            {"reason": r["exit_reason"] or "unknown",
             "count": r["count"],
             "net_pnl": round(r["net_pnl"] or 0, 2)}
            for r in conn.execute(query, params)
        ]
    finally:
        conn.close()


def get_yearly_pnl(mode: str = None, db_path: str = None) -> List[Dict]:
    """Net P&L, trades and win rate grouped by calendar year (newest first)."""
    conn = get_connection(db_path)
    try:
        query = """
            SELECT substr(date, 1, 4) AS year,
                   SUM(COALESCE(net_pnl, pnl)) AS net_pnl,
                   COUNT(*) AS trades,
                   SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) AS losses
            FROM trades
            WHERE status != 'open' AND date IS NOT NULL AND length(date) >= 4
        """
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " GROUP BY substr(date, 1, 4) ORDER BY year DESC"
        rows = []
        for r in conn.execute(query, params):
            trades = r["trades"] or 0
            wins = r["wins"] or 0
            rows.append({
                "year": r["year"],
                "net_pnl": round(r["net_pnl"] or 0, 2),
                "trades": trades,
                "wins": wins,
                "losses": r["losses"] or 0,
                "win_rate": round(wins / trades * 100, 1) if trades else 0.0,
            })
        return rows
    finally:
        conn.close()


def get_last_trade_date(mode: str = None, db_path: str = None) -> Optional[str]:
    conn = get_connection(db_path)
    try:
        query = "SELECT date FROM trades WHERE status != 'open'"
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY date DESC, id DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        return row["date"] if row else None
    finally:
        conn.close()


def get_first_trade_date(mode: str = None, db_path: str = None) -> Optional[str]:
    conn = get_connection(db_path)
    try:
        query = "SELECT date FROM trades WHERE status != 'open'"
        params: List[Any] = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY date ASC, id ASC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        return row["date"] if row else None
    finally:
        conn.close()


def get_today_trade_count(date_override: str = None, mode: str = None, db_path: str = None) -> int:
    target = date_override or get_ist_now().strftime("%Y-%m-%d")
    conn = get_connection(db_path)
    try:
        query = "SELECT COUNT(*) AS c FROM trades WHERE date = ?"
        params: List[Any] = [target]
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        return conn.execute(query, params).fetchone()["c"]
    finally:
        conn.close()


def get_consecutive_losses(date_override: str = None, mode: str = None, db_path: str = None) -> int:
    target = date_override or get_ist_now().strftime("%Y-%m-%d")
    conn = get_connection(db_path)
    try:
        query = "SELECT status FROM trades WHERE date = ? AND status != 'open'"
        params: List[Any] = [target]
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY id DESC"
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    count = 0
    for row in rows:
        if row["status"] != "loss":
            break
        count += 1
    return count


# ----------------------------------------------------------------- settings

SECRET_KEYS = {"api_key", "pin", "totp_secret", "api_token"}

DEFAULT_SETTINGS = {
    # Broker credentials (never returned in plaintext over the API)
    "api_key": "", "client_id": "", "pin": "", "totp_secret": "",

    # Mode
    "trading_mode": "paper",
    "data_source": "playback",

    # ORB strategy — defaults validated by research/backtest.py over
    # 2019-2026 NIFTY data, chosen for in-sample/out-of-sample agreement
    # rather than peak in-sample return.
    "orb_or_minutes": "60",
    "orb_min_range_pct": "0.25",
    "orb_max_range_pct": "2.00",
    "orb_entry_trigger": "close",
    "orb_confirm_interval_mins": "3",
    "orb_breakout_buffer_pct": "0.05",
    "orb_entry_cutoff": "13:30",
    "orb_sl_mode": "or_opposite",
    "orb_sl_fraction": "0.50",
    "orb_target_r": "2.0",
    "orb_breakeven_after_r": "1.0",
    "orb_trail_r": "0",
    "orb_max_trades_per_day": "1",
    "orb_allow_reversal": "false",
    "option_sl_pct": "100.0",
    "square_off_time": "15:15",

    # Risk & sizing
    "position_sizing_mode": "fixed_lots",
    "fixed_lots": "1",
    "lot_size": "75",
    "min_lots": "1",
    "max_lots": "10",
    "risk_percent_per_trade": "2.0",
    "max_capital_per_trade_pct": "15.0",
    "max_daily_loss": "10000",
    "initial_capital": "500000",
    "paper_capital": "500000",

    # Backtest / playback
    "playback_file": "bot/data/nifty_sample.csv",
    "playback_speed": "500",
    "playback_start_date": "",
    "playback_end_date": "",
    "playback_period": "all",
}


def save_setting(key: str, value: Any, db_path: str = None):
    save_settings({key: value}, db_path=db_path)


def save_settings(settings: Dict[str, Any], db_path: str = None):
    conn = get_connection(db_path)
    try:
        for key, value in settings.items():
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                         (key, "" if value is None else str(value)))
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, db_path: str = None) -> str:
    try:
        conn = get_connection(db_path)
    except sqlite3.OperationalError:
        return DEFAULT_SETTINGS.get(key, "")
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        conn.close()
        init_db(db_path)
        conn = get_connection(db_path)
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def get_all_settings(db_path: str = None, redact_secrets: bool = False) -> Dict[str, str]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    finally:
        conn.close()

    settings = dict(DEFAULT_SETTINGS)
    for row in rows:
        settings[row["key"]] = row["value"]

    if redact_secrets:
        for key in SECRET_KEYS:
            if settings.get(key):
                # Confirm a value is stored without ever exposing it.
                settings[key] = "********"
    return settings


# --------------------------------------------------------------- signal log

def insert_signal_log(data: Dict[str, Any], timestamp: datetime = None, db_path: str = None):
    now = timestamp or get_ist_now()
    conn = get_connection(db_path)
    try:
        conn.execute("""
            INSERT INTO signal_logs
                (timestamp, price, orb_high, orb_low, orb_range, phase, signal, skip_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now.strftime("%Y-%m-%d %H:%M:%S"), data.get("price"),
            data.get("orb_high"), data.get("orb_low"), data.get("orb_range"),
            data.get("phase"), data.get("signal"), data.get("skip_reason"),
        ))
        conn.commit()
    finally:
        conn.close()


def clear_trade_data(db_path: str = None) -> bool:
    """Wipe trades, signal logs and system logs. Settings are preserved."""
    conn = get_connection(db_path)
    try:
        for table in ("trades", "signal_logs", "logs"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence "
                     "WHERE name IN ('trades', 'signal_logs', 'logs')")
        conn.commit()
        try:
            conn.execute("VACUUM")
        except sqlite3.Error:
            pass
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


init_db()
