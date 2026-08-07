# -*- coding: utf-8 -*-
"""560600 全链复验 v2：pool/快照/K线/外部源"""
import asyncio, json, os, sys, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

BASE = "http://localhost:8000/api/v1"
TARGET = "560600"


def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=30).read().decode())


def main():
    from app.services.market_data_hub import market_data_hub

    # 1. pool 全量查 560600
    pool = market_data_hub.get_pool() or []
    print("[1] pool size:", len(pool))
    hit = [p for p in pool if str(p.get("symbol")) == TARGET]
    print("    560600 in pool:", json.dumps(hit, ensure_ascii=False)[:400] if hit else "NO")

    # 2. 快照文件
    snap_path = os.path.join("data", "etf_list_cache.json")
    if os.path.exists(snap_path):
        import time as _t
        print(f"[2] etf_list_cache.json mtime={_t.ctime(os.path.getmtime(snap_path))}")
        data = json.load(open(snap_path, encoding="utf-8"))
        etfs = data.get("etfs", []) if isinstance(data, dict) else data
        print("    snapshot etfs:", len(etfs))
        h2 = [e for e in etfs if str(e.get("symbol")) == TARGET]
        print("    560600 in snapshot:", json.dumps(h2, ensure_ascii=False)[:300] if h2 else "NO")
        # 抽样看 510050/560600 字段
        for code in ("510050", "510500"):
            e = next((x for x in etfs if str(x.get("symbol")) == code), None)
            print(f"    {code} snapshot:", {k: e.get(k) for k in ("symbol", "price", "change_pct")} if e else None)

    # 3. K 线
    rows = market_data_hub.get_kline_rows_any(TARGET) if hasattr(market_data_hub, "get_kline_rows_any") else None
    if rows:
        closes = [float(r["close"]) for r in rows if r.get("close") is not None]
        print(f"[3] kline rows={len(rows)} last closes={closes[-5:]}")
    else:
        print("[3] kline rows: None/empty")

    # 4. 外部实时源
    def probe(name, url, headers):
        try:
            req = urllib.request.Request(url, headers=headers)
            r = urllib.request.urlopen(req, timeout=6)
            return f"OK len={len(r.read())}"
        except Exception as e:
            return f"FAIL {type(e).__name__}: {e}"

    print("[4] 外部源 560600:")
    print("   QQ sh560600:", probe("qq", "http://qt.gtimg.cn/q=sh560600", {"User-Agent": "Mozilla/5.0"}))
    print("   Sina sh560600:", probe("sina", "http://hq.sinajs.cn/list=sh560600", {"Referer": "http://finance.sina.com.cn"}))
    print("   EM 1.560600:", probe("em", "https://push2.eastmoney.com/api/qt/stock/get?secid=1.560600&fields=f43,f57,f58,f169,f170", {"User-Agent": "Mozilla/5.0"}))

    # 5. 设计 #427 中 560600 的 allocation 全字段
    d = json.load(open(r"E:\ETF_Surge\diag\out\design_latest.json", encoding="utf-8"))
    for st in d.get("strategies") or []:
        for a in st.get("etfs") or []:
            if str(a.get("symbol")) == TARGET:
                print(f"[5] design allocation: {json.dumps(a, ensure_ascii=False)[:400]}")
                break

    # 6. 设计 #427 中其它标的变化对比：报告涨跌 vs 当前实时
    q = get("/market/realtime/batch?symbols=510050,563020,589720,562600")
    items = q if isinstance(q, list) else q.get("items") or q.get("data") or []
    print("\n[6] 当前实时 vs 设计报告:")
    cur = {x.get("symbol"): x.get("change_pct") for x in items}
    for st in d.get("strategies") or []:
        for a in st.get("etfs") or []:
            c = str(a.get("symbol"))
            if c in cur:
                print(f"   {c}: 报告={a.get('daily_change_pct')} 当前实时={cur[c]}")
                del cur[c]
    for c, v in cur.items():
        print(f"   {c}: (报告无) 当前实时={v}")


main()
