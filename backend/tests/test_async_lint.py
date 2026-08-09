"""
AST static analysis: detect direct await of known synchronous functions.

This scanner walks all .py files under backend/app/ and flags any
``await sync_function(...)`` pattern where the awaited function is known
to be synchronous (from the project's blacklist).

A correct async boundary wraps the sync call with
``asyncio.to_thread(...)`` or ``run_sync(...)``.

Phase 4 of async-boundary-fix-plan.md — test defence enhancement.
"""

import ast
import os
import sys

import pytest

# ── Project root for app/ source ──────────────────────────────────────
_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "app")

# Known synchronous function name patterns that MUST NOT be awaited
# directly on the event-loop thread.
_SYNC_PATTERNS = [
    "fetch_history",
    "fetch_a_stock_batch",
    "_sina_",
    "_tencent_",
    "run_in_thread",
    "requests.",
    "urllib.",
]

# Phase 2.8 G1: 直接同步调用黑名单（无 await 包裹），
# 这些调用出现在 async def 中且没有被 await 包裹即为违规。
_SYNC_PATTERNS_DIRECT = [
    "urllib.request.urlopen",
    "urllib.request.Request",
    "requests.get",
    "requests.post",
    "pd.read_html",
    "pd.read_csv",
    "yfinance.",
    "yf.",
]


def _is_exempted(node: ast.Await) -> bool:
    """Skip 'await asyncio.wait_for(asyncio.to_thread(...), ...)' patterns.

    These are already correctly wrapped and need no flagging.
    """
    call = node.value
    if not isinstance(call, ast.Call):
        return False
    # Match `await run_sync(...)` — already thread-pool bound
    if isinstance(call.func, ast.Name) and call.func.id == "run_sync":
        return True
    # Match asyncio.wait_for(asyncio.to_thread(...), ...)
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "wait_for":
        for arg in call.args:
            if isinstance(arg, ast.Call):
                inner = arg.func
                if isinstance(inner, ast.Attribute) and inner.attr == "to_thread":
                    return True
        # Also match wait_for(run_sync(...), ...) — already thread-pool bound
        for arg in call.args:
            if isinstance(arg, ast.Call):
                inner = arg.func
                if isinstance(inner, ast.Name) and inner.id == "run_sync":
                    return True
    return False


def _is_sync_call(node: ast.Await) -> bool:
    """Check whether the awaited call is a known synchronous function."""
    if _is_exempted(node):
        return False
    if isinstance(node.value, ast.Call):
        func = node.value.func
        if isinstance(func, ast.Name):
            return any(p in func.id for p in _SYNC_PATTERNS)
        if isinstance(func, ast.Attribute):
            return any(p in func.attr for p in _SYNC_PATTERNS)
    return False


def _scan_file(path: str) -> tuple[list[str], bool]:
    """Scan a single .py file.

    Returns:
        (errors, skipped): errors is a list of violation descriptions;
        skipped is True when the file could not be parsed.
    """
    errors: list[str] = []
    try:
        with open(path, encoding="utf-8-sig") as fh:  # utf-8-sig strips BOM
            tree = ast.parse(fh.read())
    except SyntaxError:
        return errors, True   # skip, don't count as violation

    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and _is_sync_call(node):
            rel = os.path.relpath(path, _APP_PATH)
            errors.append(f"{rel}:{node.lineno}: await sync function detected")
    return errors, False


def test_no_direct_await_of_sync_function():
    """Fail if any file directly awaits a known synchronous function."""
    all_errors: list[str] = []
    scanned = 0
    skipped = 0

    for root, dirs, files in os.walk(_APP_PATH):
        # Skip __pycache__ directories
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            scanned += 1
            errs, skip = _scan_file(path)
            all_errors.extend(errs)
            if skip:
                skipped += 1

    if all_errors:
        # Print all violations for debugging
        for err in all_errors:
            print(f"  ! {err}", file=sys.stderr)
        pytest.fail(
            f"Found {len(all_errors)} direct await-of-sync violation(s) "
            f"across {scanned} files ({skipped} skipped). "
            "Wrap synchronous calls with asyncio.to_thread() or run_sync()."
        )


# ── Phase 2.8 G1: 直接同步调用检测 ──────────────────────────────


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


def _is_awaited_in_func(func_node: ast.AsyncFunctionDef, target_call: ast.Call) -> bool:
    """检查 target_call 是否被 async def 函数中的某个 await 包裹。"""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Await):
            # Check if the Call node is inside this Await's subtree
            for child in ast.walk(node):
                if child is target_call:
                    return True
    return False


def _scan_async_for_direct_sync(func_node: ast.AsyncFunctionDef, file_path: str) -> list[str]:
    """扫描 async def 中的直接同步调用（非 await 包裹且不在嵌套 def 中）。
    
    跳过嵌套 in def 中的调用 — 它们应通过 run_sync/to_thread 执行。
    """
    violations = []
    rel = os.path.relpath(file_path, _APP_PATH)
    func_name = func_node.name

    # 收集嵌套 sync def 中所有节点的 id 集合（跳过它们）
    nested_def_node_ids = set()
    for child in ast.walk(func_node):
        if isinstance(child, ast.FunctionDef) and not isinstance(child, ast.AsyncFunctionDef):
            for grandchild in ast.walk(child):
                nested_def_node_ids.add(id(grandchild))

    for node in ast.walk(func_node):
        if id(node) in nested_def_node_ids:
            continue
        if isinstance(node, ast.Call):
            call_name = _extract_call_name(node)
            for pattern in _SYNC_PATTERNS_DIRECT:
                if call_name.startswith(pattern) or call_name == pattern.rstrip('.'):
                    if not _is_awaited_in_func(func_node, node):
                        violations.append(
                            f"{rel}:{node.lineno}: direct sync call '{call_name}' "
                            f"in async def '{func_name}'"
                        )
                    break
    return violations


def test_no_direct_sync_call_in_async_function():
    """Fail if any async def contains a direct synchronous call.
    
    检测如 urllib.request.urlopen 等同步调用在 async def 中
    没有被 await / run_sync / to_thread 包裹。
    """
    all_errors: list[str] = []
    scanned = 0

    for root, dirs, files in os.walk(_APP_PATH):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            scanned += 1
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.AsyncFunctionDef):
                        all_errors.extend(_scan_async_for_direct_sync(node, path))
            except (SyntaxError, UnicodeDecodeError):
                continue

    if all_errors:
        for err in all_errors:
            print(f"  ! {err}", file=sys.stderr)
        pytest.fail(
            f"Found {len(all_errors)} direct sync call(s) in async functions "
            f"across {scanned} files. Wrap with run_sync() or asyncio.to_thread()."
        )
