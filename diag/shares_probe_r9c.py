# -*- coding: utf-8 -*-
"""round9: 实测东财 ETF 份额字段（f124/f125/f219 等）"""
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

HDRS = {"User-Agent": "Mozilla/5.0"}


def probe(name, url):
    try:
        req = urllib.request.Request(url, headers=HDRS)
        resp = urllib.request.urlopen(req, timeout=10)
        return name, resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return name, "FAIL", str(e)[:150]


url = "https://push2delay.eastmoney.com/api/qt/stock/get?secid=1.510050&fields=f57,f58,f43,f124,f125,f219,f220&fltt=2&invt=2"
n, st, body = probe("stock/get f124", url)
print("=== %s status=%s" % (n, st))
print("   ", body[:400])

# akshare 份额接口候选
try:
    import akshare as ak
    df = ak.fund_etf_spot_em()
    print("=== fund_etf_spot_em cols:", list(df.columns)[:20] if df is not None else None)
    if df is not None and len(df) > 0:
        row = df[df["代码"] == "510050"]
        print("   510050:", row.iloc[0].to_dict() if len(row) else "not found")
except Exception as e:
    print("=== fund_etf_spot_em FAIL:", type(e).__name__, str(e)[:200])
