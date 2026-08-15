"""round24 Batch 3 后端修复单测（R15/R16/R17/R21/R23）。

契约驱动 + 测试驱动：每个修复点均有可失败的负向/正向断言，mock 外部网络与 LLM。
R15: 宏观 tab 剔除基金营销/ETF日报 软文
R16: 全球英文标题分类器（不再全 other）
R17: AI 摘要覆盖三桶（headlines/macro/global）
R21: 通用因子分强度分档（裸数值不可解读 → 分档）
R23: news 懒刷新加锁 + 失败/空桶回退上次非空桶（高负载不瞬态返 0）
"""
import asyncio
from unittest.mock import patch

from app.fetchers.news_fetcher import _is_macro_relevant
from app.fetchers.levistock_fetcher import classify_news, classify_news_category
from app.services.portfolio_service import format_factor_summary


# ── R15: 宏观 tab 过滤收紧 ──────────────────────────────────────────────


def test_r15_macro_excludes_etf_daily():
    """R15: 「ETF日报」类软文即便含宏观词也不得入宏观 tab。"""
    assert _is_macro_relevant("ETF日报：产业趋势没有变，长期配置价值凸显") is False
    assert _is_macro_relevant("基金发售：新发ETF正在募集中") is False
    assert _is_macro_relevant("某ETF净值创新高，申购火爆") is False


def test_r15_macro_keeps_genuine_macro():
    """R15: 真实宏观/政策新闻仍应入宏观 tab（无回归）。"""
    assert _is_macro_relevant("央行开展5000亿元逆回购操作") is True
    assert _is_macro_relevant("美联储维持利率不变，表态偏鸽") is True
    assert _is_macro_relevant("国务院常务会议部署稳经济政策") is True


def test_r15_macro_excludes_stock_promo():
    """R15: 个股/营销内容仍排除（O7 既有语义保留）。"""
    assert _is_macro_relevant("贵州茅台股价再创新高") is False
    assert _is_macro_relevant("限时抢购！开户送好礼") is False


# ── R16: 全球英文标题分类器 ────────────────────────────────────────────


def test_r16_global_english_classified_not_other():
    """R16: 英文 RSS 标题应分到非 other 类别。"""
    risk_title = "Treasury yields rise as U.S. threatens new tariffs on imports"
    cat, _ = classify_news(risk_title)
    assert cat != "other", f"英文标题应被分类，实得 other: {risk_title}"
    assert cat == "risk", f"含 tariff 应归 risk，实得 {cat}"

    neutral_title = "U.S. inflation cools to 3% as consumer prices ease"
    cat2, _ = classify_news(neutral_title)
    assert cat2 != "other", f"英文标题应被分类，实得 other: {neutral_title}"
    assert cat2 == "neutral", f"含 inflation 应归 neutral，实得 {cat2}"


def test_r16_english_positive_and_negative():
    """R16: 英文利好/利空词也能命中。"""
    pos, _ = classify_news("Stocks rally as tech earnings beat expectations")
    assert pos == "positive"
    neg, _ = classify_news("Shares slump after company posts weak results")
    assert neg == "negative"


def test_r16_chinese_no_regression():
    """R16: 中文标题分类不受影响（英文兜底仅对英文标题生效）。"""
    cat = classify_news_category("央行降准释放流动性")
    assert cat != "other"


# ── R17: 三桶 AI 摘要覆盖 ──────────────────────────────────────────────


def test_r17_three_bucket_summary_coverage():
    """R17: macro/global 重要项也生成摘要（不再仅 headlines）。"""
    from app.services.market_data_hub import market_data_hub as hub_inst

    buckets = {
        "headlines": [
            {"title": "头条重大", "level": 5, "stars": 2, "ai_summary": None},
        ],
        "macro": [
            {"title": "宏观重大", "level": 5, "stars": 1, "ai_summary": None},
        ],
        "global": [
            {"title": "全球重大", "level": 4, "stars": 1, "ai_summary": None},
        ],
    }

    def _fake_bucket(key):
        return buckets.get(key, [])

    monkeypatch_bucket = patch.object(hub_inst, "_news_bucket", side_effect=_fake_bucket)

    async def _fake_summary(title, content):
        return f"AI:{title}"

    with monkeypatch_bucket, patch(
        "app.analysis.llm.generate_news_summary", side_effect=_fake_summary
    ):
        n = asyncio.run(hub_inst.enrich_news_summaries(cap=6))

    # 三桶各 1 条重要项均被覆盖
    assert n == 3, f"三桶重要项应各生成 1 条摘要，实际 {n}"
    assert buckets["headlines"][0]["ai_summary"].startswith("AI:")
    assert buckets["macro"][0]["ai_summary"].startswith("AI:")
    assert buckets["global"][0]["ai_summary"].startswith("AI:")


def test_r17_cost_cap_respected():
    """R17: cap 截断生效，控制 LLM 成本。"""
    from app.services.market_data_hub import market_data_hub as hub_inst

    items = [
        {"title": f"新闻{i}", "level": 5, "stars": 1, "ai_summary": None}
        for i in range(10)
    ]
    monkeypatch_bucket = patch.object(hub_inst, "_news_bucket", return_value=items)

    async def _fake_summary(title, content):
        return f"AI:{title}"

    with monkeypatch_bucket, patch(
        "app.analysis.llm.generate_news_summary", side_effect=_fake_summary
    ):
        n = asyncio.run(hub_inst.enrich_news_summaries(cap=4))

    assert n == 4, f"cap=4 应仅生成 4 条，实际 {n}"


# ── R21: 通用因子分强度分档 ────────────────────────────────────────────


def test_r21_generic_factor_shows_band():
    """R21: 无创专属语义的通用因子分应渲染为强度分档（可解读），不裸数值。"""
    # 文档示例「政策规划因子 +8.97」「战略新兴 +8.14」→ 对应真实因子键
    s = format_factor_summary({
        "china.policy.five_year_plan": 8.97,
        "china.policy.strategic_emerging": 8.14,
    })
    assert "十五五规划" in s
    assert "战略性新兴" in s
    # 裸数值不得单独出现（应配分档括号）
    assert "（强）" in s, f"通用因子应带强度分档，实得: {s}"
    # 不应再是「+8.97」式裸数值（带分档）
    assert "+8.97" not in s, f"裸因子值不应直接暴露，实得: {s}"


def test_r21_rsi_keeps_semantic_hint():
    """R21: RSI 等已有专属语义的因子保持原样（无回归）。"""
    s = format_factor_summary({"technical.rsi.rsi_14": 85.0})
    assert "超买" in s
    assert "（强）" not in s, f"RSI 已有语义不应再叠加分档，实得: {s}"


def test_r21_weak_factor_band():
    """R21: 负向通用因子分档为「弱」。"""
    s = format_factor_summary({"factor.momentum": -3.5})
    assert "（弱）" in s, f"负向大值应判弱，实得: {s}"


# ── R23: news 懒刷新锁 + 回退 ──────────────────────────────────────────


def _make_hub_news():
    from app.services.market_data_hub import MarketDataHub

    hub = MarketDataHub.__new__(MarketDataHub)
    hub._news_cache = None
    hub._news_buckets = None
    hub._news_cache_ts = 0.0
    hub.NEWS_TTL = 120
    return hub


def test_r23_fallback_keeps_prev_nonempty_on_empty_fetch():
    """R23: TTL 过期但抓取返回空（数据源冷却）时，回退上次非空桶，不瞬态返 0。"""
    hub = _make_hub_news()
    prev = [
        {"title": "prev-headline", "level": 3},
    ]
    hub._news_buckets = {
        "headlines": prev,
        "macro": [{"title": "prev-macro"}],
        "global": [{"title": "prev-global"}],
    }
    hub._news_cache_ts = 0.0  # 过期 → 触发刷新

    with patch("app.fetchers.news_fetcher.fetch_news_headlines", return_value=[]), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", return_value=[]), \
         patch("app.fetchers.news_fetcher.fetch_global_news", return_value=[]):
        result = hub.get_news_headlines()

    # 抓取空 → 回退上次非空，高负载下不返 0
    assert result == prev, f"空抓取应回退上次非空桶，实得 {result}"
    assert hub.get_news_macro() != []
    assert hub.get_news_global() != []


def test_r23_lock_attribute_created_and_safe():
    """R23: 安全刷新建立锁且不抛异常（并发刷新路径可走）。"""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               return_value=[{"title": "h"}]), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", return_value=[]), \
         patch("app.fetchers.news_fetcher.fetch_global_news", return_value=[]):
        hub._refresh_news_buckets_safe()
    assert getattr(hub, "_news_refresh_lock", None) is not None
    assert hub.get_news_headlines() == [{"title": "h"}]
