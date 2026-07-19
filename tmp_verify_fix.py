"""E2E verify task status endpoint"""
import requests, time, sys

BASE = "http://127.0.0.1:8000/api/v1"

# 1. Check status of design #70 (should be failed - >300s old)
r = requests.get(f"{BASE}/portfolio/designs/70/status", timeout=5)
j = r.json()
print(f"Design #70: status={j['status']} alive={j['alive']}")
assert j["status"] in ("failed", "not_found"), f"Expected failed/not_found, got {j['status']}"

# 2. Trigger new design
print("\nTriggering new design...")
r = requests.post(f"{BASE}/portfolio/design", params={
    "capital": 500000, "mode": "standard", "session_id": "e2e_status_test"
}, json={}, timeout=10)
d = r.json()
did = d.get("id")
print(f"New design_id: {did}")
print(f"  regime: {d.get('market_context',{}).get('market_regime')}")

# 3. Check status immediately (should be running)
r2 = requests.get(f"{BASE}/portfolio/designs/{did}/status", timeout=5)
j2 = r2.json()
print(f"  status (immediate): {j2['status']} - alive={j2['alive']}")
assert j2["status"] == "running", f"Expected running, got {j2['status']}"
assert j2["alive"] is True

# 4. Check design_text via GET - should be empty initially
r3 = requests.get(f"{BASE}/portfolio/designs/{did}", timeout=5)
j3 = r3.json()
print(f"  design_text initially: {'empty' if not j3.get('design_text') else 'populated'}")

print("\nAll status checks passed!")
