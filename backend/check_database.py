import sqlite3
import os

print("Checking database...")

# Check if database exists
db_path = "data/portfolio.db"
if not os.path.exists(db_path):
    print(f"Database not found at: {db_path}")
    print("Current directory:", os.getcwd())
    print("Files in data directory:", os.listdir("data") if os.path.exists("data") else "Directory doesn't exist")
    exit(1)

# Connect to database
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Check if table exists
cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='portfolio_etfs'")
if cursor.fetchone()[0] == 0:
    print("✗ portfolio_etfs table does not exist")
else:
    print("✓ portfolio_etfs table exists")
    
    # Check what columns exist
    cursor = conn.execute("PRAGMA table_info(portfolio_etfs)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"Columns: {', '.join(columns)}")
    
    # Check if tracked_index column exists
    if 'tracked_index' in columns:
        print("✓ tracked_index column exists")
    else:
        print("✗ tracked_index column does not exist")
    
    # Check all holdings
    cursor = conn.execute('SELECT id, symbol, portfolio_type, tracked_index FROM portfolio_etfs ORDER BY id')
    holdings = cursor.fetchall()
    
    if holdings:
        print(f"\n{len(holdings)} holdings found:")
        for row in holdings:
            print(f"  ID: {row['id']}, Symbol: {row['symbol']}, Type: {row['portfolio_type']}, Tracked Index: {row['tracked_index']}")
        
        # Check specifically for 007467
        for row in holdings:
            if row['symbol'] == '007467':
                print(f"\n✓ Found 007467 with tracked_index: {row['tracked_index']}")
                break
        else:
            print("\n✗ 007467 not found in database")
    else:
        print("✗ No holdings found")

conn.close()