"""
Comprehensive diagnostics script:
1. Start backend with profiling
2. Wait for ready
3. Trigger portfolio design + strategy check
4. Wait for results
5. Run perf_diag.py
6. Output all findings
"""
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
BASE_URL = "http://localhost:8000"

# Set profiling env
os.environ["PROFILE_WARMUP"] = "1"
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)


async def wait_for_server(max_retries=60, delay=2):
    """Wait until the health endpoint responds."""
    for i in range(max_retries):
        try:
            req = urllib.request.Request(f"{BASE_URL}/health")
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                print(f"[OK] Server ready after ~{i*delay}s")
                return True
        except Exception:
            pass
        await asyncio.sleep(delay)
    print("[FAIL] Server did not start in time")
    return False


def api_get(path):
    """GET request returning parsed JSON."""
    try:
        req = urllib.request.Request(f"{BASE_URL}{path}")
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def api_post(path, data):
    """POST request with JSON body returning parsed JSON."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{BASE_URL}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=180)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def poll_task(task_id, max_wait=300, interval=5):
    """Poll a task until it completes or errors."""
    for _ in range(max_wait // interval):
        result = api_get(f"/api/v1/portfolio/tasks/{task_id}")
        status = result.get("status", "unknown")
        progress = result.get("progress", 0)
        stage = result.get("stage", "")
        if status in ("completed", "failed"):
            print(f"  Task {task_id}: {status} | progress={progress} | stage={stage}")
            return result
        print(f"  Task {task_id}: {status} [{progress}%] {stage}")
        time.sleep(interval)
    return {"error": "poll timed out"}


async def main():
    # Step 1: Check if server is already running
    try:
        req = urllib.request.Request(f"{BASE_URL}/health")
        resp = urllib.request.urlopen(req, timeout=3)
        if resp.status == 200:
            print("[INFO] Server already running")
    except Exception:
        print("[INFO] Starting server...")
        import subprocess
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=BACKEND_DIR,
            env={**os.environ, "PROFILE_WARMUP": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ready = await wait_for_server()
        if not ready:
            print("[FAIL] Server startup failed")
            return

    # Step 2: Design task
    print("\n=== Step 2: Portfolio Design ===")
    design_result = api_post("/api/v1/portfolio/design-async", {
        "risk_profile": "balanced",
        "capital": 500000,
        "market": "A",
    })
    task_id = design_result.get("task_id")
    print(f"Design task {task_id} created")
    design_task_result = poll_task(task_id)

    # Step 3: Strategy check task
    print("\n=== Step 3: Strategy Check ===")
    check_result = api_post("/api/v1/portfolio/strategy-check-async", {
        "risk_profile": "balanced",
        "capital": 500000,
        "market": "A",
    })
    task_id2 = check_result.get("task_id")
    print(f"Strategy check task {task_id2} created")
    check_task_result = poll_task(task_id2)

    # Step 4: Get design details
    print("\n=== Step 4: Design Details ===")
    designs = api_get("/api/v1/portfolio/designs")
    if designs and len(designs) > 0:
        latest_id = designs[0]["id"]
        detail = api_get(f"/api/v1/portfolio/designs/{latest_id}")
        print(f"Latest design (id={latest_id}):")
        print(f"  status: {detail.get('status')}")
        print(f"  risk_profile: {detail.get('risk_profile')}")
        print(f"  strategies: {len(detail.get('strategies_json', []))} strategies")
        strategies = detail.get("strategies_json", [])
        for s in strategies:
            print(f"  - {s.get('label')}: {len(s.get('etfs', []))} ETFs, expected_return={s.get('expected_return')}")
        # Save to file for review
        with open(os.path.join(BACKEND_DIR, "data", "latest_design.json"), "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        print(f"[SAVED] design to data/latest_design.json")

    # Step 5: Strategy check results
    print("\n=== Step 5: Strategy Check Results ===")
    checks = api_get("/api/v1/portfolio/strategy-checks")
    print(f"Found {len(checks)} strategy checks")
    if checks and len(checks) > 0:
        latest_check_id = checks[0].get("id") or checks[0].get("check_id")
        if latest_check_id:
            check_detail = api_get(f"/api/v1/portfolio/strategy-checks/{latest_check_id}")
            print(f"Latest check (id={latest_check_id}):")
            # Truncate for console
            summary = json.dumps(check_detail, ensure_ascii=False)[:1000]
            print(f"  {summary}")
            with open(os.path.join(BACKEND_DIR, "data", "latest_strategy_check.json"), "w", encoding="utf-8") as f:
                json.dump(check_detail, f, ensure_ascii=False, indent=2)
            print(f"[SAVED] strategy check to data/latest_strategy_check.json")

    # Step 6: Run perf_diag
    print("\n=== Step 6: Performance Diagnostics ===")
    sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))
    try:
        from perf_diag import main as perf_main
        await perf_main()
        print("[OK] perf_diag completed")
    except Exception as e:
        print(f"[WARN] perf_diag failed: {e}")

    print("\n=== ALL DIAGNOSTICS COMPLETE ===")


if __name__ == "__main__":
    asyncio.run(main())
