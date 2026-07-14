import json, urllib.request
data = json.dumps({'capital': 100000}).encode()
req = urllib.request.Request('http://localhost:8000/api/v1/analysis/portfolio-design', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read().decode())
print('Keys:', list(result.keys()))
print('Has plans:', 'plans' in result)
if 'plans' in result:
    print('Plans count:', len(result['plans']))
    for p in result['plans']:
        print(f'  Style: {p.get("style_label")}, Allocations: {len(p.get("allocations", []))}')