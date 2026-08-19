#!/usr/bin/env python3
"""全量测试通过凭据（round30 方案 B）——消除「验收全量 + patrol L1 + pre-commit 全量」三重重复。

背景：一个实施轮里同一套代码会被跑 2-3 次全量 pytest（手动验收、patrol L1-unit、
pre-commit 档 1 逻辑变更门禁），互相不知道「刚跑过且通过」。

机制：
- `--mark`：patrol.py L1-unit 全量通过后调用，写入 `logs/patrol/tests_ok.json`，
  记录 head_sha + files_hash（backend/app+tests+scripts 全部相关文件的
  path:mtime:size 指纹）+ ts。
- `--check`：pre-commit 在检测到逻辑变更、准备跑全量前调用。凭据有效
  （指纹一致 + HEAD 一致 + 未过期）→ 退出 0，pre-commit 跳过重复全量、只跑受影响测试；
  否则退出 1 → pre-commit 维持全量（安全网不失效）。

安全性：任何 backend 代码/测试/脚本/依赖/配置变更都会改变 files_hash → 凭据失效
→ 恢复全量。绝不出现「改了代码却跳过全量」的漏网。有效期 TTL 60min 兜底环境漂移。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

# backend/ 目录（本脚本位于 backend/scripts/ 下）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 凭据落盘到仓库级 logs/patrol/（gitignored，不污染工作树）
MARKER_PATH = os.path.join(os.path.dirname(PROJECT_ROOT), "logs", "patrol", "tests_ok.json")

# 指纹覆盖范围：与 pre-commit 档 0/1 判定一致的 backend 代码面
HASH_ROOTS = [
    os.path.join(PROJECT_ROOT, "app"),
    os.path.join(PROJECT_ROOT, "tests"),
    os.path.join(PROJECT_ROOT, "scripts"),
]
EXTRA_FILES = [
    os.path.join(PROJECT_ROOT, "requirements.txt"),
    os.path.join(PROJECT_ROOT, "pytest.ini"),
    os.path.join(PROJECT_ROOT, "conftest.py"),
]
# 凭据有效期：代码未变则结果长期有效；TTL 兜底环境漂移（数据源/DB 变化/测试 flaky）
TTL_SECONDS = 60 * 60

_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}


def files_hash(project_root: str = PROJECT_ROOT, roots: list[str] | None = None,
               extra: list[str] | None = None) -> str:
    """backend 代码面指纹：path:mtime_ns:size 排序拼接后 md5。

    任何文件新增/删除/内容变化都会改变指纹（mtime_ns 捕获重写，size 兜底）。
    """
    h = hashlib.md5()
    paths = list(extra if extra is not None else EXTRA_FILES)
    for root in (roots if roots is not None else HASH_ROOTS):
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in sorted(filenames):
                if fn.endswith((".pyc", ".pyo")):
                    continue
                paths.append(os.path.join(dirpath, fn))
    for p in sorted(paths):
        if not os.path.isfile(p):
            continue
        st = os.stat(p)
        rel = os.path.relpath(p, project_root).replace("\\", "/")
        h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode("utf-8"))
    return h.hexdigest()


def current_head(project_root: str = PROJECT_ROOT) -> str:
    """当前 git HEAD sha（无 git 环境 → 空串，check 时跳过 HEAD 校验）。"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=project_root, timeout=10,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def mark(marker_path: str = MARKER_PATH, project_root: str = PROJECT_ROOT,
         roots: list[str] | None = None, extra: list[str] | None = None) -> None:
    """写凭据：当前代码面 + HEAD + 时间戳。

    project_root/roots/extra 可参数化（单测用临时项目树验证指纹敏感性）；
    默认指向真实 backend 项目（pre-commit/patrol 调用路径）。
    """
    data = {
        "head_sha": current_head(project_root),
        "files_hash": files_hash(project_root, roots, extra),
        "ts": time.time(),
    }
    os.makedirs(os.path.dirname(marker_path), exist_ok=True)
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"[tests_ok] 凭据已写入 {marker_path}（files_hash={str(data['files_hash'])[:12]}）")


def check(marker_path: str = MARKER_PATH, ttl: float = TTL_SECONDS,
          project_root: str = PROJECT_ROOT, roots: list[str] | None = None,
          extra: list[str] | None = None) -> bool:
    """凭据是否可复用：存在 + 指纹一致 + HEAD 一致 + 未过期。

    project_root/roots/extra 参数化语义同 mark（单测用临时项目树验证）。
    """
    if not os.path.isfile(marker_path):
        print("[tests_ok] 无全量测试凭据，需跑全量", file=sys.stderr)
        return False
    try:
        with open(marker_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        print("[tests_ok] 凭据损坏，需跑全量", file=sys.stderr)
        return False
    cur = files_hash(project_root, roots, extra)
    if data.get("files_hash") != cur:
        print("[tests_ok] 代码已变更（指纹不匹配），需跑全量", file=sys.stderr)
        return False
    head = current_head(project_root)
    if head and data.get("head_sha") and data.get("head_sha") != head:
        print("[tests_ok] HEAD 已变化，需跑全量", file=sys.stderr)
        return False
    age = time.time() - float(data.get("ts", 0))
    if age > ttl:
        print(f"[tests_ok] 凭据过期（>{ttl/60:.0f}min），需跑全量", file=sys.stderr)
        return False
    print(f"[tests_ok] 凭据有效（{age:.0f}s 前全量通过，指纹一致）→ 可复用", file=sys.stderr)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="全量测试通过凭据 mark/check（round30 方案 B）")
    # 兼容两种调用形态：位置参数 `mark|check` 与 `--mark|--check` flag
    ap.add_argument("action", nargs="?", choices=("mark", "check"),
                    help="mark=写入凭据；check=校验可复用")
    ap.add_argument("--mark", action="store_true", help="写入凭据")
    ap.add_argument("--check", action="store_true", help="校验可复用（0=有效，1=需全量）")
    args = ap.parse_args()
    if args.mark or args.action == "mark":
        mark()
        return 0
    if args.check or args.action == "check":
        return 0 if check() else 1
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
