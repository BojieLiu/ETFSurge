"""
Start backend → trigger design + strategy check → poll to completion → review output.
Everything runs in ONE process to avoid shell session death issues.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
BASE_URL = "http://localhost:8000"

os.environ["PROFILE_WARMUP"] = "1"
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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
        req = urllib.request.Request(
            f"{BASE_URL}{path}", data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        return {"_error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"_error": str(e)}


def wait_for_server(timeout=300):
    log("Waiting for backend...")
    for i in range(int(timeout / 2)):
        try:
            req = urllib.request.Request(f"{BASE_URL}/health")
            resp = urllib.request.urlopen(req, timeout=3)
            if resp.status == 200:
                log(f"Backend ready after ~{i*2}s")
                return True
        except urllib.error.URLError as e:
            if i == 0:
                log(f"  Connection refused (backend not ready yet)")
        except Exception as e:
            if i == 0:
                log(f"  Health check error: {type(e).__name__}: {e}")
        time.sleep(2)
    return False


def poll_task(task_id, max_wait=900, interval=10):
    """Poll until completed/failed, return final result."""
    log(f"Polling task {task_id} (max {max_wait}s, interval {interval}s)...")
    heartbeat_interval = max(interval * 6, 60)
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
        # Heartbeat every 60s
        if i > 0 and i % (heartbeat_interval // interval) == 0:
            log(f"  Still waiting... ({i * interval}s elapsed)")
    log(f"  Task {task_id} did not complete within {max_wait}s")
    return {"status": "timeout", "_task_id": task_id}


def main():
    proc = None
    try:
        # ── 1. Start backend ──
        log("=" * 60)
        log("STEP 1: Starting backend with PROFILE_WARMUP=1")
        log("=" * 60)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "0.0.0.0", "--port", "8000"],
            cwd=BACKEND_DIR,
            env={**os.environ, "PROFILE_WARMUP": "1"},
        )

        if not wait_for_server(timeout=300):
            log("FAILED: Backend did not start within 300s")
            rc = proc.poll()
            if rc is not None:
                log(f"Backend exited with code {rc}")
                try:
                    out, err = proc.communicate(timeout=3)
                    if err: log(f"STDERR: {err.decode(errors='replace')[-1000:]}")
                    if out: log(f"STDOUT: {out.decode(errors='replace')[-1000:]}")
                except Exception:
                    pass
            else:
                log("Backend is still alive but not responding on :8000 — check port or firewall")
                # Dump port status
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex(('127.0.0.1', 8000))
                sock.close()
                log(f"Port 8000 connect_ex result: {result} (0=open)")
            return

        # ── 2. Check warmup profiling data ──
        log("\n" + "=" * 60)
        log("STEP 2: Warmup profiling results")
        log("=" * 60)
        timing_path = os.path.join(BACKEND_DIR, "logs", "warmup_timing.json")
        if os.path.exists(timing_path):
            with open(timing_path, encoding="utf-8") as f:
                timing = json.load(f)
            total = timing.get("total_duration_ms", 0)
            log(f"Total warmup time: {total:.0f}ms ({total/1000:.1f}s)")
            for rec in timing.get("records", []):
                label = rec.get("label", "?")
                dur = rec.get("duration_ms", 0)
                note = rec.get("note", "")
                bar = "█" * max(1, int(dur / 100))
                log(f"  {bar} {dur:7.0f}ms  {note} ({label})")
        else:
            log("(warmup_timing.json not found - profiling may not have completed)")

        # ── 3. Portfolio design ──
        log("\n" + "=" * 60)
        log("STEP 3: Triggering portfolio design (balanced, 500k)")
        log("=" * 60)
        design = http_post("/api/v1/portfolio/design-async", {
            "risk_profile": "balanced",
            "capital": 500000,
            "market": "A",
        })
        if "_error" in design:
            log(f"FAILED: {design['_error']}")
            return
        task_id = design.get("task_id")
        log(f"Design task created: {task_id}")

        design_result = poll_task(task_id, max_wait=900)
        log(f"Design final status: {design_result.get('status')}")

        # ── 4. Strategy check ──
        log("\n" + "=" * 60)
        log("STEP 4: Triggering strategy check")
        log("=" * 60)
        check = http_post("/api/v1/portfolio/strategy-check-async", {
            "risk_profile": "balanced",
            "capital": 500000,
            "market": "A",
        })
        if "_error" not in check:
            task_id2 = check.get("task_id")
            log(f"Strategy check task created: {task_id2}")
            check_result = poll_task(task_id2, max_wait=900)
            log(f"Strategy check final status: {check_result.get('status')}")
        else:
            log(f"Strategy check trigger failed: {check['_error']}")

        # ── 5. Get design details ──
        log("\n" + "=" * 60)
        log("STEP 5: Fetching design details & strategy check results")
        log("=" * 60)
        designs = http_get("/api/v1/portfolio/designs", timeout=15)
        if type(designs) is list and len(designs) > 0:
            latest_id = designs[0].get("id") or designs[0].get("design_id")
            if latest_id:
                detail = http_get(f"/api/v1/portfolio/designs/{latest_id}", timeout=30)
                detail_path = os.path.join(BACKEND_DIR, "data", "live_design_output.json")
                with open(detail_path, "w", encoding="utf-8") as f:
                    json.dump(detail, f, ensure_ascii=False, indent=2)
                log(f"Design detail saved to data/live_design_output.json")

                # Print overview
                strategies = detail.get("strategies_json", [])
                log(f"\nDesign contains {len(strategies)} strategies:")
                for s in strategies:
                    label = s.get("label", "?")
                    etfs = s.get("etfs", [])
                    er = s.get("expected_return", "?")
                    log(f"  [{label}] {len(etfs)} ETFs, expected_return={er}")
                    for i, etf in enumerate(etfs[:4]):
                        symbol = etf.get("symbol", "?")
                        w = etf.get("weight", 0)
                        score = etf.get("factor_score", "?")
                        rationale = str(etf.get("selection_rationale", ""))[:80]
                        log(f"    {i+1}. {symbol} weight={w:.2%} score={score}")
                        log(f"       rationale: {rationale}")
                    if len(etfs) > 4:
                        log(f"       ... and {len(etfs)-4} more")

                # Check for quality issues
                issues = []
                for s in strategies:
                    for etf in s.get("etfs", []):
                        r = str(etf.get("selection_rationale", ""))
                        if "今日%" in r or "{%" in r:
                            issues.append(f"占位符: {etf.get('symbol')} — {r[:80]}")

                if issues:
                    log("\n⚠️  DATA QUALITY ISSUES:")
                    for iss in issues:
                        log(f"  ❌ {iss}")
                else:
                    log("\n✅ No placeholder issues found in rationale!")
        else:
            log("No designs found via API")

        # ── 6. Strategy check details ──
        checks = http_get("/api/v1/portfolio/strategy-checks", timeout=15)
        if type(checks) is list and len(checks) > 0:
            cid = checks[0].get("id") or checks[0].get("check_id") or checks[0].get("_id")
            if cid:
                check_detail = http_get(f"/api/v1/portfolio/strategy-checks/{cid}", timeout=30)
                ck_path = os.path.join(BACKEND_DIR, "data", "live_strategy_check_output.json")
                with open(ck_path, "w", encoding="utf-8") as f:
                    json.dump(check_detail, f, ensure_ascii=False, indent=2)
                log(f"Strategy check saved to data/live_strategy_check_output.json")
                summary = json.dumps(check_detail, ensure_ascii=False)[:1000]
                log(f"Check detail preview:\n{summary}")

        log("\n" + "=" * 60)
        log("ALL DONE - results in backend/data/live_*_output.json")
        log("=" * 60)

    except KeyboardInterrupt:
        log("\nInterrupted by user")
    finally:
        if proc:
            log("Shutting down backend...")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
