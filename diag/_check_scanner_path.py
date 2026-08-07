# -*- coding: utf-8 -*-
"""etf_scanner 快照路径 + 设计 #427 中 560600 完整字段"""
import inspect, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

# 1. etf_scanner._etf_cache_file 路径
from app.fetchers.etf_scanner import _etf_cache_file as scanner_path
print("[scanner._etf_cache_file] source:")
print(inspect.getsource(scanner_path))
try:
    print("  resolves to:", scanner_path())
except Exception as e:
    print("  ERR:", e)

# 2. design #427 中 560600 allocation 完整字段
d = json.load(open(r"E:\ETF_Surge\diag\out\design_latest.json", encoding="utf-8"))
for st in d.get("strategies") or []:
    for a in st.get("etfs") or []:
        if str(a.get("symbol")) == "560600":
            print("\n[560600 allocation 字段]:", json.dumps(a, ensure_ascii=False, indent=1)[:800])
            break
