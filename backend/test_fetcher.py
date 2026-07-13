from app.fetchers.akshare_fetcher import fetch_a_stock_batch, fetch_history, fetch_index_realtime

items = fetch_a_stock_batch(['159338', '510880', '159545'])
print(f'Batch: {len(items)} items')
for i in items:
    print(f'  {i["symbol"]} price={i["price"]} change={i["change_pct"]}%')

hist = fetch_history('159338')
print(f'History: {len(hist) if hist else 0} bars')
if hist:
    print(f'  Last: {hist[-1]}')

idx = fetch_index_realtime()
print(f'Indices: {len(idx) if idx else 0}')
if idx:
    for i in idx[:3]:
        print(f'  {i["symbol"]} {i["name"]} price={i["price"]}')

print('Done')
