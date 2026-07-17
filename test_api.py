"""Test design API - check v3.0 output."""
import requests, time, sys

time.sleep(5)
BASE = 'http://127.0.0.1:8000'

# Health check
r = requests.get(BASE + '/health', timeout=5)
print('Health:', r.status_code)

# Standard mode test
print('\n=== Standard Mode ===')
try:
    r = requests.post(BASE + '/api/v1/portfolio/design?mode=standard', json={}, timeout=120)
    d = r.json()
    for s in d.get('strategies', []):
        l = s.get('label', '?')
        print('\n--- %s ---' % l)
        core = [e for e in s.get('etfs', []) if e.get('layer') == 'core']
        sat = [e for e in s.get('etfs', []) if e.get('layer') == 'satellite']
        df = [e for e in s.get('etfs', []) if e.get('layer') == 'defense']
        cash = [e for e in s.get('etfs', []) if e.get('layer') == 'cash']
        print('  Core(%d): %s' % (len(core), ', '.join(['%s %.0f%%' % (e['symbol'], e.get('weight',0)*100) for e in core])))
        print('  Sat(%d): %s' % (len(sat), ', '.join(['%s %.1f%%' % (e['symbol'], e.get('weight',0)*100) for e in sat])))
        print('  Def(%d): %s' % (len(df), ', '.join(['%s %.0f%%' % (e['symbol'], e.get('weight',0)*100) for e in df])))
        print('  Cash(%d): %.0f%%' % (len(cash), cash[0].get('weight',0)*100 if cash else 0))
        
        # Check for errors
        for e in s.get('etfs', []):
            if e['symbol'] in ['159915', '510500'] and e.get('layer') == 'core':
                print('  *** ERROR: %s should be satellite! ***' % e['symbol'])
        
        total = sum(e.get('weight', 0) for e in s.get('etfs', []))
        print('  Total: %.1f%%' % (total*100))
    print('\nOK')
except Exception as e:
    print('Error:', e)
    sys.exit(1)
