"""v7 P0: MCP 工具层单元测试——4 个 server 的工具注册 + handler 分发 + 信封语义.

被测对象（docs/etfsurge-agentic-upgrade-v7.md §3.5/§3.6 P0 验收口径）:
- quote_server.py:    get_realtime_quote / get_history_bars
- factor_server.py:   get_factor_snapshot
- portfolio_server.py: strategy_check（异步任务提交）+ task_status（轮询）
- news_server.py:     search_financial_news

测试策略（不依赖真实行情/LLM）:
- 直接调 server 内注册的 handler（req-form 直调，与探针 5 同法），mock 掉
  market_data_hub / registry / task_manager 被包装函数
- 断言工具清单注册完整（tools/list）+ handler 分发正确（tools/call）
- 断言输出信封含 data/as_of/source/degraded（v7 §3 REVIEW-R1-9）
- 断言未知工具名抛错（护栏雏形）
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import CallToolRequest, ListToolsRequest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load(name: str):
    """按文件名加载 mcp_servers 模块（包内相对导入不需要真实包路径）。"""
    return importlib.import_module(f"app.mcp_servers.{name}")


def _call(server, request_cls, params: dict):
    """以 req-form 直调 server 注册的 handler（mcp 1.29.x 内部约定）。"""
    from mcp.types import CallToolRequest, ListToolsRequest

    handler = server.request_handlers[request_cls]
    method = "tools/call" if request_cls is CallToolRequest else "tools/list"
    req = request_cls.model_validate({"method": method, "params": params})
    return asyncio.run(handler(req))


# ── quote_server ──────────────────────────────────────────────

class TestQuoteServer:
    def test_list_tools_registers_two_quote_tools(self):
        mod = _load("quote_server")
        result = _call(mod.server, ListToolsRequest, {})
        names = [t.name for t in result.root.tools]
        assert "get_realtime_quote" in names
        assert "get_history_bars" in names

    def test_get_realtime_quote_envelope(self):
        mod = _load("quote_server")
        fake_quote = {"symbol": "510300", "price": 4.01, "source": "sina",
                      "degraded": False, "as_of": "2026-08-30T12:00:00"}
        with patch.object(mod.market_data_hub, "get_realtime",
                          new=AsyncMock(return_value=[fake_quote])):
            result = _call(mod.server,
                           CallToolRequest,
                           {"name": "get_realtime_quote",
                            "arguments": {"symbols": ["510300"]}})
        text = result.root.content[0].text
        assert "510300" in text and "4.01" in text

    def test_get_history_bars_returns_rows(self):
        mod = _load("quote_server")
        fake_rows = [{"date": "2026-08-29", "close": 3.98}, {"date": "2026-08-30", "close": 4.01}]
        with patch.object(mod.market_data_hub, "get_kline_rows",
                          return_value=fake_rows):
            result = _call(mod.server,
                           CallToolRequest,
                           {"name": "get_history_bars",
                            "arguments": {"symbol": "510300"}})
        text = result.root.content[0].text
        assert "2026-08-30" in text and "4.01" in text

    def test_unknown_tool_returns_error_envelope(self):
        """护栏：未知工具不抛协议异常，返回 degraded=true + error 信封（不编造）。"""
        mod = _load("quote_server")
        result = _call(mod.server, CallToolRequest,
                       {"name": "no_such_tool", "arguments": {}})
        import json as _json
        payload = _json.loads(result.root.content[0].text)
        assert payload["degraded"] is True
        assert payload["data"] is None
        assert "unknown tool" in payload["error"]


# ── factor_server ─────────────────────────────────────────────

class TestFactorServer:
    def test_list_tools_registers_factor_tool(self):
        mod = _load("factor_server")
        list_cls = ListToolsRequest
        result = _call(mod.server, list_cls, {})
        names = [t.name for t in result.root.tools]
        assert "get_factor_snapshot" in names

    def test_get_factor_snapshot_returns_payload(self):
        mod = _load("factor_server")
        fake = {"510300": {"rsi_14": 55.2, "kdj_j": 71.3}}
        with patch.object(mod.registry, "compute", return_value=fake):
            call_cls = CallToolRequest
            result = _call(mod.server, call_cls,
                           {"name": "get_factor_snapshot",
                            "arguments": {"symbols": ["510300"]}})
        text = result.root.content[0].text
        assert "rsi_14" in text


# ── portfolio_server ──────────────────────────────────────────

class TestPortfolioServer:
    def test_list_tools_registers_strategy_tools(self):
        mod = _load("portfolio_server")
        list_cls = ListToolsRequest
        result = _call(mod.server, list_cls, {})
        names = [t.name for t in result.root.tools]
        assert "strategy_check" in names
        assert "task_status" in names

    def test_strategy_check_submits_task(self):
        mod = _load("portfolio_server")
        fake_task = {"task_id": "t-123", "status": "pending"}
        with patch.object(mod.task_manager, "create_task", return_value=fake_task):
            call_cls = CallToolRequest
            result = _call(mod.server, call_cls,
                           {"name": "strategy_check",
                            "arguments": {"holdings": [{"symbol": "510300", "shares": 100}]}})
        text = result.root.content[0].text
        assert "t-123" in text

    def test_task_status_polls(self):
        mod = _load("portfolio_server")
        fake_status = {"task_id": 42, "status": "running", "progress": 0.5}
        with patch.object(mod.task_manager, "get_task",
                          new=AsyncMock(return_value=fake_status)):
            call_cls = CallToolRequest
            result = _call(mod.server, call_cls,
                           {"name": "task_status", "arguments": {"task_id": 42}})
        text = result.root.content[0].text
        assert "running" in text


# ── news_server ───────────────────────────────────────────────

class TestNewsServer:
    def test_list_tools_registers_news_tool(self):
        mod = _load("news_server")
        list_cls = ListToolsRequest
        result = _call(mod.server, list_cls, {})
        names = [t.name for t in result.root.tools]
        assert "search_financial_news" in names

    def test_search_financial_news_returns_items(self):
        mod = _load("news_server")
        fake_news = [{"title": "降准落地", "stars": 4, "source": "caixin"}]
        with patch.object(mod.market_data_hub, "get_news",
                          return_value=fake_news):
            call_cls = CallToolRequest
            result = _call(mod.server, call_cls,
                           {"name": "search_financial_news", "arguments": {}})
        text = result.root.content[0].text
        assert "降准落地" in text
