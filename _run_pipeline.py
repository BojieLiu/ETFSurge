#!/usr/bin/env python3
import urllib.request, json, time, sys

BASE = "http://127.0.0.1:8000"

def post(path, data, timeout=30):
    req = urllib.request.Request(BASE + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read().decode())

def get(path, timeout=10):
    r = urllib.request.urlopen(BASE + path, timeout=timeout)
    return json.loads(r.read().decode())

# 1. Trigger design
print("=== Triggering Design ===")
r = post("/api/v1/portfolio/design-async", {
    "portfolio_type": "on_exchange",
    "total_capital": 500000
}, timeout=30)
tid = r.get("task_id")
print(f"  task_id={tid}, status={r.get('status')}")
sys.stdout.flush()

# 2. Poll
print("\n=== Polling (every 15s) ===")
for i in range(20):
    time.sleep(15)
    tasks = get("/api/v1/portfolio/tasks?limit=3")
    for t in tasks:
        if t.get("task_id") == tid:
            st = t.get("status")
            prog = t.get("progress")
            stage = t.get("stage")
            print(f"  [{i*15+15}s] {st} progress={prog} stage={stage}")
            if st in ("completed", "failed"):
                break
    sys.stdout.flush()

# 3. Show results
print("\n=== Latest Design ===")
designs = get("/api/v1/portfolio/designs?limit=3")
for d in designs:
    mid = d.get("id")
    st = d.get("status")
    cr = str(d.get("created_at",""))[:19]
    print(f"  ID={mid} status={st} created={cr}")

# Trigger strategy check
print("\n=== Triggering Strategy Check ===")
r2 = post("/api/v1/portfolio/strategy-check-async", {
    "portfolio_type": "on_exchange",
    "total_capital": 500000
}, timeout=30)
tid2 = r2.get("task_id")
print(f"  task_id={tid2}")

print("\n=== Polling Check ===")
for i in range(12):
    time.sleep(10)
    tasks = get("/api/v1/portfolio/tasks?limit=3")
    for t in tasks:
        if t.get("task_id") == tid2:
            print(f"  [{i*10+10}s] {t.get('status')} progress={t.get('progress')}")
            if t.get("status") in ("completed", "failed"):
                break
    sys.stdout.flush()

# Final check
print("\n=== Final Checks ===")
checks = get("/api/v1/portfolio/strategy-checks?limit=2")
for c in checks:
    cid = c.get("id")
    reg = c.get("market_regime")
    print(f"  ID={cid} regime={reg}")
    detail = get(f"/api/v1/portfolio/strategy-checks/{cid}")
    if isinstance(detail, dict):
        ha = detail.get("holdings_analysis", [])
        for h in ha[:3]:
            if isinstance(h, dict):
                sig = h.get("signal","?")
                fs = str(h.get("factor_summary",""))[:60]
                print(f"    {h.get('symbol','?')} signal={sig} factor={fs}")

print("\nDONE")
