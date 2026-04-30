
import unittest
import os
import sqlite3
from datetime import datetime, timedelta
import sys
from unittest.mock import MagicMock, patch

# Add root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.trading_bot import TradingBot, PHASE_MAX_TRADES_DONE

class TestMaxTradesEnforcement(unittest.TestCase):
    def setUp(self):
        # Use a temporary database for testing
        self.db_path = "test_trading.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            
        # Initialize DB schema matching database.py expectations
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                type TEXT,
                entry_date TEXT,
                date TEXT,
                entry_price REAL,
                quantity INTEGER,
                status TEXT,
                pnl REAL,
                exit_date TEXT,
                exit_price REAL,
                exit_reason TEXT,
                mode TEXT
            )
        """)
        conn.commit()
        conn.close()
        
        # Configure test DB
        from bot import database
        database.save_setting("max_trades_per_day", "2", db_path=self.db_path)
        
        # Initialize bot
        self.bot = TradingBot()
        self.bot.logger.db_path = self.db_path
        # Mock indicator update to avoid index errors on empty candles
        self.bot._update_indicators = MagicMock()
        
    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_max_trades_blocks_entry(self):
        """Test that entry is blocked after max trades reached."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        
        # 1. Manually insert 2 trades into DB
        conn = sqlite3.connect(self.db_path)
        for _ in range(2):
            conn.execute("""
                INSERT INTO trades (symbol, type, entry_date, date, mode, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("NIFTY", "BUY_CE", date_str + " 09:30:00", date_str, "paper", "CLOSED"))
        conn.commit()
        conn.close()
        
        # 2. Mock bot dependencies for tick simulation
        sim_now = now.replace(hour=10, minute=0)
        self.bot._get_current_time = MagicMock(return_value=sim_now)
        self.bot.data_feed = MagicMock()
        self.bot.data_feed.current_price = 18000
        
        # Mock functions IN the trading_bot module scope where they were imported
        with patch('bot.trading_bot.get_setting') as mocked_setting, \
             patch('bot.trading_bot.get_today_trade_count') as mocked_count, \
             patch('bot.trading_bot.should_bot_run') as mocked_run:
            
            # Use real implementation but forced DB path
            from bot.database import get_setting, get_today_trade_count
            mocked_setting.side_effect = lambda key, db_path=None: get_setting(key, db_path=self.db_path)
            mocked_count.side_effect = lambda date_override=None, db_path=None: get_today_trade_count(date_override=date_override, db_path=self.db_path)
            mocked_run.return_value = (True, "Market open")
            
            self.bot._tick()
            self.assertEqual(self.bot._strategy_phase, PHASE_MAX_TRADES_DONE)

    def test_counter_persistence_after_restart(self):
        """Test that trade count reloads from DB accurately."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        
        # Insert 1 trade
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO trades (symbol, type, entry_date, date, mode, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("NIFTY", "BUY_CE", date_str + " 09:30:00", date_str, "paper", "CLOSED"))
        conn.commit()
        conn.close()
        
        from bot.database import get_today_trade_count
        count = get_today_trade_count(date_override=date_str, db_path=self.db_path)
        self.assertEqual(count, 1)

if __name__ == '__main__':
    unittest.main()
