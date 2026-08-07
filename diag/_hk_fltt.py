# -*- coding: utf-8 -*-
"""验证 fltt 参数对东财港股 f2/f3 的影响 + stock-hot-rank HK 分支"""
import json, urllib.request

# 1. 对比带/不带 fltt=2
base = "http://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1&fs=m:128&fields=f12,f14,f2,f3,f6&fid=f6"
for label, extra in (("无fltt", ""), ("fltt=2", "&fltt=2&invt=2")):
    url = base + extra
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    d = json.loads(urllib.request.urlopen(req, timeout=8).read().decode())
    diff = (d.get("data") or {}).get("diff") or []
    print(f"[{label}]")
    for r in diff[:3]:
        print(f"   {r.get('f12')} {r.get('f14')}: f2={r.get('f2')} f3={r.get('f3')}")

# 2. stock-hot-rank 端点 HK 分支
import urllib.request as u
for m in ("HK", "A"):
    try:
        r = u.urlopen(f"http://localhost:8000/api/v1/market/stock-hot-rank?market={m}", timeout=30)
        d = json.loads(r.read().decode())
        items = d if isinstance(d, list) else d.get("items") or d.get("data") or []
        print(f"\n[stock-hot-rank market={m}] {len(items)} 条")
        for it in items[:3]:
            print("  ", json.dumps(it, ensure_ascii=False)[:150])
    except Exception as e:
        print(f"\n[stock-hot-rank market={m}] FAIL {type(e).__name__}: {e}")
