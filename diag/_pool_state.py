# -*- coding: utf-8 -*-
"""pool 内容/快照文件/刷新机制检查"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))


def main():
    from app.services.market_data_hub import market_data_hub

    pool = market_data_hub.get_pool() or {}
    print("[pool] type:", type(pool).__name__, "| keys:", list(pool.keys())[:8] if isinstance(pool, dict) else pool[:10])
    if isinstance(pool, dict):
        etfs = pool.get("etfs") or pool.get("items") or []
        print("  etfs entries:", len(etfs) if isinstance(etfs, list) else type(etfs).__name__)

    # 快照文件
    sp = os.path.join("data", "etf_list_cache.json")
    if os.path.exists(sp):
        import time as _t
        print(f"\n[snapshot] mtime={_t.ctime(os.path.getmtime(sp))}")
        data = json.load(open(sp, encoding="utf-8"))
        etfs = data.get("etfs", []) if isinstance(data, dict) else data
        print("  etfs:", len(etfs), "| keys of first:", list(etfs[0].keys()) if etfs else None)
        for code in ("560600", "510050", "510500"):
            e = next((x for x in etfs if str(x.get("symbol")) == code), None)
            if e:
                print(f"  {code}: price={e.get('price')} change_pct={e.get('change_pct')} daily_change_pct={e.get('daily_change_pct')}")
            else:
                print(f"  {code}: NOT IN SNAPSHOT")
    else:
        print("\n[snapshot] etf_list_cache.json NOT FOUND")


main()
