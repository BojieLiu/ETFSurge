# -*- coding: utf-8 -*-
"""拉取预热 profiler 分段耗时"""
import json
import urllib.request

r = urllib.request.urlopen("http://localhost:8000/api/v1/system/profiling", timeout=15)
d = json.loads(r.read().decode())
print("total records:", len(d))
for rec in sorted(d, key=lambda x: -x["duration_ms"])[:25]:
    print("%-38s %10.1fms  %s" % (rec["label"], rec["duration_ms"], rec.get("category", "")))
