"""
并发安全防护测试：覆盖造成线上卡死（thread pool exhaustion + event loop blockage）的
5 个盲区（conversation doc #async-boundary-gaps）。

被测项：
  G1 - 全局锁（已移除后）不再消耗线程池 worker
  G2 - async def 内部禁止直接调用同步函数
  G3 - 新代码优先用 run_sync() 而非 asyncio.to_thread()
  G4 - 后台任务并发时不阻塞事件循环
  G5 - 启动后 /health 应在合理时间内响应
"""

import ast
import asyncio
import os
import time

import pytest

_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "app")

# ── 必须在 run_sync() / asyncio.to_thread() 中调用的同步函数 ──────────
_SYNC_BLACKLIST = {
    "fetch_history", "_mootdx_realtime", "_mootdx_history",
    "_sina_realtime", "_tencent_realtime",
    "fetch_a_stock_batch", "fetch_a_stock_realtime",
    "fetch_all_etfs_base", "fetch_index_realtime",
    "fetch_major_indices", "fetch_hot_plates",
    "fetch_sector_heat", "run_in_thread",
}

# ── 应该用 run_sync() 而非 asyncio.to_thread() 的函数 ────────────────
_PREFER_RUN_SYNC = {
    "fetch_history", "_mootdx_realtime", "_mootdx_history",
    "_sina_realtime", "_tencent_realtime",
    "fetch_a_stock_batch", "fetch_a_stock_realtime",
}


# ═══════════════════════════════════════════════════════════════════
# G1: 全局锁移除后，模拟并发数据源调用不应消耗可用 worker
# ═══════════════════════════════════════════════════════════════════

class TestGlobalLockFree:
    """验证 mootdx 全局锁移除后，并发调用不阻塞线程池。"""

    @pytest.mark.asyncio
    async def test_concurrent_mootdx_calls_dont_starve_pool(self):
        """并发 16 路虚假 mootdx 调用 + 心跳：心跳应正常跳动。"""
        from app.core.async_utils import run_sync

        heartbeats = 0

        async def heartbeat():
            nonlocal heartbeats
            for _ in range(50):
                await asyncio.sleep(0.01)
                heartbeats += 1

        def _slow_fn(symbol):
            time.sleep(0.3)
            return [{"symbol": symbol, "price": 1.0}]

        heart = asyncio.create_task(heartbeat())
        tasks = [run_sync(_slow_fn, f"51{i:04d}", timeout=5) for i in range(16)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await heart

        successes = sum(1 for r in results if isinstance(r, list))
        assert successes == 16, f"只有 {successes}/16 个成功"
        assert heartbeats >= 40, (
            f"心跳应正常跳动（{heartbeats} < 40）—— 线程池可能被卡住"
        )


# ═══════════════════════════════════════════════════════════════════
# G2: async def 内禁止直接调用同步函数（AST 扫描）
# ═══════════════════════════════════════════════════════════════════

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


def _find_py_files():
    """递归获取 backend/app/ 下所有 .py 文件。"""
    files = []
    for root, _dirs, fnames in os.walk(_APP_PATH):
        for fn in fnames:
            if fn.endswith(".py"):
                files.append(os.path.join(root, fn))
    return files


def _is_safe_call(call_node: ast.Call) -> bool:
    """判断当前 Call 是否被 run_sync / to_thread / run_in_thread 包裹（向上查 3 层 parent）。"""
    parent = getattr(call_node, "_parent", None)
    for _ in range(3):
        if parent is None:
            return False
        if isinstance(parent, ast.Call):
            name = _call_name(parent)
            if name in ("run_sync", "asyncio.to_thread", "run_in_thread"):
                return True
        parent = getattr(parent, "_parent", None)
    return False


class TestNoDirectSyncInAsyncDef:
    """遍历全部 Python 源文件，确保 async def 内同步函数都被线程池包裹。

    匹配模式：
      async def foo():
          result = sync_fn(...)         # ❌ 直接调用
          result = await sync_fn(...)   # ❌ await 同步函数
          result = await run_sync(sync_fn, ...)  # ✅
          result = await asyncio.to_thread(sync_fn, ...)  # ✅
    """

    def test_no_sync_calls_directly_in_async_def(self):
        """扫描 app/ 下所有 async def，确认同步函数都被包裹。"""
        violations = []
        for fpath in _find_py_files():
            with open(fpath, "r", encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read(), filename=fpath)
                except SyntaxError:
                    continue

            # 挂载 parent 指针
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    child._parent = node  # type: ignore[attr-defined]

            relpath = os.path.relpath(fpath, _APP_PATH)

            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                if relpath.startswith("tests"):
                    continue

                for child in ast.walk(node):
                    if not isinstance(child, ast.Call):
                        continue
                    name = _call_name(child)
                    if name not in _SYNC_BLACKLIST:
                        continue

                    if _is_safe_call(child):
                        continue

                    line = getattr(child, "lineno", "?")
                    col = getattr(child, "col_offset", "?")
                    violations.append(
                        f"  {relpath}:{line}:{col}  "
                        f"direct call to `{name}` in async def `{node.name}`"
                    )

        if violations:
            pytest.fail(
                f"发现 {len(violations)} 处 async def 内部直接调用同步函数"
                f"（应在 run_sync / asyncio.to_thread 中调用）:\n"
                + "\n".join(violations)
            )


# ═══════════════════════════════════════════════════════════════════
# G3: 标记应当用 run_sync() 的 asyncio.to_thread() 调用（AST 扫描）
# ═══════════════════════════════════════════════════════════════════

class TestPreferRunSync:
    """检查 asyncio.to_thread(fn, ...) 中是否 fn 属于 _PREFER_RUN_SYNC。

    run_sync() 使用 64-worker 共享线程池，asyncio.to_thread() 使用
    Python 默认 executor（通常只 8-16 worker），高并发时易耗尽。
    """

    def test_to_thread_using_default_executor_flagged(self):
        """扫描 asyncio.to_thread 调用，确认没有使用 _PREFER_RUN_SYNC 函数。"""
        violations = []
        for fpath in _find_py_files():
            with open(fpath, "r", encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read(), filename=fpath)
                except SyntaxError:
                    continue

            relpath = os.path.relpath(fpath, _APP_PATH)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _call_name(node)
                if name != "asyncio.to_thread":
                    continue
                if not node.args:
                    continue
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Name) and first_arg.id in _PREFER_RUN_SYNC:
                    line = getattr(node, "lineno", "?")
                    col = getattr(node, "col_offset", "?")
                    violations.append(
                        f"  {relpath}:{line}:{col}  "
                        f"`asyncio.to_thread({first_arg.id}, ...)` "
                        f"应改为 `run_sync({first_arg.id}, ...)`"
                    )
                elif isinstance(first_arg, ast.Lambda):
                    line = getattr(node, "lineno", "?")
                    col = getattr(node, "col_offset", "?")
                    violations.append(
                        f"  {relpath}:{line}:{col}  "
                        f"`asyncio.to_thread(lambda: ...)` — 优先用 `run_sync(fn, ...)`"
                    )

        if violations:
            pytest.fail(
                f"发现 {len(violations)} 处应使用 run_sync() 却使用了 asyncio.to_thread():\n"
                + "\n".join(violations)
            )


# ═══════════════════════════════════════════════════════════════════
# G4: 后台任务并发时不阻塞事件循环（运行时可执行）
# ═══════════════════════════════════════════════════════════════════

class TestBackgroundTasksDontBlockLoop:
    """模拟 main.py lifespan 中的多个后台任务并发启动。"""

    @pytest.mark.asyncio
    async def test_concurrent_background_tasks_keep_loop_alive(self):
        """3 个背景任务（market cache / global indices / ETF scan）同时跑。"""
        from app.core.async_utils import run_sync

        heartbeats = 0

        async def heartbeat():
            nonlocal heartbeats
            for _ in range(50):
                await asyncio.sleep(0.01)
                heartbeats += 1

        async def _warmup_market():
            await run_sync(lambda: time.sleep(0.5), timeout=2)

        async def _warmup_indices():
            for _ in range(3):
                await run_sync(lambda: time.sleep(0.3), timeout=2)

        async def _warmup_etf():
            await run_sync(lambda: time.sleep(0.8), timeout=3)

        heart = asyncio.create_task(heartbeat())
        tasks = [
            asyncio.create_task(_warmup_market()),
            asyncio.create_task(_warmup_indices()),
            asyncio.create_task(_warmup_etf()),
        ]
        await asyncio.gather(*tasks)
        await heart

        assert heartbeats >= 40, (
            f"后台任务阻塞事件循环——心跳仅 {heartbeats}/50，预期 >= 40"
        )


# ═══════════════════════════════════════════════════════════════════
# G5: 启动后 /health 能在合理时间内响应（标记为 slow，需外部队列）
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.slow
class TestHealthResponsiveness:
    """验证导入 app 后在合理时间内 /health 可响应。

    标记为 slow，避免每次测试拉全量 import。
    手动运行：pytest -m slow tests/test_concurrency_guard.py::TestHealthResponsiveness
    """

    @pytest.mark.asyncio
    async def test_health_responds_within_timeout(self):
        from app.main import app
        from httpx import AsyncClient, ASGITransport

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.time()
            resp = await client.get("/health")
            elapsed = time.time() - t0

        assert resp.status_code == 200, f"health 返回 {resp.status_code}"
        assert elapsed < 5.0, f"health 响应时间 {elapsed:.2f}s ≥ 5s"


# ── 清理 parent 指针，避免测试间干扰 ──────────────────────────────────
@pytest.fixture(autouse=True)
def _reset_ast_parents():
    """确保 G2 测试附加的 AST parent 指针不泄漏到其他测试。"""
    yield
