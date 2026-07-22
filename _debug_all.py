"""Check market_status values in API response."""
import requests, time
r = requests.get('http://127.0.0.1:8000/api/v1/market/indices/global', timeout=30)
data = r.json()
inner = data.get('indices', data)
print("Current BJT:", time.strftime('%H:%M:%S'))
for region, items in inner.items():
    for i in items:
        sym = i.get('symbol', '?')
        ms = i.get('market_status', 'MISSING')
        avail = i.get('available')
        price = i.get('price')
        print(f"  {sym} ({region}): market_status={ms} avail={avail} price={price}")
