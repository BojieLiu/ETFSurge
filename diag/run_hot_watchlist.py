# -*- coding: utf-8 -*-
"""第4/5步：热点板块+个股验证 & 自选功能验证"""
import json
import os
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)


def api(method, path, data=None, t=60):
    try:
        if method == "GET":
            r = urllib.request.urlopen(BASE + path, timeout=t)
        else:
            body = json.dumps(data).encode()
            req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
            r = urllib.request.urlopen(req, timeout=t)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err__": "HTTP %s: %s" % (e.code, e.read().decode()[:300])}
    except Exception as e:
        return {"__err__": str(e)}


def save(name, obj):
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return obj


def main():
    # ===== 第4步：热点板块与个股 =====
    print("=== 热点板块 ===")
    hp = save("hot_plates", api("GET", "/api/v1/market/hot-plates", t=90))
    if isinstance(hp, list):
        print("hot plates:", len(hp))
        for p in hp[:8]:
            print("  -", p.get("plate_name") or p.get("name"), "| chg:", p.get("change_pct"), "| hot:", p.get("heat") or p.get("hot_score"))
    else:
        print("hot plates FAIL:", str(hp)[:200])

    print("=== 板块热度 heat ===")
    ht = save("sector_heat", api("GET", "/api/v1/market/sectors/heat?limit=10", t=90))
    items = ht.get("items") if isinstance(ht, dict) else ht
    if isinstance(items, list):
        print("heat items:", len(items))
        for it in items[:8]:
            print("  -", it.get("name") or it.get("plate_name"), "| chg:", it.get("change_pct"), "| heat:", it.get("heat"))
    else:
        print("heat FAIL:", str(ht)[:200])

    print("=== 个股热度榜 ===")
    sr = save("stock_hot_rank", api("GET", "/api/v1/market/stock-hot-rank", t=90))
    if isinstance(sr, list):
        print("stock hot rank:", len(sr))
        for s in sr[:8]:
            print("  -", s.get("name") or s.get("stock_name"), s.get("code") or s.get("symbol"), "| chg:", s.get("change_pct"))
    else:
        print("stock hot rank FAIL:", str(sr)[:200])

    # ===== 第5步：自选功能 =====
    print("=== 自选列表（前置） ===")
    wl0 = api("GET", "/api/v1/market/watchlist", t=60)
    wl0_items = wl0.get("items") if isinstance(wl0, dict) else wl0
    print("watchlist before:", len(wl0_items) if isinstance(wl0_items, list) else wl0)
    before = {str(w.get("symbol")) for w in wl0_items} if isinstance(wl0_items, list) else set()

    print("=== 新增自选 ===")
    to_add = {"510500", "159915"}
    added = {}
    for sym in to_add:
        if sym in before:
            print("  %s already in watchlist, skip" % sym)
            continue
        r = save("watchlist_add_%s" % sym, api("POST", "/api/v1/market/watchlist", {"symbol": sym}, t=60))
        print("  add %s ->" % sym, r if "__err__" in r else "OK")
        added[sym] = r

    print("=== 自选列表（后置） ===")
    wl1 = api("GET", "/api/v1/market/watchlist", t=90)
    save("watchlist_after", wl1)
    wl1_items = wl1.get("items") if isinstance(wl1, dict) else wl1
    if isinstance(wl1_items, list):
        print("watchlist after:", len(wl1_items))
        for w in wl1_items:
            rt = w.get("realtime") or {}
            print("  -", w.get("symbol"), w.get("name"), "| price:", rt.get("price"), "| chg:", rt.get("change_pct"), "| notes:", w.get("notes"))
    else:
        print("watchlist FAIL:", str(wl1)[:200])

    # 清理：删除新增项
    print("=== 清理新增 ===")
    if isinstance(wl1_items, list):
        for w in wl1_items:
            if str(w.get("symbol")) in to_add and w.get("id"):
                r = api("DELETE", "/api/v1/market/watchlist/%s" % w["id"], t=30)
                print("  remove %s(id=%s) ->" % (w.get("symbol"), w["id"]), "OK" if "__err__" not in r else r)

    print("=== DONE ===")


if __name__ == "__main__":
    main()
