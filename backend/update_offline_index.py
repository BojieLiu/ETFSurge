import sqlite3

# Update tracked_index for 007467
conn = sqlite3.connect('data/portfolio.db')
cur = conn.cursor()

# Check current state
cur.execute('SELECT symbol, tracked_index, name FROM portfolio_etfs WHERE symbol = "007467"')
row = cur.fetchone()
print(f"Current 007467: {row[0]} - {row[1]} - {row[2]}")

# Update tracked_index for 007467 to 000300 (沪深300)
cur.execute('UPDATE portfolio_etfs SET tracked_index = "000300" WHERE symbol = "007467"')
print(f"Updated tracked_index for 007467 to 000300")

# Verify
cur.execute('SELECT symbol, tracked_index, name FROM portfolio_etfs WHERE symbol IN ("007467", "512890")')
for r in cur.fetchall():
    print(f"  {r[0]} -> tracked_index: {r[1]} - {r[2]}")

conn.commit()
conn.close()
print("\nUpdate complete!")