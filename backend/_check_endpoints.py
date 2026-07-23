"""Quick test strategy-check and design-async endpoints."""
import urllib.request, json, time

def req(path, data=None, timeout=10):
    t = time.time()
    if data:
        body = json.dumps(data).encode()
        req = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
    else:
        req = urllib.request.Request(f"http://127.0.0.1:8000{path}")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        d = json.loads(resp.read())
        elapsed = time.time() - t
        return resp.status, d, elapsed
    except Exception as e:
        elapsed = time.time() - t
        return None, str(e)[:100], elapsed

print("1. Health")
s, d, e = req("/health")
print(f"   {s} ({e:.1f}s)")

print("2. Strategy check")
s, d, e = req("/api/v1/portfolio/strategy-check-async",
    {"portfolio_type": "on_exchange"}, timeout=10)
tid = d.get("task_id") if isinstance(d, dict) else "?"
print(f"   {s} task_id={tid} ({e:.1f}s)")

print("3. Design async")
s, d, e = req("/api/v1/portfolio/design-async",
    {"capital": 500000}, timeout=10)
tid = d.get("task_id") if isinstance(d, dict) else "?"
print(f"   {s} task_id={tid} ({e:.1f}s)")

print("4. Health after")
s, d, e = req("/health")
print(f"   {s} ({e:.1f}s)")
