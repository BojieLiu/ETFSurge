"""
O24 (docs/round8-rediagnosis.md §7 §5.1K ④): symbol-analysis stream 复用限流参数。

现状: runtime.run_stream 不透传 max_retries/rate_limit_cap → llm.py 重试/限流
机制在 stream 路径未生效（429 时按默认 max_retries=2 + cap 30s 长时间退避）。

修复: run_stream 透传（对齐 run() 的 R5-1-6）；symbol_analysis_stream 调用处
传 max_retries=1, rate_limit_cap=10 快速失败。
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
    async def test_run_stream_forwards_rate_limit_kwargs(self, monkeypatch):
        """run_stream 透传 max_retries/rate_limit_cap 到 llm_complete_stream。"""
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
        assert captured.get("rate_limit_cap") == 10

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

    def test_symbol_analysis_call_passes_limits(self):
        """symbol_analysis_stream 调用处传 max_retries=1 + rate_limit_cap=10。"""
        src = inspect.getsource(analysis_router.symbol_analysis_stream)
        assert "max_retries=1" in src
        assert "rate_limit_cap=10" in src
