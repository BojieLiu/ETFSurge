# -*- coding: utf-8 -*-
"""round9: 实测天天基金 ETF 份额/规模接口（fetch_etf_shares_outstanding 降级链候选）"""
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def probe(name, url, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        return name, resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return name, "FAIL", str(e)[:150]


cases = [
    ("mob-FInfo", "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo?FCODE=510050&deviceid=Wap&plat=Wap&product=EFund&version=6.2.8"),
    ("mob-PeriodIncrease", "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNPeriodIncrease?FCODE=510050&RANGE=y&deviceid=Wap&plat=Wap&product=EFund&version=6.2.8"),
]
for name, url in cases:
    n, st, body = probe(name, url)
    print("=== %s status=%s" % (n, st))
    print("   ", body[:400])
