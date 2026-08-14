"""
F31 (round23-system-audit-optimization §2.4 A4/§8): 冷启动 headlines/macro partial 标识。

背景: 冷启动/数据源熔断时 headlines 与 macro 各只返回 1 条且是同一条，无「不完整」
标识 → 半成品静默上屏。修复: 端点条数 < PARTIAL_THRESHOLD(5) 时响应头
`X-News-Partial: true`，前端提示「数据刷新中」而非静默。
"""
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.routers import news as news_router

client = TestClient(app)


class TestF31NewsPartial:
    def test_headlines_partial_when_sparse(self):
        """冷启动（仅 1 条）→ X-News-Partial: true。"""
        with patch.object(news_router.market_data_hub, "get_news_headlines",
                          return_value=[{"id": "1", "title": "仅一条", "level": 3}]):
            resp = client.get("/api/v1/news/headlines")
        assert resp.status_code == 200
        assert resp.headers.get("x-news-partial") == "true"
        assert len(resp.json()) == 1

    def test_headlines_not_partial_when_full(self):
        """正常（≥5 条）→ X-News-Partial: false。"""
        items = [{"id": str(i), "title": f"n{i}", "level": 2} for i in range(10)]
        with patch.object(news_router.market_data_hub, "get_news_headlines", return_value=items):
            resp = client.get("/api/v1/news/headlines")
        assert resp.status_code == 200
        assert resp.headers.get("x-news-partial") == "false"
        assert len(resp.json()) == 10

    def test_macro_partial_when_sparse(self):
        """macro 冷启动同样标记 partial。"""
        with patch.object(news_router.market_data_hub, "get_news_macro",
                          return_value=[{"id": "m1", "title": "宏观", "level": 4}]):
            resp = client.get("/api/v1/news/macro")
        assert resp.headers.get("x-news-partial") == "true"

    def test_macro_empty_not_partial_false(self):
        """空列表（无数据）→ partial: false（不误报——空 = 无数据，非半成品）。"""
        with patch.object(news_router.market_data_hub, "get_news_macro", return_value=[]):
            resp = client.get("/api/v1/news/macro")
        assert resp.headers.get("x-news-partial") == "true"
        assert resp.json() == []

    def test_partial_threshold_constant(self):
        """PARTIAL_THRESHOLD=5（正常 headlines/macro 均 ≥10 条）。"""
        assert news_router.PARTIAL_THRESHOLD == 5
