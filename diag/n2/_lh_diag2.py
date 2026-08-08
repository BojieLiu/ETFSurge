import json, sys
sys.stdout.reconfigure(encoding='utf-8')
for page in ['dashboard', 'market-analysis', 'portfolio-analysis']:
    d = json.load(open(r'diag\n2\out\lh_%s.json' % page, encoding='utf-8'))
    audits = d['audits']
    print('=====', page, '=====')
    # render-blocking
    rb = audits.get('render-blocking-resources')
    if rb:
        print('render-blocking-resources score:', rb.get('score'), rb.get('displayValue'))
        for it in ((rb.get('details') or {}).get('items') or [])[:6]:
            print('   ', (it.get('url') or '')[:90], 'wasted:', it.get('wastedMs', ''))
    # unminified/unused
    for k in ['unused-javascript', 'uses-responsive-images', 'uses-optimized-images', 'uses-text-compression', 'third-party-facades']:
        a = audits.get(k)
        if a is not None:
            print('%s score=%s %s' % (k, a.get('score'), a.get('displayValue', '')))
    # transfer size budget
    print('total-byte-weight:', audits.get('total-byte-weight', {}).get('displayValue'))
    print('largest-contentful-paint-element:', (audits.get('largest-contentful-paint-element') or {}).get('displayValue'))