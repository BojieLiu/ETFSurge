# -*- coding: utf-8 -*-
"""手工实测 IOPV 三级链每个源"""
import urllib.request
import json

SINA = "http://hq.sinajs.cn/list=sh510050,sh510880"
QQ = "http://qt.gtimg.cn/q=sh510050,sh510880"
EM = "https://push2.eastmoney.com/api/qt/ulist.np/get?secids=1.510050,1.510880&fields=f12,f13,f2,f236&fltt=2&invt=2"


def probe(name, url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=8)
        body = resp.read().decode("utf-8", errors="replace")
        print(f"[{name}] OK status={resp.status} len={len(body)} head={body[:120]!r}")
        return body
    except Exception as e:
        print(f"[{name}] FAIL {type(e).__name__}: {e}")
        return None


probe("sina", SINA, {"Referer": "http://finance.sina.com.cn"})
probe("sina-https", SINA.replace("http://", "https://"), {"Referer": "https://finance.sina.com.cn"})
probe("qq", QQ, {"User-Agent": "Mozilla/5.0"})
probe("em", EM, {"User-Agent": "Mozilla/5.0"})
