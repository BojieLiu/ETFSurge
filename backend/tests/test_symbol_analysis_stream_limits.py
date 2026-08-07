"""
O24 (docs/archived/round8-rediagnosis.md §7 §5.1K ④) 修复回归测试。

根因: runtime.run_stream 把 rate_limit_cap 透传给 llm_complete_stream，
但该函数签名（llm.py:415）没有 rate_limit_cap → TypeError →
symbol-analysis/stream 对 5 类标的全 STREAM_ERROR。

修复: run_stream 只透传 llm_complete_stream 支持的参数（max_retries/
retry_delay）；调用处只传 max_retries=1。429 退避由 llm.py 的
Retry-After/指数退避机制处理。
"""

import inspect
import pytest

from app.analysis.runtime import AgentRuntime
from app.routers import analysis as analysis_router


class _FakeConfig:
    name = "fake"
    system_prompt_file = ""
    response_format = None
    temperature = 0.5
    max_retries = 2


class TestRunStreamPassesLimits:
    @pytest.mark.asyncio
    async def test_run_stream_forwards_supported_kwargs_only(self, monkeypatch):
        """run_stream 只透传 llm_complete_stream 支持的参数（max_retries 过、
        rate_limit_cap 过滤——透传会 TypeError → STREAM_ERROR，见 O24）。"""
        captured = {}

        async def fake_llm_stream(**kwargs):
            captured.update(kwargs)
            return  # empty generator
            yield  # pragma: no cover

        import app.analysis.runtime as rt
        monkeypatch.setattr(rt, "llm_complete_stream", fake_llm_stream)

        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.config = _FakeConfig()
        runtime.system_prompt = "x"
        gen = runtime.run_stream("hello", max_retries=1, rate_limit_cap=10)
        async for _ in gen:
            pass

        assert captured.get("max_retries") == 1
        assert "rate_limit_cap" not in captured, \
            "rate_limit_cap 不在 llm_complete_stream 签名内，透传必 STREAM_ERROR"

    @pytest.mark.asyncio
    async def test_run_stream_defaults_when_not_passed(self, monkeypatch):
        """未显式传参时保持 llm_complete_stream 默认（None 不覆盖）。"""
        captured = {}

        async def fake_llm_stream(**kwargs):
            captured.update(kwargs)
            return
            yield  # pragma: no cover

        import app.analysis.runtime as rt
        monkeypatch.setattr(rt, "llm_complete_stream", fake_llm_stream)

        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.config = _FakeConfig()
        runtime.system_prompt = "x"
        gen = runtime.run_stream("hello")
        async for _ in gen:
            pass

        assert "max_retries" not in captured or captured["max_retries"] is None

    def test_symbol_analysis_call_passes_only_supported(self):
        """symbol_analysis_stream 调用处只传 max_retries=1，不含 rate_limit_cap。"""
        src = inspect.getsource(analysis_router.symbol_analysis_stream)
        assert "max_retries=1" in src
        assert "rate_limit_cap" not in src
