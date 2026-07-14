import json, urllib.request
data = json.dumps({'capital': 100000}).encode()
req = urllib.request.Request('http://localhost:8000/api/v1/analysis/portfolio-design', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read().decode())
plans = result.get('plans', [])
for p in plans:
    print(f"{p['style_label']}: expected_return={p.get('expected_return')}, max_drawdown={p.get('max_drawdown')}, sharpe_ratio={p.get('sharpe_ratio')}, allocations={len(p.get('allocations', []))}")