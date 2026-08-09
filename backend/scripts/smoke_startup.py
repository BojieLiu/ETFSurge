"""
smoke_startup.py — 后端启动冒烟测试

启动 uvicorn 子进程，等待 health 响应，测试 3 个核心端点，
验证进程存活。如果后端无法在 60 秒内完成初始化，视为失败。

用法:
    python scripts/smoke_startup.py              # 完整测试
    SKIP_NETWORK=1 python scripts/smoke_startup.py  # 跳过（网络不可用时）
    SMOKE_FAST=1 python scripts/smoke_startup.py    # 快速模式（pre-commit 门禁用）

退出码:
    0 = 全部通过
    1 = 任一检查失败

快速模式（SMOKE_FAST=1，pre-commit 门禁专用）：
    - 子进程设置 ETF_SURGE_SKIP_WARMUP=1，lifespan 跳过后台预热任务及
      其 60s 等待（health 响应 ~18s → ~5s）。
    - 跳过 POST /calculate（首次调用懒加载实时行情 ~30s，属业务链路，
      由 verify_e2e.py 覆盖）；仍验证 health + ETF 列表 + 进程存活。
    完整模式（默认）行为不变，保留 calculate 真实验证。
"""
import os
import sys
import json
import time
import socket
import urllib.request
import subprocess

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "127.0.0.1"
PORT = 18000  # 非标准端口，避免与正在运行的后端冲突
BASE = f"http://{HOST}:{PORT}"

PASS = 0
FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        mark = "PASS"
    else:
        FAIL += 1
        mark = "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def http_get(path, timeout=10):
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=timeout)
        body = r.read().decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = body
        return r.status, data
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


def http_post(path, body_dict, timeout=15):
    data = json.dumps(body_dict).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        body = r.read().decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = body
        return r.status, data
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


def main():
    global PASS, FAIL

    if os.environ.get("SKIP_NETWORK") == "1":
        print("[smoke] SKIP_NETWORK=1，跳过冒烟测试")
        sys.exit(0)

    fast = os.environ.get("SMOKE_FAST") == "1"

    # 检查端口可用
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((HOST, PORT))
        s.close()
    except OSError:
        print(f"[smoke] 端口 {PORT} 已被占用，无法启动测试服务器")
        sys.exit(1)

    print(f"\n── 后端启动冒烟测试 ──────────────────────────────────")
    print(f"  启动 uvicorn 到 {HOST}:{PORT} ..."
          + ("（SMOKE_FAST 快速模式：跳过预热 + calculate）" if fast else ""))

    env = os.environ.copy()
    if fast:
        # 跳过后台预热任务及其 60s 等待（lifespan await asyncio.wait）
        env["ETF_SURGE_SKIP_WARMUP"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "app.main:app", "--host", HOST, "--port", str(PORT)],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    start = time.time()

    # ── 阶段 1：等待 health ──────────────────────
    health_ok = False
    for i in range(60):
        time.sleep(1)
        status, data = http_get("/health", timeout=2)
        if status == 200 and isinstance(data, dict) and data.get("status") == "ok":
            health_ok = True
            elapsed = time.time() - start
            print(f"  [INFO] health OK at {elapsed:.0f}s")
            break

    check("Health 端点响应（≤60s）", health_ok)
    if not health_ok:
        elapsed = time.time() - start
        died = proc.poll() is not None
        print(f"  [INFO] 耗时 {elapsed:.0f}s, 进程死亡={died}, RC={proc.returncode if died else 'N/A'}")
        proc.terminate()
        proc.communicate()
        sys.exit(1)

    # ── 阶段 2：核心端点测试 ──────────────────────
    print()

    # ETF 列表
    status, data = http_get("/api/v1/portfolio/etfs", timeout=10)
    if status == 200 and isinstance(data, list):
        check(f"GET /api/v1/portfolio/etfs -> {len(data)} ETFs",
              len(data) > 0, f"共 {len(data)} 条" if data else "空列表")
    elif status is not None:
        check(f"GET /api/v1/portfolio/etfs -> {status}", False, str(data)[:100])
    else:
        check("GET /api/v1/portfolio/etfs", False, str(data))

    # 组合计算
    if fast:
        # 快速模式跳过：calculate 首次调用懒加载实时行情 ~30s，
        # 属业务链路验证，由 verify_e2e.py 覆盖（pre-commit 只验启动+路由）。
        print("  [SKIP] POST /api/v1/portfolio/calculate（SMOKE_FAST，由 verify_e2e 覆盖）")
    else:
        status, data = http_post("/api/v1/portfolio/calculate",
                                 {"total_capital": 100000}, timeout=30)
        if status == 200 and isinstance(data, dict):
            allocs = data.get("allocations", [])
            cash = data.get("cash_amount", "N/A")
            check(f"POST /api/v1/portfolio/calculate -> {len(allocs)} allocs",
                  len(allocs) > 0, f"allocs={len(allocs)}, cash={cash}")
        elif status is not None:
            check(f"POST /api/v1/portfolio/calculate -> {status}", False, str(data)[:100])
        else:
            check("POST /api/v1/portfolio/calculate", False, str(data))

    # 二次确认 health
    status, data = http_get("/health", timeout=5)
    check("Health 二次检查", status == 200)

    # ── 阶段 3：进程存活 ──────────────────────────
    alive = proc.poll() is None
    check("子进程存活", alive, "" if alive else f"退出码={proc.returncode}")

    # 清理
    print()
    total = PASS + FAIL
    elapsed = time.time() - start
    print(f"  总计 {total} 项检查: {PASS} 通过, {FAIL} 失败, 耗时 {elapsed:.0f}s")

    proc.terminate()
    proc.communicate()

    if FAIL > 0:
        sys.exit(1)

    print(f"\n  [OK] 后端启动冒烟测试通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
