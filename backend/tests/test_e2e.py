"""End-to-end test through Vite proxy."""
import urllib.request, json, sys

# Test portfolio-design through Vite proxy (same path frontend uses)
req = urllib.request.Request(
    'http://localhost:5173/api/v1/analysis/portfolio-design',
    data=b'{}',
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
        print(f'Status: {resp.status}')
        print(f'Keys: {list(data.keys())}')
        portfolios = data.get('portfolios', [])
        print(f'Portfolios: {len(portfolios)}')
        for pf in portfolios:
            etfs = pf.get('etfs', [])
            cw = pf.get('cash_weight', 0) or 0
            ew = sum(e['weight'] for e in etfs)
            total = ew + cw
            print(f'  [{pf["type"]}] {pf["name"]}: ETFs={len(etfs)} ETF_weight={ew:.2f} cash={cw:.2f} total={total:.2f}')
            if abs(total - 1.0) > 0.01:
                print(f'    WARNING: weights sum to {total:.2f}, not 1.0!')
        all_ok = all(abs(sum(e['weight'] for e in pf['etfs']) + (pf.get('cash_weight', 0) or 0) - 1.0) < 0.01 for pf in portfolios)
        print(f'\nWeights all sum to 1.0: {all_ok}')
except Exception as e:
    print(f'FAILED: {e}')
    if hasattr(e, 'read'):
        print(f'Body: {e.read()[:500]}')
    sys.exit(1)

print('All E2E tests passed!')
