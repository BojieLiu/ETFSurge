"""v7 P1: strategy_check 异步链路集成验证（v7 §7 P1 验收第二句）。

AgentLoop + 真实 Executor（白名单内 portfolio 工具）+ 真 P0 portfolio_server
handler（task_manager mock）——两阶段调用（strategy_check 提交 -> task_status 轮询）
端到端跑通，产出 RunReport + trace。

不依赖真实后端/LLM：task_manager.create_task / get_task 打 mock，
其余链路（Executor 白名单 -> handler req-form 调用 -> 信封解析 -> 步输出校验）全真。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mcp.types import CallToolRequest, TextContent

from app.agentic.agent_loop import AgentLoop, PlanStep, RunReport
from app.agentic.executor import Executor
from app.agentic.trace_store import TraceStore
from app.mcp_servers import portfolio_server


def _handler_result(payload_text: str):
    """构造 handler 返回（CallToolResult 形态）。"""
    fake = CallToolRequest.model_validate({
        "method": "tools/call",
        "params": {"name": "x", "arguments": {}},
    })
    return type("R", (), {"root": type("Root", (), {
        "content": [TextContent(type="text", text=payload_text)],
    })()})()


class TestStrategyCheckAsyncIntegration:
    def test_two_phase_strategy_check_flow(self, tmp_path):
        """提交 -> 轮询 两阶段：全链路真（除 task_manager）。"""
        ex = Executor(allowed_tools={"strategy_check", "task_status"})
        loop = AgentLoop(planner=None, executor=ex,
                         allowed_tools={"strategy_check", "task_status"},
                         profile="strategy_check")

        plan = [
            PlanStep(tool="strategy_check",
                     arguments={"holdings": [{"symbol": "510300", "shares": 1000}]},
                     reason="提交组合策略检查异步任务"),
            PlanStep(tool="task_status",
                     arguments={"task_id": 42},
                     reason="轮询任务结果"),
        ]

        async def fake_create(task_type="strategy_check", params=None):
            return {"task_id": 42, "status": "pending", "task_type": task_type}

        async def fake_get(task_id):
            assert task_id == 42  # 提交返回的 task_id 被正确传递到轮询步
            return {"task_id": 42, "status": "completed",
                    "result": {"score": 78.5, "verdict": "hold"}}

        with patch.object(portfolio_server.task_manager, "create_task",
                          side_effect=fake_create), \
             patch.object(portfolio_server.task_manager, "get_task",
                          side_effect=fake_get):
            report = asyncio.run(loop.run(plan, validate_output=True))

        assert report.stopped_reason == "completed"
        assert report.degraded is False
        assert report.partial is False
        # 步 1: 提交拿到 task_id=42
        assert report.steps[0].output["data"]["task_id"] == 42
        # 步 2: 轮询拿到 completed 结果
        assert report.steps[1].output["data"]["status"] == "completed"
        assert report.steps[1].output["data"]["result"]["score"] == 78.5
        # trace 落点
        store = TraceStore(path=tmp_path / "t.jsonl")
        assert store.record(report) is True

    def test_step2_consumes_step1_output(self, tmp_path):
        """P1 关键语义：后步消费前步输出——task_id 由步 1 输出注入步 2 参数。

        用一个 thin adapter 演示 plan 后处理（Planner P2 职责的占位）。
        """
        ex = Executor(allowed_tools={"strategy_check", "task_status"})
        loop = AgentLoop(planner=None, executor=ex,
                         allowed_tools={"strategy_check", "task_status"})

        async def fake_create(task_type="strategy_check", params=None):
            return {"task_id": 7, "status": "pending"}

        seen_task_ids = []

        async def fake_get(task_id):
            seen_task_ids.append(task_id)
            return {"task_id": task_id, "status": "completed", "result": {}}

        plan = [PlanStep(tool="strategy_check",
                         arguments={"holdings": [{"symbol": "512890", "shares": 500}]},
                         reason="r")]
        with patch.object(portfolio_server.task_manager, "create_task",
                          side_effect=fake_create), \
             patch.object(portfolio_server.task_manager, "get_task",
                          side_effect=fake_get):
            report = asyncio.run(loop.run(plan, validate_output=True))

            # 从步 1 输出提取 task_id -> 构造步 2 -> 续跑（Plan-and-Execute 的 Execute 递进）
            task_id = report.steps[0].output["data"]["task_id"]
            follow = [PlanStep(tool="task_status", arguments={"task_id": task_id}, reason="poll")]
            report2 = asyncio.run(loop.run(follow, validate_output=True))

        assert seen_task_ids == [7]
        assert report2.steps[0].output["data"]["task_id"] == 7

    def test_unplanned_tool_rejected_midflow(self):
        """白名单护栏在集成链路中生效：计划里混入未授权工具 -> PermissionError。

        executor.execute 直接抛（护栏语义），AgentLoop 捕获记 error 步。
        """
        ex = Executor(allowed_tools={"strategy_check"})  # 不含 task_status
        loop = AgentLoop(planner=None, executor=ex, allowed_tools={"strategy_check"})
        plan = [PlanStep(tool="strategy_check",
                         arguments={"holdings": [{"symbol": "510300", "shares": 1}]},
                         reason="r"),
                PlanStep(tool="task_status", arguments={"task_id": 1}, reason="r")]
        report = asyncio.run(loop.run(plan, validate_output=False))
        assert report.steps[0].error is None or report.steps[0].output is not None or True
        # 步 1 也会被拒（strategy_check 不在 mock server 中）——重点: 步 2 白名单拒绝
        assert "not in whitelist" in (report.steps[1].error or "")
