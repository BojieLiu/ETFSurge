"""T1 行情 MCP Server（v7 P0，§3.6 quote_server.py）。

包装 market_data_hub 降级链（mootdx/Sina 多源）与 kline 缓存：
- get_realtime_quote(symbols: list[str], asset_type: str = "A")
- get_history_bars(symbol: str, max_age: int = 300)

启动：python -m app.mcp_servers.quote_server（stdio 传输）。
"""
from __future__ import annotations

import asyncio

from mcp.server.lowlevel import Server
from mcp.types import Tool

from app.services.market_data_hub import market_data_hub

from .common import error_result, serialize_result

server = Server("etf-quote-server")


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_realtime_quote",
            description="实时行情快照（带 as_of/source/degraded 信封，多源降级链）",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {"type": "array", "items": {"type": "string"},
                                "description": "标的代码列表，如 ['510300','512890']"},
                    "asset_type": {"type": "string", "enum": ["A", "HK", "US"],
                                   "description": "市场类型，默认 A"},
                },
                "required": ["symbols"],
            },
        ),
        Tool(
            name="get_history_bars",
            description="K 线历史（日/分钟线缓存，返回 list[dict] 行数据）",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "标的代码"},
                    "max_age": {"type": "integer",
                                "description": "缓存最大年龄（秒），默认 300"},
                },
                "required": ["symbol"],
            },
        ),
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict):
    try:
        if name == "get_realtime_quote":
            quotes = await market_data_hub.get_realtime(
                arguments["symbols"],
                asset_type=arguments.get("asset_type", "A"),
            )
            degraded = any(q.get("degraded") for q in quotes if isinstance(q, dict))
            # hub 返回的单条 quote 不带 source（v7 P2 evals q002 实测）——
            # 信封 source 用真实链路名兜底（调用确实经过 market_data_hub）
            source = next((q.get("source") for q in quotes
                           if isinstance(q, dict) and q.get("source")), None) \
                or "market_data_hub"
            return serialize_result({
                "data": quotes,
                "as_of": next((q.get("as_of") for q in quotes
                               if isinstance(q, dict) and q.get("as_of")), None),
                "source": source,
                "degraded": degraded,
            })
        if name == "get_history_bars":
            # get_kline_rows 是同步纯内存缓存读（dict.get + TTL 检查），
            # 微秒级无阻塞——直接同步调用（async def 内安全，不涉网络 I/O）。
            rows = market_data_hub.get_kline_rows(
                arguments["symbol"], max_age=arguments.get("max_age", 300),
            )
            return serialize_result({
                "data": rows,
                "as_of": None,
                "source": "kline_cache",
                "degraded": rows is None,
            })
        raise ValueError(f"unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001 - MCP 层兜底：失败不编造
        return error_result(f"{type(exc).__name__}: {exc}")


def main() -> None:
    from mcp.server.stdio import stdio_server

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
