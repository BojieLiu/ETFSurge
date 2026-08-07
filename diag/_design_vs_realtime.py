# -*- coding: utf-8 -*-
"""解析 design #427 表格涨跌 vs 实时行情对比"""
import json, re, urllib.request

BASE = "http://localhost:8000/api/v1"

d = json.load(open("diag/out/design_latest.json", encoding="utf-8"))
dt = d.get("design_text") or ""

# 解析 markdown 表格行：| 核心 | 510300 | 沪深300ETF华泰柏瑞 | 47% | 0.32 | +0.15% | 分 2-3 批建仓 | ...
rows = []
for line in dt.split("\n"):
    line = line.strip()
    if not line.startswith("|"):
        continue
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) >= 6 and re.fullmatch(r"\d{6}", cells[1] or ""):
        rows.append({"layer": cells[0], "code": cells[1], "name": cells[2],
                     "weight": cells[3], "score": cells[4], "chg": cells[5],
                     "advice": cells[6] if len(cells) > 6 else ""})
print("表格行数:", len(rows))
for r in rows:
    print(f"  {r['layer']} {r['code']} {r['name']:<12} 权重={r['weight']:<6} 今日涨跌={r['chg']}")

# 实时行情对比
codes = sorted({r["code"] for r in rows})
url = BASE + "/market/realtime/batch?symbols=" + ",".join(codes)
quotes = json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
qmap = {q.get("symbol"): q for q in (quotes if isinstance(quotes, list) else quotes.get("items") or quotes.get("data") or [])}
print("\n=== 实时行情对比 ===")
for r in rows:
    q = qmap.get(r["code"]) or {}
    print(f"  {r['code']} 报告='{r['chg']}' 实时change_pct={q.get('change_pct')} price={q.get('price')} prev_close={q.get('prev_close')}")
