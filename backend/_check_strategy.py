import sqlite3

conn = sqlite3.connect('data/portfolio.db')
cur = conn.cursor()

print('=== Tables ===')
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
for r in cur.fetchall():
    print(r[0])

print('\n=== Strategy Check Records ===')
try:
    cur.execute("SELECT * FROM strategy_check_records ORDER BY id DESC LIMIT 5")
    cols = [d[0] for d in cur.description]
    print('Columns:', cols)
    for r in cur.fetchall():
        print(dict(zip(cols, r)))
        txt = r[cols.index('report_text')] if 'report_text' in cols else None
        if txt and len(str(txt)) > 100:
            print(f'  Report preview: {str(txt)[:500]}')
except Exception as e:
    print('Error:', e)

print('\n=== Recent designs with more details ===')
cur.execute("SELECT id, status, capital, risk_profile, report_quality, LENGTH(design_text), LENGTH(strategies_json), LENGTH(market_snapshot_json) FROM portfolio_designs ORDER BY id DESC LIMIT 5")
for r in cur.fetchall():
    print(r)

conn.close()
