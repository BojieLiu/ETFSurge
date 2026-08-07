# -*- coding: utf-8 -*-
"""search 接口 market 过滤实测（HK 场景）"""
import json, urllib.request

BASE = "http://localhost:8000/api/v1"


def search(kw, market):
    url = f"{BASE}/market/search?keyword={urllib.request.quote(kw)}&market={market}&include_stocks=true"
    d = json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
    items = d if isinstance(d, list) else d.get("items") or d.get("data") or []
    return items


for kw, mkt in (("0070", "HK"), ("腾讯", "HK"), ("盈富", "HK"), ("0070", None), ("腾讯", None)):
    items = search(kw, mkt)
    tag = f"market={mkt}" if mkt else "market=None(global)"
    print(f"[{kw} {tag}] {len(items)} 条:", [(i.get('symbol'), i.get('name'), i.get('market')) for i in items[:6]])
