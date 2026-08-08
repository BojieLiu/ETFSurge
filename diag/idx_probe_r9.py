# -*- coding: utf-8 -*-
"""round9: 确认中证A500 指数代码（159338 跟踪指数）——000510 vs 930050"""
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def probe(name, url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        return name, resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return name, "FAIL", str(e)[:120]


for idx in ["sh000510", "sh930050"]:
    n, st, body = probe("qq-index-" + idx, "http://qt.gtimg.cn/q=" + idx)
    print("=== %s status=%s" % (n, st))
    if st == 200 and "=" in body and '"' in body:
        parts = body.split('"')[1].split("~")
        print("   name=%r code=%r price=%r" % (parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "", parts[3] if len(parts) > 3 else ""))

n, st, body = probe("em-159338", "https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids=0.159338&fields=f12,f14,f2,f3&fltt=2&invt=2")
print("=== em-159338 status=%s body=%s" % (st, body[:200]))
