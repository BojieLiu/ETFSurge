"""Test standard mode with timeout."""
import requests, sys

BASE = 'http://127.0.0.1:8000'

print("=== Standard mode design ===")
try:
    r = requests.post(f'{BASE}/api/v1/portfolio/design?mode=standard',
                      json={}, timeout=60)
    print('Status:', r.status_code)
    data = r.json()
    print('Strategy count:', len(data.get('strategies', [])))
    if data.get('strategies'):
        s = data['strategies'][0]
        print('First style:', s.get('label'))
        print('ETFs:', len(s.get('etfs', [])))
        for e in s.get('etfs', [])[:5]:
            w = e.get('weight', 0) * 100
            print('  %s %.1f%% layer:%s' % (e['symbol'], w, e.get('layer', '')))

    mc = data.get('market_context', {})
    sent = mc.get('market_sentiment', {})
    print('sentiment:', sent.get('sentiment_index'), sent.get('sentiment_label'))
    bs = mc.get('benchmark_stocks', [])
    print('benchmarks:', len(bs))
    for b in bs[:3]:
        print('  %s %s signal:%s change:%s' % (b.get('symbol',''), b.get('name',''), b.get('signal',''), b.get('change_pct','')))
    print("OK - standard mode works")
except requests.Timeout:
    print("TIMEOUT - standard mode took >60s")
    sys.exit(1)
except Exception as e:
    print("ERROR:", e)
    sys.exit(1)
