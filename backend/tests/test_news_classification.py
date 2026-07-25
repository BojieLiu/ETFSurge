"""TDD tests for issue 4 (news importance level + stars).

levistock is mocked; classification is keyword-based, no network needed.

覆盖：正向匹配 + 反向精度(中性词不放利空) + P1.1/P1.2 关键词修正。
"""
from unittest.mock import MagicMock

import pytest

from app.fetchers import levistock_fetcher as lvmod
from app.fetchers.levistock_fetcher import classify_news_level, fetch_cailian_telegraph
from app.fetchers.news_fetcher import fetch_macro_news, fetch_global_news
from app.services.cache_service import sync_memory_cache


# ── 正向命中测试 ─────────────────────────────────────────────────

def test_classify_news_level_keywords_forward():
    """正向断言：关键词应命中对应级别。"""
    assert classify_news_level("【重大】央行紧急降准") == 5
    assert classify_news_level("突发：地缘冲突升级") == 5
    assert classify_news_level("利好：某板块业绩超预期") == 4
    assert classify_news_level("利空：指数暴跌") == 3
    assert classify_news_level("提醒：关注赎回风险") == 2
    assert classify_news_level("某普通上市公司公告") == 2  # 公告 → 关注


# ── 反向精度测试（P1.1/P1.2 修正） ──────────────────────────────

class TestKeywordPrecision:
    """反向断言：中性词/异动词不应被误判为利空或利好。

    这些是 P1.1/P1.2 的关键修复项，确保没有回归。
    """

    def test_neutral_words_not_level_3(self):
        """P1.1: '召开'/'会议'/'讲话'/'发言' 从 Level 3 移除后，不应被归为利空。"""
        for title in ["召开年度股东大会", "国务院常务会议", "央行行长讲话", "证监会发言人"]:
            level = classify_news_level(title)
            assert level != 3, f"'{title}' 不应标为 Level 3 (利空)，实际为 {level}"

    def test_price_moves_not_level_4_or_3(self):
        """P1.2: '反弹'/'拉升'/'回落' 移至 Level 2（异动提醒），不应在 Level 4 或 Level 3。"""
        for title in ["市场出现反弹", "午后拉升", "午后回落"]:
            level = classify_news_level(title)
            assert level == 2, f"'{title}' 应为 Level 2 (提醒)，实际为 {level}"

    def test_pi_huo_only_level_4(self):
        """P1.2: '获批' 仅保留在 Level 4，不应在 Level 2。"""
        # 按降序匹配规则，"获批" 在 Level 4 命中，不应落到 Level 2
        level = classify_news_level("项目获批")
        assert level == 4, f"'获批' 应为 Level 4 (利好)，实际为 {level}"

    def test_level_5_priority_over_lower(self):
        """Level 5 关键词优先于 Level 4。"""
        assert classify_news_level("突发重大利好") == 5

    def test_level_4_priority_over_2(self):
        """'利好' 应命中 Level 4（无 Level 5 关键词干扰时）。"""
        assert classify_news_level("政策利好：落地") == 4


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
