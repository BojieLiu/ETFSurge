# -*- coding: utf-8 -*-
"""东财板块名 vs 财联社热度板块名匹配诊断"""
import json, os, sys, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

# 1. 东财板块映射
from app.fetchers.sector_fetcher import fetch_em_sector_changes
em = fetch_em_sector_changes()
print("[东财板块] 共", len(em))
names = list(em.keys())[:40]
print("  前 40:", names)

# 2. 财联社热度板块
h = json.loads(urllib.request.urlopen("http://localhost:8000/api/v1/market/sectors/heat?limit=20", timeout=30).read().decode())
cls_names = [it["name"] for it in h.get("items") or []]
print("\n[财联社热度] 20 板块:", cls_names)

# 3. 匹配
exact = [n for n in cls_names if n in em]
contains = [n for n in cls_names if any(n in e or e in n for e in em)]
print("\n精确匹配:", exact)
print("包含/被包含匹配:", contains)
