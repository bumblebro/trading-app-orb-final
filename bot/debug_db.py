import os
import sqlite3

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.db")
print(f"Checking DB at: {db_path}")

if not os.path.exists(db_path):
    print("DB file does not exist!")
else:
    conn = sqlite3.connect(db_path)
    try:
        res = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        print(f"Tables: {[r[0] for r in res]}")
        
        res = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        print(f"Trades count: {res[0]}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
