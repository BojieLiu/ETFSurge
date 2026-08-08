import sys, json
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'diag\n2\design_detail_456.json', encoding='utf-8'))
e0 = d['strategies'][0]['etfs'][0]
print('etf keys:', list(e0.keys()))
print('factor_breakdown type:', type(e0.get('factor_breakdown')))
fb = e0.get('factor_breakdown')
if isinstance(fb, dict):
    print('fb keys:', list(fb.keys()))
    for k, v in fb.items():
        print(f'  {k}: {type(v).__name__}', (list(v.keys())[:8] if isinstance(v, dict) else v))
# 找 daily_change_pct 的兄弟字段
for k, v in e0.items():
    if isinstance(v, (int, float)):
        print(f'  direct {k} = {v}')