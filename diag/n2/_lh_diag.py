import json, sys
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'diag\n2\out\lh_dashboard.json', encoding='utf-8'))
audits = d['audits']
for name in ['layout-shift-elements', 'largest-contentful-paint-element']:
    if name in audits:
        a = audits[name]
        print('===', name, 'score:', a.get('score'))
        for it in ((a.get('details') or {}).get('items') or [])[:8]:
            node = (it.get('node') or {}).get('snippet', '')[:130]
            print('  ', node)
            print('   phase:', it.get('phase', ''), 'score:', it.get('score'))
# mainthread work breakdown
a = audits.get('mainthread-work-breakdown')
print('=== mainthread-work-breakdown ===')
for it in ((a.get('details') or {}).get('items') or [])[:6]:
    print('  %s %s' % (it.get('groupLabel', it.get('group', '?')), it.get('duration', '')))