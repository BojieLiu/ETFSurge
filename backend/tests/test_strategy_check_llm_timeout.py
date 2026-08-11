"""
R5-1-6: 策略检查 LLM 超时诊断与快速失败（docs/round5-diagnosis-and-optimization-plan.md §十 P1）。

覆盖：
1. 429 时 strategy_check summary 含 [rate-limited]
2. 连接超时含 [timeout]
3. _rate_limit_wait(attempt=3, cap=10) ≤10s（cap 参数化）
4. 成功返回后 get_last_llm_error() 为空
5. mock agent run 断言 rate_limit_cap=10 透传到 llm_complete_with_system
6. generate_strategy_check_report 传 max_retries=1, rate_limit_cap=10

mock 引用：6 用例 × 多个 mock 点 >5 处 → 抽 conftest fixture（F21 R76）。
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.analysis import llm
from app.services import portfolio_service as ps
from app.services.portfolio_service import (
    _build_llm_fail_summary,
    _collect_strategy_data,
)


@pytest.fixture
def llm_chain_env(monkeypatch):
    """R5-1-6 fixture: mock LLM 调用链（对齐 test_agent_registry.py:81）。"""
    monkeypatch.setattr(llm, "_check_key", AsyncMock(return_value=None))
    monkeypatch.setattr(llm.token_store, "record", AsyncMock(return_value=None))
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(return_value=None))
    return llm


class TestR516RateLimitWaitCap:
    def test_cap_param_limits_wait(self):
        """_rate_limit_wait(attempt=3, cap=10) ≤10s（旧固定 cap 30s）。"""
        w = llm._rate_limit_wait(3, None, cap=10.0)
        assert w <= 10.0, f"cap=10 时等待 {w}s > 10s"
        assert w >= 0

    def test_default_cap_unchanged(self):
        """默认 cap=30 不变（既有 test_llm_rate_limit.py 不破坏）。"""
        w = llm._rate_limit_wait(0, None)  # 3s * 2^0 = 3s
        assert w == 3.0
        w2 = llm._rate_limit_wait(5, None)  # cap 30
        assert w2 <= 30.0

    def test_retry_after_respects_cap(self):
        """Retry-After=25s + cap=10 → 等待 10s（cap 生效）。"""
        w = llm._rate_limit_wait(0, {"retry-after": "25"}, cap=10.0)
        assert w == 10.0


class TestR516LastErrorDiagnostics:
    def test_record_429_marks_rate_limited(self):
        """429 异常 → 诊断前缀 [rate-limited]。"""
        exc = _make_429_exc()
        llm._record_llm_error(exc)
        assert llm.get_last_llm_error() == "[rate-limited] 429 Too Many Requests"

    def test_record_timeout_marks_timeout(self):
        """连接超时 → 诊断前缀 [timeout]。"""
        llm._record_llm_error(asyncio.TimeoutError("connect timed out"))
        assert llm.get_last_llm_error().startswith("[timeout]")

    def test_success_clears_error(self):
        """成功调用后 get_last_llm_error() 为空。"""
        llm._record_llm_error(_make_429_exc())
        llm._clear_llm_error()
        assert llm.get_last_llm_error() is None


class TestR516StrategyCheckFastFail:
    @pytest.mark.asyncio
    async def test_run_json_passes_rate_limit_cap(self, llm_chain_env):
        """rate_limit_cap=10 透传到 llm_complete_with_system（mock runtime）。"""
        from app.analysis import runtime as runtime_mod

        captured = {}

        async def _fake_llm_complete(**kw):
            captured["max_retries"] = kw.get("max_retries")
            captured["rate_limit_cap"] = kw.get("rate_limit_cap")
            return '{"ok": true}'

        with patch.object(runtime_mod, "llm_complete_with_system", _fake_llm_complete):
            rt = runtime_mod.AgentRuntime(_FakeConfig())
            result = await rt.run_json("prompt", max_retries=1, rate_limit_cap=10.0)
        assert result == {"ok": True}
        assert captured["max_retries"] == 1
        assert captured["rate_limit_cap"] == 10.0

    @pytest.mark.asyncio
    async def test_timeout_summary_contains_last_error(self):
        """generate_strategy_check_report 超时兜底 summary 含最后错误诊断。"""
        from app.analysis import registry

        fake_agent = AsyncMock()
        fake_agent.run_json = AsyncMock(side_effect=asyncio.TimeoutError("boom"))

        with patch.object(registry, "get_agent", return_value=fake_agent):
            llm._record_llm_error(asyncio.TimeoutError("connect timed out"))
            result = await llm.generate_strategy_check_report(
                market_data=[{"symbol": "510300", "name": "x", "target_weight": 0.5}],
                factor_breakdowns={},
                regime="range_bound",
            )
        # 快速失败参数必须透传（round14 P0-B: max_retries 1→0——1 轮双 provider
        # 失败立即兜底，不进入会超预算的重试；2×35=70 ≤ 75 预算一致）
        kwargs = fake_agent.run_json.call_args.kwargs
        assert kwargs.get("max_retries") == 0, f"max_retries 未透传: {kwargs}"
        assert kwargs.get("rate_limit_cap") == 10.0, f"rate_limit_cap 未透传: {kwargs}"
        assert "最后错误" in result["summary"] or "[timeout]" in result["summary"], \
            f"summary 应含错误诊断: {result['summary']}"


class _FakeConfig:
    name = "strategy_check"
    max_retries = 2
    response_format = "json_object"
    system_prompt_file = "strategy_check.md"
    temperature = 0.3


def _make_429_exc():
    import httpx
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    return httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp)


# ── O7 / R6-F13: _build_llm_fail_summary 文案分级（合并自 test_strategy_check_llm_fallback.py
#    与 test_strategy_check_summary.py）──


class TestLlmFailSummary:
    def test_timeout_reason_with_data_summary(self):
        """超时兜底文案含原因分类 + 数据摘要（N/M 可用）。"""
        s = _build_llm_fail_summary(32.0, "connection timed out", {
            "filled_count": 8, "total_count": 10, "partial": True, "all_empty": False,
        })
        assert "LLM 响应超时" in s
        assert "32s" in s
        assert "8/10" in s
        assert "规则引擎兜底" in s

    def test_rate_limited_reason(self):
        s = _build_llm_fail_summary(5.0, "429 Too Many Requests", None)
        assert "LLM 限流" in s
        assert "429" in s

    def test_all_empty_quality_note(self):
        """数据全缺时文案注明「上下文不足快速兜底」。"""
        s = _build_llm_fail_summary(15.0, "timeout", {
            "filled_count": 0, "total_count": 10, "partial": False, "all_empty": True,
        })
        assert "数据缺失" in s
        assert "0/10" in s


def test_fail_summary_rate_limit():
    """诊断含 429/限流 → "LLM 限流"。"""
    s = _build_llm_fail_summary(10.0, "HTTP 429 Rate limit exceeded")
    assert "LLM 限流" in s, s
    assert "429" in s
    assert "已用规则引擎兜底" in s


def test_fail_summary_timeout():
    """诊断含 timeout → "LLM 响应超时"。"""
    s = _build_llm_fail_summary(60.0, "HTTPSConnectionPool timed out")
    assert "LLM 响应超时" in s, s


def test_fail_summary_server_error():
    """5xx 快速失败（非超时非限流）→ "LLM 服务端错误"，旧"超时 60s"文案不出现。"""
    s = _build_llm_fail_summary(10.0, "Server error '500 Internal Server Error'")
    assert "LLM 服务端错误" in s, s
    assert "超时（60s" not in s  # 旧文案残留不得出现


def test_fail_summary_unknown_diag():
    """无诊断 → 归类服务端错误且含"未知"。"""
    s = _build_llm_fail_summary(30.0, "")
    assert "服务端错误" in s
    assert "未知" in s


# ── O25: 部分采集结果保留 + 数据质量兜底（合并自 test_strategy_check_partial_data.py）──


class TestPartialCollectionKept:
    @pytest.mark.asyncio
    async def test_indicator_timeout_keeps_factors(self):
        """① 指标任务超时 → 因子结果保留（非全空）。"""
        async def slow_indicators(symbols):
            await asyncio.sleep(1.0)  # 远超 indicators_timeout
            return {"510300": {"signal": {"signal": "buy"}}}

        async def fast_factors(symbols):
            return {"510300": {"technical": 0.5}, "560600": {"technical": 0.4}}

        with patch.object(ps, "_compute_indicators", new=slow_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=fast_factors):
            indicators, factor_scores = await _collect_strategy_data(
                ["510300", "560600"], indicators_timeout=0.1, factor_timeout=5,
            )
        assert indicators == {}, "指标超时应返回 {}"
        assert factor_scores == {"510300": {"technical": 0.5}, "560600": {"technical": 0.4}}, \
            f"因子结果应保留（非全空）: {factor_scores}"

    @pytest.mark.asyncio
    async def test_factor_failure_keeps_indicators(self):
        """因子任务失败 → 指标结果保留。"""
        async def fast_indicators(symbols):
            return {"510300": {"signal": {"signal": "hold"}}}

        async def boom_factors(symbols):
            raise RuntimeError("data source down")

        with patch.object(ps, "_compute_indicators", new=fast_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=boom_factors):
            indicators, factor_scores = await _collect_strategy_data(
                ["510300"], indicators_timeout=5, factor_timeout=5,
            )
        assert indicators == {"510300": {"signal": {"signal": "hold"}}}
        assert factor_scores == {}

    @pytest.mark.asyncio
    async def test_both_ok(self):
        """正常路径：两任务均返回。"""
        async def fast_indicators(symbols):
            return {"510300": {"signal": {"signal": "hold"}}}

        async def fast_factors(symbols):
            return {"510300": {"technical": 0.5}}

        with patch.object(ps, "_compute_indicators", new=fast_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=fast_factors):
            indicators, factor_scores = await _collect_strategy_data(["510300"])
        assert indicators["510300"]["signal"]["signal"] == "hold"
        assert factor_scores["510300"]["technical"] == 0.5


class TestFallbackSummaryWithQuality:
    def test_summary_includes_data_quality(self):
        """③ 兜底 summary 携带数据质量（N/M 因子可用 + 缺失原因）。"""
        summary = _build_llm_fail_summary(
            duration_s=30.0, diag="DeepSeek timeout",
            data_quality={"filled_count": 2, "total_count": 3, "partial": True},
        )
        assert "2/3" in summary, f"summary 应含因子可用数: {summary}"
        assert "因子" in summary

    def test_summary_all_empty(self):
        summary = _build_llm_fail_summary(
            duration_s=15.0, diag="timeout",
            data_quality={"filled_count": 0, "total_count": 3, "all_empty": True},
        )
        assert "0/3" in summary
        assert "数据不足" in summary or "缺失" in summary

    def test_summary_backward_compatible(self):
        """不传 data_quality 时保持旧文案结构（兼容调用方）。"""
        summary = _build_llm_fail_summary(duration_s=30.0, diag="timeout")
        assert "规则引擎兜底" in summary
