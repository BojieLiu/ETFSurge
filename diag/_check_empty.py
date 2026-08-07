# -*- coding: utf-8 -*-
"""场内组合检查"组合为空"排查：持仓 + 最新任务 + 检查记录"""
import json, os, sqlite3, urllib.request

conn = sqlite3.connect(os.path.join("..", "data", "portfolio.db"))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. 持仓
cur.execute("SELECT symbol, name, portfolio_type, is_active, target_weight FROM portfolio_etfs ORDER BY portfolio_type, symbol")
rows = cur.fetchall()
print("[持仓] 共", len(rows))
on_ex = [r for r in rows if r["portfolio_type"] == "on_exchange"]
off_ex = [r for r in rows if r["portfolio_type"] == "off_exchange"]
print("  on_exchange:", len(on_ex), "| off_exchange:", len(off_ex))
print("  on_exchange 明细:", [(r["symbol"], r["name"], r["is_active"]) for r in on_ex[:15]])

# 2. 最新检查记录 + 任务
cur.execute("SELECT id, created_at, summary FROM strategy_check_records ORDER BY id DESC LIMIT 4")
print("\n[最新检查]")
for r in cur.fetchall():
    print(f"  #{r['id']} {r['created_at']} | {str(r['summary'])[:80]}")
conn.close()

# 3. API 任务列表
try:
    tasks = json.loads(urllib.request.urlopen("http://localhost:8000/api/v1/portfolio/tasks?limit=8", timeout=15).read().decode())
    items = tasks if isinstance(tasks, list) else tasks.get("items") or tasks.get("tasks") or []
    print("\n[最新任务]")
    for t in items[:8]:
        print(f"  #{t.get('id')} type={t.get('task_type')} status={t.get('status')} created={t.get('created_at')} record={t.get('record_id')}")
except Exception as e:
    print("\n[任务 API 失败]", repr(e))
