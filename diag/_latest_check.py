# -*- coding: utf-8 -*-
"""最新策略检查：suggestions/holdings/risk_warnings + report_text 明细"""
import sqlite3, json, os

conn = sqlite3.connect(os.path.join("..", "data", "portfolio.db"))
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM strategy_check_records ORDER BY id DESC LIMIT 3")
rows = cur.fetchall()

for r in rows:
    d = dict(r)
    print("\n===== check id=%s (%s) =====" % (d["id"], d["created_at"]))
    print("summary:", str(d.get("summary"))[:160])
    for col, label in (("suggestions_json", "suggestions"), ("holdings_json", "holdings"), ("risk_warnings_json", "risk_warnings")):
        v = d.get(col)
        if not v:
            print(f"{label}: NULL/EMPTY")
            continue
        parsed = json.loads(v) if isinstance(v, str) else v
        print(f"{label}: {len(parsed)} items")
        for it in parsed[:12]:
            print("   ", json.dumps(it, ensure_ascii=False)[:220])
    rt = d.get("report_text") or ""
    if rt:
        print("report_text 前 600 字:")
        print(rt[:600])
conn.close()
