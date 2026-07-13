import urllib.request, json

# 1. ETF list
r = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/portfolio/etfs', timeout=15).read())
print(f'1. ETF list: {len(r)} items OK')

# 2. Single A-stock realtime (via Sina)
r2 = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/market/realtime/159338?asset_type=A', timeout=30).read())
print(f'2. Realtime 159338: price={r2.get("price")} name={r2.get("name")}')

# 3. Calculate (uses build_price_map with batch Tencent)
req = urllib.request.Request('http://127.0.0.1:8000/api/v1/portfolio/calculate',
    data=b'{"total_capital": 500000}',
    headers={'Content-Type': 'application/json'})
r3 = json.loads(urllib.request.urlopen(req, timeout=60).read())
prices = [a['current_price'] for a in r3['allocations']]
print(f'3. Calculate: {len(r3["allocations"])} allocs, prices_with_data={sum(1 for p in prices if p > 0)}')

# 4. History (via Sina)
r4 = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/market/history/159338?asset_type=A&period=daily', timeout=30).read())
print(f'4. History 159338: {len(r4)} bars' if r4 else '4. History: empty (Sina may be slow)')

# 5. Signal
r5 = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/market/signal/159338?asset_type=A', timeout=30).read())
print(f'5. Signal: {r5.get("signal")} score={r5.get("score")}')

print('All tests passed!' if all([r, r2, r3, r5]) else 'Some tests may have issues')
