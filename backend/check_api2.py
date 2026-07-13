import urllib.request, json

req = urllib.request.Request('http://127.0.0.1:8000/api/v1/portfolio/calculate',
    data=b'{"total_capital": 500000}',
    headers={'Content-Type': 'application/json'})
r = json.loads(urllib.request.urlopen(req, timeout=60).read())
print('Allocations:', len(r.get('allocations', [])))
if r.get('allocations'):
    for a in r['allocations'][:3]:
        print(f'  {a["symbol"]}  target={a["target_amount"]}  price={a["current_price"]}')
