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
    "_mootdx_",
    "_sina_",
    "_tencent_",
    "run_in_thread",
    "requests.",
    "urllib.",
]


def _is_exempted(node: ast.Await) -> bool:
    """Skip 'await asyncio.wait_for(asyncio.to_thread(...), ...)' patterns.

    These are already correctly wrapped and need no flagging.
    """
    call = node.value
    if not isinstance(call, ast.Call):
        return False
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
            print(f"  ✗ {err}", file=sys.stderr)
        pytest.fail(
            f"Found {len(all_errors)} direct await-of-sync violation(s) "
            f"across {scanned} files ({skipped} skipped). "
            "Wrap synchronous calls with asyncio.to_thread() or run_sync()."
        )
