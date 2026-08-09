#!/usr/bin/env python3
"""Quick test: trigger design and check result."""
import json, sys, time, urllib.request

def api(path, method="GET", body=None, timeout=30):
    url = f"http://localhost:8000{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if body: req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        return e.code, {"error": str(e), "body": body}
    except Exception as e:
        return 0, {"error": str(e)}

# Add ETF(s)
for sym, name in [("510050", "上证50ETF"), ("510300", "沪深300ETF"), ("511880", "银华日利")]:
    s, d = api("/api/v1/portfolio/etfs", "POST",
               {"symbol": sym, "name": name, "short_name": name,
                "asset_type": "ETF", "target_weight": 0.3, "portfolio_type": "on_exchange"})

# Trigger design
s, d = api("/api/v1/portfolio/design-async", "POST",
           {"capital": 500000, "risk_profile": "balanced"})
task_id = d.get("task_id")
print(f"Task: {task_id} (status={s})")
if not task_id:
    sys.exit(1)

for i in range(30):
    time.sleep(10)
    s, ts = api(f"/api/v1/portfolio/tasks/{task_id}")
    st, pr = ts.get("status",""), ts.get("progress",0)
    sg = ts.get("stage","")
    em = ts.get("error_message") or (ts.get("result") or {}).get("error","") or ""
    print(f"  [{st}] {pr}% step={sg}", end="")
    if st == "completed":
        print()
        rq = (ts.get("result") or {}).get("report_quality","?")
        strategies = (ts.get("result") or {}).get("strategies",[])
        print(f"  quality={rq}, strategies={len(strategies)}")
        break
    elif st == "failed":
        print(f" error={em[:120]}")
        break
    else:
        print()
