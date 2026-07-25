#!/usr/bin/env python3
"""Check task, design, and strategy-check status from the running backend."""
import urllib.request, json, sys

BASE = "http://localhost:8000"

def get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=15)
        return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

# 1. Tasks
print("=== TASKS ===")
tasks = get("/api/v1/portfolio/tasks?limit=10")
if isinstance(tasks, list):
    for t in tasks:
        tid = t.get("id", "?")
        ttype = t.get("task_type", t.get("type", "?"))
        st = t.get("status", "?")
        prog = t.get("progress", t.get("progress_pct", "?"))
        err = str(t.get("error_message", ""))[:100]
        print(f"  ID={tid}  type={ttype}  status={st}  progress={prog}  error={err}")
else:
    print(f"  {str(tasks)[:500]}")
sys.stdout.flush()

# 2. Designs
print("\n=== DESIGNS ===")
designs = get("/api/v1/portfolio/designs?limit=5")
if isinstance(designs, list):
    for d in designs:
        did = d.get("id", "?")
        st = d.get("status", "?")
        created = str(d.get("created_at", ""))[:19]
        risk = d.get("risk_profile", "?")
        print(f"  ID={did}  status={st}  created={created}  risk={risk}")
else:
    print(f"  {str(designs)[:500]}")
sys.stdout.flush()

# 3. Strategy checks
print("\n=== STRATEGY CHECKS ===")
checks = get("/api/v1/portfolio/strategy-checks?limit=5")
if isinstance(checks, list):
    for c in checks:
        cid = c.get("id", "?")
        regime = c.get("market_regime", "?")
        created = str(c.get("created_at", ""))[:19]
        summary = str(c.get("summary", ""))[:100]
        print(f"  ID={cid}  regime={regime}  created={created}  summary={summary}")
else:
    print(f"  {str(checks)[:500]}")
sys.stdout.flush()

print("\nDONE")
