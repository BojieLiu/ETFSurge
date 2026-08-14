"""TDD tests for issue 4 (news importance level + stars).

levistock is mocked; classification is keyword-based, no network needed.

覆盖：正向匹配 + 反向精度(中性词不放利空) + P1.1/P1.2 关键词修正 + P2.x 新关键词修复。
"""
from unittest.mock import MagicMock

import pytest

from app.fetchers import levistock_fetcher as lvmod
from app.fetchers import news_fetcher as nf
from app.fetchers.levistock_fetcher import classify_news_level, fetch_cailian_telegraph
from app.fetchers.news_fetcher import _compute_stars, fetch_macro_news, fetch_global_news
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


def test_english_sanctions_risk_not_negative():
    """F23 (round23 P0-A): 英文 'sanctions' 应归 risk 类别（地缘/制裁），
    不得标为利好(red)；重要性 level>=4（独立重要维度）。"""
    from app.fetchers.levistock_fetcher import classify_news, classify_news_category
    cat, level = classify_news("US announces new sanctions on Iran")
    assert cat == "risk", f"制裁新闻应为 risk 类别，实际为 {cat}"
    assert level >= 4, f"制裁新闻重要性应 >=4，实际为 {level}"
    assert cat != "positive", "制裁不得标为利好"


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


# ── F3-1/§9.10: 分级质量修复（合并自 test_news_level_classification.py）──


def test_geo_political_escalated():
    """「特朗普下令对伊朗发动袭击」→ level ≥4（袭击= L5，军事词覆盖）。"""
    assert classify_news_level("特朗普下令对伊朗发动袭击") >= 4
    assert classify_news_level("油轮遭袭击引发市场恐慌") >= 4
    assert classify_news_level("伊朗冲突推高商品价格") >= 4
    assert classify_news_level("日元受干预提振") >= 3  # 干预 → L4，至少 ≥3


def test_irrelevant_stock_suspension_not_L5():
    """「7月最牛股停牌」→ level ≤2（停牌已从 L5 移至 L2）。"""
    assert classify_news_level("7月最牛股，停牌！") <= 2
    assert classify_news_level("某公司宣布违约风险") == 3  # 违约 L3


def test_source_level_overridden_when_divergent(caplog):
    """mock 源 level=5 + 本地分类 L2（差≥2）→ 输出 L2 + WARNING 日志。"""
    with caplog.at_level("WARNING"):
        level = lvmod._level_of({"level": 5}, "7月最牛股，停牌！")
    assert level == 2, f"应采用本地分类，实际 {level}"
    assert any("level 分歧" in r.message for r in caplog.records), "应记录 WARNING 漂移日志"


def test_stars_equal_level():
    """P2-1 (round9 §6.4): stars 独立「新鲜度」维度——与 level 解耦。

    旧语义「L3 恒 3★」已废弃：时间不可解析（如 "10:00"/空）回退 level（旧行为）；
    可解析且距今 >72h → 1★（无论 level）。
    """
    import app.fetchers.news_fetcher as _nf
    assert _nf._compute_stars(3, "") == 3            # 无时间 → 回退 level
    assert _nf._compute_stars(3, "10:00") == 3       # 无日期 → 回退 level
    assert _nf._compute_stars(3, "2026-07-01 00:00:00") == 1  # 旧新闻（>72h）→ 1★ 新鲜度
    assert _nf._compute_stars(5, "") == 5


def test_content_keyword_matches():
    """标题中性 + 正文含「军事行动」→ 命中 L5 词。"""
    assert classify_news_level("某地举行例行演练", "官方称该行动属军事行动范畴") >= 4
    # 注：「公告/发布」已从 L2 词表删除（步骤A 删高频泛词），该标题应归 L1
    assert classify_news_level("某公司发布公告") == 1


def test_keywords_no_cross_category_duplicate():
    """F22/F23: 每个词只属于一个 category；高频冲突词归位正确。"""
    # 词表本身已去重（_CATEGORY_WORD_OWNERSHIP 构造时后者覆盖前者）
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("停牌") == "neutral"
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("违约") == "negative"
    # F23: 制裁归 risk（地缘/军事/制裁），不再归 positive(利好)
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("制裁") == "risk"
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("冲突") == "risk"
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("利好") == "positive"
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("利空") == "negative"
    # 机构名归 neutral（提醒/关注上下文）
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("国务院") == "neutral"
    assert lvmod._CATEGORY_WORD_OWNERSHIP.get("发改委") == "neutral"


# ── round23 F22/F23: T11 方向性偏置 / 子串误命中 可失败断言 ──

def test_war_not_positive():
    """F23: 战争类不得标为利好(positive)。战争/开战/宣战属重大(major, 深红紧急)
    亦非利好红——核心是「战争不被误判为利好」。"""
    from app.fetchers.levistock_fetcher import classify_news_category
    for title in ("突发：两国爆发战争", "军方宣布开战", "国会批准宣战决议"):
        cat = classify_news_category(title)
        assert cat != "positive", f"'{title}' 不得标利好，实际 {cat}"
    # 地缘/军事/制裁（risk-only 词，不在 major 列表）明确归 risk
    assert classify_news_category("伊朗冲突推高油价") == "risk"
    assert classify_news_category("对华半导体制裁升级") == "risk"
    assert classify_news_category("军方介入干预市场") == "risk"


def test_geo_military_sanction_risk_not_positive():
    """F23: 地缘/军事/制裁 → risk，不得标利好。"""
    from app.fetchers.levistock_fetcher import classify_news_category
    for title in ("伊朗冲突推高油价", "军方介入干预市场", "对华半导体制裁升级",
                  "边境局势紧张", "多国联合军演", "国防预算上调"):
        assert classify_news_category(title) == "risk", \
            f"'{title}' 应归 risk，实际 {classify_news_category(title)}"
        assert classify_news_category(title) != "positive"


def test_substring_no_false_positive():
    """F23: 裸 '战'/'核' 误命中防护——挑战/战略/核查 不得归 risk/positive。"""
    from app.fetchers.levistock_fetcher import classify_news_category
    for title in ("公司挑战行业技术瓶颈", "企业制定长期发展战略", "审计核查未发现异常"):
        cat = classify_news_category(title)
        assert cat not in ("risk", "positive"), f"'{title}' 误命中为 {cat}"


def test_enrich_news_summaries_int_level_targets(monkeypatch):
    """F28 (round23 P0-A): AI 摘要重要性分支按 int level>=4 判定。

    旧实现 `str(level) in ("重大","利好")`（level 已是 int）恒 False →
    重要性维度永久失效；修复后 level=5 的新闻进入生成目标、level=1 的不进入。
    """
    import asyncio

    from app.services.market_data_hub import market_data_hub as hub_inst

    items = [
        {"title": "重大利空崩盘", "level": 5, "stars": 2, "ai_summary": None},  # level5 → 生成
        {"title": "普通新闻", "level": 1, "stars": 3, "ai_summary": None},       # 均<4 → 不生成
    ]
    monkeypatch.setattr(hub_inst, "_news_bucket", lambda key: items)

    async def _fake_summary(title, content):
        return f"AI:{title}"

    monkeypatch.setattr("app.analysis.llm.generate_news_summary", _fake_summary)

    n = asyncio.run(hub_inst.enrich_news_summaries())
    assert n == 1, f"应仅对 level>=4 生成 1 条，实际 {n}"
    assert items[0]["ai_summary"].startswith("AI:")
    assert items[1]["ai_summary"] is None


def test_negative_category_reachable():
    """F22/T11: 利空词归 negative 类别（非 positive/risk）。"""
    from app.fetchers.levistock_fetcher import classify_news_category
    assert classify_news_category("利空：指数暴跌") == "negative"
    assert classify_news_category("某公司暴雷违约") == "negative"


def test_important_negative_reaches_push_threshold():
    """F22: 重大利空（崩盘类）importance>=4，可进入 level>=4 推送/筛选。"""
    from app.fetchers.levistock_fetcher import classify_news_level
    # 崩盘属 major（L5），即便语义是利空也达重要性阈值 → 可推送
    assert classify_news_level("市场崩盘 千股跌停") >= 4



# ── round9 P2-1: stars 新鲜度 + 弱化词降级（合并自 test_round9_news_level.py）──

from datetime import datetime, timedelta  # noqa: E402


class TestStarsFreshnessDimension:
    def test_stars_follows_freshness_not_level(self):
        """P2-1: stars 按时间新鲜度（<1h 5★），与 level 解耦。"""
        now = datetime.now()
        assert _compute_stars(5, (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")) == 5
        assert _compute_stars(1, (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")) == 5
        assert _compute_stars(4, (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")) == 4
        assert _compute_stars(5, (now - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")) == 3
        assert _compute_stars(2, (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")) == 2
        assert _compute_stars(5, (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")) == 1

    def test_stars_parses_iso_and_slash_formats(self):
        """P2-1: stars 兼容 ISO/斜杠时间格式。"""
        now = datetime.now()
        iso = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        slash = (now - timedelta(hours=2)).strftime("%Y/%m/%d %H:%M:%S")
        assert _compute_stars(3, iso) == 4
        assert _compute_stars(3, slash) == 4

    def test_stars_unparseable_time_falls_back_to_level(self):
        """P2-1: 时间不可解析（如 "10:00" 无日期）回退 level，字段保持非空。"""
        assert _compute_stars(5, "10:00") == 5
        assert _compute_stars(2, "") == 2
        assert _compute_stars(4, None) == 4


class TestLevelWeakeningCalibration:
    def test_unrealized_events_downgraded(self):
        """P2-1: 弱化词（或将/有望/拟…）未实现事件不标重大/利好。"""
        assert classify_news_level("央行或将降准") == 3          # L4→L3
        assert classify_news_level("证监会拟放宽外资准入") == 3    # L4→L3
        assert classify_news_level("突发冲突或将升级") == 4        # L5→L4
        assert classify_news_level("财政部拟实施新一批减税政策") == 3  # L4→L3

    def test_confirmed_events_keep_level(self):
        """P2-1: 已实现事件保持原级别。"""
        assert classify_news_level("突发：地缘冲突升级") == 5
        assert classify_news_level("【重大】央行紧急降准") == 5
        assert classify_news_level("利好：某板块业绩超预期") == 4   # 「超预期」不被降级
        assert classify_news_level("央行宣布降准0.5个百分点") == 4

    def test_weakening_not_applied_below_level_4(self):
        """P2-1: 弱化规则只作用于 L5/L4，不把 L3/L2 再降。"""
        assert classify_news_level("利空：指数或继续下探") == 3    # 弱化词不影响 L3
        assert classify_news_level("下周资本市场大事提醒：或迎重磅IPO") == 2

    def test_level5_share_not_dominant_on_headline_mix(self):
        """P2-1 验收近似: 常规头条混合样本中 L5 不占 50%（分布合理性回归）。"""
        titles = [
            "央行或将降准",            # 3
            "某公司发布年报业绩",       # 2（发布→L2）
            "市场午后小幅拉升",        # 2
            "突发：地震已致多人受伤",   # 5
            "两家科技巨头宣布战略合作",  # 4
            "普通公司公告",            # 2
            "美国CPI数据公布",         # 2
            "台风登陆沿海地区",        # 5
        ]
        levels = [classify_news_level(t) for t in titles]
        l5 = sum(1 for l in levels if l == 5)
        l1 = sum(1 for l in levels if l == 1)
        assert l5 / len(levels) < 0.3, f"L5 占比 {l5}/{len(levels)} 应 <30%: {levels}"
        assert l1 >= 0, f"存在 L1: {levels}"


# ── O7: 国际重磅分级 + 宏观 tab 过滤（合并自 test_news_macro_filter.py）──


class TestInternationalLeveling:
    def test_fed_rate_decision_level4(self):
        """美联储利率决议 → L4（重磅宏观事件）。"""
        assert classify_news_level("美联储公布利率决议，维持利率不变") >= 4
        assert classify_news_level("美联储主席鲍威尔表示年内将降息") >= 2

    def test_nonfarm_payrolls_level4(self):
        """美国非农数据 → L4。"""
        assert classify_news_level("美国6月非农就业数据超预期") >= 4

    def test_opec_oil_level4(self):
        """OPEC 会议/减产 → L4（能源市场重磅）。"""
        assert classify_news_level("OPEC+宣布延长减产协议") >= 4

    def test_inflation_unemployment_level2(self):
        """通胀/失业率数据 → L2（重要数据但非紧急）。"""
        assert classify_news_level("美国5月CPI同比上涨3.1%") >= 2
        assert classify_news_level("初请失业金人数上升") >= 2


class TestMacroFilter:
    def test_macro_relevant_kept(self):
        """宏观/政策新闻 → 保留。"""
        assert nf._is_macro_relevant("央行开展5000亿元逆回购操作") is True
        assert nf._is_macro_relevant("国务院常务会议部署稳经济政策") is True
        assert nf._is_macro_relevant("美联储决议对全球市场的影响") is True

    def test_stock_news_filtered(self):
        """个股新闻（含 6 位代码/公司名+股价）→ 过滤。"""
        assert nf._is_macro_relevant("贵州茅台股价再创新高") is False
        assert nf._is_macro_relevant("600519涨停，主力资金净流入") is False
        assert nf._is_macro_relevant("某某公司发布半年报预告") is False

    def test_marketing_filtered(self):
        """营销软文 → 过滤。"""
        assert nf._is_macro_relevant("限时抢购！开户送好礼") is False
        assert nf._is_macro_relevant("下载APP领红包，新手专享") is False
