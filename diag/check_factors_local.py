import json, urllib.request

with urllib.request.urlopen('http://localhost:8000/api/v1/factors/active', timeout=30) as r:
    d = json.loads(r.read().decode('utf-8'))
with open('diag/out/market/factors_active_local.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
for cat in d['categories']:
    nos = [f['code'] for f in cat['factors'] if f['status'] == 'no_data']
    sts = [f['code'] for f in cat['factors'] if f['status'] == 'static']
    print("{}: count={} valid={} warn={} no_data={} static={}".format(
        cat['name'], cat['count'], cat['valid_count'], cat['warn_count'],
        cat['no_data_count'], cat['static_count']))
    if nos:
        print("   no_data:", nos)
    if sts:
        print("   static :", sts)
for cat in d['categories']:
    for f in cat['factors']:
        if f['status'] == 'no_data':
            print('reason:', f['code'], '->', f['reason'])
print('summary:', json.dumps(d['summary'], ensure_ascii=False))
