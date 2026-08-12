# -*- coding: utf-8 -*-
"""P2-9 (round16 3.9): 契约偏差收口 B1/B2/B6 的负向断言。

① B1: SymbolAnalysisRequest 显式声明 market 字段——前端传 market 被解析（不再 extra 忽略）；
② B2: design-async 响应含 design_id 字段；
③ B6: WatchlistPanel change_pct=null 不标红涨（源码级断言）。
"""
import pytest


class TestP29ContractFieldCompleteness:
    def test_symbol_analysis_request_parses_market(self):
        """B1: SymbolAnalysisRequest 接受 market 字段（Pydantic 显式声明）。"""
        from app.routers.analysis import SymbolAnalysisRequest

        req = SymbolAnalysisRequest(symbol="00700", name="腾讯控股", asset_type="HK", market="HK")
        assert req.market == "HK", "market 字段应被 Pydantic 解析（旧实现 extra 静默忽略）"

    @pytest.mark.asyncio
    async def test_design_async_response_has_design_id(self):
        """B2: design-async 202 响应含 design_id 字段（null 允许，前端读字段不 undefined）。"""
        from unittest.mock import patch, AsyncMock

        from fastapi.testclient import TestClient
        from app.main import app

        class _FakeTaskMgr:
            async def create_task(self, task_type="design", params=None):
                return {"task_id": 999, "created_at": "2026-08-11T12:00:00Z"}

        with patch("app.tasks.task_manager.task_manager", _FakeTaskMgr()), \
             patch("app.tasks.task_manager.design_worker", new=AsyncMock()):
            client = TestClient(app)
            resp = client.post("/api/v1/portfolio/design-async", json={"capital": 500000})
        assert resp.status_code == 202
        body = resp.json()
        assert "design_id" in body, f"design-async 响应应含 design_id: {body}"
        assert body["task_id"] == 999


class TestP29B6ChangePctNull:
    def test_watchlist_panel_null_change_pct_not_red(self):
        """B6: WatchlistPanel 涨跌着色判空——change_pct=null 不渲染红涨（源码级断言）。"""
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                            "components", "market", "WatchlistPanel.vue")
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src",
                                "components", "market", "WatchlistPanel.vue")
        src = open(path, encoding="utf-8").read()
        assert "change_pct != null && item.realtime.change_pct >= 0" in src, \
            "change_pct=null 时应判空（不得误判红涨）"
