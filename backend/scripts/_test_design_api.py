#!/usr/bin/env python3
"""Full test: smart portfolio generation with performance diagnostics."""
import json, urllib.request, time
from urllib.error import HTTPError

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0

def get(path, timeout=15):
    try:
        t0 = time.time()
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=timeout)
        return r.status, json.loads(r.read().decode()), time.time() - t0
    except HTTPError as e:
        return e.code, {"error": str(e)}, 0
    except Exception as e:
        return 0, {"error": str(e)}, 0

def post(path, body, timeout=60):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        t0 = time.time()
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read().decode()), time.time() - t0
    except HTTPError as e:
        return e.code, {"error": str(e)}, 0
    except Exception as e:
        return 0, {"error": str(e)}, 0

def check(label, ok, detail=""):
    global PASS, FAIL
    if ok: PASS += 1
    else: FAIL += 1
    print(f"  [{'OK' if ok else 'FAIL'}] {label} | {detail}")

# 1. Health
s, d, t = get("/health", 5)
check(f"Health ({t:.1f}s)", s == 200)

# 2. Warmup
s, d, t = get("/api/v1/system/warmup", 10)
check(f"Warmup ({d.get('elapsed_seconds',0):.0f}s)", d.get("all_done", False))

# 3. Add initial ETFs (needed for fresh DB)
for etf in [
    {"symbol": "510050", "name": "\u4e0a\u8bc150ETF", "short_name": "\u4e0a\u8bc150",
     "asset_type": "ETF", "target_weight": 0.3, "portfolio_type": "on_exchange"},
    {"symbol": "510300", "name": "\u6caa\u6df1300ETF", "short_name": "\u6caa\u6df1300",
     "asset_type": "ETF", "target_weight": 0.3, "portfolio_type": "on_exchange"},
    {"symbol": "511880", "name": "\u94f6\u534e\u65e5\u5229", "short_name": "\u94f6\u534e\u65e5\u5229",
     "asset_type": "ETF", "target_weight": 0.2, "portfolio_type": "on_exchange"},
]:
    s, d, t = post("/api/v1/portfolio/etfs", etf, 15)
    check(f"Add {etf['symbol']} ({t:.1f}s)", s in (200, 201), str(d.get("symbol","?")))

# 4. Verify ETFs
s, d, t = get("/api/v1/portfolio/etfs", 15)
check(f"ETFs ({len(d)} items, {t:.1f}s)", len(d) >= 3, f"count={len(d)}")

# 5. Calculate allocation
s, d, t = post("/api/v1/portfolio/calculate", {"total_capital": 500000}, 15)
allocs = d.get("allocations", d.get("data", []))
check(f"Calculate ({t:.1f}s)", len(allocs) >= 3, f"allocs={len(allocs)}")

# 6. Trigger smart portfolio DESIGN
s, d, t = post("/api/v1/portfolio/design-async",
               {"capital": 500000, "risk_profile": "balanced"}, 30)
task_id = d.get("task_id")
check(f"Design task created ({t:.1f}s)", task_id is not None, f"task_id={task_id}")

# 7. Poll design task (up to 180s)
st, pr = "pending", 0
if task_id:
    for i in range(18):
        time.sleep(10)
        s, ts, _ = get(f"/api/v1/portfolio/tasks/{task_id}", 10)
        st = ts.get("status", "")
        pr = ts.get("progress", 0)
        sg = ts.get("stage", "")
        print(f"    task [{st}] {pr}% stage={sg}")
        if st in ("completed", "failed"):
            break
    if st == "completed":
        check(f"Design pipeline ({i*10+10}s)", True, f"progress={pr}%")
        result = ts.get("result", {})
        strategies = result.get("strategies", [])
        rq = result.get("report_quality", "")
        check(f"Strategies generated", len(strategies) > 0, f"count={len(strategies)}")
        check(f"Quality grade ({rq})", rq in ("full", "partial"), f"report_quality={rq}")
    elif st == "failed":
        err = ts.get("error_message", ts.get("result", {}).get("error", "?"))
        check(f"Design failed", False, f"err={err[:100]}")
    else:
        check(f"Design timeout", False, f"still running after 180s")

# 8. Check design detail
s, d, t = get("/api/v1/portfolio/designs?limit=1", 15)
if isinstance(d, list) and len(d) > 0:
    latest = d[0]
    sid = latest.get("id", "?")
    rq = latest.get("report_quality", "")
    dt = latest.get("design_text", "") or ""
    sj = latest.get("strategies_json", "[]")
    strategies = json.loads(sj) if isinstance(sj, str) and sj else []
    total_real = sum(
        1 for s in strategies
        for e in (s.get("etfs", s.get("allocations", [])))
        if e.get("symbol", "") != "CASH"
    )
    check(f"Design detail (id={sid}, rq={rq})", total_real > 0 or rq in ("partial", "empty"),
          f"real_etfs={total_real}, design_text_len={len(dt)}")
    if total_real == 0 and rq == "full":
        check(f"Quality assertion: full + real ETFs", False,
              f"WARN: quality=full but 0 real ETFs")
else:
    check(f"Design detail", False, "no designs found")

# 9. Strategy check
s, d, t = post("/api/v1/portfolio/strategy-check-async",
               {"capital": 500000, "portfolio_type": "on_exchange"}, 30)
task_id2 = d.get("task_id")
check(f"Strategy check task ({t:.1f}s)", task_id2 is not None, f"task_id={task_id2}")

print(f"\nResults: {PASS}/{PASS+FAIL} passed, FAILURES={FAIL}")
