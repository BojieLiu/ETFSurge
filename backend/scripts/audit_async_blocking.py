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

# round35 A5 (docs/round35-architecture-review.md §13.9 T-A5) 补盲 pattern——
# 与 D1 同性质的「扫描器看不见」盲区（对抗式扫描发现的第二实例）：
#   P-a: open() 直接出现在 async def 体（实锤 hub/_regime_sentiment，round36 已修）
#   P-b: sqlite3.* 家族直接出现在 async def 体（实锤 monitor/source_events:226）
# 两者在 async 体内直接出现 = 真实事件循环阻塞，FAIL 级。
_ASYNC_DIRECT_IO_PATTERNS = ("open", "sqlite3.")

# 允许的白名单模式（这些调用即使匹配也被视为安全）
_ALLOWED_PATTERNS = [
    # 已经通过 run_sync 或 asyncio.to_thread 包装的
]


def _safe_rel(path: str) -> str:
    """round35 A5: 跨盘符（Windows C:/E:）时 os.path.relpath 抛 ValueError——
    门禁自测 fixture 在 tmp_path 构造伪文件时暴露。回退显示原路径。"""
    try:
        return os.path.relpath(path, _APP_PATH)
    except ValueError:
        return path


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


def _defined_as_async(name: str, tree: ast.AST) -> bool:
    """判断名为 name 的函数在树中是否被定义为 async def。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == name:
                return isinstance(node, ast.AsyncFunctionDef)
    return False


class _CallScanner(ast.NodeVisitor):
    """单遍扫描异步函数体内的直接同步阻塞调用。

    原实现对每个 Call 节点都整树 walk 一遍（O(调用数 × AST节点数)），在大型
    app/ 树累积到 30s+。这里改为单遍遍历：用访问栈维护「是否在 await 表达式内」
    「是否在嵌套同步 def 内」两个上下文标志，对每个 Call 仅做 O(1) 判定。
    语义与原实现完全等价（同样的阻塞/白名单模式、同样的 await/嵌套跳过）。
    """

    def __init__(self, func_node: ast.AsyncFunctionDef, file_path: str):
        self.func_node = func_node
        self.file_path = file_path
        self.violations: list[str] = []
        self._in_nested_sync = 0   # 嵌套同步 def 深度（顶层 async def 不计入）
        self._await_depth = 0      # 祖先 Await 深度

    def visit_FunctionDef(self, node):
        if node is self.func_node:
            self.generic_visit(node)
            return
        self._in_nested_sync += 1
        self.generic_visit(node)
        self._in_nested_sync -= 1

    def visit_AsyncFunctionDef(self, node):
        # 嵌套 async def 不计入「嵌套同步 def」，其体内调用仍需检查
        if node is self.func_node:
            self.generic_visit(node)
            return
        self.generic_visit(node)

    def visit_Await(self, node):
        self._await_depth += 1
        self.generic_visit(node)
        self._await_depth -= 1

    def visit_Call(self, node):
        if self._in_nested_sync == 0 and self._await_depth == 0:
            call_name = _extract_call_name(node)
            is_blocking = any(
                call_name.startswith(p) or call_name == p.rstrip('.')
                for p in _BLOCKING_PATTERNS
            )
            # round35 A5 P-a/P-b: async def 体内的直接文件 IO / 同步 sqlite
            if not is_blocking and (
                call_name in _ASYNC_DIRECT_IO_PATTERNS
                or any(call_name.startswith(p) for p in _ASYNC_DIRECT_IO_PATTERNS)
            ):
                is_blocking = True
            if is_blocking:
                is_allowed = any(
                    call_name.startswith(p) or call_name == p.rstrip('.')
                    for p in _ALLOWED_PATTERNS
                )
                if not is_allowed:
                    rel = _safe_rel(self.file_path)
                    self.violations.append(
                        f"{rel}:{node.lineno}: async def '{self.func_node.name}' "
                        f"contains direct sync call '{call_name}'"
                    )
        self.generic_visit(node)


def scan_async_function(func_node: ast.AsyncFunctionDef, file_path: str) -> list[str]:
    """扫描单个 async def 函数，返回违规列表（单遍，O(AST节点数)）。

    只报告直接位于 async 函数体的同步调用，
    跳过嵌套同步 def 中的调用（它们应被外层 def 的扫描覆盖）。
    """
    scanner = _CallScanner(func_node, file_path)
    scanner.visit(func_node)
    return scanner.violations


def _scan_to_thread_misuse(tree: ast.AST, file_path: str) -> list[str]:
    """增强检查 1：asyncio.to_thread 的参数是 async def 函数。
    
    这种情况不会报错，但返回的是协程对象而非实际结果。
    检查仅在参数是同一文件内定义的简单名称时有效。
    """
    violations = []
    rel = _safe_rel(file_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _extract_call_name(node)
        if call_name != "asyncio.to_thread":
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        # 检查第一个参数是简单名称且在文件中定义为 async def
        if isinstance(first_arg, ast.Name):
            if _defined_as_async(first_arg.id, tree):
                violations.append(
                    f"{rel}:{node.lineno}: asyncio.to_thread() called with async function "
                    f"'{first_arg.id}' — use 'await func()' instead of to_thread"
                )
        elif isinstance(first_arg, ast.Attribute):
            # 形如 asyncio.to_thread(fetch_market_sentiment) 的 import 调用
            # 我们无法跨文件判断是否为 async，但可以通过属性名猜
            # 已知错误模式：to_thread(async_fetch_fn) 在另文件中定义
            attr_name = first_arg.attr if hasattr(first_arg, 'attr') else ''
            if attr_name.endswith(('_sentiment', '_async', '_coroutine')):
                violations.append(
                    f"{rel}:{node.lineno}: asyncio.to_thread() called with potentially async "
                    f"function '{attr_name}' — verify target is sync"
                )
    return violations


def _scan_default_executor_usage(tree: ast.AST, file_path: str) -> list[str]:
    """增强检查 2：loop.run_in_executor(None, ...) 使用默认 executor。
    
    应该改用 run_sync() 来统一走 _shared_executor。
    """
    violations = []
    rel = _safe_rel(file_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _extract_call_name(node)
        if call_name.endswith("run_in_executor") and node.args:
            first_arg = node.args[0]
            # loop.run_in_executor(None, ...) — 第一个参数是 None 字面量
            if isinstance(first_arg, ast.Constant) and first_arg.value is None:
                violations.append(
                    f"{rel}:{node.lineno}: loop.run_in_executor(None, ...) uses default executor"
                    f" — use 'await run_sync(fn, args, timeout=X)' instead"
                )
    return violations


def _scan_unwrapped_nested_sync(tree: ast.AST, file_path: str) -> list[str]:
    """round35 A5 P-c（WARN 级，人工复核不阻断）：async def 内嵌套 sync def 含
    阻塞调用、且该 sync 函数名未被 to_thread/run_sync/wait_for 包装调用。

    合法用法存在（token_usage._query 经 asyncio.to_thread 包裹即合法）——自动
    区分「定义处」与「调用处包装方式」的 AST 判定复杂度高，先 WARN 观察误报率
    再考虑升级 FAIL。"""
    rel = _safe_rel(file_path)

    def _is_blocking_call(cn: str) -> bool:
        if any(cn.startswith(p) or cn == p.rstrip('.') for p in _BLOCKING_PATTERNS):
            return True
        return cn in _ASYNC_DIRECT_IO_PATTERNS or any(
            cn.startswith(p) for p in _ASYNC_DIRECT_IO_PATTERNS
        )

    wrapped_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            cn = _extract_call_name(node)
            if cn in ("asyncio.to_thread", "to_thread", "run_sync") or cn.endswith("run_in_executor"):
                if node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Name):
                        wrapped_names.add(first.id)
                    elif isinstance(first, ast.Attribute):
                        wrapped_names.add(first.attr)

    warns: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.FunctionDef) or sub is node:
                continue
            has_blocking = any(
                isinstance(call, ast.Call) and _is_blocking_call(_extract_call_name(call))
                for call in ast.walk(sub)
            )
            if has_blocking and sub.name not in wrapped_names:
                warns.append(
                    f"{rel}:{sub.lineno}: [WARN] async def '{node.name}' 内嵌套 sync def "
                    f"'{sub.name}' 含阻塞调用且未见 to_thread/run_sync 包装——人工复核"
                )
    return warns


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

    # 增强检查
    violations.extend(_scan_to_thread_misuse(tree, file_path))
    violations.extend(_scan_default_executor_usage(tree, file_path))

    return violations


def main() -> int:
    """主函数。返回 0 = 无违规, 1 = 发现违规（WARN 级不阻断）。"""
    all_violations: list[str] = []
    all_warnings: list[str] = []
    scanned = 0
    skipped = 0

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
            except (SyntaxError, UnicodeDecodeError) as e:
                all_violations.append(f"Skipping unparseable file {path}: {e}")
                skipped += 1
                continue
            errs = scan_file(path)
            if any(e.startswith("Skipping") for e in errs):
                skipped += 1
            all_violations.extend(errs)
            # round35 A5 P-c: WARN 级单独收集（不阻断 exit code）
            all_warnings.extend(_scan_unwrapped_nested_sync(tree, path))

    if all_warnings:
        print(f"[WARN] {len(all_warnings)} potential nested-sync blocking call(s) "
              f"(manual review, not blocking):", file=sys.stderr)
        for w in all_warnings:
            print(f"  ? {w}", file=sys.stderr)

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
