import sqlite3

# Simple database operations
print("Checking database state...")

conn = sqlite3.connect('data/portfolio.db')
cursor = conn.cursor()

# Check if tracked_index column exists
try:
    cursor.execute("SELECT tracked_index FROM portfolio_etfs WHERE symbol = '512890'")
    tracked_index_value = cursor.fetchone()
    print(f"512890 tracked_index: {tracked_index_value}")
except sqlite3.OperationalError as e:
    print(f"Error accessing tracked_index column: {e}")

# Update 007467 tracked_index to 000300 (沪深300)
print("\nUpdating 007467 tracked_index to 000300...")
try:
    cursor.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '007467'")
    conn.commit()
    print("✓ Update successful")
except sqlite3.OperationalError as e:
    print(f"Error updating: {e}")

# Check 007467 status
print("\nChecking 007467 after update:")
cursor.execute("SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol = '007467'")
row = cursor.fetchone()
if row:
    print(f"  Symbol: {row[0]}, tracked_index: {row[1]}")

conn.close()
print("\nOperation complete!")