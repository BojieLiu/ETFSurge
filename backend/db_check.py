import sqlite3

conn = sqlite3.connect('data/portfolio.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%etf%'")
print('Tables:')
for row in cur.fetchall():
    print(' -', row['name'])

# Check schema
cur.execute('PRAGMA table_info(portfolio_etfs)')
print('\nPortfolio_etfs schema:')
for row in cur.fetchall():
    print(f"  {row['name']} ({row['type']}) {'NOT NULL' if row['notnull'] == 1 else ''} {'PK' if row['pk'] == 1 else ''}")

conn.close()