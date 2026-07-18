#!/usr/bin/env python3
import requests, json

d = requests.get("http://127.0.0.1:8000/api/v1/portfolio/designs/51", timeout=10).json()
s = d.get("strategies", [{}])[0]
print("strategy keys:", list(s.keys()))
print()
allocs = s.get("allocations") or s.get("etfs") or []
print("allocations count:", len(allocs))
if allocs:
    e = allocs[0]
    print("etf keys:", list(e.keys()))
    print("target_weight:", e.get("target_weight"))
    print("weight:", e.get("weight"))
