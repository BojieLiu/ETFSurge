"""运行时验证（round63）：真实发起一次 design + 一次 check，在 LLM 报告窗口内
连续采样 /timeline，断言**同一次运行只出现一行**。

反假完成：不构造夹具，直接打真实链路（真 DB、真引擎、真 LLM 调用）。
旧代码在窗口内会返回两行（design「成功」+ task「运行中」）。
"""
import json
import sys
import time
import urllib.request

BASE = "http://localhost:8000/api/v1"


def _post(path, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _timeline():
    with urllib.request.urlopen(BASE + "/portfolio/timeline?limit=20&offset=0", timeout=30) as r:
        return json.loads(r.read().decode())["items"]


def _rows_for(items, rec_id, kind):
    return [i for i in items if i["_type"] == kind and i["id"] == rec_id]


print("=" * 70)
print("POST /portfolio/design-async")
d = _post("/portfolio/design-async", {"capital": 500000})
print("  task_id =", d["task_id"])
print("POST /portfolio/strategy-check-async")
c = _post("/portfolio/strategy-check-async", {"capital": 500000, "portfolio_type": "on_exchange"})
print("  task_id =", c["task_id"])

design_id = check_id = None
worst_d = worst_c = 0
samples = 0
rows_seen = []

deadline = time.time() + 420
while time.time() < deadline:
    time.sleep(4)
    samples += 1
    try:
        items = _timeline()
    except Exception as e:
        print("  timeline read failed:", e)
        continue

    # design **记录**行 = 带 capital 的那一行（task 行 capital 恒 None）；
    # 在记录落库前不存在，此时只有 task 行（id == task_id）——那是正确的，不是重复。
    drow = next((i for i in items if i["_type"] == "design"
                 and i.get("task_id") == d["task_id"] and i.get("capital") is not None), None)
    crow = next((i for i in items if i["_type"] == "check"
                 and i.get("task_id") == c["task_id"]), None)
    if drow and not design_id:
        design_id = drow["id"]
        print(f"  [sample {samples}] design 记录落库 id={drow['id']} status={drow['status']} "
              f"capital={drow['capital']} task_id={drow.get('task_id')}  <-- LLM 报告窗口开始")
    if crow and not check_id:
        check_id = crow["id"]
        print(f"  [sample {samples}] check 记录落库 id={crow['id']} task_id={crow.get('task_id')}")

    for kind, rid, bucket in (("design", design_id, "d"), ("check", check_id, "c")):
        if rid is None:
            continue
        n = len(_rows_for(items, rid, kind))
        if bucket == "d":
            worst_d = max(worst_d, n)
        else:
            worst_c = max(worst_c, n)
        if n > 1:
            print(f"  !! [sample {samples}] {kind} id={rid} 出现 {n} 行（旧缺陷复现）：")
            for i in _rows_for(items, rid, kind):
                print(f"       {i}")

    # 两个任务都到终态才算采完窗口
    dstat = next((i["status"] for i in items if i.get("task_id") == d["task_id"]), None)
    cstat = next((i["status"] for i in items if i.get("task_id") == c["task_id"]), None)
    if design_id and check_id and dstat in ("completed", "failed") and cstat in ("completed", "failed"):
        break

print("=" * 70)
print(f"samples={samples}  design_id={design_id}  check_id={check_id}")
print(f"design 行最大条数={worst_d}（期望 1）")
print(f"check  行最大条数={worst_c}（期望 1）")
ok = design_id is not None and check_id is not None and worst_d == 1 and worst_c == 1
print("RUNTIME REALITY:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)