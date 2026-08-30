"""T2 因子 MCP Server（v7 P0，§3.6 factor_server.py）。

包装 factor_registry.compute()（53 维核心因子 / 38 已实现，纯函数引擎）：
- get_factor_snapshot(symbols: list[str], codes: list[str] | None = None)

market_data 由调用方（agent 循环）传入或留空由 registry 内部取数。
启动：python -m app.mcp_servers.factor_server（stdio 传输）。
"""
from __future__ import annotations

import asyncio

from mcp.server.lowlevel import Server
from mcp.types import Tool

from app.factors.factor_registry import registry

from .common import error_result, serialize_result

server = Server("etf-factor-server")


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_factor_snapshot",
            description="因子快照（53 维核心因子注册表，纯函数引擎计算）",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {"type": "array", "items": {"type": "string"},
                                "description": "标的代码列表"},
                    "codes": {"type": "array", "items": {"type": "string"},
                              "description": "可选：显式因子代码清单（默认全部已实现因子）"},
                },
                "required": ["symbols"],
            },
        ),
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict):
    try:
        if name == "get_factor_snapshot":
            # registry.compute 是 async（内部可能回源行情），await 调用。
            result = await registry.compute(
                arguments["symbols"],
                codes=arguments.get("codes"),
            )
            missing = [s for s in arguments["symbols"]
                       if not (result or {}).get(s)]
            return serialize_result({
                "data": result,
                "as_of": None,
                "source": "factor_registry",
                "degraded": bool(missing),
                "missing_symbols": missing,
            })
        raise ValueError(f"unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001
        return error_result(f"{type(exc).__name__}: {exc}", source="factor_registry")


def main() -> None:
    from mcp.server.stdio import stdio_server

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
