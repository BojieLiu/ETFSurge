import sys, datetime, json
sys.stdout.reconfigure(encoding='utf-8')
for ds in ['2026-08-07', '2026-08-08', '2026-08-09']:
    dt = datetime.date.fromisoformat(ds)
    print(ds, dt.strftime('%A'), 'weekday=', dt.weekday())
# 设计详情里的时间字段
d = json.load(open(r'diag\n2\design_detail_456.json', encoding='utf-8'))
print('\ncreated_at:', d.get('created_at'))
print('report_generated_at:', d.get('report_generated_at'))
mc = d.get('market_context') or {}
print('market_context keys:', list(mc.keys()))
for k in ['data_fetched_at', 'market_regime', 'sentiment_score']:
    print(f'  {k}:', mc.get(k))
print('\nmarket_regime:', d.get('market_regime'))