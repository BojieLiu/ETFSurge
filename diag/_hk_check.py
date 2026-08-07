# -*- coding: utf-8 -*-
"""港股热门个股 + 板块热度数据合理性核查"""
import json, urllib.request

BASE = "http://localhost:8000/api/v1"


def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=30).read().decode())


print("=== 港股热门个股 stock-hot-rank?market=HK ===")
try:
    hk_rank = get("/market/stock-hot-rank?market=HK")
    items = hk_rank if isinstance(hk_rank, list) else hk_rank.get("items") or hk_rank.get("data") or []
    print("条数:", len(items))
    for it in items[:15]:
        print(f"  {it.get('code')} {it.get('name')}: change_pct={it.get('change_pct')} market={it.get('market')}")
except Exception as e:
    print("FAIL", repr(e))

print("\n=== 港股板块热度 sectors/heat?market=HK ===")
try:
    hk_heat = get("/market/sectors/heat?market=HK")
    items = hk_heat.get("items") or []
    print("条数:", len(items))
    for it in items[:15]:
        print(f"  {it.get('name')}: heat_index={it.get('heat_index')} change_pct={it.get('change_pct')}")
except Exception as e:
    print("FAIL", repr(e))

print("\n=== A股对照（验证 market 参数是否生效）===")
try:
    a_rank = get("/market/stock-hot-rank?market=A")
    items = a_rank if isinstance(a_rank, list) else a_rank.get("items") or a_rank.get("data") or []
    for it in items[:5]:
        print(f"  {it.get('code')} {it.get('name')}: change_pct={it.get('change_pct')} market={it.get('market')}")
except Exception as e:
    print("FAIL", repr(e))
