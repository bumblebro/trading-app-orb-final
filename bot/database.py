"""
Database module for SQLite operations.
Manages trades, settings, and logs tables.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.db")

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now():
    return datetime.now(IST)


def get_connection(db_path: str = None) -> sqlite3.Connection:
    """Get SQLite connection with row factory."""
    target_path = db_path or DB_PATH
    # print(f"[DEBUG] Opening database at: {target_path}")
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str = None):
    """Initialize database tables."""
    conn = get_connection(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('CE', 'PE')),
            strike_price INTEGER NOT NULL,
            trading_symbol TEXT,
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity INTEGER NOT NULL,
            lot_size INTEGER NOT NULL DEFAULT 65,
            pnl REAL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed', 'win', 'loss')),
            exit_reason TEXT CHECK(exit_reason IN ('target', 'stoploss', 'manual', 'squareoff', NULL)),
            mode TEXT NOT NULL DEFAULT 'paper' CHECK(mode IN ('paper', 'live')),
            stop_loss REAL,
            target REAL,
            trailing_sl REAL,
            underlying_entry_price REAL,
            token TEXT,
            entry_quality REAL,
            orb_high REAL,
            orb_low REAL,
            orb_range REAL,
            breakout_price REAL,
            fib_entry_level TEXT,
            fib_entry_price REAL,
            fib_sl_price REAL,
            macd_at_entry REAL,
            trailing_sl_used INTEGER DEFAULT 0,
            trailing_sl_final REAL,
            rsi_at_entry REAL,
            vwap_at_entry REAL,
            capital_used REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            level TEXT NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            price REAL,
            supertrend REAL,
            supertrend_direction INTEGER,
            ema_short REAL,
            ema_long REAL,
            adx REAL,
            signal TEXT,
            skip_reason TEXT
        )
    """)

    # Migration: Add columns if they don't exist (for existing databases)
    for column, col_type in [
        ("underlying_entry_price", "REAL"),
        ("token", "TEXT"),
        ("entry_quality", "REAL"),
        ("orb_high", "REAL"),
        ("orb_low", "REAL"),
        ("orb_range", "REAL"),
        ("trailing_sl", "REAL"),
        ("breakout_price", "REAL"),
        ("fib_entry_level", "TEXT"),
        ("fib_entry_price", "REAL"),
        ("fib_sl_price", "REAL"),
        ("macd_at_entry", "REAL"),
        ("trailing_sl_used", "INTEGER DEFAULT 0"),
        ("trailing_sl_final", "REAL"),
        ("rsi_at_entry", "REAL"),
        ("vwap_at_entry", "REAL"),
        ("initial_risk_pts", "REAL"),
        ("trailing_activated", "INTEGER DEFAULT 0"),
        ("entry_type", "TEXT"),
        ("partial_booked", "INTEGER DEFAULT 0"),
        ("volume_at_entry", "REAL"),
        ("score_breakdown", "TEXT"),
        ("adx_at_entry", "REAL"),
        ("supertrend_at_entry", "REAL"),
        ("ema_short_at_entry", "REAL"),
        ("ema_long_at_entry", "REAL"),
        ("exit_time", "TEXT"),
        ("capital_used", "REAL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column likely already exists

    conn.commit()
    conn.close()


# --- Trade Operations ---

def insert_trade(trade: Dict[str, Any], timestamp: datetime = None, db_path: str = None) -> int:
    """Insert a new trade and return its ID."""
    conn = get_connection(db_path)
    now = timestamp or get_ist_now()
    cursor = conn.execute("""
        INSERT INTO trades (date, time, type, strike_price, trading_symbol, entry_price, 
                          quantity, lot_size, status, mode, stop_loss, target, underlying_entry_price,
                          token, entry_quality, orb_high, orb_low, orb_range,
                          breakout_price, fib_entry_level, fib_entry_price, fib_sl_price,
                          macd_at_entry, trailing_sl_used, rsi_at_entry, vwap_at_entry,
                          entry_type, partial_booked, volume_at_entry, score_breakdown,
                          adx_at_entry, supertrend_at_entry, ema_short_at_entry, ema_long_at_entry, exit_time, capital_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.get("date", now.strftime("%Y-%m-%d")),
        trade.get("time", now.strftime("%H:%M:%S")),
        trade["type"],
        trade["strike_price"],
        trade.get("trading_symbol", ""),
        trade["entry_price"],
        trade["quantity"],
        trade.get("lot_size", 65),
        trade.get("status", "open"),
        trade.get("mode", "paper"),
        trade.get("stop_loss"),
        trade.get("target"),
        trade.get("underlying_entry_price"),
        trade.get("token"),
        trade.get("entry_quality"),
        trade.get("orb_high"),
        trade.get("orb_low"),
        trade.get("orb_range"),
        trade.get("breakout_price"),
        trade.get("fib_entry_level"),
        trade.get("fib_entry_price"),
        trade.get("fib_sl_price"),
        trade.get("macd_at_entry"),
        trade.get("trailing_sl_used", 0),
        trade.get("rsi_at_entry"),
        trade.get("vwap_at_entry"),
        trade.get("entry_type", "breakout"),
        trade.get("partial_booked", 0),
        trade.get("volume_at_entry"),
        trade.get("score_breakdown"),
        trade.get("adx_at_entry"),
        trade.get("supertrend_at_entry"),
        trade.get("ema_short_at_entry"),
        trade.get("ema_long_at_entry"),
        trade.get("exit_time"),
        trade.get("capital_used"),
    ))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def update_trade(trade_id: int, updates: Dict[str, Any], db_path: str = None):
    """Update a trade by ID."""
    conn = get_connection(db_path)
    set_clauses = []
    values = []
    for key, value in updates.items():
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(trade_id)
    conn.execute(f"UPDATE trades SET {', '.join(set_clauses)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def close_trade(trade_id: int, exit_price: float, exit_reason: str, timestamp: datetime = None, db_path: str = None):
    """Close a trade with exit price and calculate P&L."""
    conn = get_connection(db_path)
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if trade:
        pnl = (exit_price - trade["entry_price"]) * trade["quantity"]
        # For PE, profit is when price goes down (but we're buying the option, so it's still exit - entry)
        status = "win" if pnl > 0 else "loss"

        # In playback, we record the exit_date/exit_time to match the historical period
        now = timestamp or get_ist_now()

        conn.execute("""
            UPDATE trades SET exit_price = ?, pnl = ?, status = ?, exit_reason = ?, exit_time = ?
            WHERE id = ?
        """, (exit_price, pnl, status, exit_reason, now.strftime("%H:%M:%S"), trade_id))
        conn.commit()
    conn.close()
    return pnl if trade else 0


def insert_signal_log(data: Dict[str, Any], timestamp: datetime = None, db_path: str = None):
    """Log indicator values and signal decisions for every tick."""
    conn = get_connection(db_path)
    now = timestamp or get_ist_now()
    conn.execute("""
        INSERT INTO signal_logs (timestamp, price, supertrend, supertrend_direction, 
                               ema_short, ema_long, adx, signal, skip_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now.strftime("%Y-%m-%d %H:%M:%S"),
        data.get("price"),
        data.get("supertrend"),
        data.get("supertrend_direction"),
        data.get("ema_short"),
        data.get("ema_long"),
        data.get("adx"),
        data.get("signal"),
        data.get("skip_reason")
    ))
    conn.commit()
    conn.close()


def get_active_trade(db_path: str = None) -> Optional[Dict]:
    """Get the current open trade."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM trades WHERE status = 'open' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def get_trades(mode: str = None, date_from: str = None, date_to: str = None,
               limit: int = 100, db_path: str = None) -> List[Dict]:
    """Get trade history with optional filters."""
    conn = get_connection(db_path)
    query = "SELECT * FROM trades WHERE 1=1"
    params = []

    if mode:
        query += " AND mode = ?"
        params.append(mode)
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_today_trades(mode: str = None, date_override: str = None, db_path: str = None) -> List[Dict]:
    """Get today's trades (or trades for a specific date)."""
    target_date = date_override or get_ist_now().strftime("%Y-%m-%d")
    return get_trades(mode=mode, date_from=target_date, date_to=target_date, limit=100, db_path=db_path)


def get_today_pnl(mode: str = None, date_override: str = None, db_path: str = None) -> Dict:
    """Get today's P&L summary."""
    trades = get_today_trades(mode=mode, date_override=date_override, db_path=db_path)
    total_pnl = sum(t.get("pnl", 0) for t in trades if t["status"] != "open")
    wins = sum(1 for t in trades if t["status"] == "win")
    losses = sum(1 for t in trades if t["status"] == "loss")
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0

    return {
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "open_trades": sum(1 for t in trades if t["status"] == "open")
    }


def get_last_trade_date(mode: str = None, db_path: str = None) -> Optional[str]:
    """Get the date of the last closed trade."""
    conn = get_connection(db_path)
    query = "SELECT date FROM trades WHERE status != 'open'"
    params = []
    if mode:
        query += " AND mode = ?"
        params.append(mode)
    query += " ORDER BY date DESC, id DESC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    conn.close()
    return row["date"] if row else None


def get_first_trade_date(mode: str = None, db_path: str = None) -> Optional[str]:
    """Get the date of the first closed trade."""
    conn = get_connection(db_path)
    query = "SELECT date FROM trades WHERE status != 'open'"
    params = []
    if mode:
        query += " AND mode = ?"
        params.append(mode)
    query += " ORDER BY date ASC, id ASC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    conn.close()
    return row["date"] if row else None


def get_fixed_lot_pnl(mode: str = None, fixed_lots: int = 2, lot_size: int = 65, db_path: str = None) -> float:
    """Calculate what the P&L would have been with fixed lot sizing."""
    conn = get_connection(db_path)
    query = "SELECT SUM((exit_price - entry_price) * ? * ?) as pnl FROM trades WHERE status != 'open' AND entry_price IS NOT NULL AND exit_price IS NOT NULL"
    params = [fixed_lots, lot_size]
    if mode:
        query += " AND mode = ?"
        params.append(mode)
    row = conn.execute(query, params).fetchone()
    conn.close()
    return row["pnl"] or 0.0


def get_all_time_pnl(mode: str = None, date_from: str = None, date_to: str = None, db_path: str = None) -> Dict:
    """Get all-time P&L summary with optional filters."""
    conn = get_connection(db_path)
    # Only fetch closed/win/loss trades
    query = """
        SELECT 
            SUM(pnl) as total_pnl, 
            COUNT(*) as total_trades,
            SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) as losses
        FROM trades 
        WHERE status != 'open'
    """
    params = []

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
    conn.close()

    total_pnl = row["total_pnl"] or 0
    total_trades = row["total_trades"] or 0
    wins = row["wins"] or 0
    losses = row["losses"] or 0
    
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    return {
        "all_time_pnl": round(total_pnl, 2),
        "all_time_trades": total_trades,
        "all_time_win_rate": round(win_rate, 1),
        "wins": wins,
        "losses": losses
    }


def get_yearly_summary(mode: str = None, date_from: str = None, date_to: str = None, db_path: str = None) -> List[Dict]:
    """Get yearly P&L summary."""
    conn = get_connection(db_path)
    query = """
        SELECT 
            STRFTIME('%Y', date) as year,
            SUM(pnl) as pnl,
            COUNT(*) as trades,
            SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) as gross_profit,
            SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END) as gross_loss
        FROM trades
        WHERE status != 'open'
    """
    params = []
    if mode:
        query += " AND mode = ?"
        params.append(mode)
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    
    query += " GROUP BY year ORDER BY year DESC"
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_today_trade_count(date_override: str = None, db_path: str = None) -> int:
    """Get count of trades placed on a specific date (defaults to today)."""
    target_date = date_override or get_ist_now().strftime("%Y-%m-%d")
    conn = get_connection(db_path)
    row = conn.execute("SELECT COUNT(*) as count FROM trades WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    return row["count"] if row else 0


def get_consecutive_losses(date_override: str = None, db_path: str = None) -> int:
    """Get the number of consecutive losses from today's trades (or specific date)."""
    target_date = date_override or get_ist_now().strftime("%Y-%m-%d")
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT status FROM trades WHERE date = ? AND status != 'open' ORDER BY id DESC",
        (target_date,)
    ).fetchall()
    conn.close()

    count = 0
    for row in rows:
        if row["status"] == "loss":
            count += 1
        else:
            break
    return count


# --- Settings Operations ---

DEFAULT_SETTINGS = {
    # Angel One Credentials
    "api_key": "",
    "client_id": "",
    "pin": "",
    "totp_secret": "",
    # Trade Management
    "atm_delta": "0.5",
    "trailing_sl_enabled": "true",
    "max_trades_per_day": "2",
    "max_daily_loss": "10000",
    "signal_cutoff_time": "15:00",
    "square_off_time": "15:15",
    "lot_size": "65",
    # Capital & Risk
    "position_size_mode": "auto_compound",
    "fixed_lots": "2",
    "max_capital_risk_pct": "1",
    "trading_mode": "paper",
    "paper_capital": "100000",
    # Data Source
    "data_source": "smartapi",
    "playback_file": "bot/data/nifty_sample.csv",
    "playback_speed": "1",
    "playback_start_date": "",
    "playback_end_date": "",
    "playback_period": "all",
    "initial_capital": "100000",
    # Auto-Compounding Position Sizing
    "position_sizing_mode": "auto_compound", # options: "fixed_lots", "auto_compound"
    "risk_percent_per_trade": "5.0",
    "min_lots": "1",
    "max_lots": "",
    # Supertrend Strategy Parameters
    "supertrend_period": "10",
    "supertrend_multiplier": "3.0",
    "ema_short_period": "9",
    "ema_long_period": "21",
    "adx_threshold": "25",
    "max_sl_distance_pts": "50",
    "max_daily_loss": "10000", # New kill switch
}


def save_setting(key: str, value: str, db_path: str = None):
    """Save a setting (upsert)."""
    conn = get_connection(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def save_settings(settings: Dict[str, str], db_path: str = None):
    """Save multiple settings."""
    conn = get_connection(db_path)
    for key, value in settings.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )
    conn.commit()
    conn.close()


def get_setting(key: str, db_path: str = None) -> str:
    """Get a setting value."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        return row["value"]
    return DEFAULT_SETTINGS.get(key, "")


def get_all_settings(db_path: str = None) -> Dict[str, str]:
    """Get all settings merged with defaults."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    settings = dict(DEFAULT_SETTINGS)
    for row in rows:
        settings[row["key"]] = row["value"]
    return settings


# Initialize database on import
init_db()
