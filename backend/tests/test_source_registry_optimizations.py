"""
测试 SourceRegistry OPT-15 优化：try_call、fast-fail 检测、指数退避。

所有测试不依赖外部网络，完全在内存中执行。
"""
import time
import pytest
from unittest.mock import MagicMock, patch

from app.core.source_registry import SourceRegistry, SourceHealth


# ── OPT-15.1: try_call 包装器 ──────────────────────────────────────

class TestTryCall:
    """验证 try_call 包装器行为。"""

    def test_try_call_skips_when_open(self):
        """当熔断器打开时，try_call 直接返回 None，不执行 fn。"""
        registry = SourceRegistry()
        fn = MagicMock(return_value="data")
        h = registry.health("test_source")
        # 触发熔断（用非快速失败，正常计数）
        t = time.time()
        h.record_failure(t, duration_ms=1000)  # >500ms, normal path
        h.record_failure(t, duration_ms=1000)
        h.record_failure(t, duration_ms=1000)  # 3次 → 熔断
        assert not h.available(time.time() + 0.01), "熔断器应已打开"

        result = registry.try_call("test_source", fn, timeout=0)
        assert result is None, "熔断时 try_call 应返回 None"
        fn.assert_not_called(), "熔断时不应执行 fn"

    def test_try_call_success(self):
        """try_call 成功时返回 fn 结果并记录 success。"""
        registry = SourceRegistry()
        fn = MagicMock(return_value={"price": 100})
        h = registry.health("test_source")

        result = registry.try_call("test_source", fn, timeout=0)
        assert result == {"price": 100}, "应返回 fn 的结果"
        fn.assert_called_once()
        # 验证熔断器记录了成功
        assert h.available(time.time()), "成功后熔断器应关闭"

    def test_try_call_failure_records_failure(self):
        """try_call 失败时返回 None 并记录 failure。"""
        registry = SourceRegistry()
        fn = MagicMock(side_effect=ConnectionError("timeout"))
        h = registry.health("test_source")

        result = registry.try_call("test_source", fn, timeout=0)
        assert result is None, "失败时 try_call 应返回 None"
        # 因 fast-fail 检测 (< 500ms 在 perf_counter 下极快)，应已触发硬失败
        assert h._failures == 0, "硬失败后 _failures 应为 0"

    def test_try_call_with_args_kwargs(self):
        """try_call 正确传递 args 和 kwargs 到 fn。"""
        registry = SourceRegistry()
        fn = MagicMock(return_value="ok")

        registry.try_call("test_source", fn, "arg1", "arg2", timeout=0, key="val")
        fn.assert_called_once_with("arg1", "arg2", key="val")

    def test_try_call_circuit_breaker_trips_after_non_fast_failures(self):
        """非快速失败连续达到阈值后，try_call 应跳过后续调用。"""
        registry = SourceRegistry()
        fn = MagicMock(side_effect=ConnectionError("fail"))
        h = registry.health("test_source")
        h.max_cooldown = 3600

        with patch("app.core.source_registry.time.time", return_value=100.0):
            with patch("app.core.source_registry.time.perf_counter") as mock_pc:
                # 模拟非快速失败：让 elapsed > 500ms
                mock_pc.side_effect = [100.0, 100.6, 100.0, 100.6, 100.0, 100.6, 100.0, 100.6]
                for _ in range(3):
                    result = registry.try_call("test_source", fn, timeout=0)
                    assert result is None
                assert fn.call_count == 3, "前 3 次应执行 fn"

                # 第 4 次：熔断器打开，不应执行 fn
                result = registry.try_call("test_source", fn, timeout=0)
                assert result is None
                assert fn.call_count == 3, "熔断后不应执行 fn"


# ── OPT-15.2: Fast-fail 检测 ───────────────────────────────────────

class TestFastFailDetection:
    """验证 < 500ms 的快速失败被视为硬失败（立即冷却）。"""

    def test_fast_fail_triggers_immediate_cooldown(self):
        """单个快速失败（< 500ms）触发硬失败，跳过 threshold 计数直接冷却。"""
        h = SourceHealth(cooldown=60, failure_threshold=3, max_cooldown=600)
        t = 1000.0
        # 模拟 1 次快速失败（100ms < 500ms）
        h.record_failure(t, duration_ms=100)
        # 因 fast-fail 触发 record_hard_failure，立即冷却（跳过 threshold 计数）
        assert not h.available(t + 1), "1 次快速失败应触发立即冷却"
        assert h._cool_until == t + 60, f"冷却时间为 {h._cool_until - t}s，预期 60s"

    def test_normal_failure_does_not_trigger_immediate_cooldown(self):
        """正常失败（>= 500ms）不触发立即冷却，需达到 threshold。"""
        h = SourceHealth(cooldown=60, failure_threshold=3, max_cooldown=600)
        t = 1000.0
        # 1 次正常失败（1000ms > 500ms）
        h.record_failure(t, duration_ms=1000)
        assert h.available(t + 1), "1 次正常失败不应触发冷却"
        # 再 2 次（共 3 次 = threshold）
        h.record_failure(t, duration_ms=1000)
        h.record_failure(t, duration_ms=1000)
        assert not h.available(t + 1), "3 次正常失败应触发冷却"

    def test_fast_fail_with_try_call(self):
        """try_call 内部检测 fast-fail 并记录 hard_failure。"""
        registry = SourceRegistry()
        fn = MagicMock(side_effect=ConnectionError("fast fail"))
        h = registry.health("test_source")

        with patch("app.core.source_registry.time.time", return_value=100.0):
            with patch("app.core.source_registry.time.perf_counter") as mock_pc:
                # elapsed = 100ms < 500ms → fast-fail
                mock_pc.side_effect = [100.0, 100.1]
                registry.try_call("test_source", fn, timeout=0)
                # 应触发硬失败（不经过 threshold）
                assert not h.available(100.0), "快速失败后应立即冷却"


# ── OPT-15.3: 指数退避 ─────────────────────────────────────────────

class TestExponentialBackoff:
    """验证熔断冷却时间的指数退避。"""

    def test_exponential_backoff_doubles_without_success(self):
        """连续冷却（无 success 介入）时，冷却时间应指数增长。

        场景模拟：cooldown 过期后重试仍失败（无 record_success 在中间），
        连续冷却周期递增。
        """
        h = SourceHealth(cooldown=60, failure_threshold=3, max_cooldown=600)
        now = 1000.0

        # 第 1 轮：3 次失败 → 第一次冷却，60s
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._consecutive_cycles == 1, "第一次冷却周期"
        assert h._cool_until == now + 60, f"预期 60s, 实际 {h._cool_until - now}s"

        # 模拟 cooldown 过期后，仍然失败（无 success 在中间）
        now = h._cool_until + 1  # 冷却过期

        # 第 2 轮：3 次失败 → 第二次冷却，120s（2x）
        # 注意：不调用 record_success，模拟连续不可用
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._consecutive_cycles == 2, f"第二次冷却周期: {h._consecutive_cycles}"
        assert h._cool_until == now + 120, f"预期 120s, 实际 {h._cool_until - now}s"

        now = h._cool_until + 1

        # 第 3 轮：3 次失败 → 第三次冷却，240s（4x）
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._consecutive_cycles == 3, "第三次冷却周期"
        assert h._cool_until == now + 240, f"预期 240s, 实际 {h._cool_until - now}s"

        now = h._cool_until + 1

        # 第 4 轮：3 次失败 → 第四次冷却，480s（8x）
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._consecutive_cycles == 4, "第四次冷却周期"
        assert h._cool_until == now + 480, f"预期 480s, 实际 {h._cool_until - now}s"

        now = h._cool_until + 1

        # 第 5 轮：3 次失败 → 第五次冷却，600s（max）
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._consecutive_cycles == 5, "第五次冷却周期"
        assert h._cool_until == now + 600, f"预期 600s(max), 实际 {h._cool_until - now}s"

    def test_success_resets_exponential_backoff(self):
        """成功后连续冷却周期计数器应重置为 0。"""
        h = SourceHealth(cooldown=60, failure_threshold=3, max_cooldown=600)
        now = 1000.0

        # 第一次熔断
        for _ in range(3):
            h.record_failure(now, duration_ms=1000)
        assert h._consecutive_cycles == 1

        now = h._cool_until + 1
        h.record_success()
        assert h._consecutive_cycles == 0, "成功后计数器应重置"
        assert h._cool_until == 0.0, "成功后冷却应清除"

    def test_exponential_backoff_uses_try_call(self):
        """通过 try_call 触发的熔断也使用指数退避。"""
        registry = SourceRegistry()
        fn = MagicMock(side_effect=ConnectionError("fail"))
        h = registry.health("test_source")
        h.max_cooldown = 600

        with patch("app.core.source_registry.time.time", return_value=1000.0):
            with patch("app.core.source_registry.time.perf_counter") as mock_pc:
                mock_pc.side_effect = [1000.0, 1000.6] * 3  # 3次，每次 >500ms
                for _ in range(3):
                    registry.try_call("test_source", fn, timeout=0)
                assert h._cool_until == 1000.0 + 60, f"第一次熔断冷却期错误: {h._cool_until - 1000}"


# ── OPT-15.4: circuit_breaker_status 增强 ──────────────────────────

class TestCircuitBreakerStatus:
    """验证增强后的熔断器状态 API。"""

    def test_circuit_breaker_status_includes_cooldown_info(self):
        """circuit_breaker_status 返回包含详细冷却信息的列表。"""
        registry = SourceRegistry()
        h = registry.health("test_source")
        h.max_cooldown = 600

        with patch("app.core.source_registry.time.time", return_value=1000.0):
            for _ in range(3):
                h.record_failure(1000.0, duration_ms=1000)

            statuses = registry.circuit_breaker_status()

        assert len(statuses) >= 1
        test_status = [s for s in statuses if s["name"] == "test_source"][0]
        assert test_status["state"] == "open"
        assert "max_cooldown" in test_status
        assert test_status["max_cooldown"] == 600

    def test_circuit_breaker_status_returned_by_endpoint_shape(self):
        """验证熔断器状态 API 返回的 JSON 结构。"""
        registry = SourceRegistry()
        h = registry.health("sina")
        h.cooldown = 30

        result = registry.circuit_breaker_status()
        assert isinstance(result, list), "应返回列表"
        entry = result[0]
        assert "name" in entry
        assert "state" in entry
        assert "failure_threshold" in entry
        assert "max_cooldown" in entry
        assert entry["state"] in ("open", "closed")


# ── OPT-15.5: 全局清理 ─────────────────────────────────────────────

class TestRegistryCleanup:
    """验证 SourceRegistry 清理函数。"""

    def test_reset_source_clears_state(self):
        """reset_source 应清除指定源的状态。"""
        registry = SourceRegistry()
        h = registry.health("test_source")
        h.record_failure(0, duration_ms=1000)
        h.record_failure(0, duration_ms=1000)
        h.record_failure(0, duration_ms=1000)

        registry.reset_source("test_source")
        h2 = registry.health("test_source")
        # 重置后状态应清除
        assert h2._failures == 0
        assert h2._cool_until == 0.0
        assert h2._consecutive_cycles == 0
        assert h2.cooldown == h2.base_cooldown
