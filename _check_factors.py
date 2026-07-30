"""Check factor details - why china_specific factors have no data."""
import requests, json

BASE = 'http://127.0.0.1:8000'

# 1. Get active factors with detail
r = requests.get(BASE + '/api/v1/factors/active', timeout=15)
d = r.json()

print("=== Active Factors Overview ===")
print(f"Total factors: {d.get('total', 0)}")
print()

for cat in d.get('categories', []):
    name = cat['name']
    count = cat['count']
    valid = cat['valid_count']
    no_data = cat['no_data_count']
    warn = cat['warn_count']
    desc = cat.get('description', '')
    avg_ic = cat.get('avg_ic', 0)
    print(f"Category: {name} ({count} factors)")
    print(f"  Description: {desc}")
    print(f"  Valid: {valid}, No data: {no_data}, Warn: {warn}, Avg IC: {avg_ic}")
    
    # Print individual factors in this category
    for f in cat.get('factors', []):
        code = f.get('code', '?')
        fname = f.get('name', '?')
        fdesc = f.get('description', '')
        ic = f.get('ic_value', 'N/A')
        fvalid = f.get('valid', '?')
        status = f.get('status', '?')
        sample_count = f.get('sample_count', '?')
        print(f"    {code}: {fname} (IC={ic}, valid={fvalid}, status={status}, samples={sample_count})")
        if fdesc:
            print(f"      desc: {fdesc}")
    print()

# 2. Get factor IC data
print("=== Factor IC Values ===")
r = requests.get(BASE + '/api/v1/factors/ic', timeout=15)
ic_data = r.json()
print(f"Total IC records: {len(ic_data) if isinstance(ic_data, list) else len(ic_data.get('factors', ic_data))}")

if isinstance(ic_data, list):
    for f in ic_data[:25]:
        print(f"  {f.get('code','?')}: IC={f.get('ic_value','?')}")
else:
    print(str(ic_data)[:300])
