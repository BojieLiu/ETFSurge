"""Quick health check for backend after fixes."""
import urllib.request, json, time

def req(path, data=None, timeout=5):
    try:
        if data:
            body = json.dumps(data).encode()
            r = urllib.request.Request(f"http://localhost:8000{path}", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
        else:
            r = urllib.request.Request(f"http://localhost:8000{path}")
        resp = urllib.request.urlopen(r, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except Exception as e:
        return None, str(e)[:120]

print("1. Health check")
s, d = req("/health")
print(f"   /health -> {s} {d}")

print("2. Designs list")
s, d = req("/api/v1/portfolio/designs?limit=5")
items = d if isinstance(d, list) else d.get('designs', [d])
print(f"   {len(items)} items")
for item in items[:3]:
    dt = item.get('design_text','') or ''
    print(f"   ID={item.get('id')} status={item.get('status')} design_text_len={len(dt)}")

print("3. Strategy checks list")
s, d = req("/api/v1/portfolio/strategy-checks?limit=5")
items = d if isinstance(d, list) else []
print(f"   {len(items)} items")

print("4. Design submit (should return fast)")
s, d = req("/api/v1/portfolio/design-async",
    {"capital": 500000, "constraints": {"risk_profile": "balanced"}}, timeout=10)
tid = d.get("task_id") if isinstance(d, dict) else "?"
print(f"   -> {s} task_id={tid}")

print("5. Strategy check submit (should return fast)")
s, d = req("/api/v1/portfolio/strategy-check-async",
    {"portfolio_type": "on_exchange"}, timeout=10)
tid = d.get("task_id") if isinstance(d, dict) else "?"
print(f"   -> {s} task_id={tid}")

print("6. Backend still alive?")
time.sleep(2)
s, d = req("/health", timeout=3)
print(f"   -> /health after submits: {s}")

print("\nDone. All checks passed if no errors above.")
