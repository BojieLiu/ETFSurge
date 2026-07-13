import sqlite3

# Connect to database
conn = sqlite3.connect('data/portfolio.db')
cursor = conn.cursor()

print("Current columns in portfolio_etfs table:")
try:
    cursor.execute("PRAGMA table_info(portfolio_etfs)")
    columns = cursor.fetchall()
    for column in columns:
        col_id, col_name, col_type, not_null, default_value, pk = column
        print(f"  {col_name} ({col_type}), NOT NULL={not_null}, PK={pk}")
except Exception as e:
    print(f"Error: {e}")

# Check if tracked_index column exists
try:
    cursor.execute("SELECT tracked_index FROM portfolio_etfs WHERE symbol = '007467'")
    result = cursor.fetchone()
    print(f"\ntracked_index column exists! 007467 tracked_index: {result}")
except sqlite3.OperationalError as e:
    print(f"\ntracked_index column does NOT exist: {e}")
    
    # Show all columns in the result
    cursor.execute("PRAGMA table_info(portfolio_etfs)")
    for col in cursor.fetchall():
        print(f"  {col[1]}")

conn.close()
print("\nDone!")