# -*- coding: utf-8 -*-
"""拉取因子模型当前状态：no_data/warn/static 因子明细"""
import urllib.request, json
from collections import Counter


def get(p):
    return json.loads(urllib.request.urlopen("http://localhost:8000" + p, timeout=30).read().decode())


act = get("/api/v1/factors/active")
cats = act.get("categories", [])
fs = [f for c in cats for f in c.get("factors", [])]
print("total:", act.get("total"), "| categories:", [c.get("name") for c in cats])
print("status dist:", dict(Counter(f.get("status") for f in fs)))
print()
for f in fs:
    if f.get("status") in ("no_data", "warn", "static"):
        print(
            f"[{f.get('status')}] {f.get('name')} (code={f.get('code')}) "
            f"avg_ic={f.get('avg_ic')} reason={f.get('reason')}"
        )
