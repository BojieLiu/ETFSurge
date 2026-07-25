#!/usr/bin/env python3
"""Investigate strategy check failures - read the function and check task params."""
import urllib.request, json, sqlite3, sys

# 1. Read the strategy_check function
text = open("backend/app/services/portfolio_service.py", "r", encoding="utf-8").read()
idx = text.find("async def strategy_check")
if idx >= 0:
    end = text.find("\ndef ", idx + 10)
    if end == -1 or end > idx + 6000:
        end = idx + 6000
    func_text = text[idx:end]
    print("=== strategy_check function (start) ===")
    print(func_text[:2000])
    sys.stdout.flush()

# 2. Check DB for tasks and their params
print("\n=== Task params from DB ===")
conn = sqlite3.connect("data/portfolio.db")
c = conn.cursor()

# Check the task_manager tasks table
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"Tables: {tables}")

# Try to find tasks table
for tbl in tables:
    if 'task' in tbl.lower():
        print(f"\nTable: {tbl}")
        c.execute(f"SELECT * FROM {tbl} LIMIT 3")
        cols = [d[0] for d in c.description]
        print(f"  Columns: {cols}")
        for row in c.fetchall():
            print(f"  {row}")

# Check strategy check records with portfolio_type
print("\n=== Strategy Check portfolio_type values ===")
c.execute("SELECT id, portfolio_type, capital FROM strategy_check_records ORDER BY id")
for r in c.fetchall():
    print(f"  ID={r[0]}: portfolio_type={r[1]}, capital={r[2]}")

# Check pool_manager cache for market data availability
print("\n=== Pool manager candidate counts ===")
try:
    import urllib.request
    r = urllib.request.urlopen("http://localhost:8000/api/v1/market/realtime?symbols=159338,510880", timeout=10)
    data = json.loads(r.read().decode())
    print(f"  Realtime data checks: {len(data) if isinstance(data, list) else type(data).__name__}")
except Exception as e:
    print(f"  Error: {e}")

conn.close()
print("\nDONE")
