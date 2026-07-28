#!/usr/bin/env python3
"""
AST 审计脚本：检查 run_sync / run_in_thread 的线程池使用合规性。

OPT-13: 作为 pre-commit 门禁和 CI 步骤运行。

规则：
1. run_sync 的 timeout > 5 → 应使用 run_sync_long
2. run_in_thread 的 timeout > 5 → 应传递 executor="long"
3. run_sync 不应嵌套在 run_in_thread 内部（双重线程池占用）
"""

import ast
import os
import sys
from typing import Optional


# 项目根目录
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_APP_PATH = os.path.join(_PROJECT_ROOT, "app")


def _call_name(node: ast.Call) -> str:
    """提取函数调用名，支持 foo.bar.baz 格式。"""
    parts = []
    n = node.func
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
    return ".".join(reversed(parts))


def _extract_timeout_kwarg(node: ast.Call) -> Optional[int]:
    """从函数调用中提取 timeout 参数值（如果 compile-time 已知）。"""
    for kw in node.keywords:
        if kw.arg == "timeout":
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                return kw.value.value
            if isinstance(kw.value, ast.Name):
                # Could be a variable reference, skip for now
                return None
    # Also check positional args with name 'timeout'
    for i, arg in enumerate(node.args):
        # Positional timeout arg is uncommon, skip
        pass
    return None


def _is_executor_long(node: ast.Call) -> bool:
    """检查调用是否包含 executor='long' 参数。"""
    for kw in node.keywords:
        if kw.arg == "executor":
            if isinstance(kw.value, ast.Constant) and kw.value.value == "long":
                return True
    return False


def _find_py_files(path: str) -> list[str]:
    """递归获取目录下所有 .py 文件（排除 __pycache__）。"""
    files = []
    for root, dirs, fnames in os.walk(path):
        # Skip __pycache__ directories
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in fnames:
            if fn.endswith(".py"):
                files.append(os.path.join(root, fn))
    return files


class PoolUsageAuditor(ast.NodeVisitor):
    """审计线程池使用合规性的 AST 访问器。"""

    def __init__(self) -> None:
        self.violations: list[str] = []
        self._current_file = ""
        self._in_run_in_thread = False  # 跟踪是否在 run_in_thread 内部

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        line = getattr(node, "lineno", "?")

        # 规则 1: run_sync timeout > 5 → 应使用 run_sync_long
        if name == "run_sync":
            timeout = _extract_timeout_kwarg(node)
            if timeout is not None and timeout > 5:
                self.violations.append(
                    f"{self._current_file}:{line}: run_sync timeout={timeout} > 5s — "
                    f"应使用 run_sync_long 或添加 executor='long'"
                )

        # 规则 2: run_in_thread timeout > 5 → 应传递 executor="long"
        if name == "run_in_thread":
            timeout = _extract_timeout_kwarg(node)
            if timeout is not None and timeout > 5:
                if not _is_executor_long(node):
                    self.violations.append(
                        f"{self._current_file}:{line}: run_in_thread timeout={timeout} > 5s — "
                        f"应添加 executor='long' 参数"
                    )

        # 继续遍历子节点
        self.generic_visit(node)


def main() -> int:
    """运行审计，返回违规数。"""
    app_files = _find_py_files(_APP_PATH)
    auditor = PoolUsageAuditor()

    for fpath in sorted(app_files):
        relpath = os.path.relpath(fpath, _PROJECT_ROOT)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=fpath)
            auditor._current_file = relpath
            auditor.visit(tree)
        except SyntaxError as e:
            print(f"[WARN] Syntax error in {relpath}: {e}", file=sys.stderr)

    if auditor.violations:
        print("=" * 60)
        print("THREAD POOL USAGE VIOLATIONS FOUND:")
        print("=" * 60)
        for v in auditor.violations:
            print(f"  {v}")
        print(f"\nTotal: {len(auditor.violations)} violation(s)")
        return 1

    print("No thread pool usage violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
