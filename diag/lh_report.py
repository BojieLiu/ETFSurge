# -*- coding: utf-8 -*-
"""提取 Lighthouse 报告关键指标。"""
import json, sys, glob

files = sys.argv[1:] or glob.glob("diag/out/market/lighthouse_*.report.json")
for f in files:
    print("=" * 20, f)
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        print("  load fail:", e)
        continue
    for k, v in d.get("categories", {}).items():
        print(f"  {k}: {round(v['score']*100, 1)}")
    a = d.get("audits", {})
    keys = ["first-contentful-paint", "largest-contentful-paint", "cumulative-layout-shift",
            "total-blocking-time", "speed-index", "interactive", "server-response-time",
            "mainthread-work-breakdown", "render-blocking-resources", "unused-javascript",
            "network-requests", "max-potential-fid"]
    for key in keys:
        if key in a:
            av = a[key]
            val = av.get("displayValue", "")
            if isinstance(val, str):
                val = val.replace("\xa0", " ")
            print(f"  {key}: {val} (score={av.get('score')})")
    # 网络请求统计
    nr = a.get("network-requests", {})
    if nr and "details" in nr and "items" in nr["details"]:
        items = nr["details"]["items"]
        total = sum(i.get("transferSize", 0) for i in items) / 1024
        print(f"  network requests: {len(items)} 条, 总传输 {total:.0f} KB")
        big = sorted(items, key=lambda i: i.get("transferSize", 0), reverse=True)[:5]
        for i in big:
            print(f"    {i.get('transferSize',0)/1024:.0f} KB  {i.get('url','')[:90]}")
