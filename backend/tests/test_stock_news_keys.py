"""
P2-3 (R4-06): /news/stock/{symbol} 中文键归一化。

- fetch_stock_news 对东方财富 stock_news_em 的中文键（新闻标题/新闻内容/发布时间/
  新闻来源/新闻链接）归一化为英文键（title/content/time/source/url），
  与 headlines/macro/global 契约一致。

mock akshare，无网络。
"""

from unittest.mock import patch

from app.fetchers import news_fetcher


def test_stock_news_chinese_keys_normalized(monkeypatch):
    """P2-3: 中文键输入 → 英文键输出。"""
    cn_items = [
        {"新闻标题": "半导体大涨", "新闻内容": "板块涨幅居前",
         "发布时间": "2026-08-01 10:00:00", "新闻来源": "东方财富",
         "新闻链接": "http://example.com/1"},
        {"新闻标题": "黄金创新高", "新闻内容": "避险需求升温",
         "发布时间": "2026-08-01 09:30:00", "新闻来源": "东方财富",
         "新闻链接": "http://example.com/2"},
    ]

    def _fake_ak(fn, timeout=None):
        return cn_items

    def _fake_cached(key, producer, **kwargs):
        return producer()

    with patch.object(news_fetcher, "_ak", _fake_ak), \
         patch.object(news_fetcher, "cached", _fake_cached), \
         patch.object(news_fetcher, "fetch_cailian_telegraph", lambda n: []):
        items = news_fetcher.fetch_stock_news("159338")

    assert items, "应有归一化后的新闻"
    first = items[0]
    for en_key in ("title", "content", "time", "source", "url"):
        assert en_key in first, f"缺失英文键 {en_key}: {list(first.keys())}"
        assert first[en_key], f"英文键 {en_key} 值为空"
    assert not any("新闻标题" in i for i in items), "中文键应全部替换"
    # _attach_level 附加 level/stars
    assert "level" in first and "stars" in first


def test_english_keys_untouched(monkeypatch):
    """P2-3: 已是英文键的输入原样保留。"""
    en_items = [
        {"title": "test", "content": "c", "time": "2026-08-01 10:00:00",
         "source": "s", "url": "http://x"},
    ]

    def _fake_ak(fn, timeout=None):
        return en_items

    def _fake_cached(key, producer, **kwargs):
        return producer()

    with patch.object(news_fetcher, "_ak", _fake_ak), \
         patch.object(news_fetcher, "cached", _fake_cached), \
         patch.object(news_fetcher, "fetch_cailian_telegraph", lambda n: []):
        items = news_fetcher.fetch_stock_news("159338")

    assert items[0]["title"] == "test"
    assert "新闻标题" not in items[0]


def test_no_chinese_keys_remain_after_normalization(monkeypatch):
    """R5-2-2: 归一化后只输出英文键——其他中文键（关键词等）全部删除，不得残留。"""
    cn_items = [
        {"新闻标题": "半导体大涨", "新闻内容": "板块涨幅居前",
         "发布时间": "2026-08-01 10:00:00", "新闻来源": "东方财富",
         "新闻链接": "http://example.com/1", "关键词": "半导体,芯片",
         "文章来源": "东方财富网"},
        {"新闻标题": "黄金创新高", "新闻内容": "避险需求升温",
         "发布时间": "2026-08-01 09:30:00", "新闻来源": "东方财富",
         "新闻链接": "http://example.com/2", "关键词": "黄金,避险"},
    ]

    def _fake_ak(fn, timeout=None):
        return cn_items

    def _fake_cached(key, producer, **kwargs):
        return producer()

    with patch.object(news_fetcher, "_ak", _fake_ak), \
         patch.object(news_fetcher, "cached", _fake_cached), \
         patch.object(news_fetcher, "fetch_cailian_telegraph", lambda n: []):
        items = news_fetcher.fetch_stock_news("159338")

    allowed = {"id", "title", "content", "time", "sort_time", "url",
               "source", "level", "stars", "ai_summary"}
    for item in items:
        for key in item.keys():
            # 任何含中文字符的键不得残留（契约：键集 == headlines 全英文键）
            assert not any("\u4e00" <= ch <= "\u9fff" for ch in key), \
                f"R5-2-2 中文键残留: {key!r} in {list(item.keys())}"
            assert key in allowed, f"R5-2-2 非契约键残留: {key!r}"
    # 归一化后关键英文键存在
    first = items[0]
    for en_key in ("title", "content", "time", "source", "url"):
        assert en_key in first, f"缺失英文键 {en_key}: {list(first.keys())}"
