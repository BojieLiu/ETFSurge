"""Quick self-verification of 4 fixes."""
import urllib.request, json, time

def req(path, data=None, timeout=10):
    start = time.time()
    try:
        if data:
            body = json.dumps(data).encode()
            r = urllib.request.Request(f"http://localhost:8000{path}", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
        else:
            r = urllib.request.Request(f"http://localhost:8000{path}")
        resp = urllib.request.urlopen(r, timeout=timeout)
        elapsed = time.time() - start
        return resp.status, json.loads(resp.read()), elapsed
    except Exception as e:
        elapsed = time.time() - start
        return None, str(e)[:100], elapsed

def check(n, name, ok, detail=""):
    mark = "[PASS]" if ok else "[FAIL]"
    print(f"  {mark} {n}: {name}" + (f" - {detail}" if detail else ""))

print("=" * 50)
print("Self-Verification Report")
print("=" * 50)
print()

# 1. Backend stays alive
print("[1] Backend alive and responsive")
s, d, e = req("/health")
check("1a", f"/health 200 ({e:.1f}s)", s == 200)
time.sleep(3)
s, d, e = req("/health")
check("1b", f"/health after 3s ({e:.1f}s)", s == 200)
print()

# 2. Task list non-empty
print("[2] Task list")
s, d, e = req("/api/v1/portfolio/designs?limit=5")
if s == 200:
    count = len(d) if isinstance(d, list) else len(d.get("designs", []))
    check("2a", f"designs: {count} items ({e:.1f}s)", count > 0)
    if count > 0:
        items = d if isinstance(d, list) else d.get("designs", [])
        for item in items[:2]:
            dt = item.get("design_text", "") or ""
            check("2b", f"  ID={item.get('id')} text_len={len(dt)}", len(dt) > 0)
else:
    check("2a", f"designs endpoint HTTP {s}", False)

s, d, e = req("/api/v1/portfolio/strategy-checks?limit=5")
if s == 200:
    count = len(d) if isinstance(d, list) else 0
    check("2c", f"strategy-checks: {count} items ({e:.1f}s)", count > 0)
else:
    check("2c", "strategy-checks endpoint", False)
print()

# 3. Design submission -> no timeout
print("[3] Design submission no timeout")
s, d, e = req("/api/v1/portfolio/design-async",
    {"capital": 500000, "constraints": {"risk_profile": "balanced"}}, timeout=30)
tid = d.get("task_id") if isinstance(d, dict) else None
check("3a", f"POST returned {s} ({e:.1f}s)", s in (200, 202) and tid is not None)
if tid:
    check("3b", f"task_id={tid} received", True)
print()

# 4. Strategy check submission -> no timeout
print("[4] Strategy check no timeout")
s, d, e = req("/api/v1/portfolio/strategy-check-async",
    {"portfolio_type": "on_exchange"}, timeout=30)
tid = d.get("task_id") if isinstance(d, dict) else None
check("4a", f"POST returned {s} ({e:.1f}s)", s in (200, 202) and tid is not None)
if tid:
    check("4b", f"task_id={tid} received", True)
print()

# Final: confirm backend still alive
time.sleep(3)
s, d, e = req("/health")
check("END", f"Backend still alive after all submits ({e:.1f}s)", s == 200)
print()
print("=" * 50)
print("Done.")
