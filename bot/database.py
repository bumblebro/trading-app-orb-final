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
    """Get SQLite connection with row factory and increased timeout."""
    target_path = db_path or DB_PATH
    # Increase timeout to 30s to prevent 'database is locked' during concurrent access
    conn = sqlite3.connect(target_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        # WAL might fail on some filesystems, ignore if so
        pass
    return conn

def init_db(db_path: str = None):
    """Initialize database tables and handle migrations."""
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
            capital_used REAL,
            underlying_entry_price REAL,
            token TEXT,
            adx_at_entry REAL,
            supertrend_at_entry REAL,
            ema_short_at_entry REAL,
            ema_long_at_entry REAL,
            exit_time TEXT,
            total_capital REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Ensure settings table exists immediately
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    
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
    
    # Migration: Ensure all newer columns exist
    migrations = [
        ("adx_at_entry", "REAL"),
        ("supertrend_at_entry", "REAL"),
        ("ema_short_at_entry", "REAL"),
        ("ema_long_at_entry", "REAL"),
        ("exit_time", "TEXT"),
        ("trailing_sl", "REAL"),
        ("capital_used", "REAL"),
        ("initial_risk_pts", "REAL"),
        ("partial_booked", "INTEGER DEFAULT 0"),
        ("underlying_entry_price", "REAL"),
        ("token", "TEXT"),
        ("total_capital", "REAL"),
        ("brokerage", "REAL DEFAULT 0"),
        ("stt", "REAL DEFAULT 0"),
        ("exc_charges", "REAL DEFAULT 0"),
        ("gst", "REAL DEFAULT 0"),
        ("net_pnl", "REAL DEFAULT 0")
    ]
    
    for col, ctype in migrations:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {ctype}")
        except sqlite3.OperationalError:
            pass  # Column already exists
            
    conn.commit()
    conn.close()

def insert_trade(trade: Dict[str, Any], timestamp: datetime = None, db_path: str = None) -> int:
    conn = get_connection(db_path)
    now = timestamp or get_ist_now()
    cursor = conn.execute("""
        INSERT INTO trades (date, time, type, strike_price, trading_symbol, entry_price, 
                          quantity, lot_size, status, mode, stop_loss, target, capital_used,
                          underlying_entry_price, token, adx_at_entry, supertrend_at_entry, 
                          ema_short_at_entry, ema_long_at_entry, total_capital)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.get("date", now.strftime("%Y-%m-%d")),
        trade.get("time", now.strftime("%H:%M:%S")),
        trade["type"], trade["strike_price"], trade.get("trading_symbol", ""),
        trade["entry_price"], trade["quantity"], trade.get("lot_size", 65),
        trade.get("status", "open"), trade.get("mode", "paper"),
        trade.get("stop_loss"), trade.get("target"), trade.get("capital_used"),
        trade.get("underlying_entry_price"), trade.get("token"), 
        trade.get("adx_at_entry"), trade.get("supertrend_at_entry"),
        trade.get("ema_short_at_entry"), trade.get("ema_long_at_entry"),
        trade.get("total_capital")
    ))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id

def calculate_charges(entry_price: float, exit_price: float, quantity: int) -> Dict[str, float]:
    """
    Calculate realistic Indian market transaction charges for Nifty Options.
    Based on standard discount broker (e.g., Angel One) rates.
    """
    buy_value = entry_price * quantity
    sell_value = exit_price * quantity
    turnover = buy_value + sell_value
    
    # 1. Brokerage: ₹20 per order
    brokerage = 40.0 
    
    # 2. STT: 0.05% on Sell side only
    stt = round(sell_value * 0.0005, 2)
    
    # 3. Exchange Transaction Charges (NFO): ~0.053% of turnover
    exc_charges = round(turnover * 0.00053, 2)
    
    # 4. SEBI Charges: ₹10 per crore
    sebi = round(turnover * 0.0000001, 2)
    
    # 5. Stamp Duty: 0.003% on Buy side
    stamp = round(buy_value * 0.00003, 2)
    
    # 6. GST: 18% on (Brokerage + Exchange Charges + SEBI)
    taxable = brokerage + exc_charges + sebi
    gst = round(taxable * 0.18, 2)
    
    total_charges = round(brokerage + stt + exc_charges + sebi + stamp + gst, 2)
    
    return {
        "brokerage": brokerage,
        "stt": stt,
        "exc_charges": exc_charges,
        "gst": gst,
        "total_charges": total_charges
    }

def update_trade(trade_id: int, updates: Dict[str, Any], db_path: str = None):
    conn = get_connection(db_path)
    sets = ", ".join([f"{k} = ?" for k in updates.keys()])
    conn.execute(f"UPDATE trades SET {sets} WHERE id = ?", list(updates.values()) + [trade_id])
    conn.commit()
    conn.close()

def close_trade(trade_id: int, exit_price: float, exit_reason: str, timestamp: datetime = None, db_path: str = None):
    conn = get_connection(db_path)
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if trade:
        gross_pnl = round((exit_price - trade["entry_price"]) * trade["quantity"], 2)
        
        # Calculate charges
        charges = calculate_charges(trade["entry_price"], exit_price, trade["quantity"])
        net_pnl = round(gross_pnl - charges["total_charges"], 2)
        
        now = timestamp or get_ist_now()
        conn.execute("""
            UPDATE trades SET 
                exit_price = ?, pnl = ?, net_pnl = ?, 
                brokerage = ?, stt = ?, exc_charges = ?, gst = ?,
                status = ?, exit_reason = ?, exit_time = ?
            WHERE id = ?
        """, (
            exit_price, gross_pnl, net_pnl, 
            charges["brokerage"], charges["stt"], charges["exc_charges"], charges["gst"],
            "win" if net_pnl > 0 else "loss", exit_reason, now.strftime("%H:%M:%S"), trade_id
        ))
        conn.commit()
    conn.close()
    return net_pnl if trade else 0

def get_active_trade(db_path: str = None) -> Optional[Dict]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM trades WHERE status = 'open' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None

def get_trades(mode: str = None, date_from: str = None, date_to: str = None, limit: int = 100, db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    if mode: query += " AND mode = ?"; params.append(mode)
    if date_from: query += " AND date >= ?"; params.append(date_from)
    if date_to: query += " AND date <= ?"; params.append(date_to)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_trades(mode: str = None, date_override: str = None, db_path: str = None) -> List[Dict]:
    target = date_override or get_ist_now().strftime("%Y-%m-%d")
    return get_trades(mode=mode, date_from=target, date_to=target, limit=100, db_path=db_path)

def get_today_pnl(mode: str = None, date_override: str = None, db_path: str = None) -> Dict:
    trades = get_today_trades(mode=mode, date_override=date_override, db_path=db_path)
    # Use net_pnl if available (newly closed trades), else gross pnl
    total_net_pnl = sum(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl", 0) for t in trades if t["status"] != "open")
    wins = sum(1 for t in trades if t["status"] == "win")
    losses = sum(1 for t in trades if t["status"] == "loss")
    closed = wins + losses
    return {
        "total_pnl": round(total_net_pnl, 2), "total_trades": len(trades),
        "wins": wins, "losses": losses, "win_rate": round((wins/closed*100) if closed > 0 else 0, 1),
        "open_trades": sum(1 for t in trades if t["status"] == "open")
    }

def get_all_time_pnl(mode: str = None, date_from: str = None, date_to: str = None, db_path: str = None) -> Dict:
    conn = get_connection(db_path)
    # Fetch Gross P&L and Net P&L (legacy handling with COALESCE)
    query = """
        SELECT 
            SUM(pnl) as gross_pnl, 
            SUM(COALESCE(net_pnl, pnl)) as net_pnl,
            SUM(brokerage + stt + exc_charges + gst) as total_charges,
            COUNT(*) as total_trades, 
            SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as wins, 
            SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) as losses 
        FROM trades WHERE status != 'open'
    """
    params = []
    if mode: query += " AND mode = ?"; params.append(mode)
    if date_from: query += " AND date >= ?"; params.append(date_from)
    if date_to: query += " AND date <= ?"; params.append(date_to)
    row = conn.execute(query, params).fetchone()
    conn.close()
    
    gross = row["gross_pnl"] or 0
    net = row["net_pnl"] or 0
    charges = row["total_charges"] or (gross - net)
    trades, wins, losses = row["total_trades"] or 0, row["wins"] or 0, row["losses"] or 0
    
    return {
        "all_time_pnl": round(net, 2), 
        "all_time_gross_pnl": round(gross, 2),
        "all_time_charges": round(charges, 2),
        "all_time_trades": trades, 
        "all_time_win_rate": round((wins/trades*100) if trades > 0 else 0, 1), 
        "wins": wins, 
        "losses": losses
    }

def get_yearly_summary(mode: str = None, date_from: str = None, date_to: str = None, db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    # Using COALESCE(net_pnl, pnl) to handle legacy data
    # Added a subquery to get the total_capital from the first trade of each year
    query = """
        SELECT 
            STRFTIME('%Y', date) as year, 
            SUM(COALESCE(net_pnl, pnl)) as pnl, 
            COUNT(*) as trades, 
            SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) as wins, 
            SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) as losses, 
            SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) as gross_profit, 
            SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END) as gross_loss,
            (SELECT total_capital FROM trades t2 
             WHERE STRFTIME('%Y', t2.date) = STRFTIME('%Y', trades.date) 
             AND t2.status != 'open' 
             ORDER BY t2.date ASC, t2.id ASC LIMIT 1) as starting_capital
        FROM trades 
        WHERE status != 'open'
    """
    params = []
    if mode: query += " AND mode = ?"; params.append(mode)
    if date_from: query += " AND date >= ?"; params.append(date_from)
    if date_to: query += " AND date <= ?"; params.append(date_to)
    query += " GROUP BY year ORDER BY year DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_last_trade_date(mode: str = None, db_path: str = None) -> Optional[str]:
    conn = get_connection(db_path)
    query = "SELECT date FROM trades WHERE status != 'open' "
    if mode: query += "AND mode = ? "; params = [mode]
    else: params = []
    query += "ORDER BY date DESC, id DESC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    conn.close()
    return row["date"] if row else None

def get_first_trade_date(mode: str = None, db_path: str = None) -> Optional[str]:
    conn = get_connection(db_path)
    query = "SELECT date FROM trades WHERE status != 'open' "
    if mode: query += "AND mode = ? "; params = [mode]
    else: params = []
    query += "ORDER BY date ASC, id ASC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    conn.close()
    return row["date"] if row else None

def get_fixed_lot_pnl(mode: str = None, fixed_lots: int = 2, lot_size: int = 65, db_path: str = None) -> float:
    conn = get_connection(db_path)
    # For fixed lot comparison, we must also subtract simulated charges
    query = "SELECT entry_price, exit_price FROM trades WHERE status != 'open' AND entry_price IS NOT NULL AND exit_price IS NOT NULL"
    if mode: query += " AND mode = ?"; params = [mode]
    else: params = []
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    total_net_pnl = 0.0
    qty = fixed_lots * lot_size
    for r in rows:
        gross = (r["exit_price"] - r["entry_price"]) * qty
        charges = calculate_charges(r["entry_price"], r["exit_price"], qty)["total_charges"]
        total_net_pnl += (gross - charges)
        
    return round(total_net_pnl, 2)

def get_consecutive_losses(date_override=None, db_path=None) -> int:
    target = date_override or get_ist_now().strftime("%Y-%m-%d")
    conn = get_connection(db_path)
    rows = conn.execute("SELECT status FROM trades WHERE date = ? AND status != 'open' ORDER BY id DESC", (target,)).fetchall()
    conn.close()
    count = 0
    for r in rows:
        if r["status"] == "loss": count += 1
        else: break
    return count

DEFAULT_SETTINGS = {
    "api_key": "", "client_id": "", "pin": "", "totp_secret": "",
    "trading_mode": "paper", "position_size_mode": "auto_compound", 
    "initial_capital": "500000", "lot_size": "65", "fixed_lots": "2",
    "adx_threshold": "20", "supertrend_period": "10", "supertrend_multiplier": "3.0",
    "max_trades_per_day": "5", "max_daily_loss": "10000",
    "morning_max_trades": "3", "afternoon_max_trades": "2",
    "option_sl_pct": "40.0", "max_capital_per_trade_pct": "20.0",
    "max_trade_duration_mins": "90"
}

def save_setting(k, v, db_path=None):
    conn = get_connection(db_path)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit(); conn.close()

def save_settings(settings, db_path=None):
    conn = get_connection(db_path)
    for k, v in settings.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit(); conn.close()

def get_setting(k, db_path=None):
    try:
        conn = get_connection(db_path)
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (k,)).fetchone()
        conn.close()
        return row["value"] if row else DEFAULT_SETTINGS.get(k, "")
    except sqlite3.OperationalError as e:
        if "no such table: settings" in str(e):
            # Self-healing: if settings table is missing, try to initialize it
            init_db(db_path)
            # Re-try once
            conn = get_connection(db_path)
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (k,)).fetchone()
            conn.close()
            return row["value"] if row else DEFAULT_SETTINGS.get(k, "")
        raise

def get_all_settings(db_path=None) -> Dict[str, str]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    s = dict(DEFAULT_SETTINGS)
    for r in rows: s[r["key"]] = r["value"]
    return s

def get_today_trade_count(date_override=None, db_path=None):
    target = date_override or get_ist_now().strftime("%Y-%m-%d")
    conn = get_connection(db_path)
    row = conn.execute("SELECT COUNT(*) as count FROM trades WHERE date = ?", (target,)).fetchone()
    conn.close()
    return row["count"] if row else 0

def insert_signal_log(data, timestamp=None, db_path=None):
    conn = get_connection(db_path)
    now = timestamp or get_ist_now()
    conn.execute("INSERT INTO signal_logs (timestamp, price, supertrend, supertrend_direction, ema_short, ema_long, adx, signal, skip_reason) VALUES (?,?,?,?,?,?,?,?,?)",
                 (now.strftime("%Y-%m-%d %H:%M:%S"), data.get("price"), data.get("supertrend"), data.get("supertrend_direction"), data.get("ema_short"), data.get("ema_long"), data.get("adx"), data.get("signal"), data.get("skip_reason")))
    conn.commit(); conn.close()

def clear_trade_data(db_path=None):
    """Clear all trade history, signal logs, and system logs while preserving settings."""
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM signal_logs")
        conn.execute("DELETE FROM logs")
        # Reset autoincrement counters
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('trades', 'signal_logs', 'logs')")
        conn.commit()
        return True
    except Exception as e:
        print(f"Error clearing data: {e}")
        return False
    finally:
        conn.close()

init_db()
