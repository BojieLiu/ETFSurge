"""Diagnose bottleneck: is the event loop blocked or just the task slow?"""
import requests, time, threading, sys

BASE = 'http://localhost:8013'
results = []

def log(msg):
    t = time.strftime('%H:%M:%S')
    print(f'[{t}] {msg}')
    sys.stdout.flush()

# 1. Baseline: health check
try:
    r = requests.get(BASE + '/health', timeout=10)
    log(f'HEALTH pre: {r.status_code} {r.json()}')
except Exception as e:
    log(f'HEALTH pre FAILED: {type(e).__name__} — server may be down')
    sys.exit(1)

# 2. Submit design task
try:
    r = requests.post(BASE + '/api/v1/portfolio/design-async',
                      json={'capital': 500000}, timeout=30)
    log(f'POST design-async: {r.status_code} task_id={r.json().get("task_id")}')
    task_id = r.json().get('task_id')
except Exception as e:
    log(f'POST design-async FAILED: {type(e).__name__}')
    task_id = None

# 3. Concurrent poll: check task progress AND health simultaneously
def health_poller():
    for i in range(20):
        time.sleep(2)
        try:
            r = requests.get(BASE + '/health', timeout=5)
            results.append(('health', i, r.status_code, 'ok'))
        except Exception as e:
            results.append(('health', i, -1, type(e).__name__))

def task_poller():
    if not task_id:
        return
    for i in range(20):
        time.sleep(2)
        try:
            r = requests.get(BASE + f'/api/v1/portfolio/tasks/{task_id}', timeout=5)
            if r.status_code == 200:
                pd = r.json()
                results.append(('task', i, pd.get('status'), pd.get('progress'), pd.get('stage', '')))
        except Exception as e:
            results.append(('task', i, -1, type(e).__name__))

t1 = threading.Thread(target=health_poller, daemon=True)
t2 = threading.Thread(target=task_poller, daemon=True)
t1.start()
t2.start()

# Wait 45s
time.sleep(45)

log(f'--- Collected {len(results)} data points ---')
for r in results:
    log(f'  {r}')

# 4. Final check: is the server still alive?
try:
    r = requests.get(BASE + '/health', timeout=10)
    log(f'HEALTH post: {r.status_code}')
except Exception as e:
    log(f'HEALTH post FAILED: {type(e).__name__}')

# 5. Check DB for any design records created
try:
    r = requests.get(BASE + '/api/v1/portfolio/designs?limit=5', timeout=10)
    log(f'DESIGNS list: {r.status_code} count={len(r.json()) if r.status_code==200 else "N/A"}')
    if r.status_code == 200 and r.json():
        for d in r.json():
            log(f'  id={d["id"]} quality={d.get("report_quality")} text_len={len(d.get("design_text","") or "")}')
except Exception as e:
    log(f'DESIGNS list FAILED: {type(e).__name__}')

log('=== Diagnosis complete ===')
