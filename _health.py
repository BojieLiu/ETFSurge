#!/usr/bin/env python3
import urllib.request, json
try:
    r = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)
    print(json.loads(r.read().decode()))
except Exception as e:
    print(f"Health error: {e}")
