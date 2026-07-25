#!/usr/bin/env python3
"""Wait for backend to start, then submit design and verify."""
import urllib.request, json, time, sys
from urllib.error import URLError

BASE = "http://localhost:8000"

print("Waiting for backend...")
deadline = time.time() + 60
while time.time() < deadline:
    try:
        r = urllib.request.urlopen(f"{BASE}/health", timeout=5)
        h = r.read().decode()
        if "ok" in h:
            print(f"  Backend started in {time.time()-deadline+60:.0f}s")
            break
    except URLError:
        pass
    time.sleep(2)
else:
    print("  Backend failed to start within 60s")
    print("  Check if uvicorn process is running...")
    import subprocess
    proc = subprocess.run(["python", "-m", "app.main"], capture_output=True, timeout=5)
    print(f"  stdout: {proc.stdout.decode()[:200]}")
    print(f"  stderr: {proc.stderr.decode()[:200]}")
    sys.exit(1)

PASS, FAIL = 0, 0

def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        print(f"  [+] {name} {detail}")
        PASS += 1
    else:
        print(f"  [!] FAIL {name} - {detail}")
        FAIL += 1

def fetch(url, timeout=10):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=timeout).read())

def post(url, data, timeout=120):
    r = urllib.request.Request(url, data=json.dumps(data).encode(),
                                headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())

print("\n=== Submit Design ===")
result = post(f"{BASE}/api/v1/portfolio/design-async", {"capital": 500000})
tid = result.get("task_id")
check("Design submitted", tid is not None, f"task_id={tid}")
if not tid:
    sys.exit(1)

print("\n=== Polling ===")
deadline = time.time() + 240
while time.time() < deadline:
    task = fetch(f"{BASE}/api/v1/portfolio/tasks/{tid}")
    st = task.get("status")
    pr = task.get("progress")
    print(f"  status={st} progress={pr}")
    if st in ("completed", "failed", "completed_with_errors"):
        break
    time.sleep(5)
else:
    check("Design completion", False, "timed out")
    sys.exit(1)

print("\n=== Inspect Design ===")
designs = fetch(f"{BASE}/api/v1/portfolio/designs?limit=2")
for d in designs:
    did = d["id"]
    dd = fetch(f"{BASE}/api/v1/portfolio/designs/{did}")
    st = dd.get("status")
    rq = dd.get("report_quality", "?")
    strs = dd.get("strategies", [])
    dt = dd.get("design_text", "") or ""
    err = dd.get("error_message", "")
    print(f"\nDesign {did}: status={st} quality={rq} text_len={len(dt)} err={err[:60] if err else 'none'}")
    check(f"Status completed", st == "completed", st)
    check(f"3 strategies", len(strs) == 3, f"got {len(strs)}")

    all_etfs_by_strategy = []
    for i, s in enumerate(strs):
        label = s.get("label", s.get("name", f"S{i}"))
        allocs = s.get("allocations", s.get("etfs", []))
        non_cash = [a for a in allocs if a.get("symbol") and a["symbol"] != "CASH"]
        syms = [a["symbol"] for a in non_cash]
        wts = [a.get("target_weight", a.get("weight", 0)) for a in non_cash]
        print(f"  {label}: {len(non_cash)} ETFs weights={[round(w,3) for w in wts[:5]]} symbols={syms[:5]}")
        all_etfs_by_strategy.append(syms)

        for a in non_cash:
            rt = a.get("selection_rationale", "")
            assert "今日" not in rt, f"Placeholder 今日 in {a['symbol']}: {rt[:60]}"
            assert "{" not in rt, f"Placeholder {{ in {a['symbol']}: {rt[:60]}"

    # Dedup check within each strategy
    for i, syms in enumerate(all_etfs_by_strategy):
        if len(set(syms)) != len(syms):
            check(f"Strategy {i} dedup", False, str(syms))
    check(f"Design text > 200", len(dt) > 200, f"len={len(dt)}")
    check(f"Report quality", rq in ("full", "fallback"), f"actual={rq}")

    # Strategy differentiation
    if len(all_etfs_by_strategy) >= 3:
        def_top3 = all_etfs_by_strategy[2][:3]
        agg_top3 = all_etfs_by_strategy[0][:3]
        check(f"Defensive != Aggressive top picks", def_top3 != agg_top3,
              f"def={def_top3} agg={agg_top3}")

print(f"\n=== RESULT: {PASS} PASS, {FAIL} FAIL ===")
sys.exit(0 if FAIL == 0 else 1)
