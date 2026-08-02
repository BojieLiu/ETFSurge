# -*- coding: utf-8 -*-
"""实测个股搜索路径耗时（instruments 无个股 → levistock 降级）"""
import json, sys, io, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8000/api/v1/market/search"

def t(label, url):
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(url, timeout=30)
        d = json.loads(r.read())
        print(f"{label}: {(time.monotonic()-t0)*1000:7.0f} ms, {len(d)} 条 | {json.dumps(d[:2], ensure_ascii=False)[:100]}")
    except Exception as e:
        print(f"{label}: {(time.monotonic()-t0)*1000:.0f} ms ERR {str(e)[:60]}")

# 个股（A 股）搜索——instruments 无 stock → levistock 降级
t("market=A 茅台", f"{BASE}?keyword=%E8%8C%85%E5%8F%B0&market=A")
t("market=A 600519", f"{BASE}?keyword=600519&market=A")
# 跨市场 include_stocks（前端实际调用）——个股
t("global 茅台 include_stocks", f"{BASE}?keyword=%E8%8C%85%E5%8F%B0&include_stocks=true")
t("global 宁德 include_stocks", f"{BASE}?keyword=%E5%AE%81%E5%BE%B7&include_stocks=true")
# ETF 对照
t("global 510300 (ETF 对照)", f"{BASE}?keyword=510300")
