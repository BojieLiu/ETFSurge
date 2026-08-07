# -*- coding: utf-8 -*-
"""取最新设计详情全文，定位涨跌幅数字与"数据源不可用"出现位置"""
import urllib.request, json

BASE = "http://localhost:8000/api/v1"


def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=30).read().decode())


# 最新设计列表
designs = get("/portfolio/designs?limit=5")
items = designs if isinstance(designs, list) else designs.get("items") or designs.get("designs") or []
print("designs count:", len(items))
for d in items:
    print(f"  id={d.get('id')} status={d.get('status')} created={d.get('created_at')} profile={d.get('risk_profile')}")

# 取最新一条详情
if items:
    latest = items[0]
    did = latest.get("id")
    detail = get(f"/portfolio/designs/{did}")
    print(f"\n=== design #{did} ===")
    print("status:", detail.get("status"))
    dt = detail.get("design_text") or ""
    print("design_text len:", len(dt))
    # 定位涨跌幅/数据源相关行
    for kw in ("涨跌", "数据源", "不可用", "异常", "%"):
        idx = dt.find(kw)
        if idx >= 0:
            start = max(0, idx - 120)
            print(f"\n--- 命中 '{kw}' @ {idx} ---")
            print(dt[start:idx + 120].replace("\n", " ")[:260])
    # 保存全文
    open("diag/out/design_latest.json", "w", encoding="utf-8").write(
        json.dumps(detail, ensure_ascii=False, indent=1)
    )
