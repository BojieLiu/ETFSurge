import urllib.request, json

# Test realtime
r = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/market/realtime', timeout=60).read())
print('Realtime count:', len(r))
if r:
    for x in r[:3]:
        print(f'  {x["symbol"]}  {x["name"]}  price={x["price"]}')

# Test calculate
req = urllib.request.Request('http://127.0.0.1:8000/api/v1/portfolio/calculate',
    data=b'{"total_capital": 500000}',
    headers={'Content-Type': 'application/json'})
r2 = json.loads(urllib.request.urlopen(req, timeout=60).read())
for a in r2['allocations'][:3]:
    print(f'  {a["symbol"]}  target={a["target_amount"]}  price={a["current_price"]}')
