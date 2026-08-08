# -*- coding: utf-8 -*-
"""round9: 实测主题 ETF 基准指数代码（P1-8 扩展映射）"""
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


# 候选：半导体(sh931865?) / 证券公司(sz399975) / 中证医药(sh000933) / 新能源车(sh930997?)
for idx in ["sh931865", "sz399975", "sh000933", "sh930997", "sh000922"]:
    n, st, body = probe("qq-" + idx, "http://qt.gtimg.cn/q=" + idx)
    print("=== %s status=%s" % (n, st))
    if st == 200 and "=" in body and '"' in body:
        parts = body.split('"')[1].split("~")
        print("   name=%r" % (parts[1] if len(parts) > 1 else ""))
