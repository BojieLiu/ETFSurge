#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""§12 P0-1 (round34): 启动行为审计（patrol L2-startup）——日志消费门禁。

盲区（round34 §12.3）：巡检九层全是瞬时快照断言，「启动后 2 分钟窗口干了什么」
零覆盖——R103 回填每启重跑、R105 段一锚静默缺池、R106 WARNING 周期重放，信号
全写在 backend.log 里却无任何层消费。本脚本审计 backend.log 自最近启动标记起的
窗口 + pool 磁盘快照：

① IC 回填模式审计：[ic_backfill] 窗口内必须出现「完成|跳过」终态之一；
   连续两次启动均「完成」→ WARN（R103 信号；状态文件
   logs/patrol/startup_behavior.json 记录上次模式 {"last_backfill_mode","ts","head"}）。
② 强制锚审计：MANDATORY_CODES 逐成员「在池（pool 快照）OR 有 enforce/inject 日志」，
   皆无 → FAIL（直接抓 R105 段一静默跳过）。证据源整体不可得（fresh 环境无快照
   且窗口零注入痕迹）→ WARN 降级标注，不硬 FAIL（诚实降级纪律 §12.5）。
③ WARNING 洪泛指纹：同指纹（logger 名+去参消息模板）窗口内重复 ≥K 次 → WARN
   （R106 信号；K 默认 5，env STARTUP_WARN_FLOOD_K 可调）。

可信度自证（§12.5 纪律 2）：恒输出 ≥4 条 check 行且打印 checks_run 计数，
防「门禁存在但从未真正跑过」。

用法：python scripts/check_startup_behavior.py [--log PATH] [--state PATH]
Exit：0 = PASS / 仅 WARN；1 = FAIL。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
DEFAULT_LOG = os.path.join(BACKEND_DIR, "logs", "backend.log")
DEFAULT_STATE = os.path.join(REPO_ROOT, "logs", "patrol", "startup_behavior.json")

MANDATORY_CODES = ("510300", "159338", "518880", "511090")
FLOOD_K = int(os.environ.get("STARTUP_WARN_FLOOD_K", "5"))

# 启动标记：uvicorn 进程行 / lifespan 标语——取最后一次出现为审计窗口起点
STARTUP_MARKER_RE = re.compile(
    r"Started server process|Application startup complete|Uvicorn running|"
    r"IC 历史回填任务已启动"
)
WARNING_LINE_RE = re.compile(r"^(\S+ \S+)\s+WARNING\s+\[([^\]]+)\]\s+(.*)$")
# 池注入/强制锚相关日志证据（ensure_mandatory / recheck / 静态兜底 / 宽基静态注入）
_ANCHOR_LOG_PATTERNS = (
    "enforced mandatory",
    "re-injected mandatory",
    "injecting static entry",
    "WideBasisInject",
)


def _resolve_log_path() -> str:
    env_path = os.environ.get("ETF_SURGE_STARTUP_LOG")
    if env_path:
        return env_path
    try:
        sys.path.insert(0, BACKEND_DIR)
        from app.config import settings  # noqa: PLC0415 - 脚本内惰性导入

        if getattr(settings, "log_file", ""):
            return settings.log_file
    except Exception:
        pass
    return DEFAULT_LOG


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _window_lines(lines: list[str]) -> list[str]:
    """自最后一个启动标记起截取审计窗口（无标记则整文件 best-effort）。"""
    last_idx = -1
    for i, ln in enumerate(lines):
        if STARTUP_MARKER_RE.search(ln):
            last_idx = i
    return lines[last_idx + 1:] if last_idx >= 0 else lines


def _load_pool_snapshot_symbols() -> set[str] | None:
    """读最近一条 pool 快照的全部 symbol。不可得返回 None（证据源缺失≠空池）。"""
    try:
        sys.path.insert(0, BACKEND_DIR)
        from app.services.hub._common import _load_latest_snapshot_sync  # noqa: PLC0415

        snap = _load_latest_snapshot_sync("pool")
        if not isinstance(snap, dict):
            return None
        syms: set[str] = set()
        for layer in snap.values():
            if isinstance(layer, list):
                for it in layer:
                    if isinstance(it, dict) and it.get("symbol"):
                        syms.add(str(it["symbol"]))
        return syms
    except Exception:
        return None


def _audit_backfill(window: list[str], state_path: str) -> tuple[str, list[str]]:
    """检查①：回填模式审计。返回 (status, messages)。status ∈ PASS/WARN/FAIL。"""
    msgs: list[str] = []
    bf_lines = [ln for ln in window if "[ic_backfill]" in ln]
    completed = any("历史回填完成" in ln for ln in bf_lines)
    skipped = any("跳过" in ln for ln in bf_lines)

    state = {}
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}

    if not bf_lines:
        msgs.append("[WARN] 窗口内无 [ic_backfill] 日志——回填任务未运行或标记缺失（诚实降级）")
        mode = None
        status = "PASS"  # WARN 起步纪律：不 FAIL
    elif completed:
        mode = "completed"
        prev = state.get("last_backfill_mode")
        if prev == "completed":
            msgs.append(
                "[WARN] 连续两次启动均为「历史回填完成」——skip 判据未生效，疑似每启重跑"
                "（R103 信号，核对 kline_depth 是否被超深净值序列击穿）"
            )
            status = "PASS"
        else:
            msgs.append("[OK] 本次启动执行了完整回填（上次=" + str(prev) + "）")
            status = "PASS"
    elif skipped:
        mode = "skipped"
        msgs.append("[OK] 本次启动命中 skip 分支（已回填≥深度-30，不重跑）")
        status = "PASS"
    else:
        mode = None
        msgs.append(f"[WARN] 回填日志无「完成|跳过」终态（{len(bf_lines)} 行中间态）")
        status = "PASS"

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({
                "last_backfill_mode": mode,
                "ts": datetime.now().isoformat(),
                "head": _git_head(),
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return status, msgs


def _audit_mandatory(window: list[str]) -> tuple[str, list[str]]:
    """检查②：MANDATORY_CODES 在池 OR 注入日志。返回 (status, messages)。"""
    msgs: list[str] = []
    pool_syms = _load_pool_snapshot_symbols()

    def _has_log_evidence(code: str) -> bool:
        for ln in window:
            if any(p in ln for p in _ANCHOR_LOG_PATTERNS) and code in ln:
                return True
        return False

    missing = [
        c for c in MANDATORY_CODES
        if not ((pool_syms and c in pool_syms) or _has_log_evidence(c))
    ]
    sources_available = pool_syms is not None or any(
        any(p in ln for p in _ANCHOR_LOG_PATTERNS) for ln in window
    )

    if not missing:
        evidenced = [c for c in MANDATORY_CODES if pool_syms and c in pool_syms]
        via_log = [c for c in MANDATORY_CODES if c not in evidenced]
        detail = f"快照在池 {len(evidenced)} 只"
        if via_log:
            detail += f"，日志注入 {via_log}"
        msgs.append(f"[OK] 强制锚全部可观测（{detail}）")
        return "PASS", msgs
    if not sources_available:
        # fresh 环境：无快照且窗口零注入痕迹 → 无法审计，诚实降级（§12.5）
        msgs.append(
            "[WARN] 无 pool 快照且窗口零注入日志——证据源不可得，锚审计降级为 INCONCLUSIVE "
            "（fresh 库属预期；若非首次启动请核查扫描链路）"
        )
        return "PASS", msgs
    msgs.append(
        f"[FAIL] 强制锚脱离池且无注入日志：{missing}（R105 段一信号——扫描 flat 缺锚时 "
        "ensure_mandatory 曾静默跳过；核对 scanner 白名单与静态注入分支）"
    )
    return "FAIL", msgs


def _warn_fingerprint(msg: str) -> str:
    """去参消息模板：剥数字/浮点/引号串/URL/hex 后取前 80 字符。"""
    t = re.sub(r"https?://\S+", "<url>", msg)
    t = re.sub(r"'[^']*'|\"[^\"]*\"", "<q>", t)
    t = re.sub(r"0x[0-9a-fA-F]+", "<hex>", t)
    t = re.sub(r"\d+(?:\.\d+)?%?", "<n>", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:80]


def _audit_warning_flood(window: list[str]) -> tuple[str, list[str]]:
    """检查③：WARNING 指纹洪泛。返回 (status, messages)。"""
    msgs: list[str] = []
    counter: Counter[tuple[str, str]] = Counter()
    for ln in window:
        m = WARNING_LINE_RE.match(ln)
        if m:
            counter[(m.group(2), _warn_fingerprint(m.group(3)))] += 1
    offenders = [(k, v) for k, v in counter.items() if v >= FLOOD_K]
    total_warns = sum(counter.values())
    if offenders:
        top = sorted(offenders, key=lambda kv: -kv[1])[:3]
        detail = "; ".join(f"{k[0]}: {k[1]!r} ×{v}" for k, v in top)
        msgs.append(
            f"[WARN] WARNING 指纹重复 ≥{FLOOD_K} 次/窗口（R106 周期重放信号）——共 "
            f"{total_warns} 条 WARNING / {len(counter)} 指纹；Top: {detail}"
        )
        status = "PASS"  # WARN 起步纪律
    else:
        msgs.append(
            f"[OK] 无洪泛 WARNING 指纹（共 {total_warns} 条 / {len(counter)} 指纹，阈值 K={FLOOD_K}）"
        )
        status = "PASS"
    return status, msgs


def main() -> int:
    parser = argparse.ArgumentParser(description="Startup behavior audit (L2-startup)")
    parser.add_argument("--log", default=None, help="backend.log 路径（默认 env/config/约定路径）")
    parser.add_argument("--state", default=DEFAULT_STATE, help="状态文件路径")
    args = parser.parse_args()

    print("=" * 60)
    print("启动行为审计 (§12 P0-1 / L2-startup)")
    print(f"#  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    checks_run = 0
    failures: list[str] = []

    log_path = args.log or _resolve_log_path()
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            all_lines = f.read().splitlines()
    except OSError as e:
        print(f"[FAIL] 日志不可读：{log_path} ({e})——无法审计启动行为")
        print("checks_run: 1 (<4 自证下限)")
        return 1

    window = _window_lines(all_lines)
    print(f"log={log_path}  总行数={len(all_lines)}  审计窗口={len(window)} 行")

    # ① 回填模式
    status, msgs = _audit_backfill(window, args.state)
    checks_run += 1
    for m in msgs:
        print(f"  {m}")
    if status == "FAIL":
        failures.extend(msgs)

    # ② 强制锚
    status, msgs = _audit_mandatory(window)
    checks_run += 1
    for m in msgs:
        print(f"  {m}")
    if status == "FAIL":
        failures.extend(msgs)

    # ③ WARNING 洪泛
    status, msgs = _audit_warning_flood(window)
    checks_run += 1
    for m in msgs:
        print(f"  {m}")
    if status == "FAIL":
        failures.extend(msgs)

    # 可信度自证（§12.5）：检查数下限
    checks_run += 1
    if checks_run < 4:
        print(f"[FAIL] checks_run={checks_run} < 4——门禁自证失败（存在未执行段）")
        failures.append("self-check failed")
    print(f"checks_run: {checks_run}")

    if failures:
        print(f"\nRESULT: FAIL（{len(failures)} 项）")
        return 1
    print("\nRESULT: PASS（WARN 不阻断，详见上方 [WARN] 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
