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
    conn = sqlite3.connect(db_path or DB_PATH)
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
            underlying_entry_price REAL,
            token TEXT,
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

    # Migration: Add underlying_entry_price and token columns if they don't exist
    for column, col_type in [("underlying_entry_price", "REAL"), ("token", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass # Column likely already exists
            
    conn.commit()
    conn.close()


# --- Trade Operations ---

def insert_trade(trade: Dict[str, Any], timestamp: datetime = None, db_path: str = None) -> int:
    """Insert a new trade and return its ID."""
    conn = get_connection(db_path)
    now = timestamp or get_ist_now()
    cursor = conn.execute("""
        INSERT INTO trades (date, time, type, strike_price, trading_symbol, entry_price,
                          quantity, lot_size, status, mode, stop_loss, target, underlying_entry_price, token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)
    """, (
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        trade["type"],
        trade["strike_price"],
        trade.get("trading_symbol", ""),
        trade["entry_price"],
        trade["quantity"],
        trade.get("lot_size", 65),
        trade.get("mode", "paper"),
        trade.get("stop_loss"),
        trade.get("target"),
        trade.get("underlying_entry_price"),
        trade.get("token")
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
            UPDATE trades SET exit_price = ?, pnl = ?, status = ?, exit_reason = ?
            WHERE id = ?
        """, (exit_price, pnl, status, exit_reason, trade_id))
        conn.commit()
    conn.close()
    return pnl if trade else 0


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
    "api_key": "",
    "client_id": "",
    "password": "",
    "totp_secret": "",
    "ema_fast": "9",
    "ema_slow": "21",
    "stop_loss_pct": "0.5",
    "target_pct": "1.0",
    "max_trades_per_day": "3",
    "square_off_time": "15:15",
    "lot_size": "65",
    "trading_mode": "paper",
    "paper_capital": "100000",
    "rsi_period": "14",
    "rsi_overbought": "55",
    "rsi_oversold": "45",
    "data_source": "auto",
    "playback_file": "bot/data/nifty_sample.csv",
    "playback_speed": "1",
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
