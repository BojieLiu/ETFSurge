import urllib.request, json

# Test ETF list
r = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/portfolio/etfs', timeout=15).read())
print(f'ETFs: {len(r)} items')

# Test calculate
req = urllib.request.Request('http://127.0.0.1:8000/api/v1/portfolio/calculate',
    data=b'{"total_capital": 500000}',
    headers={'Content-Type': 'application/json'})
r2 = json.loads(urllib.request.urlopen(req, timeout=45).read())
print(f'Calculate: {len(r2["allocations"])} allocations')
for a in r2['allocations'][:3]:
    print(f'  {a["symbol"]}  price={a["current_price"]}  target={a["target_amount"]}')

# Test realtime
r3 = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/market/realtime/159338?asset_type=A', timeout=30).read())
print(f'Realtime 159338: {r3}')
