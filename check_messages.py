import sqlite3
import os

db_path = os.path.expanduser("~/Helix/data/memory/helix_memory.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

tables = [('short_term',), ('long_term',), ('core_memories',)]

for table in tables:
    table_name = table[0]
    print(f"\n--- {table_name} (last 3 days) ---")
    try:
        # Check column names first
        cursor.execute(f"PRAGMA table_info({table_name});")
        cols = [c[1] for n, c in enumerate(cursor.fetchall())]
        print(f"Columns: {cols}")
        
        # Query
        if 'timestamp' in cols:
            cursor.execute(f"SELECT * FROM {table_name} WHERE timestamp > datetime('now', '-3 days') ORDER BY timestamp DESC LIMIT 20;")
        else:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 5;")
        
        rows = cursor.fetchall()
        for row in rows:
            print(row)
    except Exception as e:
        print(f"Error: {e}")

conn.close()
