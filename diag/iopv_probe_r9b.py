# -*- coding: utf-8 -*-
"""round9: 实测东财 clist/get 的 IOPV 字段形态"""
import urllib.request

HDRS = {"User-Agent": "Mozilla/5.0"}


def probe(name, url):
    try:
        req = urllib.request.Request(url, headers=HDRS)
        resp = urllib.request.urlopen(req, timeout=8)
        return name, resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return name, "FAIL", str(e)[:150]


cases = [
    ("clist-MK0021-push2delay", "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=2&po=1&np=1&fltt=2&invt=2&fid=f12&fs=b:MK0021&fields=f12,f13,f14,f2,f3,f236"),
    ("ulist-secids-f236-push2delay", "https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids=1.510050&fields=f12,f14,f2,f3,f236&fltt=2&invt=2"),
    ("ulist-secids-f2f3f236-nonfltt", "https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids=1.510050&fields=f12,f13,f2,f3,f236"),
    ("ulist-hk-f236", "https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids=100.00700&fields=f12,f13,f2,f3,f236&fltt=2&invt=2"),
]
for name, url in cases:
    n, st, body = probe(name, url)
    print("=== %s status=%s" % (n, st))
    if st == 200:
        print("   ", body[:400])
    else:
        print("   ", body)
