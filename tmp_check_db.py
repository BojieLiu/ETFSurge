"""Check latest design record in DB for LLM report status"""
import sqlite3, time

db = sqlite3.connect(r'E:\ETF_Surge\data\portfolio.db')
row = db.execute(
    'SELECT id, design_text IS NOT NULL, created_at FROM portfolio_designs ORDER BY id DESC LIMIT 1'
).fetchone()
print(f'id={row[0]}, has_text={bool(row[1])}, created={row[2]}')

if row[1]:
    preview = db.execute(
        "SELECT substr(design_text,1,120) FROM portfolio_designs WHERE id=?",
        (row[0],)
    ).fetchone()[0]
    print(f'preview={preview}')
else:
    print('design_text field is NULL/empty')
    # Check if a compose task might still be running
    from datetime import datetime
    created_ts = datetime.fromisoformat(row[2]) if row[2] else None
    if created_ts:
        age_min = (datetime.now() - created_ts).total_seconds() / 60
        print(f'age_min={age_min:.1f}')
        if age_min < 2:
            print('Report may still be generating...')
        else:
            print('Report generation likely failed (age > 2min)')

db.close()
