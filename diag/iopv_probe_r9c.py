# -*- coding: utf-8 -*-
"""round9: 实测 nav/IOPV 可用源——TTJ 日净值 + 东财 stock/get 字段"""
import urllib.request
import json

HDRS = {"User-Agent": "Mozilla/5.0"}


def probe(name, url):
    try:
        req = urllib.request.Request(url, headers=HDRS)
        resp = urllib.request.urlopen(req, timeout=10)
        return name, resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return name, "FAIL", str(e)[:150]


# 1) 东财 stock/get 全字段扫 IOPV 候选字段
for fields in ["f57,f58,f43,f170,f236,f140,f141,f60", "f236", "f140,f141"]:
    url = "https://push2delay.eastmoney.com/api/qt/stock/get?secid=1.510050&fields=%s&fltt=2&invt=2" % fields
    n, st, body = probe("stock/get %s" % fields, url)
    print("=== %s status=%s" % (n, st))
    print("   ", body[:300])

# 2) akshare fund_open_fund_info_em 对场内 ETF 是否可用（TTJ 路径）
try:
    import akshare as ak
    df = ak.fund_open_fund_info_em(symbol="510050", indicator="单位净值")
    print("=== fund_open_fund_info_em(510050) rows=%d" % (0 if df is None else len(df)))
    if df is not None and len(df) > 0:
        print("   cols:", list(df.columns))
        print("   last:", df.tail(1).to_string())
except Exception as e:
    print("=== fund_open_fund_info_em FAIL:", type(e).__name__, str(e)[:200])

# 3) 腾讯 pos 78/81 语义确认：对比 510050（ETF）与一只股票
for sym in ["sh510050", "sz000001"]:
    url = "http://qt.gtimg.cn/q=%s" % sym
    n, st, body = probe("qq %s" % sym, url)
    if st == 200:
        parts = body.split('"')[1].split("~")
        print("=== qq %s nfields=%d" % (sym, len(parts)))
        for i in (1, 2, 3, 31, 32, 78, 81):
            if i < len(parts):
                print("   [%d]=%r" % (i, parts[i]))
