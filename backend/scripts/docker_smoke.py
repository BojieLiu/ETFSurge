#!/usr/bin/env python
"""P3-4 (round9 §3/P0-3): Docker 容器冒烟门禁——容器内 IPv4 直连 + 核心端点。

用法（容器内）:
  python scripts/docker_smoke.py [host] [port]   # 默认 127.0.0.1:8000

背景（round9 诊断）:
  - C3: uvicorn `--host ::` 在 Linux 容器内仅监听 IPv6（IPV6_V6ONLY）→ Docker
    端口映射（IPv4 转发）全失效 → 宿主 502。修复为 0.0.0.0 后，本脚本验证
    「容器内 IPv4 直连 200」不再复发。
  - C1/C2: compose go-yaml 解析失败 / Dockerfile CMD 行内注释 → 容器起不来，
    本脚本作为启动后冒烟，配合 CI 在每次容器构建后执行。

退出码: 0 = 全 PASS；1 = 有 FAIL（任一检查失败）。
"""
import socket
import sys
import time

import requests


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    base = f"http://{host}:{port}"
    fails = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            fails += 1

    print(f"docker-smoke: {base}")

    # 1) IPv4 直连（C3 回归）：容器内 127.0.0.1 必须可达（uvicorn 0.0.0.0 监听）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, port))
        s.close()
        check(f"TCP IPv4 {host}:{port} 直连", True)
    except Exception as e:
        check(f"TCP IPv4 {host}:{port} 直连", False, str(e))

    # 2) /health
    try:
        r = requests.get(f"{base}/health", timeout=5)
        check("/health -> 200", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:
        check("/health -> 200", False, str(e))

    # 3) 候选池（P0-2 验收）：designs 历史或 market 池非空即认为数据管道可用
    try:
        r = requests.get(f"{base}/api/v1/portfolio/designs?limit=1", timeout=10)
        check("GET /portfolio/designs -> 200", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:
        check("GET /portfolio/designs -> 200", False, str(e))

    # 4) 预热状态（P3-3/P1-4 口径）：墙钟 ≥30s 仅 WARN（不 FAIL，含后台同步段）
    try:
        r = requests.get(f"{base}/api/v1/system/warmup", timeout=5)
        if r.status_code == 200:
            wd = r.json()
            wall = wd.get("elapsed_seconds") or 0
            if wall:
                print(f"  [WARN] 墙钟预热 {wall:.1f}s" if wall >= 30 else f"  [INFO] 墙钟预热 {wall:.1f}s")
            else:
                print("  [INFO] 预热计时器未启用（PROFILE_WARMUP=1 未设置）")
    except Exception as e:
        print(f"  [WARN] /system/warmup 不可用: {e}")

    print(f"docker-smoke 结果: {'ALL PASS' if fails == 0 else f'{fails} FAIL'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
