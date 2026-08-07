# -*- coding: utf-8 -*-
"""DB tasks 表全部记录"""
import sqlite3, os

conn = sqlite3.connect(os.path.join("..", "data", "portfolio.db"))
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cols = [c[1] for c in cur.execute("PRAGMA table_info(tasks)").fetchall()]
print("tasks cols:", cols)
cur.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 15")
for r in cur.fetchall():
    d = dict(r)
    print(" ", {k: d.get(k) for k in ("id", "task_type", "status", "created_at", "record_id", "task_id") if k in d})
print("check 任务数:", cur.execute("SELECT COUNT(*) FROM tasks WHERE task_type='check'").fetchone()[0])
conn.close()
