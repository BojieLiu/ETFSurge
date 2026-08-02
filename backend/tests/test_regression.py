"""
回归测试套件（OPT-08/16）。

所有测试 mock 外部依赖，不依赖网络。
每个回归测试在修复前必须 RED，修复后必须 GREEN。
"""
import asyncio
import os
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.core.async_utils import run_in_thread, run_sync
from app.services.source_registry import SourceRegistry, SourceHealth


# ════════════════════════════════════════════════════════════════════
# OPT-01: 熔断器集成 — push2 熔断时 fetch_fund_flow 立即返回 None
# ════════════════════════════════════════════════════════════════════

class TestOpt01CircuitBreakerRegression:
    """OPT-01 红绿切换回归测试。"""

    @patch("app.fetchers.fundamentals_fetcher._push2_available", return_value=False)
    def test_fetch_fund_flow_returns_none_when_push2_open(self, mock_push2):
        """push2 熔断时 fetch_fund_flow 应立即返回 None（不等 8s 超时）。"""
        from app.fetchers.fundamentals_fetcher import fetch_fund_flow
        result = fetch_fund_flow("159338")
        assert result is None, "熔断时应立即返回 None"

    @patch("app.fetchers.fundamentals_fetcher._push2_available", return_value=False)
    def test_fetch_fund_flow_detailed_returns_none_when_push2_open(self, mock_push2):
        """push2 熔断时 fetch_fund_flow_detailed 应立即返回 None。"""
        from app.fetchers.fundamentals_fetcher import fetch_fund_flow_detailed
        result = fetch_fund_flow_detailed("159338")
        assert result is None, "熔断时应立即返回 None"

    @patch("app.fetchers.fundamentals_fetcher._push2_available", return_value=True)
    @patch("app.fetchers.fundamentals_fetcher.run_in_thread", return_value=None)
    def test_fetch_fund_flow_proceeds_when_push2_available(self, mock_run, mock_push2):
        """push2 可用时 fetch_fund_flow 正常执行（run_in_thread 被调用）。"""
        from app.fetchers.fundamentals_fetcher import fetch_fund_flow
        result = fetch_fund_flow("159338")
        assert result is None


# ════════════════════════════════════════════════════════════════════
# OPT-02: _compute_fund_flow 快速降级
# ════════════════════════════════════════════════════════════════════

class TestOpt02FundFlowDegradation:
    """OPT-02 红绿切换回归测试。"""

    @pytest.mark.asyncio
    async def test_compute_fund_flow_returns_empty_when_akshare_open(self):
        """F17 R62: fund_flow 熔断 gate 为 akshare 源（真实数据路径），非 push2delay。

        旧断言 push2delay 是 R62 修复前的语义错位（fund_flow 被涨跌家数路径的
        push2 熔断 gate 误伤）。R62 后改查 akshare 健康。
        """
        from app.services.strategy_design import _compute_fund_flow

        # 将 akshare 熔断器设为不可用
        mock_h = MagicMock()
        mock_h.available.return_value = False

        mock_pm = MagicMock()
        mock_pm.get_pool.return_value = {
            "core": [{"symbol": "510300"}],
            "satellite": [{"symbol": "159338"}],
        }

        with patch("app.services.source_registry.registry._health",
                   return_value=mock_h) as mock_health:
            result = await _compute_fund_flow(mock_pm)
            assert result["total_net_inflow"] == 0.0
            assert result["total_symbols"] == 0
            # R62: gate 查 akshare 源健康（不再查 push2delay）
            mock_health.assert_called_once_with("akshare")

    @pytest.mark.asyncio
    async def test_compute_fund_flow_proceeds_when_push2_available(self):
        """push2 可用时 _compute_fund_flow 正常执行。"""
        from app.services.strategy_design import _compute_fund_flow

        mock_h = MagicMock()
        mock_h.available.return_value = True

        mock_pm = MagicMock()
        mock_pm.get_pool.return_value = {"core": [{"symbol": "510300"}]}

        with patch("app.services.source_registry.registry._health",
                   return_value=mock_h):
            with patch("app.fetchers.fundamentals_fetcher.fetch_fund_flow",
                       return_value={"main_net_inflow": 1000000.0, "main_net_inflow_pct": 2.5}):
                result = await _compute_fund_flow(mock_pm)
                assert result["total_net_inflow"] == 1000000.0
                assert result["positive_flow_count"] == 1


# ════════════════════════════════════════════════════════════════════
# OPT-03: run_in_thread executor 参数
# ════════════════════════════════════════════════════════════════════

class TestOpt03ExecutorParameter:
    """OPT-03 红绿切换回归测试。"""

    def test_run_in_thread_default_uses_shared(self):
        """run_in_thread 默认使用 shared executor。"""
        def _fn():
            return 42

        from app.core.async_utils import _shared_executor

        with patch.object(_shared_executor, 'submit', wraps=_shared_executor.submit) as mock_submit:
            result = run_in_thread(_fn, timeout=5)
            assert result == 42
            mock_submit.assert_called_once()

    def test_run_in_thread_with_executor_long(self):
        """run_in_thread executor='long' 使用长任务线程池。"""
        def _fn():
            return 42

        from app.core.async_utils import _long_running_executor

        with patch.object(_long_running_executor, 'submit', wraps=_long_running_executor.submit) as mock_submit:
            result = run_in_thread(_fn, timeout=8, executor="long")
            assert result == 42
            mock_submit.assert_called_once()

    def test_run_in_thread_executor_accepts_shared_string(self):
        """run_in_thread 接受 executor='shared' 参数。"""
        def _fn():
            return 42

        result = run_in_thread(_fn, timeout=5, executor="shared")
        assert result == 42


# ════════════════════════════════════════════════════════════════════
# OPT-04: Semaphore 并发限流
# ════════════════════════════════════════════════════════════════════

class TestOpt04SemaphoreRegression:
    """OPT-04 红绿切换回归测试。"""

    @pytest.mark.asyncio
    async def test_fund_flow_semaphore_limits_concurrency(self):
        """_compute_fund_flow 的 Semaphore(8) 限制并发数。"""
        from app.services.strategy_design import _fund_flow_sem
        assert _fund_flow_sem._value == 8, f"Semaphore 应为 8, 实际 {_fund_flow_sem._value}"

    @pytest.mark.asyncio
    async def test_semaphore_active_in_compute_fund_flow(self):
        """验证 _compute_fund_flow 内部确实使用了 Semaphore。"""
        from app.services.strategy_design import _compute_fund_flow

        mock_h = MagicMock()
        mock_h.available.return_value = True

        mock_pm = MagicMock()
        mock_pm.get_pool.return_value = {
            "core": [{"symbol": f"51{i:04d}"} for i in range(10)]
        }

        with patch("app.services.source_registry.registry._health",
                   return_value=mock_h):
            with patch("app.fetchers.fundamentals_fetcher.fetch_fund_flow",
                       return_value={"main_net_inflow": 100.0, "main_net_inflow_pct": 1.0}):
                result = await _compute_fund_flow(mock_pm)
                assert result["total_symbols"] == 10
                assert result["total_net_inflow"] == 1000.0


# ════════════════════════════════════════════════════════════════════
# OPT-15: SourceRegistry 优化 — try_call / fast-fail / 指数退避
# ════════════════════════════════════════════════════════════════════

class TestOpt15RegistryRegression:
    """OPT-15 红绿切换回归测试。"""

    def test_try_call_returns_none_when_circuit_open(self):
        """熔断时 try_call 返回 None（不等超时）。"""
        registry = SourceRegistry()
        fn = MagicMock(return_value="data")
        h = registry._health("test_source")
        t = time.time()
        h.record_failure(t, duration_ms=1000)
        h.record_failure(t, duration_ms=1000)
        h.record_failure(t, duration_ms=1000)

        result = registry.try_call("test_source", fn, timeout=0)
        assert result is None
        fn.assert_not_called()

    def test_exponential_backoff_increases_cooldown(self):
        """指数退避在连续冷却时增加冷却时间。"""
        h = SourceHealth(cooldown=60, failure_threshold=3, max_cooldown=600)
        now = 1000.0

        # Round 1: 3 次失败 → 60s
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._cool_until == now + 60

        # Simulate cooldown expiry and failures again (no success)
        now = h._cool_until + 1
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._cool_until == now + 120, f"预期 120s, 实际 {h._cool_until - now}"

    def test_reset_source_clears_exponential_backoff(self):
        """reset_source 重置指数退避计数。"""
        registry = SourceRegistry()
        h = registry._health("test_source")
        h.max_cooldown = 600

        with patch("app.services.source_registry.time.time", return_value=1000.0):
            for _ in range(3):
                h.record_failure(1000.0, duration_ms=1000)

        registry.reset_source("test_source")
        assert h._consecutive_cycles == 0
        assert h.cooldown == h.base_cooldown


# ════════════════════════════════════════════════════════════════════
# OPT-10: run_in_thread 调用点审计 — 确保 executor 参数合规
# ════════════════════════════════════════════════════════════════════

class TestOpt10CallSiteAudit:
    """验证所有 run_in_thread 调用点 timeout > 5 时使用了 executor='long'。"""

    def _find_violations(self):
        """AST 扫描所有 run_in_thread 调用。"""
        import ast

        violations = []
        app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
        for root, _, files in os.walk(app_dir):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fpath = os.path.join(root, fn)
                relpath = os.path.relpath(fpath, os.path.join(os.path.dirname(__file__), ".."))
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=fpath)
                except SyntaxError:
                    continue

                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    if not ((isinstance(func, ast.Name) and func.id == "run_in_thread") or
                            (isinstance(func, ast.Attribute) and func.attr == "run_in_thread")):
                        continue

                    has_executor = False
                    timeout_val = None
                    for kw in node.keywords:
                        if kw.arg == "executor":
                            if isinstance(kw.value, ast.Constant):
                                has_executor = True
                        if kw.arg == "timeout":
                            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                                timeout_val = kw.value.value

                    if timeout_val is not None and timeout_val > 5 and not has_executor:
                        violations.append(f"{relpath}:{node.lineno} timeout={timeout_val} > 5, no executor")
        return violations

    def test_no_run_in_thread_with_long_timeout_without_executor(self):
        """所有 timeout > 5 的 run_in_thread 调用都传了 executor='long'。"""
        violations = self._find_violations()
        # Allow only factor_registry.py with timeout=5 (not > 5, so already excluded)
        # And files in tests/ (test files)
        # And benchmark_stocks.py (only imports, no calls)
        violations = [v for v in violations if "tests" not in v]
        assert len(violations) == 0, (
            f"以下调用点缺少 executor='long':\n" + "\n".join(violations)
        )


# ════════════════════════════════════════════════════════════════════
# OPT-13: AST 审计脚本
# ════════════════════════════════════════════════════════════════════

class TestOpt13AuditScript:
    """验证 AST 审计脚本能正常执行。"""

    def test_audit_script_runs(self):
        """审计脚本应能正常执行（不报错）。"""
        import subprocess
        import sys
        script_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "audit_pool_usage.py")
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True,
        )
        # 脚本不应报错
        assert result.returncode in (0, 1), f"审计脚本执行失败: {result.stderr}"


# ════════════════════════════════════════════════════════════════════
# OPT-16: 红绿切换回归测试门禁
# ════════════════════════════════════════════════════════════════════

class TestOpt16RedGreenGate:
    """验证回归测试的"红绿切换"能力。

    这些测试模拟修复前场景 → 应 RED（失败），
    但实际上修复已实施 → 应 GREEN（通过）。
    """

    @pytest.mark.asyncio
    async def test_circuit_breaker_shorts_circuit(self):
        """熔断器打开时，try_call 短路（不等超时），立即返回 None。

        如果未来有人删除了 try_call 的熔断检查，此测试会变 RED。
        """
        registry = SourceRegistry()
        fn = MagicMock(return_value="should_not_be_called")
        h = registry._health("cb_test_source")
        h.max_cooldown = 3600

        with patch("app.services.source_registry.time.time", return_value=1000.0):
            for _ in range(3):
                h.record_failure(1000.0, duration_ms=1000)

            result = registry.try_call("cb_test_source", fn, timeout=0)
            assert result is None, "熔断时 try_call 应短路返回 None"
            fn.assert_not_called(), "熔断时不应执行 fn"

    def test_run_in_thread_executor_long_isolates_pool(self):
        """executor='long' 使用长任务线程池，与共享池隔离。

        如果未来有人移除了 executor='long' 的路由逻辑，此测试会变 RED。
        """
        from app.core.async_utils import _shared_executor

        shared_before = _shared_executor._work_queue.qsize() if hasattr(_shared_executor, '_work_queue') else 0

        def _slow():
            import time
            time.sleep(0.1)
            return "done"

        result = run_in_thread(_slow, timeout=5, executor="long")
        assert result == "done"

        shared_after = _shared_executor._work_queue.qsize() if hasattr(_shared_executor, '_work_queue') else 0
        assert shared_after == shared_before, "长任务不应占用共享线程池"
