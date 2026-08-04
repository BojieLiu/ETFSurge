"""
TDD: 新闻管道降级链测试。

覆盖 P1.3-P1.5：新浪源 → akshare CLS → 财联社兜底 的三级降级行为。
所有外部网络调用通过 monkeypatch 隔离。
"""
from unittest.mock import MagicMock

import pytest

from app.fetchers.news_fetcher import fetch_macro_news
from app.services.cache_service import sync_memory_cache


class TestMacroNewsDegradationChain:
    """fetch_macro_news() 三级降级链：新浪 → CLS → 财联社。"""

    def test_primary_source_sina_returns_results(self, monkeypatch):
        """第一优先级新浪源返回数据时，不应触发降级。"""
        import app.fetchers.news_fetcher as nfmod
        sync_memory_cache.clear()

        # Mock 新浪源返回真实数据
        monkeypatch.setattr(nfmod, "fetch_sina_roll_news", lambda n: [
            {"title": "宏观数据超预期，经济稳增长可期", "content": "x", "time": "t", "source": "新浪财经"}
        ])
        # Mock CLS 以确保不会被调用
        cls_called = False
        def _mock_cls():
            nonlocal cls_called
            cls_called = True
            return []
        monkeypatch.setattr(nfmod, "_ak", lambda fn: _mock_cls())
        # Mock 财联社
        monkeypatch.setattr(nfmod, "fetch_cailian_telegraph", lambda n: [])

        items = fetch_macro_news()
        assert len(items) >= 1
        assert items[0]["source"] == "新浪财经"
        assert not cls_called, "新浪有数据时不应调用 CLS 降级"

    def test_fallback_to_cls_when_sina_empty(self, monkeypatch):
        """新浪源返回空时，应降级到 CLS。"""
        import app.fetchers.news_fetcher as nfmod
        sync_memory_cache.clear()

        monkeypatch.setattr(nfmod, "fetch_sina_roll_news", lambda n: [])
        monkeypatch.setattr(nfmod, "_ak", lambda fn: [
            {"title": "东方财富宏观：央行逆回购操作", "content": "x", "time": "t", "source": "东方财富"}
        ])
        monkeypatch.setattr(nfmod, "fetch_cailian_telegraph", lambda n: [])

        items = fetch_macro_news()
        assert len(items) >= 1
        assert "东方财富" in items[0].get("source", "")

    def test_fallback_to_cailian_when_all_empty(self, monkeypatch):
        """新浪和 CLS 都空时，兜底到财联社。"""
        import app.fetchers.news_fetcher as nfmod
        sync_memory_cache.clear()

        monkeypatch.setattr(nfmod, "fetch_sina_roll_news", lambda n: [])
        monkeypatch.setattr(nfmod, "_ak", lambda fn: [])
        monkeypatch.setattr(nfmod, "fetch_cailian_telegraph", lambda n: [
            {"title": "财联社快讯：央行开展逆回购", "content": "x", "time": "t", "source": "财联社"}
        ])

        items = fetch_macro_news()
        assert len(items) >= 1
        assert items[0]["source"] == "财联社"

    def test_all_sources_fail_returns_empty(self, monkeypatch):
        """全部源失败时返回空列表。"""
        import app.fetchers.news_fetcher as nfmod
        sync_memory_cache.clear()

        monkeypatch.setattr(nfmod, "fetch_sina_roll_news", lambda n: [])
        monkeypatch.setattr(nfmod, "_ak", lambda fn: [])
        monkeypatch.setattr(nfmod, "fetch_cailian_telegraph", lambda n: [])

        items = fetch_macro_news()
        # _attach_level + _dedupe + [] 最终返回空
        assert items == [] or all(
            not it.get("title") for it in items
        )
