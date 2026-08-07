# -*- coding: utf-8 -*-
import json
import re
import urllib.request

# O12 完整 status 分布
tl = json.load(urllib.request.urlopen("http://localhost:8000/api/v1/portfolio/timeline", timeout=90))
items = tl.get("items") if isinstance(tl, dict) else tl
print("O12 timeline items:", len(items))
st = {}
for e in items:
    k = (e.get("_type"), e.get("status"))
    st[k] = st.get(k, 0) + 1
print("  (type,status) dist:", st)
failed = [e for e in items if e.get("status") == "failed"]
print("  failed entries:", len(failed))
for e in failed[:3]:
    print("   ", e.get("task_id"), str(e.get("error_message"))[:100])

# O26 板块报告全文
txt = open("diag/out/sector-industry.sse.json", encoding="utf-8").read()
full = ""
for m in re.finditer(r'"full_text": "(.*?)"\s*}', txt, re.S):
    full += m.group(1)
full = full.encode().decode("unicode_escape", "ignore")
print("O26 report len:", len(full))
print("  head:", full[:350])
print("  含板块指数?", "板块指数" in full, "| 含点位?", "点位" in full, "| 含BK?", "BK" in full)

# O2: history 接口对 00700 的原始响应
h = json.load(urllib.request.urlopen("http://localhost:8000/api/v1/market/history/00700?asset_type=HK&days=30", timeout=90))
print("O2 history raw type:", type(h).__name__, "len:", len(h) if isinstance(h, list) else str(h)[:150])
