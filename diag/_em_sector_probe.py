# -*- coding: utf-8 -*-
"""东财板块行情接口验证（行业板块涨跌幅补充源）"""
import json, urllib.request

URLS = [
    # 行业板块 fs=m:90+t:2
    ("行业板块 t:2", "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=8&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f3,f104,f105"),
    # 概念板块 fs=m:90+t:3
    ("概念板块 t:3", "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=8&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f12,f14,f3,f104,f105"),
]
for name, url in URLS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=8).read().decode()
        d = json.loads(raw)
        diff = (d.get("data") or {}).get("diff") or []
        print(f"[{name}] rows={len(diff)}")
        for r in diff[:5]:
            print(f"   {r.get('f12')} {r.get('f14')}: f3={r.get('f3')} 涨跌额f104={r.get('f104')}")
    except Exception as e:
        print(f"[{name}] FAIL {type(e).__name__}: {e}")
