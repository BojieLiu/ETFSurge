"""v7 P1.5: LangGraph 对照实现边界用例（docs/etfsurge-agentic-upgrade-v7.md §7.5）。

设计目的：把 P1 自研 AgentLoop（app/agentic/agent_loop.py）的核心护栏边界平移到
LangGraph StateGraph 对照实现（app/agentic/lg_agent.py），验证：
1. 同样的护栏（步数预算/时间超时/写确认/输出校验/数据缺失）两种实现都能守住——
   这是对照的核心价值（框架 vs 自研，护栏一个不省）。
2. LangGraph 用 pytest -m agentic 隔离运行，不污染主测试（v7 §7.5 CI 配置）。

对照实现复用 P1 的 Executor（白名单+循环检测）+ StepOutput schema 校验，
差异只在编排层（StateGraph 条件边 vs 手写 for 循环）。本测试 mock 全部护栏，
不依赖真实行情/LLM。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agentic.agent_loop import PlanStep
from app.agentic.lg_agent import LangGraphExecutor
from app.agentic.executor import Executor

# langgraph 是隔离依赖（requirements-agentic.txt）——未装时整个对照测试跳过
# （v7 §7.5：默认不跑 P1.5；-m agentic 显式跑，但若依赖缺失则无法运行）
pytest.importorskip("langgraph")

pytestmark = pytest.mark.agentic


def _make_plan(n: int, tool: str = "get_realtime_quote") -> list[PlanStep]:
    return [PlanStep(tool=tool, arguments={"symbols": ["510300"]}, reason="r")
            for _ in range(n)]


class _FakeExecutor:
    """通用 mock Executor：可配置步行为（成功/挂起/缺 source）。"""

    def __init__(self, source: str = "sina", hang: bool = False,
                 no_source: bool = False):
        self.source = source
        self.hang = hang
        self.no_source = no_source

    async def execute(self, tool: str, arguments: dict) -> dict:
        if self.hang:
            await asyncio.sleep(10)
        out: dict = {"data": {"symbols": arguments.get("symbols", [])},
                     "as_of": "2026-08-31", "degraded": False}
        if self.no_source:
            out["source"] = None
        else:
            out["source"] = self.source
        return out


@pytest.mark.agentic
class TestLangGraphBudgets:
    def test_happy_path_full_plan(self):
        """happy path：3 步全部执行，non-partial（对照 P1 test_happy_path_full_report）。"""
        ge = LangGraphExecutor(executor=_FakeExecutor(),
                               allowed_tools={"get_realtime_quote"},
                               max_steps=10, time_budget_s=5.0)
        report = asyncio.run(ge.run(_make_plan(3)))
        assert len(report.steps) == 3
        assert report.partial is False
        assert report.degraded is False
        assert all(not s.data_missing for s in report.steps)

    def test_step_limit_truncates_with_partial(self):
        """步数预算截断：plan 11 步，max_steps=10 -> 跑 10 步 + partial=True。"""
        ge = LangGraphExecutor(executor=_FakeExecutor(),
                               allowed_tools={"get_realtime_quote"},
                               max_steps=10, time_budget_s=5.0)
        report = asyncio.run(ge.run(_make_plan(11)))
        assert len(report.steps) == 10, f"应在 10 步截断: {len(report.steps)}"
        assert report.partial is True

    def test_time_budget_single_step_timeout(self):
        """时间预算：单步挂起超过预算 -> 该步标 timeout + degraded。"""
        ge = LangGraphExecutor(executor=_FakeExecutor(hang=True),
                               allowed_tools={"get_realtime_quote"},
                               time_budget_s=0.05)
        report = asyncio.run(ge.run(_make_plan(1)))
        assert report.degraded is True
        assert any("timeout" in (s.error or "").lower() for s in report.steps)


@pytest.mark.agentic
class TestLangGraphWriteConfirm:
    def test_write_without_confirm_skipped(self):
        """写操作未确认 -> 拒绝执行（对照 P1 §4.5-6）。"""
        plan = [PlanStep(tool="t", arguments={"symbols": ["510300"]},
                         reason="r", write=True)]
        ge = LangGraphExecutor(executor=_FakeExecutor(),
                               allowed_tools={"t"}, time_budget_s=5.0)
        report = asyncio.run(ge.run(plan, confirm=False))
        assert report.steps[0].skipped is True
        assert "not confirmed" in report.steps[0].error

    def test_write_with_confirm_executes(self):
        """写操作+confirm=True -> 正常执行。"""
        plan = [PlanStep(tool="t", arguments={"symbols": ["510300"]},
                         reason="r", write=True)]
        ge = LangGraphExecutor(executor=_FakeExecutor(),
                               allowed_tools={"t"}, time_budget_s=5.0)
        report = asyncio.run(ge.run(plan, confirm=True))
        assert report.steps[0].skipped is False


@pytest.mark.agentic
class TestLangGraphParallelExecutorsSameBase:
    """注意：Executor 复用（白名单+循环检测）+ StepOutput schema 在 lg_agent 中。"""

    def test_executor_whitelist_still_blocks(self):
        """复用 Executor 的白名单护栏仍在（对照 P1 §4.5-1 语义）。"""
        ex = Executor(allowed_tools={"get_realtime_quote"})
        from app.agentic.executor import ExecutorPermissionError
        with pytest.raises(ExecutorPermissionError):
            asyncio.run(ex.execute("no_such_tool", {"symbols": ["510300"]}))


@pytest.mark.agentic
class TestLangGraphGuardDurability:
    def test_data_missing_marked(self):
        """工具返回 data=None -> 步标 data_missing（对照 P1 §4.5-8）。"""
        class NullExecutor:
            async def execute(self, tool, arguments):
                return {"data": None, "source": "sina", "as_of": None,
                        "degraded": False}
        ge = LangGraphExecutor(executor=NullExecutor(),
                               allowed_tools={"get_realtime_quote"},
                               time_budget_s=5.0)
        report = asyncio.run(ge.run(_make_plan(1)))
        assert report.steps[0].data_missing is True

    def test_output_schema_validates_no_source(self):
        """输出缺 source -> ValidationError（对照 P1 §4.5-7）。"""
        ge = LangGraphExecutor(executor=_FakeExecutor(no_source=True),
                               allowed_tools={"get_realtime_quote"},
                               time_budget_s=5.0)
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            asyncio.run(ge.run(_make_plan(1)))
