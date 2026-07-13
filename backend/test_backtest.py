import requests
url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000300&scale=1200&datalen=50'
r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
data = r.json()
print(f'Items: {len(data) if isinstance(data, list) else "not a list"}')
if isinstance(data, list) and len(data) >= 2:
    prices = [float(d.get('close', 0)) for d in data if d.get('close')]
    prices = prices[-9:]
    print(f'Prices: {prices[:5]}...')
    if len(prices) >= 2:
        rets = []
        for i in range(min(8, len(prices) - 1)):
            prev, curr = prices[-(i+2)], prices[-(i+1)]
            r = round((curr - prev) / prev * 100, 2) if prev else 0
            rets.append(r)
        print(f'Returns: {[f"{x:.2f}" for x in rets]}')
        avg_r = sum(rets) / len(rets)
        var_r = sum((r - avg_r) ** 2 for r in rets) / len(rets)
        csi_avg = round(avg_r, 2)
        csi_vol = round(var_r ** 0.5, 2)
        print(f'Avg: {csi_avg}, Vol: {csi_vol}')
        print(f'Annual return: {csi_avg * 52:.2f}%')