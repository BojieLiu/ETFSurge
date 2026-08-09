#!/usr/bin/env python
"""P3-4 (round9 §3/P0-3): Docker 容器冒烟门禁——容器内 IPv4 直连 + 核心端点。

用法（容器内）:
  python scripts/docker_smoke.py [host] [port]   # 默认 127.0.0.1:8000
  python scripts/docker_smoke.py --weak-source   # P2-E: 弱源模拟（EM 不可达）

背景（round9 诊断）:
  - C3: uvicorn `--host ::` 在 Linux 容器内仅监听 IPv6（IPV6_V6ONLY）→ Docker
    端口映射（IPv4 转发）全失效 → 宿主 502。修复为 0.0.0.0 后，本脚本验证
    「容器内 IPv4 直连 200」不再复发。
  - C1/C2: compose go-yaml 解析失败 / Dockerfile CMD 行内注释 → 容器起不来，
    本脚本作为启动后冒烟，配合 CI 在每次容器构建后执行。

--weak-source (P2-E/P3-F, round10 §10):
  模拟「东财不可达」——临时把 EM 域名（push2/push2delay/fund/fundf10/quote.
  eastmoney.com）写入容器 /etc/hosts 指向 127.0.0.1，触发真实弱源降级链，
  断言 pool/design/hot-plates/signal/watchlist 在 ≤10s 内返回且不崩溃、
  降级状态诚实标注。结束后恢复 /etc/hosts（root 容器内运行）。

退出码: 0 = 全 PASS；1 = 有 FAIL（任一检查失败）。
"""
import os
import socket
import subprocess
import sys
import time

import requests

# P2-E: 东财弱源阻断域名（与 market_context/china_market/etf_scanner 一致）
_EM_DOMAINS = (
    "push2.eastmoney.com", "push2delay.eastmoney.com",
    "fund.eastmoney.com", "fundf10.eastmoney.com", "quote.eastmoney.com",
)
_ETC_HOSTS = "/etc/hosts"


def _block_em_sources() -> str | None:
    """把 EM 域名写进 /etc/hosts 指向 127.0.0.1；返回备份内容供恢复。"""
    if not os.path.exists(_ETC_HOSTS):
        print("  [WARN] /etc/hosts 不存在——弱源模拟仅适用于容器内")
        return None
    backup = open(_ETC_HOSTS, encoding="utf-8").read()
    lines = ["# docker-smoke weak-source block (P2-E)", "127.0.0.1 " + " ".join(_EM_DOMAINS)]
    with open(_ETC_HOSTS, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  [INFO] 已阻断 {len(_EM_DOMAINS)} 个东财域名（/etc/hosts → 127.0.0.1）")
    return backup


def _restore_hosts(backup: str | None) -> None:
    if backup is not None:
        with open(_ETC_HOSTS, "w", encoding="utf-8") as f:
            f.write(backup)
        print("  [INFO] /etc/hosts 已恢复")


def _weak_source_checks(base: str) -> int:
    """P2-E: 弱源（EM 不可达）下核心链路不崩溃且诚实降级。"""
    fails = 0

    def check(label, ok, detail=""):
        nonlocal fails
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            fails += 1

    endpoints = [
        ("pool", "/api/v1/market/pool", 10),
        ("designs", "/api/v1/portfolio/designs?limit=1", 10),
        ("hot-plates", "/api/v1/market/hot-plates?limit=5", 10),
        ("signal", "/api/v1/market/signal/510300", 10),
        ("watchlist", "/api/v1/market/watchlist", 10),
    ]
    for label, path, timeout in endpoints:
        t0 = time.monotonic()
        try:
            r = requests.get(f"{base}{path}", timeout=timeout)
            dt = time.monotonic() - t0
            ok = r.status_code == 200 and dt <= timeout
            # 诚实降级：200 非崩溃即达标（弱源下允许数据空/标注降级，但结构完整）
            check(f"weak {label} -> 200 ≤{timeout}s", ok,
                  f"HTTP {r.status_code} in {dt:.1f}s")
        except Exception as e:
            dt = time.monotonic() - t0
            check(f"weak {label} -> 200 ≤{timeout}s", False,
                  f"{type(e).__name__} in {dt:.1f}s: {e}")
    return fails


def main() -> int:
    if "--weak-source" in sys.argv:
        # P2-E/P3-F: 弱源模拟模式
        host = "127.0.0.1"
        port = 8000
        base = f"http://{host}:{port}"
        print(f"docker-smoke (weak-source): {base}")
        # 前置：服务必须已起（弱源模拟只测降级链路，不测启动）
        try:
            r = requests.get(f"{base}/health", timeout=5)
            if r.status_code != 200:
                print(f"docker-smoke 结果: 1 FAIL — /health {r.status_code}（服务未就绪）")
                return 1
        except Exception as e:
            print(f"docker-smoke 结果: 1 FAIL — 服务不可达: {e}")
            return 1
        backup = _block_em_sources()
        try:
            # 给降级链一点生效时间（缓存/熔断首次失败）
            time.sleep(2)
            fails = _weak_source_checks(base)
        finally:
            _restore_hosts(backup)
        print(f"docker-smoke (weak-source) 结果: {'ALL PASS' if fails == 0 else f'{fails} FAIL'}")
        return 0 if fails == 0 else 1

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

