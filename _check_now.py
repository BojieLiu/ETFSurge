#!/usr/bin/env python3
import urllib.request, json, sys
r = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)
d = json.loads(r.read().decode())
print("health:", d["status"])

r2 = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/portfolio/tasks?limit=3", timeout=5)
t = json.loads(r2.read().decode())
for x in t[:3]:
    print(f"  tid={x['task_id']} type={x['type']} status={x['status']} progress={x['progress']}")

r3 = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/portfolio/designs?limit=1", timeout=5)
d2 = json.loads(r3.read().decode())
if d2:
    print(f"design: id={d2[0]['id']} status={d2[0]['status']}")

r4 = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/portfolio/strategy-checks?limit=1", timeout=5)
c = json.loads(r4.read().decode())
if c:
    print(f"check: id={c[0]['id']} regime={c[0]['market_regime']}")
    print(f"  summary={str(c[0]['summary'])[:100]}")
sys.stdout.flush()
