#!/usr/bin/env python3
"""Check task API response format."""
import urllib.request, json

r = urllib.request.urlopen("http://localhost:8000/api/v1/portfolio/tasks?limit=3", timeout=10)
data = json.loads(r.read().decode())

if isinstance(data, list):
    print(f"List, count={len(data)}")
    for t in data:
        print(json.dumps(t, ensure_ascii=False)[:300])
elif isinstance(data, dict):
    print(f"Dict keys={list(data.keys())}")
    print(json.dumps(data, ensure_ascii=False)[:500])
else:
    print(f"Type={type(data).__name__}: {str(data)[:500]}")
