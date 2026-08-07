# -*- coding: utf-8 -*-
"""560600 外部源 + 510050 今日K线走势 + 快照路径"""
import json, os, sys, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))


def probe(name, url, headers, dec="utf-8"):
    try:
        req = urllib.request.Request(url, headers=headers)
        r = urllib.request.urlopen(req, timeout=6)
        body = r.read().decode(dec, errors="replace")
        return f"OK len={len(body)} head={body[:80]!r}"
    except Exception as e:
        return f"FAIL {type(e).__name__}: {e}"


print("[560600 外部源]")
print("  QQ:", probe("qq", "http://qt.gtimg.cn/q=sh560600", {"User-Agent": "Mozilla/5.0"}))
print("  Sina:", probe("sina", "http://hq.sinajs.cn/list=sh560600", {"Referer": "http://finance.sina.com.cn"}))
print("  EM:", probe("em", "https://push2.eastmoney.com/api/qt/stock/get?secid=1.560600&fields=f43,f57,f58,f169,f170", {"User-Agent": "Mozilla/5.0"}))
print("  EM-batch:", probe("em", "https://push2.eastmoney.com/api/qt/ulist.np/get?secids=1.560600&fields=f12,f14,f2,f3&fltt=2&invt=2", {"User-Agent": "Mozilla/5.0"}))

print("\n[对照 510050]")
print("  QQ:", probe("qq", "http://qt.gtimg.cn/q=sh510050", {"User-Agent": "Mozilla/5.0"}))

print("\n[快照路径]")
from app.services.market_data_hub import market_data_hub
print("  _etf_cache_file:", market_data_hub._etf_cache_file() if hasattr(market_data_hub, "_etf_cache_file") else "?")
import glob
for p in glob.glob(os.path.join("data", "*.json")):
    print("  data/*.json:", p)
for p in glob.glob(os.path.join("..", "data", "*.json")):
    print("  ../data/*.json:", p)

print("\n[510050 K线今日]")
rows = market_data_hub.get_history("510050", "A", "daily") or []
if rows:
    for r in rows[-3:]:
        print(f"  {r.get('date')}: close={r.get('close')} change={r.get('change_pct')}")
