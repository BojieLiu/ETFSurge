import json, urllib.request, sys, time
sys.stdout.reconfigure(encoding='utf-8')
def post(url, body, t=180):
    req = urllib.request.Request('http://localhost:8000' + url, data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.loads(r.read().decode('utf-8'))
for mkt in ['A', 'HK', 'US']:
    d = post('/api/v1/analysis/llm-report', {'market': mkt})
    json.dump(d, open('diag/n2/llmreport_%s.json' % mkt, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('saved llmreport_%s, report len=%d, indices keys=%s' % (mkt, len(d['report']), list(d.get('indices', {}).keys())[:5]))
    print('  report_data keys:', list(d.get('market_data', {}).keys()))