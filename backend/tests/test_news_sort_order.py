"""
TDD: 新闻时序优化测试。

覆盖:
1. _normalize_time 同时产出 sort_time 数值键
2. fetch_news_headlines 返回的所有条目都包含 sort_time
3. 后端按 sort_time 降序排列
4. news_refresh 的批次推送格式
5. ws.py 的 websocket 快照推送格式
"""
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.fetchers import news_fetcher
from app.fetchers.news_fetcher import (
    _normalize_time,
    _parse_time,
    fetch_news_headlines,
    fetch_macro_news,
    fetch_global_news,
    _dedupe,
    _attach_level,
    _filter_fresh,
)
from app.factors import factor_registry as fr
from app.tasks.news_refresh import refresh_news_cache
from app.services.cache_service import sync_memory_cache


class TestSortTime:
    """sort_time 数值键的添加与排序。"""

    def test_parse_time_returns_sort_time(self):
        """_parse_time 的返回应当与 sort_time 等价（Unix epoch）。"""
        raw = "2026-07-26 15:30:00"
        dt = _parse_time(raw)
        assert dt is not None
        # 验证能转成数值
        expected = int(dt.timestamp())
        assert isinstance(expected, int)
        assert expected > 0

    def test_normalize_time_adds_sort_time(self):
        """_normalize_time 应同时添加 sort_time 字段。"""
        item = {"title": "测试", "time": "2026-07-26 15:30:00"}
        _normalize_time(item)
        assert "sort_time" in item
        assert isinstance(item["sort_time"], int)
        assert item["sort_time"] > 0

    def test_normalize_time_with_timestamp(self):
        """Unix 时间戳（int）输入应正确转成 sort_time。"""
        ts = 1802410200  # 2026-07-26 15:30:00 UTC approx
        item = {"title": "测试", "ctime": ts}
        _normalize_time(item)
        assert "sort_time" in item
        assert isinstance(item["sort_time"], int)
        assert item["sort_time"] > 0
        # sort_time 与输入值在同一个时间量级（约 17亿秒）
        assert abs(item["sort_time"] - ts) < 86400  # 1天容忍时区偏移

    def test_normalize_time_with_rss_date(self):
        """RFC 2822 日期输入应正确解析。"""
        rfc = "Tue, 14 Jul 2026 10:00:00 GMT"
        item = {"title": "测试", "time": rfc}
        _normalize_time(item)
        assert "sort_time" in item
        assert isinstance(item["sort_time"], int)
        assert item["sort_time"] > 0

    def test_normalize_time_relative_minutes(self):
        """相对时间 'X分钟前' 应生成合理的 sort_time。"""
        item = {"title": "测试", "time": "5分钟前"}
        _normalize_time(item)
        assert "sort_time" in item
        now = time.time()
        assert item["sort_time"] <= int(now)
        assert item["sort_time"] >= int(now) - 360  # 5min ± 容忍

    def test_normalize_time_no_time_field(self):
        """没有时间字段的条目，sort_time 应为 0。"""
        item = {"title": "无时间"}
        _normalize_time(item)
        # 没有时间字段时，sort_time 应设为 0
        assert item.get("sort_time") == 0

    @pytest.mark.network  # F23: 真实抓取财新新闻（集成验证 sort_time 契约）
    def test_headlines_all_have_sort_time(self):
        """fetch_news_headlines 的所有条目都应包含 sort_time。"""
        sync_memory_cache.clear()
        items = fetch_news_headlines()
        assert len(items) > 0, "应有不少于 1 条新闻"
        for it in items:
            assert "sort_time" in it, f"条目 {it.get('title', '?')} 缺少 sort_time"
            assert isinstance(it["sort_time"], int), f"sort_time 应为 int"

    @pytest.mark.network  # F23: 真实抓取财新新闻（集成验证排序）
    def test_headlines_are_sorted_by_sort_time_desc(self):
        """fetch_news_headlines 按 sort_time 降序排列。"""
        sync_memory_cache.clear()
        items = fetch_news_headlines()
        assert len(items) >= 2, "至少需要 2 条来验证排序"
        sort_times = [it.get("sort_time", 0) for it in items]
        for i in range(len(sort_times) - 1):
            assert sort_times[i] >= sort_times[i + 1], (
                f"排序错误: 索引 {i}={sort_times[i]} < {i+1}={sort_times[i+1]}"
            )

    def test_dedupe_preserves_sort_time(self):
        """去重后的条目应保留 sort_time。"""
        items = [
            {"title": "第一条", "time": "2026-07-26 15:30:00", "sort_time": 1802410200},
            {"title": "第二条", "time": "2026-07-26 14:00:00", "sort_time": 1802402400},
        ]
        result = _dedupe(items)
        assert len(result) == 2
        for it in result:
            assert "sort_time" in it

    def test_attach_level_correctly_recalculates_sort_time(self):
        """_attach_level 会根据 time 重新计算 sort_time，正确覆盖旧值。"""
        items = [
            {"title": "测试", "time": "2026-07-26 15:30:00"}
        ]
        result = _attach_level(items)
        assert "sort_time" in result[0]
        assert result[0]["sort_time"] > 0, "sort_time 应由 time 正确计算"

    def test_filter_fresh_preserves_sort_time(self):
        """_filter_fresh 不应丢失 sort_time。"""
        items = [
            {"title": "旧闻", "time": "2026-07-25 15:30:00", "sort_time": 1802323800},
            {"title": "新W", "time": "2026-07-26 15:30:00", "sort_time": 1802410200},
        ]
        result = _filter_fresh(items, max_age_hours=48)
        for it in result:
            assert "sort_time" in it

    @pytest.mark.network  # F23: real news fetch (field contract)
    def test_field_contract_all_required_fields(self):
        """每个头条条目必须包含 id/title/time/sort_time/source/level/stars。"""
        sync_memory_cache.clear()
        items = fetch_news_headlines()
        assert len(items) > 0
        REQUIRED = {"id", "title", "time", "sort_time", "source", "level", "stars"}
        for it in items:
            missing = REQUIRED - set(it.keys())
            assert not missing, f"条目 {it.get('title','?')} 缺少字段: {missing}"
            assert isinstance(it["sort_time"], int), f"sort_time 应为 int, got {type(it['sort_time'])}"
            assert isinstance(it["level"], int) and 1 <= it["level"] <= 5, f"level 超出范围: {it['level']}"

    @pytest.mark.network  # F23: real news fetch (cross-source sorting)
    def test_sort_time_monotonic_across_mixed_sources(self):
        """跨来源合并后 sort_time 必须严格不增（允许相等）。"""
        sync_memory_cache.clear()
        items = fetch_news_headlines()
        assert len(items) >= 2
        for i in range(len(items) - 1):
            assert items[i]["sort_time"] >= items[i + 1]["sort_time"], (
                f"排序违反单调性: idx {i} ({items[i]['sort_time']}) < idx {i+1} ({items[i+1]['sort_time']})"
            )


class TestIndividualFetcherSortTime:
    """验证各个 news fetcher 单独调用时也产生 sort_time。"""

    def test_fetch_cailian_has_sort_time_after_normalize(self, monkeypatch):
        """fetch_cailian_telegraph 条目经 normalize 后应含 sort_time。"""
        import app.fetchers.news_fetcher as nfmod

        orig = nfmod.fetch_cailian_telegraph
        def _mock(*args, **kwargs):
            items = orig(*args, **kwargs)
            # 模拟 fetch_news_headlines 中的 normalize 步骤
            for it in items:
                nfmod._normalize_time(it)
            return items
        monkeypatch.setattr(nfmod, "fetch_cailian_telegraph", _mock)

        items = nfmod.fetch_cailian_telegraph(5)
        for it in items:
            assert "sort_time" in it, f"财联社条目 {it.get('title','?')} 缺少 sort_time"

    def test_fetch_macro_all_have_sort_time(self, monkeypatch):
        """fetch_macro_news 的条目应全部含 sort_time。"""
        import app.fetchers.news_fetcher as nfmod
        sync_memory_cache.clear()

        # Mock 新浪返回
        monkeypatch.setattr(nfmod, "fetch_sina_roll_news", lambda n: [
            {"title": "宏观1", "content": "x", "time": "2026-07-26 15:30:00", "source": "新浪"},
            {"title": "宏观2", "content": "y", "time": "2026-07-26 14:00:00", "source": "新浪"},
        ])
        monkeypatch.setattr(nfmod, "_ak", lambda fn: [])
        monkeypatch.setattr(nfmod, "fetch_cailian_telegraph", lambda n: [])

        items = fetch_macro_news()
        for it in items:
            assert "sort_time" in it, f"宏观条目 {it.get('title','?')} 缺少 sort_time"
            assert isinstance(it["sort_time"], int), f"sort_time 应为 int"
        # 确认排序正确
        if len(items) >= 2:
            assert items[0]["sort_time"] >= items[1]["sort_time"]

    def test_fetch_global_all_have_sort_time(self, monkeypatch):
        """fetch_global_news 的条目应全部含 sort_time。"""
        import app.fetchers.news_fetcher as nfmod
        sync_memory_cache.clear()

        # Mock: 模拟 _safe 返回一个带 entries 的对象
        class MockEntry:
            def __init__(self, title, summary, published, link):
                self.title = title
                self.summary = summary
                self.published = published
                self.link = link
            def get(self, key, default=""):
                return getattr(self, key, default)

        class MockFeed:
            entries = [
                MockEntry("Global 1", "s1", "Tue, 14 Jul 2026 10:00:00 GMT", "https://x.com/1"),
                MockEntry("Global 2", "s2", "Tue, 14 Jul 2026 09:00:00 GMT", "https://x.com/2"),
            ]

        monkeypatch.setattr(nfmod, "safe_call", lambda fn, **kw: MockFeed())
        monkeypatch.setattr(nfmod, "_ak", lambda fn: [])

        items = fetch_global_news()
        for it in items:
            assert "sort_time" in it, f"全球条目 {it.get('title','?')} 缺少 sort_time"
            assert isinstance(it["sort_time"], int)
        if len(items) >= 2:
            assert items[0]["sort_time"] >= items[1]["sort_time"]


class TestNewsRefreshBatch:
    """news_refresh 批次推送行为。"""

    @patch("app.services.market_data_hub.market_data_hub.get_news_headlines")
    @patch("app.tasks.news_refresh.manager")
    async def test_first_cycle_broadcasts_batch(self, mock_manager, mock_fetch):
        """首轮应广播一条 news_batch 消息（数组），而非逐条广播。"""
        from app.tasks.news_refresh import _last_titles, refresh_news_cache

        # 重置
        _last_titles.clear()

        mock_fetch.return_value = [
            {"id": "1", "title": "新闻A", "time": "2026-07-26 15:30:00", "sort_time": 1802410200},
            {"id": "2", "title": "新闻B", "time": "2026-07-26 14:00:00", "sort_time": 1802402400},
        ]
        await refresh_news_cache()

        # 验证 broadcast 被调用，且参数是 news_batch 消息
        assert mock_manager.broadcast.call_count >= 1
        # 查找 news_batch 调用
        batch_calls = [
            call for call in mock_manager.broadcast.call_args_list
            if call[0][1].get("type") == "news_batch"
        ]
        assert len(batch_calls) >= 1, "应有 news_batch 广播"
        batch_data = batch_calls[0][0][1]
        assert isinstance(batch_data["data"], list)
        assert len(batch_data["data"]) == 2
        # 批次内已排序（最新在前）
        assert batch_data["data"][0]["sort_time"] >= batch_data["data"][1]["sort_time"]

    @patch("app.services.market_data_hub.market_data_hub.get_news_headlines")
    @patch("app.tasks.news_refresh.manager")
    async def test_subsequent_cycle_only_new_titles(self, mock_manager, mock_fetch):
        """后续轮次只推新增条目。"""
        from app.tasks.news_refresh import _last_titles, refresh_news_cache

        # 模拟已有旧条目
        _last_titles.clear()
        _last_titles.add("新闻A")

        mock_fetch.return_value = [
            {"id": "1", "title": "新闻A", "time": "2026-07-26 15:30:00", "sort_time": 1802410200},
            {"id": "3", "title": "新闻C", "time": "2026-07-26 16:00:00", "sort_time": 1802412000},
        ]
        # 重置 call count
        mock_manager.reset_mock()
        await refresh_news_cache()

        # 应只广播了包含新闻C的 batch
        batch_calls = [
            call for call in mock_manager.broadcast.call_args_list
            if call[0][1].get("type") == "news_batch"
        ]
        assert len(batch_calls) >= 1
        batch_data = batch_calls[0][0][1]
        titles = [it["title"] for it in batch_data["data"]]
        assert "新闻A" not in titles, "不应重复广播已有条目"
        assert "新闻C" in titles, "应广播新增条目"
        assert len(batch_data["data"]) == 1


# ── 新闻管道降级链（合并自 test_news_pipeline.py）──


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


# ── P2-3: /news/stock/{symbol} 中文键归一化（合并自 test_stock_news_keys.py）──


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
               "source", "level", "category", "stars", "ai_summary"}
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


# ── F12: sentiment news_heat 标的相关/市态级降级（合并自 test_news_heat_scope.py）──


def _news_items():
    return [{"title": f"n{i}", "stars": i % 5 + 1, "level": "利好"} for i in range(10)]


def _patch_kline(monkeypatch):
    """K 线路径全 mock：run_sync 直连 + 无缓存 + 无网络。"""
    from app.core import async_utils

    def _fake_history(symbol, market="A", period="daily", timeout=20):
        return [{"close": 4.0 + i * 0.01, "high": 4.1, "low": 3.9, "volume": 1e7,
                 "total_mv": 5e9, "float_mv": 3e9} for i in range(30)]

    async def _direct(call, *args, timeout=None, **kwargs):
        # fetch_one 的 call 是 hub.get_history——直接返回 fake K 线（不触网）
        return _fake_history(*args, **kwargs)

    monkeypatch.setattr(async_utils, "run_sync", _direct)
    monkeypatch.setattr(fr, "_get_cached_kline", lambda symbols: None)
    return _fake_history


async def _fetch_with_news(monkeypatch, stock_news):
    """构造经真实 _fetch_market_data（K 线 mock、新闻 mock）后的单标的 data。"""
    from app.services.market_data_hub import market_data_hub as hub_inst

    monkeypatch.setattr(hub_inst, "get_news_stock", lambda sym: stock_news)
    monkeypatch.setattr(hub_inst, "get_news_headlines", lambda: _news_items())
    monkeypatch.setattr(hub_inst, "get_market_sentiment", lambda: {"sentiment_index": 50.0})
    monkeypatch.setattr(hub_inst, "get_fund_nav", lambda sym, **kw: {})
    _patch_kline(monkeypatch)
    reg = fr.FactorRegistry()
    data = await reg._fetch_market_data(["510300"])
    return data.get("510300", {})


async def test_stock_news_used_when_available(monkeypatch):
    """标的新闻可用 → news_items 用标的新闻且 news_scope=stock。"""
    stock_news = [{"title": "个股专属新闻", "stars": 5, "level": "利好"}] * 5
    d = await _fetch_with_news(monkeypatch, stock_news)
    assert d.get("news_scope") == "stock"
    assert d.get("news_items") == stock_news[-30:]
    # 标的新闻的 news_heat 有区分度来源
    assert fr._compute_news_heat(d) > 0


async def test_market_fallback_marks_scope(monkeypatch):
    """标的新闻不可用 → 市态级降级 + news_scope=market 标注。"""
    d = await _fetch_with_news(monkeypatch, [])
    assert d.get("news_scope") == "market"
    assert d.get("news_items"), "市态级降级仍应注入全市场新闻（供 regime 输入）"
    # 全市场新闻注入时标注"非个股值"——前端/明细据此避免误导
    assert d.get("news_items") == _news_items()[-30:]
