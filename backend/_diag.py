"""API 诊断脚本 — 验证任务链路每个环节"""
import urllib.request, json, sys

BASE = "http://localhost:8000"

def req(path, timeout=10):
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=timeout)
        return r.status, json.loads(r.read())
    except Exception as e:
        return None, str(e)[:200]

# 1. Health
status, data = req("/health")
print(f"[1] Health: {status} {data}")

# 2. Designs list
status, data = req("/api/v1/portfolio/designs")
if isinstance(data, dict):
    items = data.get("designs", [data])
elif isinstance(data, list):
    items = data
else:
    items = []
print(f"[2] Designs: {len(items)} items")
for item in items[:3]:
    tid = item.get("id", "?")
    st = item.get("status", "?")
    dt = item.get("design_text", "") or ""
    print(f"    ID={tid} status={st} design_text_len={len(dt)}")

# 3. Tasks (in-memory)
status, data = req("/api/v1/portfolio/tasks")
print(f"[3] Tasks: type={type(data).__name__} data={str(data)[:200]}")

# 4. Strategy checks
status, data = req("/api/v1/portfolio/strategy-checks")
print(f"[4] StrategyChecks: type={type(data).__name__} data={str(data)[:200]}")

print("\n=== DONE ===")
