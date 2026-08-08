# -*- coding: utf-8 -*-
"""round9: 实测天天基金 f10/lsjz 净值接口对场内 ETF 可用性 + 腾讯 78/81 语义"""
import urllib.request
import json

HDRS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "http://fundf10.eastmoney.com/",
}


def probe(name, url, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or HDRS)
        resp = urllib.request.urlopen(req, timeout=10)
        return name, resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return name, "FAIL", str(e)[:150]


# 天天基金历史净值（f10/lsjz）
url = "https://api.fund.eastmoney.com/f10/lsjz?fundCode=510050&pageIndex=1&pageSize=3"
n, st, body = probe("ttj-lsjz-510050", url)
print("=== %s status=%s" % (n, st))
if st == 200:
    d = json.loads(body)
    rows = (d.get("Data") or {}).get("LSJZList") or []
    print("   errcode:", d.get("ErrCode"), "rows:", len(rows))
    for r in rows[:2]:
        print("   ", {k: r.get(k) for k in ("FSRQ", "DWJZ", "LJJZ", "JZZZL")})
else:
    print("   ", body)

# 天天基金移动端接口
url2 = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNPeriodIncrease?FCODE=510050&RANGE=y&deviceid=Wap&plat=Wap&product=EFund&version=6.2.8"
n, st, body = probe("ttj-mobile-510050", url2)
print("=== %s status=%s" % (n, st))
print("   ", body[:300])

# 腾讯 78/81 语义（对比 ETF 与股票）
url3 = "http://qt.gtimg.cn/q=sh510050,sz000001,sh510880"
n, st, body = probe("qq-3", url3)
if st == 200:
    for line in body.strip().split("\n"):
        try:
            parts = line.split('"')[1].split("~")
        except Exception:
            continue
        print("=== qq", parts[1], parts[2], "n=", len(parts))
        for i in (3, 31, 78, 79, 80, 81):
            if i < len(parts):
                print("   [%d]=%r" % (i, parts[i]))
