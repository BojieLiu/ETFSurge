#!/usr/bin/env python
"""check_engine_purity.py — round23 §10.5 A2: engine 层纯度硬约束。

AGENTS.md 把 engine 标为「无 I/O 纯函数」，但此前仅文档声明、无门禁守护
（实测泄漏 1 处：allocation_engine.py:379 循环内 import factor_registry 读私有全局态）。

本门禁（pre-commit 第 14 段，差异化 = 分层边界守护，与 check_routes/audit_unused_symbols/
check_unused_styles 对象正交）：
1. AST 扫描 `app/engine/**/*.py`，禁止 import app.services / app.fetchers / app.tasks /
   app.analysis / app.routers（下层不得依赖上层）。
2. 禁止 open() / urllib / requests / sqlite3 / aiohttp / httpx 等 I/O 调用（engine 无 IO）。

纯 AST 静态检查，零网络/DB/文件副作用；违例打印 file:line + exit 1。
"""
from __future__ import annotations

import ast
import pathlib
import sys

ENGINE_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "engine"

# 下层不得依赖的上层包（engine 只能依赖 core/自身/第三方纯库）
# A1 参数化后 engine 不再需要 app.factors（factor_registry 私有态）——一并禁止防复发
FORBIDDEN_PACKAGES = (
    "app.services",
    "app.fetchers",
    "app.tasks",
    "app.analysis",
    "app.routers",
    "app.factors",
)

# engine 内禁止的 I/O 调用
FORBIDDEN_IO = (
    "open(",
    "urllib",
    "requests.",
    "aiohttp",
    "httpx",
    "sqlite3",
    "socket.",
)


def _iter_imports(tree: ast.AST):
    """yield (module, level)：level=0 绝对导入；level=n 相对导入点数（round35 B1-F1a）。

    旧实现丢弃 level——`from ..analysis.signal import X` 的 node.module 是
    "analysis.signal"（无 app. 前缀），前缀匹配永不命中 → rationale.py:238 的
    上层依赖绕过了本门禁（D1 门禁级缺陷）。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield (node.module or ""), (node.level or 0)


def _resolve(module: str, level: int, pkg_parts: list[str]) -> str:
    """相对导入 → 绝对模块路径（round35 B1-F1a）。

    level=0 → 原样；level=n → 按文件所属包上跳 n-1 层拼接。
    例：app/engine/rationale.py（pkg_parts=["app", "engine"]）
      · from .budgets import X        (level=1) → app.engine.budgets   ✓合法
      · from ..analysis.signal import X (level=2) → app.analysis.signal → 命中禁入
    """
    if level <= 0:
        return module
    base = pkg_parts[: len(pkg_parts) - (level - 1)]
    if not base:
        return module  # 超出顶层包（engine 一级包结构不会出现），保守放行
    return ".".join(base + ([module] if module else []))


def check_file(path: pathlib.Path) -> list[str]:
    violations: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return [f"{path}: SyntaxError {e}"]
    src_lines = path.read_text(encoding="utf-8").splitlines()

    # 文件所属包：["app"] + 相对 app/ 的父目录链（engine 平包 → ["app", "engine"]）
    rel = path.relative_to(ENGINE_DIR.parent)
    pkg_parts = ["app"] + list(rel.parent.parts)

    for name, level in _iter_imports(tree):
        resolved = _resolve(name, level, pkg_parts)
        # engine 内部 import（app.engine.xxx）允许；外部上层包禁止
        if resolved == "app.engine" or resolved.startswith("app.engine."):
            continue
        for pkg in FORBIDDEN_PACKAGES:
            if resolved == pkg or resolved.startswith(pkg + "."):
                violations.append(
                    f"{path}: import 上层包 {resolved}"
                    + (f"（相对导入 level={level}）" if level else "")
                    + "（engine 不得依赖 services/fetchers/tasks/analysis/routers）"
                )
                break

    # I/O 调用检测（AST Call func 名 / Attribute 访问）
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "open":
                lineno = getattr(node, "lineno", 0)
                violations.append(f"{path}:{lineno}: engine 内禁止 open() I/O")
            elif isinstance(fn, ast.Attribute):
                attr = fn.attr
                parent = fn.value
                full = ""
                if isinstance(parent, ast.Name):
                    full = parent.id + "." + attr
                elif isinstance(parent, ast.Attribute):
                    full = parent.attr + "." + attr
                if any(io_key in full or io_key in attr for io_key in
                       ("urllib", "requests", "aiohttp", "httpx", "sqlite3", "socket")):
                    lineno = getattr(node, "lineno", 0)
                    violations.append(f"{path}:{lineno}: engine 内禁止 I/O 调用 {full or attr}")
    return violations


def main() -> int:
    files = sorted(ENGINE_DIR.rglob("*.py"))
    if not files:
        print(f"check_engine_purity: engine 目录不存在或为空: {ENGINE_DIR}")
        return 1
    all_violations: list[str] = []
    for f in files:
        all_violations.extend(check_file(f))
    if all_violations:
        print("check_engine_purity: FAIL — engine 层纯度违规:")
        for v in all_violations:
            print(f"  {v}")
        print("engine 必须为纯函数层：无上层依赖、无 I/O（参数化注入替代全局态）。")
        return 1
    print(f"check_engine_purity: OK — engine 层 {len(files)} 文件纯净（无上层 import / 无 I/O）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
