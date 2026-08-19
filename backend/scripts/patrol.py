#!/usr/bin/env python3
"""patrol.py — 巡检编排（docs/patrol-orchestration-plan.md 实施方案，2026-08-19）。

把分散的巡检资产（pytest / verify_e2e / data_health_check / verify_perf /
check_routes / check_engine_purity / audit_async_blocking / smoke_startup /
npm test+build）串成一条可重复执行的「巡检流水线」，并把人工从「测试员」降级为
「审查员」。

用法:
    python scripts/patrol.py                     # 全量巡检（默认）
    python scripts/patrol.py --diff              # 增量巡检（按工作区改动选层）
    python scripts/patrol.py --smoke             # 快速冒烟（L2-e2e --smoke + L2-health）
    python scripts/patrol.py --layer L1-unit,L2-e2e   # 显式指定层
    python scripts/patrol.py --diff --module news     # 覆盖 e2e 模块映射

退出码（§3）:
    0 全过（WARN 允许，perf 超阈值不阻断）
    1 任一硬门禁层失败
    2 被选定的依赖后端的必需层（L2-e2e / L3-perf）因后端未启动被 SKIP（巡检不完整）
    3 用法错误 / 环境不可用（非 git 仓库、node_modules 缺失等）

设计要点（反假完成）:
    - 分层编排，各层独立 subprocess，依赖不满足必须显式 SKIP 并计入报告（带 reason），
      绝不静默跳过冒充通过。
    - 性能超阈值仅 WARN（软门禁，verify_perf 既有语义）。
    - 报告物 logs/patrol/latest.json + 控制台摘要。
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime

# ── 路径常量 ──────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
DEFAULT_REPORT_DIR = os.path.join(REPO_ROOT, "logs", "patrol")

# ── 退出码（§3） ──────────────────────────────────────────────────
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_INCOMPLETE = 2
EXIT_USAGE = 3

# ── 层注册表（§2）: 层 → (超时秒, 是否依赖后端在线) ──────────────
LAYER_DEFAULTS = {
    "L1-unit": {"timeout": 1800, "backend_dependent": False},
    "L2-e2e": {"timeout": 900, "backend_dependent": True},
    "L2-health": {"timeout": 120, "backend_dependent": False},
    "L2-smoke": {"timeout": 120, "backend_dependent": False},
    "L3-perf": {"timeout": 120, "backend_dependent": True},
    "L4-routes": {"timeout": 60, "backend_dependent": False},
    "L4-purity": {"timeout": 60, "backend_dependent": False},
    "L4-async": {"timeout": 60, "backend_dependent": False},
    "L5-frontend": {"timeout": 600, "backend_dependent": False},
}

LAYER_ORDER = [
    "L1-unit", "L2-e2e", "L2-health", "L2-smoke", "L3-perf",
    "L4-routes", "L4-purity", "L4-async", "L5-frontend",
]

# --full 层集（§3: 不含 L2-smoke —— 后端在线时启动能力已被证明，且双实例
# 共享 SQLite 有写锁风险，§8-6）
FULL_LAYERS = [
    "L1-unit", "L2-e2e", "L2-health", "L3-perf",
    "L4-routes", "L4-purity", "L4-async", "L5-frontend",
]

# 依赖后端的必需层：后端离线时打 SKIP + 退出码 2（§3）
BACKEND_DEPENDENT_LAYERS = ("L2-e2e", "L3-perf")

# ── §4.3 e2e 子模块映射（模块级常量，新增 router/section 需同步维护） ──
# 值为 None 表示「全量」（不传 --module）。匹配按序，精确优先，兜底全量。
E2E_MODULE_MAP = [
    # 表 A：路由层（精确）
    ("backend/app/routers/market.py", ("market", "search", "sectors", "indicator-quality",
                                       "fundamentals", "db-integrity", "encoding", "hk-market",
                                       "us-market", "5xx", "round19-boundary", "quality")),
    ("backend/app/routers/portfolio.py", ("portfolio", "resilience", "task", "task-persistence",
                                          "design-quality", "diversity", "round19-boundary")),
    ("backend/app/routers/news.py", ("news", "5xx", "encoding")),
    ("backend/app/routers/analysis.py", ("analysis", "llm")),
    ("backend/app/routers/factors.py", ("factors", "factor-integrity", "factor-thresholds",
                                        "factor_ic", "zscore")),
    ("backend/app/routers/admin.py", ("admin", "circuit-breaker", "factor-integrity", "llm", "quality")),
    ("backend/app/routers/system.py", ("health",)),
    ("backend/app/routers/ws.py", ("ws", "nginx-proxy")),
    # 表 B：共享层（宽集/全量）
    ("backend/app/services/portfolio_service.py", ("portfolio", "resilience", "task",
                                                   "task-persistence", "design-quality",
                                                   "diversity", "round19-boundary")),
    ("backend/app/services/portfolio/*", ("portfolio", "resilience", "task", "task-persistence",
                                          "design-quality", "diversity", "round19-boundary")),
    ("backend/app/services/strategy_design.py", ("portfolio", "design-quality", "diversity",
                                                 "task", "task-persistence", "resilience")),
    ("backend/app/services/llm_context.py", ("analysis", "llm")),
    ("backend/app/services/market_service.py", None),
    ("backend/app/services/market_data_hub.py", None),
    ("backend/app/services/hub/*", None),
    ("backend/app/fetchers/*", None),
    ("backend/app/factors/*", None),
    ("backend/app/engine/*", None),
    ("backend/app/tasks/*", None),
    ("backend/app/core/*", None),
    # 兜底：其它 backend/app/**（未知路径）→ 全量，防映射滞后漏测
    ("backend/app/*", None),
]


# ══════════════════════════════════════════════════════════════════
# 纯函数（无 I/O，可单测）
# ══════════════════════════════════════════════════════════════════

def classify_changes(changed_files):
    """按 §4.2 档位规则归类改动路径，返回 tiers/logic_files/test_files/frontend。

    tiers 取值: 0(conftest/fixtures) / 1(app+scripts+requirements 逻辑变更) /
    1e(engine+纯度门禁) / 1r(契约+路由) / 2(仅测试 .py) / 3(前端源码)。
    纯文档/未知非代码文件 → tiers 为空（档 4，不触发任何层）。
    """
    tiers = set()
    logic_files = []
    test_files = []
    frontend = False

    for raw in changed_files:
        f = raw.replace("\\", "/")
        if f in ("backend/tests/conftest.py", "backend/tests/db_fixtures.py"):
            tiers.add(0)

        is_logic = (
            fnmatch.fnmatch(f, "backend/app/*")
            or fnmatch.fnmatch(f, "backend/scripts/*.py")
            or f == "backend/requirements.txt"
        )
        # 保守兜底：backend 根级非测试文件（pytest.ini / Dockerfile / *.py 等）
        # 影响测试或运行行为 → 按档 1 全量（对齐 pre-commit OTHER_BACKEND 语义）。
        is_backend_other = (
            fnmatch.fnmatch(f, "backend/*")
            and not fnmatch.fnmatch(f, "backend/tests/*")
            and not is_logic
        )
        if is_logic or is_backend_other:
            tiers.add(1)
            logic_files.append(f)

        if fnmatch.fnmatch(f, "backend/app/engine/*") or f == "backend/scripts/check_engine_purity.py":
            tiers.add("1e")
        if fnmatch.fnmatch(f, "api-contracts/*") or fnmatch.fnmatch(f, "backend/app/routers/*.py"):
            tiers.add("1r")
        if fnmatch.fnmatch(f, "backend/tests/*.py"):
            test_files.append(f)
        if (fnmatch.fnmatch(f, "frontend/src/*")
                or f in ("frontend/index.html", "frontend/vite.config.js", "frontend/package.json")):
            tiers.add(3)
            frontend = True

    # 档 2：仅测试 .py 变更（无档 0/1 命中）→ 只跑变更测试文件
    if test_files and 0 not in tiers and 1 not in tiers:
        tiers.add(2)

    return {
        "tiers": tiers,
        "logic_files": logic_files,
        "test_files": test_files,
        "frontend": frontend,
    }


def select_e2e_modules(logic_files, explicit_modules=None):
    """按 §4.3 映射选取 e2e 模块集。返回 None 表示全量（不传 --module）。

    explicit_modules 显式优先于映射（§3 --module）。未知路径兜底全量（宁可多跑不漏测）。
    """
    if explicit_modules:
        return list(explicit_modules)

    modules = set()
    for f in logic_files:
        f = f.replace("\\", "/")
        matched = False
        for pattern, mods in E2E_MODULE_MAP:
            if fnmatch.fnmatch(f, pattern):
                matched = True
                if mods is None:
                    return None  # 全量
                modules.update(mods)
                break
        if not matched:
            # scripts/*.py / requirements.txt 等不在表 A/B → 保守全量
            return None
    if not modules:
        return None
    return sorted(modules)


def plan_layers(mode, changed_files, explicit_layers=None, explicit_modules=None):
    """根据模式 + 改动档位（+ 显式覆盖）计算要执行的层集与 e2e 参数。"""
    tiers = set()
    e2e_modules = None
    e2e_smoke = (mode == "smoke")
    pytest_subset = None

    if explicit_layers:
        selected = {l for l in explicit_layers if l in LAYER_DEFAULTS}
        layers = [l for l in LAYER_ORDER if l in selected]
    elif mode == "full":
        layers = list(FULL_LAYERS)
    elif mode == "smoke":
        layers = ["L2-e2e", "L2-health"]
    elif mode == "diff":
        c = classify_changes(changed_files)
        tiers = c["tiers"]
        layers = []
        if 0 in tiers or 1 in tiers:
            layers += ["L1-unit", "L2-e2e", "L2-health"]
        if 1 in tiers:
            layers += ["L3-perf", "L2-smoke", "L4-async"]
        if "1e" in tiers:
            layers.append("L4-purity")
        if "1r" in tiers:
            layers.append("L4-routes")
        if 2 in tiers:
            layers.append("L1-unit")
            pytest_subset = [t.replace("backend/", "", 1) for t in c["test_files"]]
        if 3 in tiers:
            layers.append("L5-frontend")

        if 0 in tiers:
            e2e_modules = None  # 档 0 → e2e 全量
        elif 1 in tiers:
            e2e_modules = select_e2e_modules(c["logic_files"])
        layers = list(dict.fromkeys(layers))  # 去重保序
    else:
        layers = list(FULL_LAYERS)

    # --module 显式覆盖映射（仅 L2-e2e 层生效）
    if explicit_modules:
        e2e_modules = list(explicit_modules)

    return {
        "layers": layers,
        "pytest_subset": pytest_subset,
        "e2e_modules": e2e_modules,
        "e2e_smoke": e2e_smoke,
        "tiers": tiers,
    }


def backend_layer_skip_reason(name, online):
    """依赖后端的必需层在后端离线时的 SKIP reason（§4.4，防误报硬失败）。"""
    if name in BACKEND_DEPENDENT_LAYERS and not online:
        return "backend offline (L2/L3 require a running backend; use --start-backend or restart.bat)"
    return None


def compute_exit_code(layer_results, required_backend_skipped):
    """退出码聚合（§3）：FAIL(1) > 必需层 SKIP(2) > 全过(0)。"""
    if any(r.get("status") == "FAIL" for r in layer_results.values()):
        return EXIT_FAIL
    if required_backend_skipped:
        return EXIT_INCOMPLETE
    return EXIT_OK


def build_report(mode, duration_s, exit_code, layer_results, timestamp):
    """§5 报告结构：timestamp/mode/duration_s/exit_code/layers（四级状态）。"""
    return {
        "timestamp": timestamp,
        "mode": mode,
        "duration_s": round(duration_s, 2),
        "exit_code": exit_code,
        "layers": {name: _clean_layer(layer_results[name])
                   for name in LAYER_ORDER if name in layer_results},
    }


def _clean_layer(result):
    """剥掉内部 _output 字段，保留报告字段。"""
    return {k: v for k, v in result.items() if not k.startswith("_")}


def _classify(name, returncode, out, err):
    """层状态分类：默认 exit 0=PASS / 非 0=FAIL；L3-perf 特殊（WARN 软门禁）。"""
    if name == "L3-perf":
        if returncode != 0:
            return "FAIL"
        if "[WARN]" in out:
            return "WARN"
        return "PASS"
    return "PASS" if returncode == 0 else "FAIL"


# ══════════════════════════════════════════════════════════════════
# 环境探测 / 进程执行（有 I/O，单测中 mock）
# ══════════════════════════════════════════════════════════════════

def _has_xdist():
    return importlib.util.find_spec("xdist") is not None


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run(cmd, cwd, env=None, timeout=None):
    """执行单个子进程，返回 (returncode, stdout, stderr, timed_out)。

    Windows 下子进程 stdout 为管道时默认用 ANSI 代码页（cp936）写中文，会导致
    UTF-8 解码成乱码（污染报告 detail 字段）。强制 PYTHONUTF8=1 让子进程 Python
    以 UTF-8 输出，与 patrol 的 encoding="utf-8" 解码对齐。
    """
    merged = dict(os.environ)
    merged.setdefault("PYTHONUTF8", "1")
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=merged,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return proc.returncode, proc.stdout or "", proc.stderr or "", False
    except subprocess.TimeoutExpired:
        return None, "", f"timeout after {timeout}s", True


def _git(args):
    proc = subprocess.run(
        ["git"] + args, cwd=REPO_ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.stdout or ""


def get_changed_files():
    """§4.1 改动来源：git diff HEAD（含 staged+unstaged）+ 未跟踪文件并集。"""
    files = set()
    for line in _git(["diff", "--name-only", "HEAD"]).splitlines():
        if line.strip():
            files.add(line.strip())
    for line in _git(["ls-files", "--others", "--exclude-standard"]).splitlines():
        if line.strip():
            files.add(line.strip())
    return sorted(files)


def is_git_repo():
    return _git(["rev-parse", "--is-inside-work-tree"]).strip() == "true"


def backend_online(host, port, timeout=2.0):
    """§4.4 后端在线探测（对齐 pre-commit perf 段 socket.create_connection）。"""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _start_backend(port, log_path):
    """§4.4 --start-backend：直接起 uvicorn（非 start.ps1，避免连带前端 vite）。

    复用 start.ps1:37 命令模板（--host ::），stdout 重定向到日志文件。
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "::", "--port", str(port)],
            cwd=BACKEND_DIR, stdout=fh, stderr=subprocess.STDOUT,
        )
    return proc


def _poll_health(host, port, timeout_s=90):
    """轮询 /health 直至 200（对齐 start.ps1 90s 健康检查窗口）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if backend_online(host, port):
            return True
        time.sleep(1)
    return backend_online(host, port)


def _build_command(name, plan, args):
    """构造层执行命令，返回 (cmd, cwd, env)。"""
    host = args.backend_host
    port = args.backend_port

    if name == "L1-unit":
        cmd = [sys.executable, "-m", "pytest", "-x"]
        if _has_xdist():
            # round30 修复1: `-n auto` 作为单 token 传给 argparse 会被解析为值
            # `' auto'`（前导空格）→ "invalid parse_numprocesses value: ' auto'"。
            # 必须拆成两个独立 arg（-n 与 auto）。
            # round30 修复2: `-n auto` 按 cpu_count（本机 20 核）启动 20 个 worker，
            # Windows 资源/句柄上限 → execnet gateway bootstrap EOFError（INTERNALERROR）。
            # 封顶默认 4（env PYTEST_XDIST_WORKERS 可调），仍享并行加速。
            _workers = os.environ.get("PYTEST_XDIST_WORKERS", "4")
            cmd += ["-n", _workers]
        if plan["pytest_subset"]:
            cmd.extend(plan["pytest_subset"])
        return cmd, BACKEND_DIR, {}

    if name == "L2-e2e":
        cmd = [sys.executable, "scripts/verify_e2e.py", "--host", host, "--port", str(port)]
        if plan["e2e_smoke"]:
            cmd.append("--smoke")
        elif plan["e2e_modules"]:
            cmd += ["--module", ",".join(plan["e2e_modules"])]
        return cmd, BACKEND_DIR, {}

    if name == "L2-health":
        return [sys.executable, "scripts/data_health_check.py"], BACKEND_DIR, {}
    if name == "L2-smoke":
        return [sys.executable, "scripts/smoke_startup.py"], BACKEND_DIR, {"SMOKE_FAST": "1"}
    if name == "L3-perf":
        return [sys.executable, "scripts/verify_perf.py", "--base", f"http://{host}:{port}"], BACKEND_DIR, {}
    if name == "L4-routes":
        return [sys.executable, "scripts/check_routes.py"], BACKEND_DIR, {}
    if name == "L4-purity":
        return [sys.executable, "scripts/check_engine_purity.py"], BACKEND_DIR, {}
    if name == "L4-async":
        return [sys.executable, "scripts/audit_async_blocking.py"], BACKEND_DIR, {}

    raise ValueError(f"no command builder for layer {name}")


def _layer_timeout(name, args):
    return args.timeout if args.timeout is not None else LAYER_DEFAULTS[name]["timeout"]


def _detail_for(name, out, err):
    """失败/警示详情：优先错误输出尾部，其次 stdout 尾部。"""
    text = (err or "").strip()
    if not text:
        text = (out or "").strip()
    lines = text.splitlines()
    return "\n".join(lines[-8:]) if lines else ""


def _extra_fields(name, out):
    """层特定报告字段（best-effort，解析不到则省略）。"""
    if name == "L1-unit":
        m = re.search(r"(\d+) passed", out)
        d = {}
        if m:
            d["passed"] = int(m.group(1))
        mf = re.search(r"(\d+) failed", out)
        d["failed"] = int(mf.group(1)) if mf else 0
        return d
    if name == "L2-e2e":
        m = re.search(r"结果:\s*(\d+)/(\d+)\s*通过", out)
        if m:
            passed, total = int(m.group(1)), int(m.group(2))
            return {"checks_total": total, "checks_failed": total - passed}
        return {}
    if name == "L2-health":
        m = re.search(r"PASS:\s*(\d+)/(\d+)", out)
        if m:
            passed, total = int(m.group(1)), int(m.group(2))
            return {"checks_total": total, "checks_failed": total - passed}
        return {}
    if name == "L3-perf":
        warnings = [ln.strip() for ln in out.splitlines() if "[WARN]" in ln]
        return {"warnings": warnings} if warnings else {}
    return {}


def run_layer(name, plan, args, online):
    """执行单个层，返回结果 dict（status + duration_s + detail/reason + 层字段）。"""
    t0 = time.monotonic()
    reason = backend_layer_skip_reason(name, online)
    if reason:
        return {"status": "SKIP", "reason": reason, "duration_s": 0.0, "detail": ""}

    if name == "L5-frontend":
        return _run_frontend(args, t0)

    cmd, cwd, env = _build_command(name, plan, args)
    timeout = _layer_timeout(name, args)
    rc, out, err, timed_out = _run(cmd, cwd, env, timeout)
    dur = round(time.monotonic() - t0, 2)

    status = "FAIL" if timed_out else _classify(name, rc, out, err)
    res = {"status": status, "duration_s": dur, "detail": _detail_for(name, out, err)}
    res.update(_extra_fields(name, out))
    res["_output"] = out + "\n" + err

    # round30 方案 B：L1-unit 全量通过 → 写全量测试凭据，供 pre-commit 复用
    # （消除「验收全量 + patrol L1 + pre-commit 全量」三重重复）。仅在全量
    # （无 pytest_subset）时写；子集/失败不写。
    if (name == "L1-unit" and status == "PASS"
            and not plan.get("pytest_subset")):
        try:
            import subprocess as _sp
            _sp.run(
                [sys.executable, os.path.join(os.path.dirname(__file__), "tests_ok_marker.py"), "--mark"],
                cwd=BACKEND_DIR, timeout=30,
            )
        except Exception as _me:  # noqa: BLE001 — 凭据写失败不阻断巡检
            print(f"[patrol] ⚠️ 全量测试凭据写失败（非阻断）: {_me}")
    return res


def _run_frontend(args, t0):
    """L5：npm test +（可选）npm run build。任一失败 → FAIL。"""
    skip_build = args.no_frontend_build or os.environ.get("SKIP_FRONTEND_BUILD") == "1"
    if os.name == "nt":
        runner = ["cmd", "/c"]
    else:
        runner = ["sh", "-c"]

    timeout = _layer_timeout("L5-frontend", args)

    rc, out, err, timed_out = _run(runner + ["npm test"], FRONTEND_DIR, timeout=timeout)
    if timed_out or rc != 0:
        dur = round(time.monotonic() - t0, 2)
        return {"status": "FAIL", "duration_s": dur,
                "detail": _detail_for("L5-frontend", out, err),
                "_output": out + "\n" + err}

    if not skip_build:
        rc2, out2, err2, timed_out2 = _run(runner + ["npm run build"], FRONTEND_DIR, timeout=timeout)
        if timed_out2 or rc2 != 0:
            dur = round(time.monotonic() - t0, 2)
            return {"status": "FAIL", "duration_s": dur,
                    "detail": _detail_for("L5-frontend", out2, err2),
                    "_output": out2 + "\n" + err2}

    dur = round(time.monotonic() - t0, 2)
    return {"status": "PASS", "duration_s": dur,
            "detail": "npm test" + ("" if skip_build else " + npm run build"),
            "_output": out}


def precheck(args, plan):
    """环境预检，返回错误消息（None 表示通过）→ 否则退出码 3（§3）。"""
    if args.mode == "diff" and not is_git_repo():
        return "not a git repository (--diff requires git diff HEAD)"
    if "L5-frontend" in plan["layers"]:
        if not os.path.isdir(os.path.join(FRONTEND_DIR, "node_modules")):
            return "frontend/node_modules missing — run `cd frontend && npm install`"
    return None


def write_report(report, report_dir):
    """§5 报告物：logs/patrol/latest.json（每次运行覆盖）。"""
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, "latest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return path


_STATUS_ICON = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "WARN": "[WARN]"}


def print_summary(report, verbose):
    """控制台摘要 + 失败详情（-v 打全量输出）。"""
    print(f"\npatrol [{report['mode']}] {report['timestamp']} "
          f"— exit {report['exit_code']} ({report['duration_s']}s)")
    for name in LAYER_ORDER:
        if name not in report["layers"]:
            continue
        r = report["layers"][name]
        icon = _STATUS_ICON.get(r["status"], "?")
        line = f"  {icon} {name}: {r['status']}"
        if r["status"] == "SKIP" and r.get("reason"):
            line += f" — {r['reason']}"
        if r.get("detail") and r["status"] in ("FAIL", "WARN"):
            detail = r["detail"].replace("\n", " | ")[:240]
            line += f" — {detail}"
        print(line)
        if verbose and r.get("_output"):
            print(r["_output"])
    print()


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="patrol — 多资产 ETF 组合巡检编排（L1 单测/L2 探活/L3 性能/L4 静态/L5 前端）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", dest="mode", action="store_const", const="full",
                      help="全量巡检（默认）")
    mode.add_argument("--diff", dest="mode", action="store_const", const="diff",
                      help="增量巡检（按工作区改动选层）")
    mode.add_argument("--smoke", dest="mode", action="store_const", const="smoke",
                      help="快速冒烟（L2-e2e --smoke + L2-health）")

    parser.add_argument("--layer", default=None,
                        help="显式指定层（逗号分隔，覆盖模式默认层集）")
    parser.add_argument("--module", default=None,
                        help="覆盖 e2e 模块映射（逗号分隔，仅 L2-e2e 层生效）")
    parser.add_argument("--backend-host", default="localhost")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--timeout", type=int, default=None,
                        help="单层 subprocess 超时秒（默认各层独立值）")
    parser.add_argument("--report-dir", default=None)
    parser.add_argument("--no-frontend-build", action="store_true",
                        help="增量模式跳过 npm run build（只跑 npm test）")
    parser.add_argument("--start-backend", action="store_true",
                        help="后端不在线时尝试直接拉起 uvicorn")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="打印各层完整输出")

    args = parser.parse_args(argv)
    if args.mode is None:
        args.mode = "full"
    args.explicit_layers = None
    if args.layer:
        args.explicit_layers = [l.strip() for l in args.layer.split(",") if l.strip()]
    args.explicit_modules = None
    if args.module:
        args.explicit_modules = [m.strip() for m in args.module.split(",") if m.strip()]
    if args.report_dir is None:
        args.report_dir = DEFAULT_REPORT_DIR
    elif not os.path.isabs(args.report_dir):
        args.report_dir = os.path.join(REPO_ROOT, args.report_dir)
    return args


def run_patrol(args):
    start = time.monotonic()

    changed_files = get_changed_files() if args.mode == "diff" else []
    plan = plan_layers(args.mode, changed_files, args.explicit_layers, args.explicit_modules)

    # 环境预检 → 退出码 3
    err = precheck(args, plan)
    if err:
        print(f"[patrol] usage error: {err}")
        return EXIT_USAGE

    if not plan["layers"]:
        print("[patrol] 纯文档/无代码改动，无巡检层触发（档 4）")
        return EXIT_OK

    # 后端在线探测 + 可选拉起（§4.4）
    online = True
    if any(l in BACKEND_DEPENDENT_LAYERS for l in plan["layers"]):
        online = backend_online(args.backend_host, args.backend_port)
        if not online and args.start_backend:
            print(f"[patrol] 后端离线，尝试拉起 uvicorn(:{args.backend_port}) ...")
            log_path = os.path.join(REPO_ROOT, "logs", "backend_stdout.log")
            _start_backend(args.backend_port, log_path)
            online = _poll_health(args.backend_host, args.backend_port)
            if not online:
                print("[patrol] 后端拉起失败或超时（90s）——依赖层将 SKIP")

    # 逐层执行
    results = {}
    required_backend_skipped = False
    for name in plan["layers"]:
        res = run_layer(name, plan, args, online)
        results[name] = res
        if res["status"] == "SKIP" and name in BACKEND_DEPENDENT_LAYERS:
            required_backend_skipped = True

    # 未选中层标 SKIP（§5 示例：L5 在 --diff 无前端变更时显式 SKIP）
    for name in LAYER_ORDER:
        if name not in results:
            results[name] = {"status": "SKIP",
                             "reason": "not in scope for this mode/tier",
                             "duration_s": 0.0, "detail": ""}

    exit_code = compute_exit_code(results, required_backend_skipped)
    duration = time.monotonic() - start
    report = build_report(args.mode, duration, exit_code, results, _now_iso())

    path = write_report(report, args.report_dir)
    print_summary(report, args.verbose)
    print(f"报告: {path}")

    return exit_code


def main(argv=None):
    # Windows 下 stdout 重定向到管道时默认 cp936，中文摘要会乱码；强制 UTF-8 输出
    # （真实控制台 PEP 528 已走 UTF-8，此 reconfigure 无副作用）。
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    args = _parse_args(argv)
    return run_patrol(args)


if __name__ == "__main__":
    raise SystemExit(main())
