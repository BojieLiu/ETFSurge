import sys, json
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'diag\n2\design_detail_456.json', encoding='utf-8'))
print('top-level keys:', list(d.keys()))
# find today change / 涨跌幅 fields across nested
def find_keys(obj, path='', hits=None):
    if hits is None: hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)) and ('change' in str(k).lower() or 'chg' in str(k).lower() or '涨' in str(k)):
                hits.append((f'{path}.{k}', v))
            elif isinstance(v, (dict, list)):
                find_keys(v, f'{path}.{k}', hits)
    elif isinstance(obj, list):
        for i, it in enumerate(obj[:200]):
            find_keys(it, f'{path}[{i}]', hits)
    return hits
hits = find_keys(d)
print('=== change-related fields (first 60) ===')
for p, v in hits[:60]:
    print(f'{p} = {v}')
