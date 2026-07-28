#!/usr/bin/env python3
"""Test smart portfolio generation and performance diagnostics.

Runs inside Docker container against the live backend.
Tests:
  1. Health check
  2. ETF list
  3. Portfolio design trigger (async task)
  4. Check task status
  5. Check design details
  6. Performance timing
"""
import json
import time
import urllib.request

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
results = []


def check(label: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        results.append((label, "PASS", detail))
    else:
        FAIL += 1
        results.append((label, "FAIL", detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {label}" + (f" — {detail}" if detail else ""))


# 1. Health
t0 = time.time()
try:
    r = urllib.request.urlopen(f"{BASE}/health", timeout=10)
    data = r.read().decode()
    check(f"Health check ({time.time()-t0:.1f}s)", r.status == 200, data)
except Exception as e:
    check(f"Health check", False, str(e))


# 2. ETF list
t0 = time.time()
try:
    r = urllib.request.urlopen(f"{BASE}/api/v1/portfolio/etfs", timeout=15)
    etfs = json.loads(r.read().decode())
    etf_list = etfs if isinstance(etfs, list) else etfs.get("etfs", [])
    check(f"ETF list ({len(etf_list)} items, {time.time()-t0:.1f}s)", len(etf_list) > 0, f"count={len(etf_list)}")
except Exception as e:
    check(f"ETF list", False, str(e))


# 3. Warmup status
t0 = time.time()
try:
    r = urllib.request.urlopen(f"{BASE}/api/v1/system/warmup", timeout=10)
    wd = json.loads(r.read().decode())
    elapsed = wd.get("elapsed_seconds", 0)
    all_done = wd.get("all_done", False)
    check(f"Warmup status ({elapsed:.0f}s)", all_done, f"elapsed={elapsed:.0f}s")
except Exception as e:
    check(f"Warmup status", False, str(e))


# 4. Trigger portfolio design (async task)
t0 = time.time()
try:
    body = json.dumps({"capital": 500000, "risk_profile": "balanced"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/portfolio/design",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=10)
    design_resp = json.loads(r.read().decode())
    task_id = design_resp.get("task_id")
    if task_id:
        check(f"Design task created (task={task_id}, {time.time()-t0:.1f}s)", True, f"task_id={task_id}")
    else:
        check(f"Design task created", True, f"direct_result keys: {list(design_resp.keys())[:5]}")

    # 5. Poll task status
    if task_id:
        for i in range(12):  # up to 120s wait
            time.sleep(10)
            try:
                r = urllib.request.urlopen(f"{BASE}/api/v1/portfolio/tasks/{task_id}", timeout=10)
                ts = json.loads(r.read().decode())
                status = ts.get("status", "")
                progress = ts.get("progress", 0)
                if status == "completed":
                    check(f"Design completed ({i*10+10}s)", True, f"progress=100, status={status}")
                    break
                elif status == "failed":
                    err = ts.get("error_message", ts.get("result", {}).get("error", "unknown"))
                    check(f"Design failed ({i*10+10}s)", False, f"error={err}")
                    break
                elif i == 11:
                    check(f"Design timeout", False, f"still {status} after 120s")
            except Exception as e:
                check(f"Design poll error", False, str(e))
                break
    else:
        # Direct response - check it
        strategies = design_resp.get("strategies", design_resp.get("data", {}).get("strategies", []))
        check(f"Design direct response ({time.time()-t0:.1f}s)", len(strategies) > 0, f"strategies={len(strategies)}")
except Exception as e:
    check(f"Design trigger", False, str(e))


# 6. Check latest design detail
t0 = time.time()
try:
    r = urllib.request.urlopen(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=15)
    dd = json.loads(r.read().decode())
    designs = dd.get("designs", dd.get("data", []))
    if designs and len(designs) > 0:
        latest = designs[0]
        sid = latest.get("id", "?")
        rq = latest.get("report_quality", "?")
        strategies = latest.get("strategies_json", latest.get("strategies", []))
        if isinstance(strategies, str):
            strategies = json.loads(strategies) if strategies else []
        total_etfs = 0
        for s in strategies:
            etfs = s.get("etfs", s.get("allocations", []))
            real = [e for e in etfs if e.get("symbol", "") != "CASH"]
            total_etfs += len(real)
        check(f"Design detail (id={sid}, rq={rq}, etfs={total_etfs}, {time.time()-t0:.1f}s)",
              rq in ("full", "partial", "empty", "pending"),
              f"report_quality={rq}, real_etfs={total_etfs}")
    else:
        check(f"Design detail", True, "no designs found")
except Exception as e:
    check(f"Design detail", False, str(e))


# Summary
print(f"\n{'='*50}")
print(f"Results: {PASS}/{PASS+FAIL} passed")
if FAIL:
    print(f"FAILURES: {FAIL}")
    for label, status, detail in results:
        if status == "FAIL":
            print(f"  - {label}: {detail}")
print(f"{'='*50}")
