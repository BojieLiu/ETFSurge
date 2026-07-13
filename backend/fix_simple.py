import sqlite3
import os

import sqlite3
import os

print("Fixing tracked_index column...")

# Check database
if not os.path.exists('data/portfolio.db'):
    print("Creating new database...")
    with sqlite3.connect('data/portfolio.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS portfolio_etfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(20) NOT NULL,
            name VARCHAR(100) NOT NULL,
            asset_type VARCHAR(20) NOT NULL DEFAULT "A",
            target_weight FLOAT NOT NULL,
            portfolio_type VARCHAR(20) NOT NULL DEFAULT "on_exchange",
            short_name VARCHAR(60),
            is_active BOOLEAN DEFAULT TRUE
        )''')
        print("Created database and table")

# Now add tracked_index column
with sqlite3.connect('data/portfolio.db') as conn:
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio_etfs'")
    if cursor.fetchone():
        print("portfolio_etfs table exists")
        
        # Check if tracked_index column exists
        cursor.execute("PRAGMA table_info(portfolio_etfs)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'tracked_index' not in columns:
            print("Adding tracked_index column...")
            cursor.execute("ALTER TABLE portfolio_etfs ADD COLUMN tracked_index VARCHAR(20)")
            print("tracked_index column added")
        else:
            print("tracked_index column already exists")
        
        # Update 007467
        cursor.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '007467'")
        print(f"Updated tracked_index for 007467 to 000300")
        
        conn.commit()
        print("Changes committed")
        
        # Verify
        cursor.execute("SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol IN ('007467', '512890')")
        print("\nVerification:")
        for row in cursor.fetchall():
            print(f"  {row[0]}: tracked_index={row[1]}")

print("\nFix complete!")