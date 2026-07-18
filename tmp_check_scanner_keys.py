#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from app.fetchers.etf_scanner import fetch_all_etfs_base

raw = fetch_all_etfs_base()
row = raw[0]
# Show all keys that might relate to "scale" or "fund"
for k in row.keys():
    if any(w in k.encode('utf-8','ignore').decode('utf-8','ignore') for w in ['金', '规', '模', 'fund', 'scale']):
        print(f"  '{k}': {row[k]}")
print("---")
# Also show all keys
print("all keys:")
for k in list(row.keys())[:15]:
    print(f"  [{k}]")
