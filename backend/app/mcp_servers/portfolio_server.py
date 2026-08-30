"""T3 组合 MCP Server（v7 P0，§3.6 portfolio_server.py）。

包装现有异步策略检查链路（round37 长稳实证的 strategy-check-async）：
- strategy_check(holdings: list[dict]) -> 提交任务返回 task_id
- task_status(task_id: str) -> 轮询任务状态/结果

两阶段调用（REVIEW-R1-3 修订：异步任务 + task_id 轮询，非同步 analyze_portfolio）。
启动：python -m app.mcp_servers.portfolio_server（stdio 传输）。
"""
from __future__ import annotations

import asyncio

from mcp.server.lowlevel import Server
from mcp.types import Tool

from app.tasks.task_manager import task_manager

from .common import error_result, serialize_result

server = Server("etf-portfolio-server")


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return [
        Tool(
            name="strategy_check",
            description="提交组合策略检查异步任务（返回 task_id，用 task_status 轮询）",
            inputSchema={
                "type": "object",
                "properties": {
                    "holdings": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "持仓清单 [{symbol, shares, cost}...]",
                    },
                    "params": {"type": "object",
                               "description": "可选：透传给任务的额外参数"},
                },
                "required": ["holdings"],
            },
        ),
        Tool(
            name="task_status",
            description="轮询异步任务状态（strategy_check 提交后用 task_id 查询）",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            },
        ),
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict):
    try:
        if name == "strategy_check":
            params = dict(arguments.get("params") or {})
            params.setdefault("holdings", arguments["holdings"])
            # create_task 是 async（内部写 DB + 启动 worker），await 调用。
            task = await task_manager.create_task("strategy_check", params)
            return serialize_result({
                "data": task,
                "as_of": None,
                "source": "task_manager",
                "degraded": False,
                "next_step": "poll task_status with task_id",
            })
        if name == "task_status":
            status = await task_manager.get_task(arguments["task_id"])
            return serialize_result({
                "data": status,
                "as_of": None,
                "source": "task_manager",
                "degraded": status is None,
            })
        raise ValueError(f"unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001
        return error_result(f"{type(exc).__name__}: {exc}", source="task_manager")


def main() -> None:
    from mcp.server.stdio import stdio_server

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
