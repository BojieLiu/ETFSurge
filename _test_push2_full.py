#!/usr/bin/env python3
"""Comprehensive test: push2delay + other data sources with various header configs."""
import urllib.request, json, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

print("=" * 65)
print("CROSS-SOURCE HEADER SENSITIVITY TEST")
print("=" * 65)

# === 1. push2delay (EastMoney) ===
print()
print("--- 1. push2delay (EastMoney delay API) ---")
url1 = ("https://push2delay.eastmoney.com/api/qt/clist/get?"
        "pn=1&pz=3&po=1&np=1&fields=f2,f3,f14&fs=m:0+t:6,m:0+t:80")

tests = [
    ("No headers", {}),
    ("Minimal UA", {"User-Agent": "Mozilla/5.0"}),
    ("Full browser", {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }),
    ("With Cookie", {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
        "Cookie": "qzha=nosso; Hm_lvt_6f7b2c09475ed38a6f32cc7fab8f45fa=1710000000",
    }),
]

for label, headers in tests:
    try:
        req = urllib.request.Request(url1, headers=headers)
        r = urllib.request.urlopen(req, timeout=10, context=ctx)
        n = len(json.loads(r.read().decode()).get("data",{}).get("diff",[]))
        print("  [%-14s] %d items  OK" % (label, n))
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

# === 2. push2delay - HK market ===
print()
print("--- 1b. push2delay HK market ---")
url1b = ("https://push2delay.eastmoney.com/api/qt/clist/get?"
         "pn=1&pz=3&po=1&np=1&fields=f2,f3,f14&fs=m:1+t:2")
for label, headers in tests:
    try:
        req = urllib.request.Request(url1b, headers=headers)
        r = urllib.request.urlopen(req, timeout=10, context=ctx)
        n = len(json.loads(r.read().decode()).get("data",{}).get("diff",[]))
        print("  [%-14s] %d items  OK" % (label, n))
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

# === 3. Sina Real-time API ===
print()
print("--- 2. Sina (hq.sinajs.cn) ---")
url2 = "http://hq.sinajs.cn/list=sh510050"

for label, headers in [
    ("No headers", {}),
    ("UA only", {"User-Agent": "Mozilla/5.0"}),
    ("UA+Referer ", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Referer": "https://finance.sina.com.cn/"}),
]:
    try:
        req = urllib.request.Request(url2, headers=headers)
        r = urllib.request.urlopen(req, timeout=10)
        body = r.read().decode("gbk", errors="ignore")
        if "=" in body and '"' in body:
            print("  [%-14s] DATA (has quote fields)" % label)
        else:
            print("  [%-14s] %s" % (label, body[:80]))
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

# === 4. Sina - large batch (stock market list) ===
print()
print("--- 2b. Sina batch stock list ---")
url2b = "http://hq.sinajs.cn/list=sh600000,sh600036,sh601166,sz000001,sz000002"

for label, headers in [
    ("UA only", {"User-Agent": "Mozilla/5.0"}),
    ("UA+Referer ", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Referer": "https://finance.sina.com.cn/"}),
]:
    try:
        req = urllib.request.Request(url2b, headers=headers)
        r = urllib.request.urlopen(req, timeout=10)
        body = r.read().decode("gbk", errors="ignore")
        lines = body.strip().split("\n")
        print("  [%-14s] %d stocks" % (label, len(lines)))
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

# === 5. Sina K-line ===
print()
print("--- 2c. Sina K-line (used by KDJ/RSI etc) ---")
url2c = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
         "CN_MarketData.getKLineData?symbol=sh510050&scale=60&ma=no&datalen=100")

for label, headers in [
    ("UA only", {"User-Agent": "Mozilla/5.0"}),
    ("UA+Referer ", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Referer": "https://finance.sina.com.cn/"}),
]:
    try:
        req = urllib.request.Request(url2c, headers=headers)
        r = urllib.request.urlopen(req, timeout=10)
        body = r.read().decode("gbk", errors="ignore")
        print("  [%-14s] %d chars" % (label, len(body)))
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

# === 6. Tencent gtimg ===
print()
print("--- 3. Tencent gtimg (qt.gtimg.cn) ---")
url3 = "http://qt.gtimg.cn/q=sh510050,sh510300,sz159915"

for label, headers in [
    ("No headers", {}),
    ("Full browser", {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://gu.qq.com/",
    }),
]:
    try:
        req = urllib.request.Request(url3, headers=headers)
        r = urllib.request.urlopen(req, timeout=10)
        body = r.read().decode("gbk", errors="ignore")
        lines = body.strip().split("\n")
        print("  [%-14s] %d stocks" % (label, len(lines)))
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

# === 7. EastMoney fund API ===
print()
print("--- 4. EastMoney fund NAV ---")
url4 = "https://api.fund.eastmoney.com/f10/lsjz?fundCode=510050&pageIndex=1&pageSize=1"

for label, headers in [
    ("No headers", {}),
    ("UA only", {"User-Agent": "Mozilla/5.0"}),
    ("UA+Referer ", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Referer": "https://fund.eastmoney.com/"}),
]:
    try:
        req = urllib.request.Request(url4, headers=headers)
        r = urllib.request.urlopen(req, timeout=10)
        raw = r.read().decode("utf-8")
        data = json.loads(raw)
        records = data.get("Data", {}).get("LSJZList", [])
        if records:
            print("  [%-14s] NAV=%s" % (label, records[0]["DWJZ"]))
        else:
            print("  [%-14s] no records" % label)
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

# === 8. EastMoney F10 ETF info (used by etf_scanner) ===
print()
print("--- 5. EastMoney fund page (fund.eastmoney.com) ---")
url5 = "https://fund.eastmoney.com/510050.html"

for label, headers in [
    ("UA only", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}),
    ("UA+Referer ", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Referer": "https://fund.eastmoney.com/"}),
]:
    try:
        req = urllib.request.Request(url5, headers=headers)
        r = urllib.request.urlopen(req, timeout=10)
        body = r.read().decode("utf-8", errors="ignore")
        print("  [%-14s] %d bytes" % (label, len(body)))
    except Exception as e:
        print("  [%-14s] FAIL: %s" % (label, e))

print()
print("=" * 65)
print("DONE")
