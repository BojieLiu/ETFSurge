# -*- coding: utf-8 -*-
"""连续多次个股搜索，验证 get_all_stocks 1h 缓存是否生效"""
import json, sys, io, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = 'http://127.0.0.1:8000/api/v1/market/search'

keywords = [('茅台', '%E8%8C%85%E5%8F%B0'), ('宁德', '%E5%AE%81%E5%BE%B7'),
            ('茅台', '%E8%8C%85%E5%8F%B0'), ('宁德', '%E5%AE%81%E5%BE%B7')]
for i, (label, kw) in enumerate(keywords):
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(f'{BASE}?keyword={kw}&include_stocks=true', timeout=30)
        d = json.loads(r.read())
        print(f'第{i+1}次 {label}: {(time.monotonic()-t0)*1000:.0f} ms, {len(d)} 条')
    except Exception as e:
        print(f'第{i+1}次 {label}: ERR {str(e)[:60]}')
