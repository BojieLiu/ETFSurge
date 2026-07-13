import sqlite3

# Connect to the database
conn = sqlite3.connect('data/portfolio.db')
cur = conn.cursor()

# Set tracked_index for 007467 (华泰柏瑞中证红利低波ETF联接C)
# Note: 512890 (华泰柏瑞中证红利低波动ETF) tracks 中证红利低波动指数
# For off-exchange funds like 007467, we'll map to a major index like 000300 (沪深300)

print("Before update:")
cur.execute("SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol IN ('512890', '007467')")
for row in cur.fetchall():
    print(f"  {row['symbol']} -> tracked_index: {row['tracked_index']}")

print("\nUpdating 007467 tracked_index to 000300...")
cur.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '007467'")

print("\nAfter update:")
cur.execute("SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol IN ('512890', '007467')")
for row in cur.fetchall():
    print(f"  {row['symbol']} -> tracked_index: {row['tracked_index']}")

conn.commit()
conn.close()
print("\nDatabase updated successfully!")