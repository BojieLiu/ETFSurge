import sqlite3

conn = sqlite3.connect('data/portfolio.db')
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', cur.fetchall())

print('\n=== Latest Designs ===')
cur.execute("SELECT id, status, capital, risk_profile, report_quality, LENGTH(design_text) FROM portfolio_designs ORDER BY id DESC LIMIT 3")
for r in cur.fetchall():
    print(r)

print('\n=== Latest Design Text (id=224) ===')
cur.execute("SELECT design_text FROM portfolio_designs WHERE id=224")
txt = cur.fetchone()
if txt and txt[0]:
    print(txt[0][:3000])
else:
    print('No text')

conn.close()
