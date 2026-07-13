import sqlite3
import os

print("Fixing tracked_index column in portfolio database...")

# Check current directory and file
print(f"Current directory: {os.getcwd()}")
db_path = 'data/portfolio.db'
print(f"Database path: {db_path}")
print(f"Database exists: {os.path.exists(db_path)}")

# Connect to database
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# First, let's see what columns exist
print("\nCurrent table schema:")
try:
    cursor.execute("PRAGMA table_info(portfolio_etfs)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col['name']} ({col['type']}) - PK: {col['pk']}, NOT NULL: {col['notnull']}")
except Exception as e:
    print(f"Error getting schema: {e}")

# Check if tracked_index column exists
print("\nChecking if tracked_index column exists...")
try:
    cursor.execute("SELECT tracked_index FROM portfolio_etfs LIMIT 1")
    print("✓ tracked_index column exists")
except sqlite3.OperationalError as e:
    print(f"✗ tracked_index column does NOT exist: {e}")
    # Try to add it
    try:
        cursor.execute("ALTER TABLE portfolio_etfs ADD COLUMN tracked_index VARCHAR(20)")
        print("✓ Added tracked_index column")
    except Exception as e2:
        print(f"✗ Failed to add column: {e2}")

# Now set tracked_index for 007467
print("\nSetting tracked_index for 007467...")
try:
    cursor.execute("SELECT COUNT(*) as count FROM portfolio_etfs WHERE symbol = '007467'")
    count = cursor.fetchone()['count']
    print(f"007467 exists: {count > 0}")
    
    if count > 0:
        cursor.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '007467'")
        print(f"Updated tracked_index for 007467 to 000300")
except Exception as e:
    print(f"Error: {e}")

# Commit changes
conn.commit()

# Verify the update
print("\nVerifying updates:")
try:
    cursor.execute("SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol IN ('007467', '512890')")
    for row in cursor.fetchall():
        print(f"  {row['symbol']}: tracked_index={row['tracked_index']}")
except Exception as e:
    print(f"Error verifying: {e}")

conn.close()
print("\n✓ Fix complete!")