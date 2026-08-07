# -*- coding: utf-8 -*-
"""第2步：组合设计 + 场内策略检查（on_exchange）+ 市场快照"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
OUT = os.path.join(os.path.dirname(__file__), "out")


def api_get(path, t=60):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=t)
        return json.loads(r.read().decode())
    except Exception as e:
        return {"__err__": str(e)}


def api_post(path, data, t=300):
    body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=t)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err__": "HTTP %s: %s" % (e.code, e.read().decode()[:300])}
    except Exception as e:
        return {"__err__": str(e)}


def poll(task_id, max_wait=420, interval=5):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        r = api_get("/api/v1/portfolio/tasks/%s" % task_id, t=30)
        st = r.get("status", "?")
        print("  task %s: %s %s%% %s" % (task_id, st, r.get("progress", 0), r.get("stage", "")), flush=True)
        if st in ("completed", "failed"):
            return r
        time.sleep(interval)
    return {"__err__": "poll timeout"}


def main():
    os.makedirs(OUT, exist_ok=True)

    # 1) 市场快照（审阅对照）
    print("=== 市场快照 ===")
    snap = {}
    for name, path in [
        ("regime", "/api/v1/market/regime"),
        ("sentiment", "/api/v1/market/sentiment"),
        ("indices", "/api/v1/market/indices/global"),
        ("hot_plates", "/api/v1/market/hot-plates"),
        ("pool_metrics", "/api/v1/admin/metrics"),
    ]:
        snap[name] = api_get(path, t=90)
        ok = "OK" if "__err__" not in snap[name] else "FAIL"
        print("  %-12s %s" % (name, ok), flush=True)
    with open(os.path.join(OUT, "market_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    # 2) 组合设计
    print("=== 组合设计 ===")
    r = api_post("/api/v1/portfolio/design-async", {"risk_profile": "balanced", "capital": 500000, "market": "A"})
    tid = r.get("task_id")
    print("design task:", tid, r.get("__err__", ""))
    if tid:
        tr = poll(tid)
        with open(os.path.join(OUT, "design_task.json"), "w", encoding="utf-8") as f:
            json.dump(tr, f, ensure_ascii=False, indent=1)
        rid = tr.get("record_id")
        if rid:
            detail = api_get("/api/v1/portfolio/designs/%s" % rid, t=120)
            with open(os.path.join(OUT, "design_detail.json"), "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=1)
            print("  design detail saved (id=%s)" % rid)

    # 3) 场内策略检查（portfolio_type=on_exchange）
    print("=== 场内策略检查 ===")
    r2 = api_post("/api/v1/portfolio/strategy-check-async",
                  {"risk_profile": "balanced", "capital": 500000, "market": "A", "portfolio_type": "on_exchange"})
    tid2 = r2.get("task_id")
    print("check task:", tid2, r2.get("__err__", ""))
    if tid2:
        tr2 = poll(tid2)
        with open(os.path.join(OUT, "check_task.json"), "w", encoding="utf-8") as f:
            json.dump(tr2, f, ensure_ascii=False, indent=1)
        rid2 = tr2.get("record_id")
        if rid2:
            cd = api_get("/api/v1/portfolio/strategy-checks/%s" % rid2, t=120)
            with open(os.path.join(OUT, "check_detail.json"), "w", encoding="utf-8") as f:
                json.dump(cd, f, ensure_ascii=False, indent=1)
            print("  check detail saved (id=%s)" % rid2)

    print("=== DONE ===")


if __name__ == "__main__":
    main()
