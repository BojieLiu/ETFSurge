#!/usr/bin/env python3
"""CI 审计脚本：禁止 async def 中包含直接同步阻塞调用。

扫描 backend/app/ 下所有 .py 文件，检查 async def 函数体内
是否包含已知的同步 I/O 调用（urllib.request.*, requests.*, ak.* 等），
这些调用必须通过 run_sync() / asyncio.to_thread() 包装。

用法:
    python scripts/audit_async_blocking.py
    返回 0 = 无违规; 返回 1 = 发现违规

集成到 pre-commit 门禁中，在 Python 文件变更时自动运行。
"""

import ast
import os
import sys

# ── 项目根目录 ──────────────────────────────────────────────────
_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "app")

# 已知的同步阻塞调用模式（点分格式）
# 这些函数在 async def 内直接调用会阻塞事件循环
_BLOCKING_PATTERNS = [
    "urllib.request.urlopen",
    "urllib.request.Request",
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
    "ak.",
    "akshare.",
    "yfinance.",
    "yf.",
    "pd.read_html",
    "pd.read_csv",
    "pd.read_excel",
    "run_in_thread",        # 同步等待，非线程池
]

# 允许的白名单模式（这些调用即使匹配也被视为安全）
_ALLOWED_PATTERNS = [
    # 已经通过 run_sync 或 asyncio.to_thread 包装的
]


def _extract_call_name(node: ast.Call) -> str:
    """提取函数调用名称，支持 foo.bar.baz 格式。"""
    parts = []
    n = node.func
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
    return '.'.join(reversed(parts))


def _is_in_await_context(tree: ast.AST, target_node: ast.AST) -> bool:
    """判断 target_node 是否被 await 表达式包裹。

    通过遍历 AST 时维护 in_await 标志栈实现。
    """
    class AwaitFinder(ast.NodeVisitor):
        def __init__(self):
            self.in_await = 0
            self.found = False

        def visit_Await(self, node):
            self.in_await += 1
            if node is target_node or node == target_node:
                self.found = True
            elif hasattr(node, 'value'):
                # 检查 await xxx 中 xxx 是否就是目标节点
                inner = node.value
                if inner is target_node or inner == target_node:
                    self.found = True
            self.generic_visit(node)
            self.in_await -= 1

        def generic_visit(self, node):
            if node is target_node and self.in_await > 0:
                self.found = True
            super().generic_visit(node)

    finder = AwaitFinder()
    finder.visit(tree)
    return finder.found


def _is_exempted_await(node: ast.Await, tree: ast.AST) -> bool:
    """检查 await 调用是否已经是安全的线程池包装。

    跳过 asyncio.wait_for(asyncio.to_thread(...)) 和 await run_sync() 模式。
    """
    call = node.value
    if not isinstance(call, ast.Call):
        return False

    # await run_sync(...) - 已经线程池包装
    if isinstance(call.func, ast.Name) and call.func.id == "run_sync":
        return True

    # await asyncio.wait_for(asyncio.to_thread(...), ...)
    if isinstance(call.func, ast.Attribute) and call.func.attr == "wait_for":
        for arg in call.args:
            if isinstance(arg, ast.Call):
                inner = arg.func
                if isinstance(inner, ast.Attribute) and inner.attr == "to_thread":
                    return True
    return False


def _is_inside_nested_def(node: ast.AST, func_node: ast.AsyncFunctionDef) -> bool:
    """判断 node 是否在 async def 内部嵌套的同步 def 中。"""
    for parent in ast.walk(func_node):
        if isinstance(parent, ast.FunctionDef) and not isinstance(parent, ast.AsyncFunctionDef):
            # 检查 node 是否在这个 nested def 的子树中
            for child in ast.walk(parent):
                if child is node:
                    return True
    return False


def scan_async_function(func_node: ast.AsyncFunctionDef, file_path: str) -> list[str]:
    """扫描单个 async def 函数，返回违规列表。
    
    只报告直接位于 async 函数体的同步调用，
    跳过嵌套同步 def 中的调用（它们应被外层 def 的扫描覆盖）。
    """
    violations = []

    for node in ast.walk(func_node):
        # 跳过嵌套在同步 def 中的节点
        if _is_inside_nested_def(node, func_node):
            continue

        # 检查直接同步调用（非 await 包裹）
        if isinstance(node, ast.Call):
            call_name = _extract_call_name(node)

            # 检查是否是阻塞模式
            is_blocking = any(
                call_name.startswith(p) or call_name == p.rstrip('.')
                for p in _BLOCKING_PATTERNS
            )
            if not is_blocking:
                continue

            # 检查是否被 await 包裹（await 包裹的是安全的）
            if _is_in_await_context(func_node, node):
                continue

            # 检查是否是白名单
            is_allowed = any(
                call_name.startswith(p) or call_name == p.rstrip('.')
                for p in _ALLOWED_PATTERNS
            )
            if is_allowed:
                continue

            rel = os.path.relpath(file_path, _APP_PATH)
            violations.append(
                f"{rel}:{node.lineno}: async def '{func_node.name}' "
                f"contains direct sync call '{call_name}'"
            )

    return violations


def scan_file(file_path: str) -> list[str]:
    """扫描单个 .py 文件，返回所有 async def 中的违规列表。"""
    violations: list[str] = []
    try:
        with open(file_path, encoding="utf-8-sig") as f:
            tree = ast.parse(f.read())
    except (SyntaxError, UnicodeDecodeError) as e:
        return [f"Skipping unparseable file {file_path}: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            violations.extend(scan_async_function(node, file_path))

    return violations


def main() -> int:
    """主函数。返回 0 = 无违规, 1 = 发现违规。"""
    all_violations: list[str] = []
    scanned = 0
    skipped = 0

    for root, dirs, files in os.walk(_APP_PATH):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            scanned += 1
            errs = scan_file(path)
            if any(e.startswith("Skipping") for e in errs):
                skipped += 1
            all_violations.extend(errs)

    if all_violations:
        print(f"[FAIL] Found {len(all_violations)} async-blocking violation(s):", file=sys.stderr)
        for v in all_violations:
            print(f"  ! {v}", file=sys.stderr)
        print(f"\nScanned {scanned} files ({skipped} skipped)", file=sys.stderr)
        return 1

    print(f"[PASS] No async-blocking violations found ({scanned} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
