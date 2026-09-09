# -*- coding: utf-8 -*-
"""P1-3 第一批（docs/redundant-review.md §4.2 T1）: verify_e2e 存量断言下沉 pytest。

冗余评审判定: verify_e2e.py 2685 行已长成「第二测试套件」，与 pytest 重叠。
第一批下沉 3 个纯 HTTP 契约断言模块（不依赖外部网络/数据源真值，TestClient +
mock 即可闭环）：

- section_encoding（编码验证）：实时行情/组合列表 UTF-8 无替换符（下沉为
  HTTP 层结构断言——数据源慢值在 e2e 才有意义，本测试只锁「响应字节流合法」）；
- section_fundamentals（基本面契约）：200 + symbol + daily 为 list；
- section_task_status（设计历史端点）：GET /portfolio/designs 返回 list 结构。

冻结规则（同步写入 verify_e2e.py 头部注释）: verify_e2e.py 只减不增，
新链路断言一律写 pytest（本文件即首批载体）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

_client = TestClient(app)


def _mock_db_rows(rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return cm


class TestEncodingContract:
    """原 verify_e2e section_encoding（P3.5）: 响应不得含 U+FFFD 替换符。"""

    def test_realtime_response_no_replacement_char(self, monkeypatch):
        from app.routers import market as market_router

        async def _fake_rt(symbol, asset_type="A"):
            return {"symbol": "510050", "name": "上证50ETF", "price": 3.15,
                    "change_pct": 0.32, "data_available": True}

        monkeypatch.setattr(market_router.market_data_hub, "get_asset_realtime", _fake_rt)
        r = _client.get("/api/v1/market/realtime/510050")
        assert r.status_code == 200
        assert "\ufffd" not in r.text[:2000], "实时行情响应含 U+FFFD 乱码"

    def test_portfolio_etfs_response_no_replacement_char(self, monkeypatch):
        from app.routers import portfolio as portfolio_router

        monkeypatch.setattr(
            portfolio_router, "get_etfs",
            AsyncMock(return_value=[{"symbol": "510300", "name": "沪深300ETF",
                                     "target_weight": 0.1}]),
        )
        r = _client.get("/api/v1/portfolio/etfs")
        assert r.status_code == 200
        assert "\ufffd" not in r.text[:2000], "组合列表响应含 U+FFFD 乱码"


class TestFundamentalsContract:
    """原 verify_e2e section_fundamentals（Z16/Z15/C5）: 200 + symbol + daily list。"""

    def test_fundamentals_shape(self, monkeypatch):
        from app.routers import market as market_router

        async def _fake_fundamentals(symbol):
            return {"symbol": symbol, "daily": [{"date": "2026-09-01", "close": 100.0}]}

        monkeypatch.setattr(market_router.market_data_hub, "get_market_fundamentals",
                            _fake_fundamentals)
        r = _client.get("/api/v1/market/fundamentals/510300")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert data.get("symbol"), "fundamentals 必须含 symbol 字段"
        assert isinstance(data.get("daily"), list), "daily 必须为 list"

    def test_fundamentals_none_returns_structured_empty(self, monkeypatch):
        """负向: 数据源不可用必须返回结构化空响应（Z16 契约），非 500/裸 None。"""
        from app.routers import market as market_router

        async def _none(symbol):
            return None

        monkeypatch.setattr(market_router.market_data_hub, "get_market_fundamentals", _none)
        r = _client.get("/api/v1/market/fundamentals/510300")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict) and isinstance(data.get("daily"), list)
        assert data.get("error"), "数据源不可用必须带 error 标注（诚实降级，非假成功）"


class TestTaskStatusContract:
    """原 verify_e2e section_task_status（P3.2）: /portfolio/designs 返回 list 结构。"""

    def test_designs_endpoint_returns_list(self, monkeypatch):
        from app.routers import portfolio as portfolio_router

        monkeypatch.setattr(
            portfolio_router, "_DESIGNS_LIST_CACHE", {},
        )
        monkeypatch.setattr(
            portfolio_router, "get_db",
            lambda: _mock_db_rows([{"id": 1, "status": "completed", "etf_count": 31}]),
        )
        r = _client.get("/api/v1/portfolio/designs", params={"limit": 5})
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert isinstance(data, list), f"designs 必须返回 list，实际 {type(data).__name__}"
