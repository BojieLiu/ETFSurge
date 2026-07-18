#!/usr/bin/env python3
import requests, json

BASE = "http://127.0.0.1:8000/api/v1"

# 1. Latest design
detail = requests.get(f"{BASE}/portfolio/designs/51", timeout=10).json()
print("=== 设计51 ===")
print("strategies:", len(detail.get("strategies", [])))
for s in detail.get("strategies", []):
    syms = [(e.get("symbol"), e.get("target_weight", 0)) for e in (s.get("allocations") or s.get("etfs") or [])[:3]]
    print(f"  {s['label']}: {syms}")

# 2. History first item
hist = requests.get(f"{BASE}/portfolio/designs", timeout=10).json()
print()
print("=== 历史列表第一条 ===")
h = hist[0] if hist else {}
print(f"id={h.get('id')}, strategies_len={len(h.get('strategies', []) or [])}")
if h.get("strategies"):
    s = h["strategies"][0]
    syms = [(e.get("symbol"), e.get("target_weight", 0)) for e in (s.get("allocations") or s.get("etfs") or [])[:3]]
    print(f"  1st: {s.get('label')} {syms}")

# 3. Index data format
ctx = detail.get("market_context", {})
idx = ctx.get("index_realtime", [])
print()
print("=== 指数数据格式 ===")
for i in idx[:3]:
    cp = i.get("change_pct")
    print(f"  {i.get('name')}: price={i.get('price')}, change_pct={cp} ({type(cp).__name__})")

# 4. Benchmark format
bench = ctx.get("benchmark_stocks") or detail.get("market_sentiment", {}).get("benchmark_stocks", [])
print()
print("=== benchmark_stocks 格式 ===")
for b in (bench or [])[:3]:
    cp = b.get("change_pct")
    print(f"  {b.get('name')}: change_pct={cp} ({type(cp).__name__})")

# 5. Sentiment
sent = ctx.get("market_sentiment", {})
print()
print(f"sentiment_index={sent.get('sentiment_index')}, sentiment_label={sent.get('sentiment_label')}")
