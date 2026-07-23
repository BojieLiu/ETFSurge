"""
E2E self-verification — validate 4 fixes.
Tests:
  1. Backend stays alive (/health responds)
  2. Task list is non-empty (designs + strategy-checks endpoints)
  3. Design submission returns task_id without timeout
  4. Strategy check submission returns task_id without timeout
"""
import urllib.request, json, sys, time

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0

def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: {detail}")

def req(path, data=None, timeout=30):
    start = time.time()
    try:
        if data:
            body = json.dumps(data).encode()
            req_obj = urllib.request.Request(
                f"{BASE}{path}", data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        else:
            req_obj = urllib.request.Request(f"{BASE}{path}")
        r = urllib.request.urlopen(req_obj, timeout=timeout)
        elapsed = time.time() - start
        return r.status, json.loads(r.read()), elapsed
    except Exception as e:
        elapsed = time.time() - start
        return None, str(e)[:200], elapsed

print("=" * 55)
print("ETF Surge E2E Verification Report")
print("=" * 55)
print()

# Test 1: Backend alive and responsive
print("[1/4] Backend stays alive")
status, data, elapsed = req("/health", timeout=5)
check(f"GET /health -> {status} ({elapsed:.1f}s)", status == 200, f"got {status}")
print()

# Test 2: Task list non-empty
print("[2/4] Task list")
status, data, elapsed = req("/api/v1/portfolio/designs?limit=5&offset=0")
if status == 200:
    count = len(data) if isinstance(data, list) else len(data.get("designs", []))
    check(f"GET /designs -> {count} records ({elapsed:.1f}s)", count > 0, "empty list")
else:
    check("GET /designs", False, f"HTTP {status}")
print()

status, data, elapsed = req("/api/v1/portfolio/strategy-checks?limit=5&offset=0")
if status == 200:
    count = len(data) if isinstance(data, list) else 0
    check(f"GET /strategy-checks -> {count} records ({elapsed:.1f}s)", count > 0, "empty list")
else:
    check("GET /strategy-checks", False, f"HTTP {status}")
print()

# Test 3: Design submission does not timeout
print("[3/4] Design submission")
status, data, elapsed = req(
    "/api/v1/portfolio/design-async",
    data={"capital": 500000, "constraints": {"risk_profile": "balanced"}},
    timeout=30,
)
if status in (200, 202):
    task_id = data.get("task_id") if isinstance(data, dict) else None
    check(f"POST /design-async -> task_id={task_id} ({elapsed:.1f}s)", task_id is not None,
          f"HTTP {status}, no task_id: {str(data)[:100]}")
else:
    check("POST /design-async", False, f"HTTP {status} ({elapsed:.1f}s): {str(data)[:100]}")
print()

# Test 4: Strategy check submission does not timeout
print("[4/4] Strategy check submission")
status, data, elapsed = req(
    "/api/v1/portfolio/strategy-check-async",
    data={"portfolio_type": "on_exchange"},
    timeout=30,
)
if status in (200, 202):
    task_id = data.get("task_id") if isinstance(data, dict) else None
    check(f"POST /strategy-check-async -> task_id={task_id} ({elapsed:.1f}s)", task_id is not None,
          f"HTTP {status}, no task_id: {str(data)[:100]}")
else:
    check("POST /strategy-check-async", False, f"HTTP {status} ({elapsed:.1f}s): {str(data)[:100]}")
print()

# Summary
print("=" * 55)
print(f"Result: {PASS}/4 passed, {FAIL}/4 failed")
if FAIL == 0:
    print("ALL PASSED")
else:
    print(f"{FAIL} failure(s)")
print("=" * 55)
sys.exit(0 if FAIL == 0 else 1)
