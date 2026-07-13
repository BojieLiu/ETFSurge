import sqlite3
from sqlalchemy import text

# Read existing schema to check for tracked_index column
conn = sqlite3.connect('data/portfolio.db')
cur = conn.cursor()

cur.execute("PRAGMA table_info(portfolio_etfs)")
columns = [row[1] for row in cur.fetchall()]

if 'tracked_index' not in columns:
    print('Adding tracked_index column...')
    conn.execute('ALTER TABLE portfolio_etfs ADD COLUMN tracked_index VARCHAR(20)')
    conn.commit()
    print('✓ tracked_index column added successfully')
else:
    print('tracked_index column already exists')

# Now update the 007467 record
cur.execute('SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol = "007467"')
row = cur.fetchone()
if row:
    print(f'007467 current tracked_index: {row[1]}')
else:
    print('007467 not found in database')

# Set tracked_index for 007467 to 000300 (沪深300)
cur.execute('UPDATE portfolio_etfs SET tracked_index = "000300" WHERE symbol = "007467"')
print('✓ Updated tracked_index for 007467 to 000300')

# Verify it worked
cur.execute('SELECT symbol, tracked_index FROM portfolio_etfs WHERE symbol IN ("007467", "512890")')
for r in cur.fetchall():
    print(f'  {r[0]} -> tracked_index: {r[1]}')

conn.commit()
conn.close()

print('\nMigration complete!')