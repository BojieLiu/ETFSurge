import sqlite3, json

conn = sqlite3.connect('data/portfolio.db')
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', cur.fetchall())

cur.execute("SELECT id, status, capital, risk_profile, substr(design_text,1,100) as design_preview FROM portfolio_designs ORDER BY id DESC LIMIT 5")
for row in cur.fetchall():
    print(row)

cur.execute("SELECT id, status, portfolio_type, created_at, substr(report_text,1,100) FROM strategy_checks ORDER BY id DESC LIMIT 5")
for row in cur.fetchall():
    print(row)

conn.close()
