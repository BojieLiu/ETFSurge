# -*- coding: utf-8 -*-
"""round8 O2/O12/O26/O5 补充验证"""
import json
import urllib.request

BASE = "http://localhost:8000"


def get(p, t=90):
    try:
        r = urllib.request.urlopen(BASE + p, timeout=t)
        return json.loads(r.read().decode())
    except Exception as e:
        return {"__err__": str(e)}


# O2: 港股 K 线
h = get("/api/v1/market/history/00700?asset_type=HK", t=90)
if isinstance(h, list):
    print("O2 HK history 00700: %d bars, last date=%s" % (len(h), h[-1].get("date") if h else None))
else:
    print("O2 HK history:", str(h)[:120])

# O12: timeline join tasks（失败任务可见性）
tl = get("/api/v1/portfolio/timeline", t=90)
if isinstance(tl, list):
    print("O12 timeline entries:", len(tl))
    statuses = {}
    for e in tl:
        st = e.get("status") or e.get("type")
        statuses[st] = statuses.get(st, 0) + 1
        if st == "failed":
            print("   failed entry:", e.get("task_id"), e.get("error_message", "")[:80])
    print("   status dist:", statuses)
else:
    print("O12 timeline:", str(tl)[:150])

# O26: 板块分析报告点位口径
try:
    txt = open("diag/out/sector-industry.sse.json", encoding="utf-8").read()
    has_label = ("板块指数" in txt) and ("点位" in txt) and ("BK1600" in txt)
    print("O26 sector report contains 板块指数/点位/BK1600 label:", has_label)
except Exception as e:
    print("O26 file read fail:", e)

# O5: design 426 涨跌幅值域
try:
    d = json.load(open("diag/out/design_detail.json", encoding="utf-8"))
    vals = []
    for s in (d.get("strategies") or []):
        for e in (s.get("etfs") or []):
            for k in ("change_pct", "daily_change_pct"):
                if e.get(k) is not None:
                    vals.append((e.get("symbol"), e.get(k)))
    out_of = [v for v in vals if v[1] is not None and abs(v[1]) > 10]
    print("O5 design change_pct values: %d samples, out-of-range(>10): %s" % (len(vals), out_of[:5]))
except Exception as e:
    print("O5 read fail:", e)

# O21 本地 IPv6 直连（对比：容器 0.0.0.0 后 localhost 直连延迟）
import time
for url in ("http://localhost:8000/health", "http://127.0.0.1:8000/health"):
    t0 = time.time()
    try:
        r = urllib.request.urlopen(url, timeout=10)
        print("O21 connect %s -> %d in %.0fms" % (url, r.status, (time.time() - t0) * 1000))
    except Exception as e:
        print("O21 connect %s FAIL: %s" % (url, str(e)[:80]))
