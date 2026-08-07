# -*- coding: utf-8 -*-
"""修复后复验：港股热门个股 + 板块热度涨跌幅"""
import json, urllib.request

BASE = "http://localhost:8000/api/v1"


def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=30).read().decode())


d = get("/market/stock-hot-rank?market=HK")
items = d if isinstance(d, list) else d.get("items") or d.get("data") or []
print("[港股热门个股]", len(items), "条")
for it in items[:8]:
    print(f"  {it.get('symbol')} {it.get('name')}: price={it.get('price')} change_pct={it.get('change_pct')}")

h = get("/market/sectors/heat?market=HK")
items = h.get("items") or []
print("\n[港股板块热度]", len(items), "条")
for it in items[:12]:
    print(f"  {it.get('name')}: change_pct={it.get('change_pct')}")
