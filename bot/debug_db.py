
import os
import sqlite3

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.db")
print(f"DB Path: {db_path}")
print(f"File exists: {os.path.exists(db_path)}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Tables: {tables}")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
