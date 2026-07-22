"""Seed global indices cache with known closing data.

Strategy: try Finnhub for each symbol, fall back to known values.
Finnhub returns 0 off-hours, but SPY works even on weekends.
For indices, use approximate recent closing levels as seed.
"""
import sys, json, urllib.request, os, time

data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.makedirs(data_dir, exist_ok=True)

from app.config import settings
fh_key = settings.finnhub_api_key

# Seed data: approximate recent closing levels
# Format: finnhub_symbol -> (symbol, name, region, recent_close)
SEED = {
    'SPX':     ('^GSPC', '标普500', '美股', 5560.0),
    'IXIC':    ('^IXIC', '纳斯达克', '美股', 17980.0),
    'DJI':     ('^DJI', '道琼斯', '美股', 41150.0),
    'HSI':     ('^HSI', '恒生指数', '港股', 17750.0),
    'HSCE':    ('^HSCE', '恒生国企指数', '港股', 6350.0),
    'HSTECH':  ('^HSTECH', '恒生科技指数', '港股', 3620.0),
    'N225':    ('^N225', '日经225', '日经', 39800.0),
    'KS11':    ('^KS11', '韩国综合指数', '韩国', 2820.0),
    'AXJO':    ('^AXJO', '澳洲标普200', '澳洲', 8100.0),
    'FTSE':    ('^FTSE', '英国富时100', '欧洲', 8280.0),
    'STOXX50E':('^STOXX50E', '欧洲斯托克50', '欧洲', 4950.0),
}

regions = {}
count_ok = 0
count_err = 0

BASE_FH = 'https://finnhub.io/api/v1'

for sym, (orig_sym, name, region, default_close) in SEED.items():
    price = None
    available = False
    change_pct = None
    
    # Try Finnhub first
    if fh_key:
        url = '%s/quote?symbol=%s&token=%s' % (BASE_FH, sym, fh_key)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            c = data.get('c', 0) or 0
            pc = data.get('pc', 0) or 0
            dp = data.get('dp', 0) or 0
            
            if c > 0:
                price = c
                change_pct = dp
                available = True
            elif pc > 0:
                price = pc
            # else: both 0, fall through to seed
        except Exception:
            pass  # Fall through to seed
    
    # Fall back to seed data if Finnhub couldn't provide
    if price is None or price == 0:
        price = default_close
        available = False  # Mark as cached/stale
        print('[SEED] %s: using seed %.0f (Finnhub=0)' % (name, default_close))
    else:
        status = 'LIVE' if available else 'CACHED'
        print('[%s] %s: price=%.2f' % (status, name, price if available else (pc or 0)))
        count_ok += 1
    
    entry = {
        'symbol': orig_sym,
        'name': name,
        'region': region,
        'asset_type': 'index',
        'price': price if price and price > 0 else None,
        'change_pct': change_pct,
        'change_amount': None,
        'available': available,
    }
    
    if region not in regions:
        regions[region] = []
    regions[region].append(entry)

# Write cache
cache_path = os.path.join(data_dir, 'indices_cache.json')
blob = {'ts': time.time(), 'data': regions}
with open(cache_path, 'w', encoding='utf-8') as f:
    json.dump(blob, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in regions.values())
print('\n=== DONE ===')
print('Written: %d entries to %s' % (total, cache_path))
print('Live: %d, Seeded: %d' % (count_ok, total - count_ok))
print('Regions: %s' % list(regions.keys()))
