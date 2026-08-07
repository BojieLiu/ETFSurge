# -*- coding: utf-8 -*-
"""#343 孤立记录全字段 + 前后检查记录对比"""
import sqlite3, os, json

conn = sqlite3.connect(os.path.join("..", "data", "portfolio.db"))
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM strategy_check_records WHERE id IN (341, 342, 343, 344) ORDER BY id")
for r in cur.fetchall():
    d = dict(r)
    print(f"\n=== #{d['id']} {d['created_at']} ===")
    for k, v in d.items():
        if v is None:
            continue
        s = str(v)
        print(f"  {k}: {s[:160]}")
conn.close()
