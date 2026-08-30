"""v7 P1: Plan-and-Execute 循环护栏边界用例（docs/etfsurge-agentic-upgrade-v7.md §4.5）。

每个护栏阈值 1 个 pytest 边界用例（REVIEW-R3-1），防止失控回归：
- 工具白名单: 未注册工具 -> PermissionError
- 步数预算: 11 步 -> 终止 + 部分结果（StopIteration 语义用 AgentStepLimit 标记）
- 时间预算: 策略检查 90s / 设计报告 120s -> asyncio.TimeoutError + degraded
- 循环检测: 同工具+同参数连续 2 次 -> RuntimeError("loop detected")
- 写操作确认: confirm=False -> 拒绝执行
- 输出校验: 输出缺 source -> ValidationError
- 失败语义: 工具返回 None -> 报告标注「数据缺失」（不编造）

执行层直接进程内调用 P0 的 MCP server handler（server.request_handlers），
不经过 stdio 子进程——护栏测试全部 mock，不依赖真实行情/LLM。
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mcp.types import CallToolRequest

from app.agentic.executor import Executor, ExecutorPermissionError
from app.agentic.agent_loop import (
    AgentLoop,
    AgentBudgetExceeded,
    AgentLoopDetected,
    AgentWriteNotConfirmed,
    PlanStep,
    RunReport,
)
from app.core import llm_timeouts


def _req(name: str, args: dict) -> CallToolRequest:
    return CallToolRequest.model_validate(
        {"method": "tools/call", "params": {"name": name, "arguments": args}}
    )


# ── Executor：工具白名单 + 循环检测 + 步数 ─────────────────────

class TestExecutorWhitelist:
    def test_guard_unknown_tool_raises(self):
        """§4.5-1: Executor 收到未注册工具 -> PermissionError。"""
        ex = Executor(allowed_tools={"get_realtime_quote"})
        with pytest.raises(ExecutorPermissionError):
            asyncio.run(ex.execute("no_such_tool", {"symbols": ["510300"]}))

    def test_registered_tool_executes(self):
        """白名单内工具正常执行（mock MCP handler 返回信封）。"""
        ex = Executor(allowed_tools={"get_realtime_quote"})
        fake_result = MagicMock()
        fake_result.root.content = [MagicMock(text='{"data": 1, "source": "sina"}')]
        mock_server = MagicMock()
        mock_server.request_handlers = {CallToolRequest: AsyncMock(return_value=fake_result)}
        with patch("app.agentic.executor.load_server", return_value=mock_server):
            out = asyncio.run(ex.execute("get_realtime_quote", {"symbols": ["510300"]}))
        assert out["source"] == "sina"


class TestExecutorLoopGuard:
    def test_guard_loop_detected_terminates(self):
        """§4.5-5: 同工具+同参数连续 2 次 -> RuntimeError(loop detected)。"""
        ex = Executor(allowed_tools={"get_realtime_quote"})
        call = ("get_realtime_quote", '{"symbols": ["510300"]}')
        ex._check_loop(*call)  # 第 1 次：登记
        with pytest.raises(RuntimeError, match="loop detected"):
            ex._check_loop(*call)  # 第 2 次：拦截

    def test_loop_guard_resets_on_different_args(self):
        """不同参数不触发循环检测（同工具不同参数是合法重试）。"""
        ex = Executor(allowed_tools={"get_realtime_quote"})
        ex._check_loop("get_realtime_quote", '{"symbols": ["510300"]}')
        # 不同参数 -> 不抛
        ex._check_loop("get_realtime_quote", '{"symbols": ["512890"]}')


# ── AgentLoop：步数/时间预算 + 写确认 + 输出校验 + 失败语义 ────

def _make_plan(n: int, tool: str = "get_realtime_quote") -> list[PlanStep]:
    return [PlanStep(tool=tool, arguments={"symbols": ["510300"]}, reason="r")
            for _ in range(n)]


class TestAgentLoopBudgets:
    def test_guard_step_limit_terminates_with_partial(self):
        """§4.5-2: 计划 11 步 -> 第 10 步后终止 + 返回部分结果。"""
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                         allowed_tools={"t"}, max_steps=10)
        # executor mock 成功，让循环跑到步数上限
        loop._execute_step = AsyncMock(return_value={"data": 1, "source": "m"})
        report = asyncio.run(loop.run(_make_plan(11)))
        assert len(report.steps) == 10, f"应在 10 步截断: {len(report.steps)}"
        assert report.partial is True
        assert report.degraded is True

    def test_guard_strategy_check_timeout_90s(self):
        """§4.5-3a: 策略检查路径 90s 预算 -> asyncio.TimeoutError + degraded。

        mock 步执行挂起超过预算（用 0.05s 模拟测试，不真等 90s——
        通过 time_budget_override 注入小预算验证同一超时机制）。
        """
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                         allowed_tools={"t"},
                         time_budget_s=0.05)  # 机制验证注入；生产=llm_timeouts 常量
        async def _hang(*a, **kw):
            await asyncio.sleep(5)
        loop._execute_step = _hang
        report = asyncio.run(loop.run(_make_plan(1)))
        assert report.degraded is True
        assert any("timeout" in (s.error or "").lower() for s in report.steps)

    def test_time_budget_constants_aligned_with_llm_timeouts(self):
        """§4-护栏表: 分级超时对齐 llm_timeouts.py 常量（90s/120s 单源）。"""
        loop_sc = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                            allowed_tools={"t"}, profile="strategy_check")
        loop_dr = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                            allowed_tools={"t"}, profile="design_report")
        assert loop_sc.time_budget_s == llm_timeouts.STRATEGY_CHECK_READ_S == 90.0
        assert loop_dr.time_budget_s == llm_timeouts.DESIGN_REPORT_READ_S == 120.0

    def test_guard_design_report_timeout_120s(self):
        """§4.5-3b: 设计报告路径 120s 预算同机制（注入小预算验证）。"""
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                         allowed_tools={"t"}, time_budget_s=0.05)
        async def _hang(*a, **kw):
            await asyncio.sleep(5)
        loop._execute_step = _hang
        report = asyncio.run(loop.run(_make_plan(1)))
        assert report.degraded is True


class TestAgentLoopWriteConfirm:
    def test_guard_write_requires_confirm(self):
        """§4.5-6: 写操作（调仓/下单类）confirm=False -> 拒绝执行。"""
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"place_order"}),
                         allowed_tools={"place_order"})
        step = PlanStep(tool="place_order", arguments={"symbol": "510300"},
                        reason="r", write=True)
        report = asyncio.run(loop.run([step], confirm=False))
        assert report.steps[0].error and "not confirmed" in report.steps[0].error
        assert report.degraded is True

    def test_write_with_confirm_executes(self):
        """写操作 confirm=True 放行。"""
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"place_order"}),
                         allowed_tools={"place_order"})
        loop._execute_step = AsyncMock(return_value={"data": "ok", "source": "m"})
        step = PlanStep(tool="place_order", arguments={"symbol": "510300"},
                        reason="r", write=True)
        report = asyncio.run(loop.run([step], confirm=True))
        assert report.steps[0].error is None


class TestAgentLoopOutput:
    def test_guard_output_schema_validates(self):
        """§4.5-7: 步输出缺 source -> ValidationError（引用溯源强制）。"""
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                         allowed_tools={"t"})
        loop._execute_step = AsyncMock(return_value={"data": 1})  # 缺 source
        with pytest.raises(Exception):  # pydantic ValidationError
            asyncio.run(loop.run(_make_plan(1), validate_output=True))

    def test_guard_data_missing_marked(self):
        """§4.5-8: 工具返回 data=None -> 步标注 data_missing（不编造）。"""
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                         allowed_tools={"t"})
        loop._execute_step = AsyncMock(return_value={"data": None, "source": "s",
                                                     "degraded": True})
        report = asyncio.run(loop.run(_make_plan(1), validate_output=True))
        assert report.steps[0].data_missing is True
        assert report.summary_note and "数据缺失" in report.summary_note

    def test_happy_path_full_report(self):
        """正常路径: 3 步全成功 -> 非降级完整报告 + trace 落点。"""
        loop = AgentLoop(planner=None, executor=Executor(allowed_tools={"t"}),
                         allowed_tools={"t"})
        loop._execute_step = AsyncMock(return_value={"data": 1, "source": "m",
                                                     "degraded": False})
        report = asyncio.run(loop.run(_make_plan(3), validate_output=True))
        assert len(report.steps) == 3
        assert report.degraded is False
        assert report.partial is False
        assert report.trace_id
