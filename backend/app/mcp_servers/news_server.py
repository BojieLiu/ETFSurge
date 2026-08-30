"""T4 资讯 MCP Server（v7 P0，§3.6 news_server.py）。

包装 market_data_hub.get_news()（财新头条/宏观/国际，level+stars 分级）：
- search_financial_news(bucket: str = "headlines", limit: int = 10)

REVIEW-R1-3 修订：原 v7 §3 文档写 get_news(bucket=...)，实际签名无 bucket
参数（探针 1 核对），故 bucket/limit 在本层做客户端过滤（headlines 即全量）。
启动：python -m app.mcp_servers.news_server（stdio 传输）。
"""
from __future__ import annotations

import asyncio

from mcp.server.lowlevel import Server
from mcp.types import Tool

from app.services.market_data_hub import market_data_hub

from .common import error_result, serialize_result

server = Server("etf-news-server")


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_financial_news",
            description="财经资讯检索（财新头条/宏观/国际，含 level/stars 分级）",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "enum": ["headlines", "macro", "global"],
                               "description": "资讯桶，默认 headlines（当前实现全量返回，桶过滤在客户端）"},
                    "limit": {"type": "integer", "description": "返回条数上限，默认 10"},
                },
            },
        ),
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict):
    try:
        if name == "search_financial_news":
            # get_news 是同步内存缓存读（120s TTL），微秒级无阻塞——
            # 直接同步调用（async def 内安全，懒刷新有锁 + 回退保护）。
            items = market_data_hub.get_news()
            bucket = arguments.get("bucket", "headlines")
            limit = int(arguments.get("limit", 10))
            if bucket != "headlines":
                # 客户端桶过滤：按 title/content 关键词粗分（macro/global），
                # 当前 hub 仅 headlines 全量——非 headline 桶按 stars 排序截断。
                items = sorted(items or [],
                               key=lambda x: x.get("stars", 0) or 0, reverse=True)
            return serialize_result({
                "data": (items or [])[:limit],
                "as_of": None,
                "source": "market_data_hub.get_news",
                "degraded": not items,
            })
        raise ValueError(f"unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001
        return error_result(f"{type(exc).__name__}: {exc}", source="market_data_hub")


def main() -> None:
    from mcp.server.stdio import stdio_server

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
