import sqlite3
import os
from datetime import datetime, timedelta

db_path = os.path.join(os.path.dirname(__file__), "data", "memory", "helix_memory.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

tables = ['short_term', 'long_term']

print("Searching for recent Telegram messages...")

for table in tables:
    print(f"\n--- Table: {table} ---")
    try:
        # Get all columns
        cursor.execute(f"PRAGMA table_info({table});")
        cols = [c[1] for c in cursor.fetchall()]
        
        # Look for content containing 'telegram' or messages from users
        # Filter by date if possible
        query = f"SELECT * FROM {table} WHERE content LIKE '%telegram%' OR source = 'telegram' OR tags LIKE '%telegram%';"
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if rows:
            for row in rows:
                # Try to find a date column
                date_val = "N/A"
                if 'created_at' in cols:
                    date_val = row[cols.index('created_at')]
                elif 'timestamp' in cols:
                    date_val = row[cols.index('timestamp')]
                
                print(f"[{date_val}] {row}")
        else:
            print("No Telegram-related entries found.")
            
    except Exception as e:
        print(f"Error: {e}")

conn.close()
