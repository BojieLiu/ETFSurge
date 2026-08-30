"""MCP Server 共享设施：统一输出信封 + handler 直调测试钩子（v7 P0）。

_envelope：所有工具输出遵循 {data, as_of, source, degraded} 约定
（REVIEW-R1-9：沿用 MarketDataHub 既有 envelope 语义，缺失字段填 None，
降级链切换标 degraded=true，数据缺失标 data=None——不编造）。

serialize_result：把 Python 对象转成 MCP TextContent（json.dumps，
ensure_ascii=False 保留中文可读性，default=str 兜底 datetime 等）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from mcp.types import TextContent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def envelope(data: Any, source: str | None = None,
             degraded: bool = False, as_of: str | None = None) -> dict:
    """统一输出信封。data=None 表示该维度数据缺失（不编造）。"""
    return {
        "data": data,
        "as_of": as_of or _now_iso(),
        "source": source,
        "degraded": degraded,
    }


def serialize_result(payload: Any) -> list[TextContent]:
    """任意 payload -> 单个 TextContent（MCP call_tool 返回约定）。"""
    return [TextContent(type="text", text=json.dumps(
        payload, ensure_ascii=False, default=str,
    ))]


def error_result(message: str, *, source: str | None = None) -> list[TextContent]:
    """失败语义：如实返回错误信封（degraded=true, data=None），不编造数据。"""
    return serialize_result(envelope(data=None, source=source, degraded=True,
                                     as_of=_now_iso()) | {"error": message})
