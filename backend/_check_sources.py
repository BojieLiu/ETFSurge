import requests
r = requests.get('http://localhost:8000/api/v1/admin/sources/health', timeout=30)
data = r.json()
print('count:', len(data))
for s in data:
    print(f'  name={s["name"]} avail={s["available"]} fail={s["failures"]}')
