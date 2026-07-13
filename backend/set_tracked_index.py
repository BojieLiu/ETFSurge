import sqlite3

# Connect to database
conn = sqlite3.connect('data/portfolio.db')
cursor = conn.cursor()

# Update 007467 (华泰柏瑞中证红利低波动ETF联接C) tracked_index to 000300 (沪深300)
cursor.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '007467'")

# Commit the change
conn.commit()

# Verify the change
cursor.execute("SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol = '007467'")
result = cursor.fetchone()
if result:
    symbol, tracked_index = result
    print(f"Updated {symbol} tracked_index to: {tracked_index}")
else:
    print("Error updating tracked_index for 007467")

# Show all tracked_index values for off-exchange funds
print("\nOff-exchange funds with tracked_index:")
cursor.execute("SELECT symbol, name, tracked_index FROM portfolio_etfs WHERE portfolio_type = 'off_exchange' AND tracked_index IS NOT NULL")
for row in cursor.fetchall():
    print(f"  {row['symbol']} ({row['name']}): {row['tracked_index']}")

conn.close()
print("\nDone!")