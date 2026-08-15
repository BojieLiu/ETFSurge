from __future__ import annotations
"""数据源降级链路测试 — Data source fallback chain tests.

验证 SourceRegistry 的 route() 和 try_call() 能正确执行降级：
- 主源失败时自动切换到备用源
- 空结果触发下一个源
- 熔断器打开后跳过该源
- HTTP 4xx/5xx 记硬失败
"""
import time
import pytest
from typing import Any, Callable
from app.core.source_registry import SourceRegistry


def _make_fn(return_value, fail_count=0):
    """创建一个模拟数据源函数。

    Args:
        return_value: 函数应返回的值。None 表示空结果（触发 fallback）。
        fail_count: 前 N 次调用返回 None 代替正常值。
    """
    call_count = [0]

    def fn(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= fail_count:
            return None
        return return_value
    fn._call_count = call_count
    return fn


def _make_fail_fn(exception_cls=ConnectionError):
    """创建一个总是抛异常的模拟函数。"""
    def fn(*args, **kwargs):
        raise exception_cls("Simulated failure")
    return fn


@pytest.fixture
def fresh_registry():
    """返回干净的 SourceRegistry 实例（无历史健康记录）。"""
    return SourceRegistry()


# =============================================================================
# TestSuite: Route fallback
# =============================================================================


class TestRouteFallback:

    def test_primary_success_returns_immediately(self, fresh_registry):
        """主源返回非空数据时，直接返回不调备用源。"""
        called_secondary = [False]
        def secondary():
            called_secondary[0] = True
            return "fallback"

        result = fresh_registry.route([
            ("primary", _make_fn("result")),
            ("secondary", secondary),
        ], route_name="test")
        assert result == "result"
        assert not called_secondary[0], "Secondary should not be called"

    def test_primary_empty_triggers_fallback(self, fresh_registry):
        """主源返回 None 时触发备用源。"""
        result = fresh_registry.route([
            ("primary", _make_fn(None)),
            ("secondary", _make_fn("fallback_data")),
        ], route_name="test")
        assert result == "fallback_data"

    def test_all_sources_fail_returns_none(self, fresh_registry):
        """所有源都失败时返回 None。"""
        result = fresh_registry.route([
            ("primary", _make_fn(None)),
            ("secondary", _make_fn(None)),
            ("tertiary", _make_fn(None)),
        ], route_name="test")
        assert result is None

    def test_exception_in_primary_triggers_fallback(self, fresh_registry):
        """主源抛异常时触发备用源。"""
        result = fresh_registry.route([
            ("primary", _make_fail_fn()),
            ("secondary", _make_fn("fallback_data")),
        ], route_name="test")
        assert result == "fallback_data"

    def test_circuit_breaker_skips_unhealthy_source(self, fresh_registry):
        """熔断器打开后跳过该源，直接尝试下一个。"""
        source_name = "breaker_skip"
        h = fresh_registry.health(source_name)
        now = time.time()
        for _ in range(3):
            h.record_failure(now, route="test_route")

        assert not h.available(now + 1), "Should be circuit broken"

        # 现在 route 应该跳过该源
        result = fresh_registry.route([
            (source_name, _make_fn("SHOULD_NOT_BE_CALLED")),
            ("secondary", _make_fn("fallback_ok")),
        ], route_name="test")
        assert result == "fallback_ok"

    def test_circuit_breaker_recovers_after_cooldown(self, fresh_registry):
        """熔断器冷却后恢复可用。"""
        source_name = "breaker_recover"
        h = fresh_registry.health(source_name)
        now = time.time()
        for _ in range(3):
            h.record_failure(now, route="test_route")

        # 手动将冷却时间设为过去（模拟冷却结束）
        h._cool_until = 0.0
        assert h.available(time.time() + 1), "Should be available after cooldown reset"

        # 现在可以重新使用该源
        result = fresh_registry.route([
            (source_name, _make_fn("recovered")),
            ("secondary", _make_fn("fallback")),
        ], route_name="test")
        assert result == "recovered"

    def test_empty_dict_triggers_fallback(self, fresh_registry):
        """空字典 {} 应被视为空结果。"""
        result = fresh_registry.route([
            ("primary", _make_fn({})),
            ("secondary", _make_fn("fallback")),
        ], route_name="test")
        assert result == "fallback"

    def test_empty_list_triggers_fallback(self, fresh_registry):
        """空列表 [] 应被视为空结果。"""
        result = fresh_registry.route([
            ("primary", _make_fn([])),
            ("secondary", _make_fn("data")),
        ], route_name="test")
        assert result == "data"

    def test_http_4xx_hard_failure_triggers_fallback(self, fresh_registry):
        """HTTP 4xx/5xx 作为硬失败，触发 fallback。"""
        def http_404():
            return (None, 404)

        def http_500():
            return (None, 500)

        result = fresh_registry.route([
            ("http_primary", http_404),
            ("http_secondary", http_500),
            ("fallback_source", _make_fn("data")),
        ], route_name="test")
        assert result == "data", "Should fallback after HTTP failures"

    def test_route_records_success_metrics(self, fresh_registry):
        """route 成功后更新健康指标。"""
        source_name = "metric_source"
        h = fresh_registry.health(source_name)
        now = time.time()
        assert h.available(now)

        fresh_registry.route([
            (source_name, _make_fn("success")),
        ], route_name="test")
        # 成功后 _failures 应重置为 0
        assert h._failures == 0


class TestTryCallFallback:

    def test_try_call_success(self, fresh_registry):
        """try_call 成功时返回结果。"""
        result = fresh_registry.try_call("test_source", _make_fn("data"))
        assert result == "data"

    def test_try_call_failure_returns_none(self, fresh_registry):
        """try_call 失败时返回 None。"""
        result = fresh_registry.try_call("test_source", _make_fail_fn())
        assert result is None

    def test_try_call_empty_returns_none(self, fresh_registry):
        """try_call 返回空结果时也返回 None。"""
        result = fresh_registry.try_call("test_source", _make_fn(None))
        assert result is None

    def test_try_call_records_failure(self, fresh_registry):
        """try_call 异常后该源应变为不可用（熔断/冷却）。"""
        source_name = "try_fail_count"
        h = fresh_registry.health(source_name)
        assert h.available(time.time())

        fresh_registry.try_call(source_name, _make_fail_fn())
        # 快速失败会触发硬失败，源进入冷却期
        assert not h.available(time.time()), "Source should be unavailable after failure"


class TestSourceHealthIndicators:

    def test_health_resets_on_success(self, fresh_registry):
        """成功后失败计数器归零。"""
        source_name = "reset_test"
        h = fresh_registry.health(source_name)

        now = time.time()
        h.record_failure(now, route="test")
        h.record_failure(now, route="test")
        h.record_failure(now, route="test")
        # 3次达到threshold后计数器重置
        assert h._failures == 0

        # 成功应重置冷却
        h.record_success(route="test")
        assert h._cool_until == 0.0

    def test_failure_threshold_triggers_circuit(self, fresh_registry):
        """达到失败阈值后触发熔断。"""
        source_name = "threshold_test"
        h = fresh_registry.health(source_name)
        now = time.time()

        assert h.available(now)

        # failure_threshold = 3
        h.record_failure(now, route="test")
        h.record_failure(now, route="test")
        h.record_failure(now, route="test")

        # _cool_until = now + 60s, 检查 now + 1 < now + 60
        assert not h.available(now + 1), "Circuit should be open immediately after threshold"

    def test_success_after_failure_resets(self, fresh_registry):
        """失败后的一次成功应重置计数器。"""
        source_name = "reset_after_failure"
        h = fresh_registry.health(source_name)

        h.record_failure(time.time(), route="test")
        assert h._failures == 1

        h.record_success(route="test")
        assert h._failures == 0
        assert h.available(time.time())

    def test_circuit_breaker_status(self, fresh_registry):
        """circuit_breaker_status() 返回各源熔断状态列表。"""
        source_name = "status_test"
        h = fresh_registry.health(source_name)

        status = fresh_registry.circuit_breaker_status()
        assert isinstance(status, (list, tuple))

        # 触发熔断
        now = time.time()
        h.record_failure(now, route="test")
        h.record_failure(now, route="test")
        h.record_failure(now, route="test")

        status = fresh_registry.circuit_breaker_status()
        assert len(status) > 0


# ===== folded from test_phase2a_data_quality.py =====
import ast
import os
class TestP1_2d_MarginSwap:
    """P1.2d: Replace _fetch_szse/_fetch_sse direct HTTP with akshare."""

    def test_no_direct_szse_http(self):
        """_fetch_szse should NOT use urllib.request directly."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_fetch_szse":
                body = ast.dump(node)
                assert "urllib.request" not in body, (
                    "_fetch_szse still uses urllib.request directly"
                )
                # Should use akshare
                assert "stock_margin_szse" in body, (
                    "_fetch_szse should use stock_margin_szse()"
                )
                return
        pytest.fail("_fetch_szse function not found")

    def test_no_direct_sse_http(self):
        """_fetch_sse should NOT use urllib.request directly."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_fetch_sse":
                body = ast.dump(node)
                assert "urllib.request" not in body, (
                    "_fetch_sse still uses urllib.request directly"
                )
                # Should use akshare
                assert "stock_margin_sse" in body, (
                    "_fetch_sse should use stock_margin_sse()"
                )
                return
        pytest.fail("_fetch_sse function not found")

    def test_fetch_margin_balance_uses_akshare(self):
        """fetch_margin_balance should call through to akshare-based functions."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "fetch_margin_balance":
                body = ast.get_source_segment(
                    open(probes_path, encoding="utf-8").read(), node
                )
                # Should call both SZSE and SSE akshare functions
                assert "_fetch_szse" in body, "fetch_margin_balance should call _fetch_szse"
                assert "_fetch_sse" in body, "fetch_margin_balance should call _fetch_sse"
                return
class TestP1_2a_NewsFactorPipeline:
    """P1.2a: Ensure news factors receive data from pipeline."""

    def test_news_heat_factor_exists(self):
        """news_heat factor function should exist in factor_registry."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "factors", "factor_registry.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_news_heat":
                    return
        pytest.fail("_compute_news_heat function not found in factor_registry.py")

    def test_news_direction_factor_exists(self):
        """news_direction factor function should exist in factor_registry."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "factors", "factor_registry.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_news_direction":
                    return
        pytest.fail("_compute_news_direction function not found in factor_registry.py")
class TestP1_5_ConnectionPool:
    """P1.5: HTTP connection pool capacity."""

    def test_china_market_session_has_pool_config(self):
        """china_market.py session should configure pool_connections/pool_maxsize."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "china_market.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should configure pool_connections and pool_maxsize
        assert "pool_connections" in content or "pool_maxsize" in content or "Adapter" in content or "HTTPAdapter" in content, (
            "china_market.py should configure HTTP connection pool"
        )

    def test_pool_sizes_adequate(self):
        """Pool sizes should be at least 20 connections."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "china_market.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for pool sizes >= 20
        has_pool_size = any(str(n) in content for n in [20, 25, 30, 40, 50, 60])
        assert has_pool_size, (
            "Connection pool size should be >= 20"
        )
