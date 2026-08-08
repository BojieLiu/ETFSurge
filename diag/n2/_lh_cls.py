import json, sys
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'diag\n2\out\lh_dashboard.json', encoding='utf-8'))
audits = d['audits']
# 找所有 CLS 相关
for k, a in audits.items():
    title = (a.get('title') or '')
    if 'layout' in k or 'shift' in k or 'CLS' in title or 'Layout' in title:
        print('AUDIT:', k, '|', title)
        items = ((a.get('details') or {}).get('items') or [])
        for it in items[:5]:
            node = (it.get('node') or {}).get('snippet', '')
            print('   node:', node[:150])
            print('   score:', it.get('score'))
            for kk, vv in it.items():
                if kk not in ('node',):
                    print('   ', kk, '=', str(vv)[:60])