"""round6 诊断辅助脚本：提交设计/策略检查任务并轮询，结果存 JSON。
用法:
  python diag/api_diag.py design [capital]
  python diag/api_diag.py check [capital]
"""
import json, os, sys, time, urllib.request

BASE = "http://localhost:8000/api/v1"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)


def req(method, path, body=None, timeout=120):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def poll_task(task_id, max_wait=600, interval=5):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        t = req("GET", f"/portfolio/tasks?limit=1&task_id={task_id}") if False else None
        # list_tasks 不支持按 id 过滤，直接用详情接口
        try:
            detail = req("GET", f"/portfolio/tasks/{task_id}")
        except Exception as e:
            detail = {"status": "unknown", "error": str(e)}
        status = detail.get("status")
        stage = detail.get("stage", "")
        progress = detail.get("progress", 0)
        print(f"  [{time.time()-t0:5.1f}s] task={task_id} status={status} stage={stage} progress={progress}")
        if status in ("completed", "failed", "canceled"):
            return detail
        time.sleep(interval)
    return {"status": "timeout"}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "design"
    capital = int(sys.argv[2]) if len(sys.argv) > 2 else 500000
    if cmd == "design":
        body = {"capital": capital, "market": "A"}
        resp = req("POST", "/portfolio/design-async", body, timeout=30)
        print("submit:", json.dumps(resp, ensure_ascii=False))
        tid = resp.get("task_id")
        if not tid:
            return
        detail = poll_task(tid)
        with open(os.path.join(OUT, f"design_task_{tid}.json"), "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        # 汇总
        result = detail.get("result", {})
        print("\n=== DESIGN SUMMARY ===")
        print("status:", detail.get("status"), "stage:", detail.get("stage"))
        print("error:", detail.get("error_message"))
        for s in result.get("strategies", []):
            etfs = s.get("etfs", [])
            core = [e for e in etfs if e.get("layer") == "core"]
            print(f"\n[{s.get('id')}] {s.get('label')} 层预算={s.get('layer_budget')}")
            print("  core:", [(e.get("symbol"), e.get("name"), round(e.get("weight", 0), 4)) for e in core])
            print("  etfs:", [(e.get("symbol"), e.get("name"), e.get("layer"), round(e.get("weight", 0), 4)) for e in etfs if e.get("symbol") != "CASH"])
        md = result.get("design_metadata", {})
        print("\nmetadata:", {k: v for k, v in md.items() if not isinstance(v, (list, dict))})
    elif cmd == "check":
        body = {"total_capital": capital, "portfolio_type": "on_exchange"}
        resp = req("POST", "/portfolio/strategy-check-async", body, timeout=30)
        print("submit:", json.dumps(resp, ensure_ascii=False))
        tid = resp.get("task_id")
        if not tid:
            return
        detail = poll_task(tid)
        with open(os.path.join(OUT, f"check_task_{tid}.json"), "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        result = detail.get("result", {})
        print("\n=== STRATEGY CHECK SUMMARY ===")
        print("status:", detail.get("status"), "stage:", detail.get("stage"))
        print("error:", detail.get("error_message"))
        print("regime:", result.get("market_regime"))
        print("suggestions:", len(result.get("suggestions", [])))
        for s in result.get("suggestions", [])[:30]:
            print("  ", s if isinstance(s, str) else json.dumps(s, ensure_ascii=False))
        print("holdings_analysis:", len(result.get("holdings_analysis", [])))
        for h in result.get("holdings_analysis", [])[:30]:
            print("  ", h if isinstance(h, str) else json.dumps(h, ensure_ascii=False))
        print("risk_warnings:", result.get("risk_warnings"))
        summary = result.get("summary")
        if isinstance(summary, str):
            print("\nsummary[:800]:", summary[:800].replace("\\n", "\n"))
    else:
        print("unknown cmd", cmd)


if __name__ == "__main__":
    main()
