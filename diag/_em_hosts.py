# -*- coding: utf-8 -*-
"""东财板块接口多域名可用性对比（push2 vs push2delay）"""
import json, urllib.request

HOSTS = ["push2.eastmoney.com", "push2delay.eastmoney.com"]
for host in HOSTS:
    url = (
        f"https://{host}/api/qt/clist/get?pn=1&pz=10&po=1&np=1"
        f"&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f3"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=8).read().decode()
        d = json.loads(raw)
        diff = (d.get("data") or {}).get("diff") or []
        print(f"[{host}] OK rows={len(diff)} sample={[(r.get('f14'), r.get('f3')) for r in diff[:3]]}")
    except Exception as e:
        print(f"[{host}] FAIL {type(e).__name__}: {e}")
