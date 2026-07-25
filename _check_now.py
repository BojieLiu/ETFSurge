#!/usr/bin/env python3
"""Check design 219 and plan next steps."""
import urllib.request, json

BASE = "http://127.0.0.1:8000"

def get(path):
    r = urllib.request.urlopen(BASE + path, timeout=10)
    return json.loads(r.read().decode())

# Check latest strategy check with factor data
checks = get("/api/v1/portfolio/strategy-checks?limit=1")
if checks:
    cid = checks[0].get("id")
    detail = get(f"/api/v1/portfolio/strategy-checks/{cid}")
    ha = detail.get("holdings_analysis", [])
    print(f"Latest check #{cid}: {len(ha)} holdings")
    for h in ha[:5]:
        sym = h.get("symbol","?")
        sig = h.get("signal","?")
        fs = str(h.get("factor_summary",""))[:60]
        print(f"  {sym:8s} signal={sig:10s} factor={fs}")
    
    suggs = detail.get("suggestions", [])
    print(f"\nSuggestions: {len(suggs)}")
    for s in suggs[:3]:
        print(f"  {s.get('action'):10s} {s.get('symbol'):8s} cur={s.get('current_weight',0):.4f} sug={s.get('suggested_weight',0):.4f}")
        print(f"    reason: {str(s.get('reason',''))[:100]}")

# Check if backend is healthy
try:
    h = get("/health")
    print(f"\nBackend: {h}")
except Exception as e:
    print(f"\nBackend not ready: {e}")
