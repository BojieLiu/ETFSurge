import json, sys
sys.stdout.reconfigure(encoding='utf-8')
t = json.load(open('diag/n2/check_task_299.json', encoding='utf-8'))
res = t['result']
print('=== all 10 holdings: symbol / tech_signal / industry / filled ===')
for h in res['holdings_analysis']:
    fa = h.get('factor_availability', {})
    print("%s %s signal=%s industry=%r filled=%s/%s conf=%s" % (
        h['symbol'], h.get('name',''), h.get('tech_signal'), h.get('industry'),
        fa.get('filled'), fa.get('total'), h.get('confidence')))
print()
print('=== quality/coverage/market_regime ===')
for k in ['data_quality','data_confidence','coverage','market_regime']:
    print(k, '=', json.dumps(res.get(k), ensure_ascii=False))
print()
print('=== report_text last 500 ===')
print(res['report_text'][-500:])
