# -*- coding: utf-8 -*-
"""手动触发场内策略检查，验证本地后端是否"组合为空" """
import json, time, urllib.request

BASE = "http://localhost:8000/api/v1"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read().decode())


# 1. 触发场内检查
try:
    r = post("/portfolio/strategy-check-async", {
        "risk_profile": "balanced", "capital": 500000, "market": "A",
        "portfolio_type": "on_exchange",
    })
    print("[触发]", json.dumps(r, ensure_ascii=False)[:200])
    task_id = r.get("task_id") or r.get("taskId") or r.get("id")
except Exception as e:
    print("[触发失败]", repr(e))
    raise SystemExit

# 2. 轮询任务
for i in range(40):
    time.sleep(3)
    t = get(f"/portfolio/tasks/{task_id}") if task_id else None
    if t is None:
        t = {}
    status = t.get("status")
    print(f"  轮询 {i}: status={status} progress={t.get('progress')}")
    if status in ("completed", "failed", "error"):
        break
else:
    print("  超时未完成")

# 3. 查结果
print("\n[任务详情]", json.dumps(t, ensure_ascii=False)[:400])
rec = t.get("record_id") or t.get("recordId")
if rec:
    d = get(f"/portfolio/strategy-checks/{rec}")
    print("[检查详情] status=", d.get("status"))
    print("summary:", str(d.get("summary"))[:200])
    ha = d.get("holdings_analysis") or []
    print("holdings:", len(ha))
