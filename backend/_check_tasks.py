"""Quick task/design status check."""
import json, urllib.request

BASE = "http://127.0.0.1:8000"

def api_get(path, timeout=10):
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=timeout)
        return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)[:200]}

# Task 86 (design)
d = api_get("/api/v1/portfolio/tasks/86", timeout=10)
print("=== TASK 86 (DESIGN) ===")
print(json.dumps(d, indent=2, ensure_ascii=False)[:500])

# Task 87 (strategy check)
d = api_get("/api/v1/portfolio/tasks/87", timeout=10)
print("\n=== TASK 87 (STRATEGY CHECK) ===")
print(json.dumps(d, indent=2, ensure_ascii=False)[:500])

# Designs list
d = api_get("/api/v1/portfolio/designs?limit=5", timeout=10)
print("\n=== DESIGNS LIST ===")
if isinstance(d, list):
    print(f"Count: {len(d)}")
    if d:
        for item in d[-3:]:
            rid = item.get("id", "?")
            created = str(item.get("created_at", ""))[:19]
            print(f"  id={rid} created={created}")
else:
    print(str(d)[:300])

# Tasks list
d = api_get("/api/v1/portfolio/tasks?limit=10", timeout=10)
print("\n=== TASKS LIST ===")
if isinstance(d, list):
    print(f"Count: {len(d)}")
    if d:
        for item in d[-5:]:
            tid = item.get("id", "?")
            ttype = item.get("task_type", "")
            status = item.get("status", "")
            created = str(item.get("created_at", ""))[:19]
            print(f"  id={tid} type={ttype} status={status} created={created}")
else:
    print(str(d)[:300])
