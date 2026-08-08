import sys, json
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'diag\n2\design_detail_456.json', encoding='utf-8'))
mc = d.get('market_context') or {}
print('--- index_realtime ---')
ir = mc.get('index_realtime')
if isinstance(ir, list):
    for x in ir[:8]:
        print(' ', x)
elif isinstance(ir, dict):
    for k, v in list(ir.items())[:8]:
        print(' ', k, '=', v)
else:
    print(' ', ir)
print('--- sector_momentum (first 15) ---')
sm = mc.get('sector_momentum')
if isinstance(sm, list):
    for x in sm[:15]:
        print(' ', {k: x.get(k) for k in list(x.keys()) if k in ('name','change_pct','pct','momentum','heat') })
elif isinstance(sm, dict):
    for k, v in list(sm.items())[:10]:
        print(' ', k, '=', v)
else:
    print(' ', sm)
print('--- fund_flow (first 8) ---')
ff = mc.get('fund_flow')
if isinstance(ff, list):
    for x in ff[:8]:
        print(' ', x if not isinstance(x, dict) else {k: x.get(k) for k in list(x.keys())[:5]})
else:
    print(' ', ff)
print('--- benchmark_stocks (first 8) ---')
bs = mc.get('benchmark_stocks')
if isinstance(bs, list):
    for x in bs[:8]:
        print(' ', x if not isinstance(x, dict) else {k: x.get(k) for k in list(x.keys())[:5]})