"""Check design task failure state."""
import urllib.request, json

def req(path, timeout=4):
    r = urllib.request.urlopen(f'http://localhost:8000{path}', timeout=timeout)
    return json.loads(r.read())

try:
    r = urllib.request.urlopen('http://localhost:8000/health', timeout=3)
    print('Health:', r.status, r.read().decode()[:60])
except Exception as e:
    print(f'Backend unavailable: {type(e).__name__}')
    exit(1)

# Designs
d = req('/api/v1/portfolio/designs?limit=15&offset=0')
items = d if isinstance(d, list) else d.get('designs', [d])
print(f'\nDesigns: {len(items)} records')
for item in items:
    e = item.get('error_message') or item.get('error') or ''
    t = item.get('design_text','') or ''
    st = item.get('status','')
    print(f'  ID={item.get("id")} status={st} err={e[:80] if e else "-"} text_len={len(t)}')

# Tasks
t = req('/api/v1/portfolio/tasks?limit=15&offset=0')
print(f'\nTasks: {len(t)} records')
for item in t:
    e = item.get('error_message') or item.get('error') or ''
    print(f'  task_id={str(item.get("task_id",""))[:8]} status={item.get("status")} err={e[:80] if e else "-"}')
