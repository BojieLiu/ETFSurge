import urllib.request, json

r = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/portfolio/etfs', timeout=15).read())
print('All ETFs count:', len(r))
for x in r[:5]:
    print(f'  {x["symbol"]}  {x["name"]}')

r2 = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/portfolio/etfs?portfolio_type=on_exchange', timeout=15).read())
print('On-exchange count:', len(r2))

r3 = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/portfolio/calculate', data=b'{"total_capital": 500000}', timeout=15).read())
print('Calculate OK, allocations:', len(r3.get('allocations', [])))
