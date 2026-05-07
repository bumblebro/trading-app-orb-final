import os
import sqlite3

db_path = os.path.join("bot", "trading.db")
conn = sqlite3.connect(db_path, timeout=30)
try:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('initial_capital', '500000')")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('paper_capital', '500000')")
    conn.commit()
    print("Successfully updated capital to 5 lakh in database.")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
