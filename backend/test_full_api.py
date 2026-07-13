import urllib.request, json

base = 'http://127.0.0.1:8000'

# 1. ETF list
r = json.loads(urllib.request.urlopen(f'{base}/api/v1/portfolio/etfs', timeout=15).read())
print(f'1. ETF list: {len(r)} items')

# 2. single ETF realtime (A)
r2 = json.loads(urllib.request.urlopen(f'{base}/api/v1/market/realtime/159338?asset_type=A', timeout=30).read())
print(f'2. Realtime 159338: price={r2.get("price")}')

# 3. Calculate
req = urllib.request.Request(f'{base}/api/v1/portfolio/calculate',
    data=b'{"total_capital": 500000}',
    headers={'Content-Type': 'application/json'})
r3 = json.loads(urllib.request.urlopen(req, timeout=60).read())
prices = [a['current_price'] for a in r3['allocations']]
print(f'3. Calculate: {len(r3["allocations"])} allocs, {sum(1 for p in prices if p>0)} with prices')

# 4. Daily PnL
req2 = urllib.request.Request(f'{base}/api/v1/portfolio/daily-pnl',
    data=b'{"total_capital": 500000}',
    headers={'Content-Type': 'application/json'})
r4 = json.loads(urllib.request.urlopen(req2, timeout=60).read())
print(f'4. Daily PnL: {len(r4)} items')

# 5. History
r5 = json.loads(urllib.request.urlopen(f'{base}/api/v1/market/history/159338?asset_type=A&period=daily', timeout=30).read())
print(f'5. History: {len(r5)} bars' if r5 else '5. History: empty')

# 6. Signal
r6 = json.loads(urllib.request.urlopen(f'{base}/api/v1/market/signal/159338?asset_type=A', timeout=30).read())
print(f'6. Signal: {r6.get("signal")} score={r6.get("score")}')

# 7. Market overview (indices)
r7 = json.loads(urllib.request.urlopen(f'{base}/api/v1/market/realtime', timeout=30).read())
print(f'7. Market overview: {len(r7)} items')

print('ALL PASSED' if r and r2 and r3 and r4 else 'SOME FAILED')
