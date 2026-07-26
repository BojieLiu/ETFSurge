"""TDD tests for issue 4 (news importance level + stars).

levistock is mocked; classification is keyword-based, no network needed.

覆盖：正向匹配 + 反向精度(中性词不放利空) + P1.1/P1.2 关键词修正 + P2.x 新关键词修复。
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
        level = classify_news_level("项目获批")
        assert level == 4, f"'获批' 应为 Level 4 (利好)，实际为 {level}"

    def test_level_5_priority_over_lower(self):
        """Level 5 关键词优先于 Level 4。"""
        assert classify_news_level("突发重大利好") == 5

    def test_level_4_priority_over_2(self):
        """'利好' 应命中 Level 4（无 Level 5 关键词干扰时）。"""
        assert classify_news_level("政策利好：落地") == 4


# ── P2.x 新关键词修复 (2026-07-26) ─────────────────────────────

def test_zhong_bang_not_level_5():
    """P2.1: '重磅' 不应为 L5 (紧急), 应为 L2 (提醒/关注)."""
    # Use a title without other level keywords to isolate '重磅'
    level = classify_news_level("下周资本市场大事提醒：A股港股迎重磅IPO")
    assert level == 2, f"'重磅' 应为 Level 2 (提醒/关注)，实际为 {level}"


def test_typhoon_level_5():
    """P2.2: '台风' 应为 L5 (自然灾害)."""
    level = classify_news_level("台风\"红霞\"在广东登陆 中心附近最大风力14级")
    assert level == 5, f"台风新闻应为 Level 5，实际为 {level}"


def test_cai_gou_level_2():
    """P2.3: '采购' 应为 L2 (公司公告/关注)."""
    level = classify_news_level("子公司拟不超20亿元采购服务器及配套设备")
    assert level == 2, f"采购新闻应为 Level 2，实际为 {level}"


def test_xie_yi_level_4():
    """P2.4: '协议' 应为 L4 (利好/正面商业合作)."""
    level = classify_news_level("英伟达锁定SK海力士内存供应协议")
    assert level == 4, f"供应协议应为 Level 4，实际为 {level}"


def test_he_zuo_level_4():
    """P2.5: '合作' 应为 L4 (利好/正面合作)."""
    level = classify_news_level("两家科技巨头宣布战略合作")
    assert level == 4, f"战略合作应为 Level 4，实际为 {level}"


def test_english_sanctions_level_3():
    """P2.6: 英文 'sanctions' 应命中 L3 (利空)."""
    level = classify_news_level("US announces new sanctions on Iran")
    assert level == 3, f"制裁新闻应为 Level 3，实际为 {level}"


def test_english_airstrike_level_5():
    """P2.7: 英文 'airstrike' 应命中 L5 (重大/紧急)."""
    level = classify_news_level("Airstrike hits civilian area, 15 killed")
    assert level == 5, f"空袭新闻应为 Level 5，实际为 {level}"


def test_english_layoffs_level_3():
    """P2.8: 英文 'layoffs' 应命中 L3 (利空)."""
    level = classify_news_level("Tech company announces layoffs")
    assert level == 3, f"裁员新闻应为 Level 3，实际为 {level}"


def test_english_collapse_level_5():
    """P2.9: 英文 'collapse' 应命中 L5 (重大)."""
    level = classify_news_level("Stock market collapse triggers panic")
    assert level == 5, f"collapse 应为 Level 5，实际为 {level}"


# ── 集成测试 ────────────────────────────────────────────────────

def test_fetch_cailian_telegraph_attaches_level_stars(monkeypatch):
    sync_memory_cache.clear()
    fake_lv = MagicMock()
    # Mock: 'important' returns 2 items, 'all' returns fallback
    fake_lv.news_telegraph_cls.side_effect = lambda category: [
        {"title": "重大利好：央行降准", "content": "x", "time": "10:00"},
        {"title": "某普通新闻", "content": "y", "time": "11:00"},
    ] if category == "important" else [
        {"title": "fallback news", "content": "z", "time": "12:00"},
    ]
    monkeypatch.setattr(lvmod, "lv", fake_lv)

    items = fetch_cailian_telegraph(10)
    # important (2) + unique all (1) = 3 items total
    assert len(items) == 3
    assert items[0]["level"] == 5  # "重大" → L5, +1 boost caps at 5
    assert items[0]["stars"] == 5
    for it in items:
        assert "level" in it and "stars" in it
        # items[1] is L2 (普通新闻 has no keywords, but important +1 boost = L2)
        # items[2] is L1 from 'all' (no keywords, no boost)


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
