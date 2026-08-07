# -*- coding: utf-8 -*-
"""实测 sectors/heat 涨跌幅回填 + symbol stream（修复后）"""
import json, urllib.request

BASE = "http://localhost:8000/api/v1"


def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=30).read().decode())


h = get("/market/sectors/heat?limit=20")
items = h.get("items") or []
print("[sectors/heat] total:", h.get("total"))
non_zero = 0
for it in items[:15]:
    c = it.get("change_pct")
    if c:
        non_zero += 1
    print(f"  {it.get('name'):<10} change_pct={c}")
print("非零涨跌幅板块:", non_zero, "/", len(items))

# symbol stream 复验
payload = {"symbol": "600519", "market": "A"}
req = urllib.request.Request(BASE + "/analysis/symbol-analysis/stream", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
r = urllib.request.urlopen(req, timeout=90)
body = r.read().decode()
print("\n[symbol stream] STREAM_ERROR?", "STREAM_ERROR" in body, "| full_text?", "full_text" in body)
