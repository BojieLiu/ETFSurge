"""
Step 2 script: Wait for backend, trigger design + strategy check, poll, save results.
Designed to be run separately from backend startup.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "http://localhost:8000"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "backend", "data")
LOG_FILE = os.path.join(OUTPUT_DIR, "design_operation.log")
LIVE_DESIGN_FILE = os.path.join(OUTPUT_DIR, "live_design_output.json")
LIVE_CHECK_FILE = os.path.join(OUTPUT_DIR, "live_strategy_check_output.json")


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_get(path, timeout=30):
    try:
        req = urllib.request.Request(f"{BASE_URL}{path}")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {"_error": str(e)}


def http_post(path, data, timeout=180):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(f"{BASE_URL}{path}", data=body,
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read().decode()[:300]}"}
    except Exception as e:
        return {"_error": str(e)}


def wait_for_server(timeout=300):
    log(f"Waiting for backend on {BASE_URL}...")
    for i in range(int(timeout / 3)):
        try:
            req = urllib.request.Request(f"{BASE_URL}/health")
            resp = urllib.request.urlopen(req, timeout=3)
            if resp.status == 200:
                log(f"Backend ready after ~{i*3}s")
                return True
        except urllib.error.URLError:
            if i == 0:
                log("  Connection refused (backend not ready)")
        except Exception as e:
            if i == 0:
                log(f"  Health error: {e}")
        time.sleep(3)
    log("Backend wait TIMEOUT")
    return False


def fetch_warmup_data():
    timing_path = os.path.join(os.path.dirname(__file__), "backend", "logs", "warmup_timing.json")
    if os.path.exists(timing_path):
        with open(timing_path, encoding="utf-8") as f:
            timing = json.load(f)
        total = timing.get("total_duration_ms", 0)
        log(f"=== Warmup Profiling ===")
        log(f"Total warmup: {total:.0f}ms ({total/1000:.1f}s)")
        for rec in timing.get("records", []):
            dur = rec.get("duration_ms", 0)
            note = rec.get("note", "")
            log(f"  {dur:7.0f}ms  {note}")
    else:
        log("(no warmup timing data)")


def trigger_design():
    log("\n=== Triggering Portfolio Design ===")
    result = http_post("/api/v1/portfolio/design-async", {
        "risk_profile": "balanced",
        "capital": 500000,
        "market": "A",
    })
    if "_error" in result:
        log(f"DESIGN TRIGGER FAILED: {result['_error']}")
        return None
    task_id = result.get("task_id")
    log(f"Design task created: {task_id}")
    return task_id


def trigger_strategy_check():
    log("\n=== Triggering Strategy Check ===")
    result = http_post("/api/v1/portfolio/strategy-check-async", {
        "risk_profile": "balanced",
        "capital": 500000,
        "market": "A",
    })
    if "_error" in result:
        log(f"CHECK TRIGGER FAILED: {result['_error']}")
        return None
    task_id = result.get("task_id")
    log(f"Strategy check task created: {task_id}")
    return task_id


def poll_task(task_id, max_wait=900, interval=10):
    log(f"Polling {task_id} (max {max_wait}s)...")
    heartbeat = max(interval * 6, 60)
    for i in range(max_wait // interval):
        result = http_get(f"/api/v1/portfolio/tasks/{task_id}", timeout=15)
        if "_error" in result:
            log(f"  Poll error: {result['_error']}")
            time.sleep(interval)
            continue
        status = result.get("status", "unknown")
        progress = result.get("progress", 0)
        stage = result.get("stage", "")
        log(f"  Task {task_id}: {status} [{progress}%] {stage}")
        if status in ("completed", "failed"):
            return result
        time.sleep(interval)
        if i > 0 and i % (heartbeat // interval) == 0:
            elapsed = i * interval
            log(f"  [heartbeat] Still waiting... ({elapsed}s elapsed)")
    log(f"  Task {task_id} TIMEOUT after {max_wait}s")
    return {"status": "timeout"}


def fetch_results_and_review():
    log("\n=== Results ===")

    # Design list
    designs = http_get("/api/v1/portfolio/designs", timeout=15)
    if type(designs) is list and designs:
        latest_id = designs[0].get("id") or designs[0].get("design_id")
        log(f"Latest design ID: {latest_id}")
        detail = http_get(f"/api/v1/portfolio/designs/{latest_id}", timeout=60)
        with open(LIVE_DESIGN_FILE, "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        log(f"Saved to {LIVE_DESIGN_FILE}")

        strategies = detail.get("strategies_json", [])
        log(f"\n--- Review: {len(strategies)} strategies ---")
        for s in strategies:
            label = s.get("label", "?")
            etfs = s.get("etfs", [])
            log(f"\n  [{label}] {len(etfs)} ETFs")
            for etf in etfs:
                symbol = etf.get("symbol", "?")
                weight = etf.get("weight", 0)
                score = etf.get("factor_score", "?")
                rationale = str(etf.get("selection_rationale", ""))[:120]
                log(f"    {symbol} w={weight:.0%} score={score}")
                log(f"      rationale: {rationale}")
                if "今日%" in rationale:
                    log(f"      ⚠️  PLACEHOLDER FOUND!")

            # Check for duplicate factor scores
            scores = [e.get("factor_score") for e in etfs]
            if len(scores) != len(set(str(s) for s in scores)):
                log(f"      ⚠️  Duplicate factor scores in {label}!")

    else:
        log("(no designs found)")

    # Strategy checks
    checks = http_get("/api/v1/portfolio/strategy-checks", timeout=15)
    if type(checks) is list and checks:
        cid = checks[0].get("id") or checks[0].get("check_id")
        check_detail = http_get(f"/api/v1/portfolio/strategy-checks/{cid}", timeout=60)
        with open(LIVE_CHECK_FILE, "w", encoding="utf-8") as f:
            json.dump(check_detail, f, ensure_ascii=False, indent=2)
        log(f"Strategy check saved to {LIVE_CHECK_FILE}")
        # Quick preview
        preview = json.dumps(check_detail, ensure_ascii=False)[:800]
        log(f"Check preview:\n{preview}")
    else:
        log("(no strategy checks found)")


def main():
    log("=" * 50)
    log("ETF Surge Design Trigger")
    log("=" * 50)

    # Step 1: Wait for server
    if not wait_for_server():
        # Maybe server is already running - try health directly
        log("Trying direct health check...")
        if not wait_for_server(timeout=10):
            sys.exit(1)

    # Step 2: Warmup data
    fetch_warmup_data()

    # Step 3: Trigger design
    task_id = trigger_design()
    if task_id:
        poll_task(task_id)
    else:
        log("Skipping design poll because trigger failed")

    # Step 4: Trigger strategy check
    task_id2 = trigger_strategy_check()
    if task_id2:
        poll_task(task_id2)

    # Step 5: Fetch results
    fetch_results_and_review()

    log("\n=== DONE ===")


if __name__ == "__main__":
    main()
