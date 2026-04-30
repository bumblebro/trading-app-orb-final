"""
Structured logging module for the trading bot.
Logs to both rotating file (trading.log) and SQLite database.
All timestamps in IST.
"""

import logging
import json
import traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime
import os
import sqlite3

# IST timezone offset
IST_OFFSET = "+05:30"

def get_ist_now():
    """Get current time in IST."""
    from datetime import timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist)

def format_ist_time(dt=None):
    """Format datetime in IST string."""
    if dt is None:
        dt = get_ist_now()
    return dt.strftime("%Y-%m-%d %H:%M:%S IST")


class TradingLogger:
    """Centralized trading logger with file + database logging."""

    def __init__(self, db_path: str = None, log_dir: str = None):
        if log_dir is None:
            log_dir = os.path.dirname(os.path.abspath(__file__))
        if db_path is None:
            db_path = os.path.join(log_dir, "trading.db")

        self.db_path = db_path
        self.log_file = os.path.join(log_dir, "trading.log")

        # Set up Python logger
        self.logger = logging.getLogger("TradingBot")
        self.logger.setLevel(logging.DEBUG)

        # Rotating file handler (10MB max, 5 backups)
        file_handler = RotatingFileHandler(
            self.log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "[%(asctime)s IST] [%(levelname)s] [%(category)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "[%(levelname)s] [%(category)s] %(message)s"
        )
        console_handler.setFormatter(console_formatter)

        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        # Initialize logs table
        self._init_db()

    def _init_db(self):
        """Create logs table if not exists."""
        try:
            conn = sqlite3.connect(self.db_path)
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
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Failed to init logs table: {e}")

    def _log_to_db(self, level: str, category: str, message: str, details: dict = None, timestamp: datetime = None):
        """Insert log entry to SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO logs (timestamp, level, category, message, details) VALUES (?, ?, ?, ?, ?)",
                (
                    format_ist_time(timestamp),
                    level,
                    category,
                    message,
                    json.dumps(details) if details else None
                )
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # Don't let DB logging failures crash the bot

    def _log(self, level: int, category: str, message: str, details: dict = None, timestamp: datetime = None):
        """Log to both file and database."""
        extra = {"category": category}
        # For the file log, we still use real time for the [asctime] but we can prepend historical time
        log_message = message
        if timestamp:
            log_message = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
            
        self.logger.log(level, log_message, extra=extra)
        level_name = logging.getLevelName(level)
        self._log_to_db(level_name, category, message, details, timestamp=timestamp)

    # --- Public API ---

    def signal(self, signal_type: str, indicators: dict, timestamp: datetime = None):
        """Log a generated signal."""
        parts = [f"{signal_type}"]
        if "ema9" in indicators and "ema21" in indicators:
            parts.append(f"EMA9={indicators['ema9']:.2f} vs EMA21={indicators['ema21']:.2f}")
        if "vwap" in indicators:
            parts.append(f"VWAP={indicators['vwap']:.2f}")
        if "rsi" in indicators:
            parts.append(f"RSI={indicators['rsi']:.2f}")
        if "price" in indicators:
            parts.append(f"Price={indicators['price']:.2f}")
        message = " | ".join(parts)
        self._log(logging.INFO, "SIGNAL", message, indicators, timestamp=timestamp)

    def order_placed(self, order_type: str, strike: int, price: float, quantity: int, mode: str, timestamp: datetime = None):
        """Log an order placement."""
        message = f"{order_type} | Strike={strike} | Price={price:.2f} | Qty={quantity} | Mode={mode}"
        self._log(logging.INFO, "ORDER", message, {
            "type": order_type, "strike": strike, "price": price,
            "quantity": quantity, "mode": mode
        }, timestamp=timestamp)

    def order_exit(self, reason: str, pnl: float, details: dict = None, timestamp: datetime = None):
        """Log an order exit."""
        message = f"EXIT | Reason={reason} | P&L={pnl:+.2f}"
        self._log(logging.INFO, "ORDER", message, {
            "reason": reason, "pnl": pnl, **(details or {})
        }, timestamp=timestamp)

    def order_failed(self, reason: str, details: dict = None):
        """Log a failed order."""
        message = f"ORDER FAILED | {reason}"
        self._log(logging.ERROR, "ORDER", message, details)

    def margin_check(self, available: float, required: float, sufficient: bool):
        """Log margin check result."""
        message = f"Margin Check | Available={available:.2f} | Required={required:.2f} | {'PASS' if sufficient else 'FAIL'}"
        level = logging.INFO if sufficient else logging.WARNING
        self._log(level, "SYSTEM", message, {
            "available": available, "required": required, "sufficient": sufficient
        })

    def websocket_event(self, event: str, details: str = ""):
        """Log WebSocket events."""
        message = f"WebSocket {event}"
        if details:
            message += f" | {details}"
        level = logging.INFO if event in ("CONNECTED", "SUBSCRIBED") else logging.WARNING
        self._log(level, "SYSTEM", message)

    def market_status(self, message: str):
        """Log market calendar decisions."""
        self._log(logging.INFO, "SYSTEM", message)

    def bot_status(self, status: str, details: str = ""):
        """Log bot status changes."""
        message = f"Bot {status}"
        if details:
            message += f" | {details}"
        self._log(logging.INFO, "SYSTEM", message)

    def error(self, message: str, exc: Exception = None):
        """Log an error with optional traceback."""
        details = {}
        if exc:
            details["traceback"] = traceback.format_exc()
            message += f" | {str(exc)}"
        self._log(logging.ERROR, "ERROR", message, details)

    def warning(self, message: str):
        """Log a warning."""
        self._log(logging.WARNING, "SYSTEM", message)

    def info(self, message: str):
        """Log general info."""
        self._log(logging.INFO, "SYSTEM", message)

    def get_recent_logs(self, limit: int = 200, category: str = None) -> list:
        """Get recent logs from database."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            if category:
                rows = conn.execute(
                    "SELECT * FROM logs WHERE category = ? ORDER BY id DESC LIMIT ?",
                    (category, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM logs ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def get_margin_failures(self, limit: int = 100) -> list:
        """Get logs where margin check failed."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            # Filter specifically for margin failures stored in details
            rows = conn.execute(
                "SELECT * FROM logs WHERE category = 'SYSTEM' AND message LIKE 'Margin Check%' AND details LIKE '%\"sufficient\": false%' ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception:
            return []


# Global logger instance
_logger = None

def get_logger(db_path: str = None) -> TradingLogger:
    """Get or create the global logger instance."""
    global _logger
    if _logger is None:
        _logger = TradingLogger(db_path=db_path)
    return _logger