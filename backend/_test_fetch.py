#!/usr/bin/env python3
"""Check fetch_history after fixing imports."""
import sys
sys.path.insert(0, ".")

from app.fetchers.china_market import fetch_history
result = fetch_history("510300", "A", "daily")
print(f"fetch_history 510300: {len(result)} candles")
if result:
    r = result[-1]
    print(f"  Latest: {r.get('date')} close={r.get('close')} volume={r.get('volume')}")
