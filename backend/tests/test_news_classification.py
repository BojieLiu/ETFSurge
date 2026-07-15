"""TDD tests for issue 4 (news importance level + stars).

levistock is mocked; classification is keyword-based, no network needed.
"""
from unittest.mock import MagicMock

import pytest

from app.fetchers import levistock_fetcher as lvmod
from app.fetchers.levistock_fetcher import classify_news_level, fetch_cailian_telegraph
from app.fetchers.news_fetcher import fetch_macro_news, fetch_global_news
from app.services.cache_service import sync_memory_cache


def test_classify_news_level_keywords():
    assert classify_news_level("【重大】央行紧急降准") == 5
    assert classify_news_level("突发：地缘冲突升级") == 5
    assert classify_news_level("利好：某板块业绩超预期") == 4
    assert classify_news_level("利空：指数暴跌") == 3
    assert classify_news_level("提醒：关注赎回风险") == 2
    assert classify_news_level("某普通上市公司公告") == 2  # 公告 → 关注


def test_fetch_cailian_telegraph_attaches_level_stars(monkeypatch):
    sync_memory_cache.clear()
    fake_lv = MagicMock()
    fake_lv.news_telegraph_cls.return_value = [
        {"title": "重大利好：央行降准", "content": "x", "time": "10:00", "level": 5},
        {"title": "某普通新闻", "content": "y", "time": "11:00"},
    ]
    monkeypatch.setattr(lvmod, "lv", fake_lv)

    items = fetch_cailian_telegraph(10)
    assert len(items) == 2
    assert items[0]["level"] == 5
    assert items[0]["stars"] == 5
    assert "level" in items[1] and "stars" in items[1]
    assert items[1]["stars"] == items[1]["level"]


def test_fetch_macro_news_attaches_level(monkeypatch):
    import app.fetchers.news_fetcher as nfmod
    sync_memory_cache.clear()
    monkeypatch.setattr(nfmod, "fetch_cailian_telegraph",
                        lambda n: [{"title": "利好：政策加码", "content": "x", "time": "t", "source": "财联社"}])
    items = fetch_macro_news()
    assert items
    assert all("level" in it and "stars" in it for it in items)


def test_fetch_global_news_attaches_level(monkeypatch):
    import app.fetchers.news_fetcher as nfmod
    sync_memory_cache.clear()
    monkeypatch.setattr(nfmod, "_ak", lambda fn: [
        {"title": "利空：海外股市大跌", "content": "x", "source": "ak"}
    ])
    items = fetch_global_news()
    assert items
    assert all("level" in it and "stars" in it for it in items)
