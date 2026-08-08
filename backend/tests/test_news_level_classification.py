# -*- coding: utf-8 -*-
"""F3-1 / §9.10: 新闻重要性分级质量修复（词表治理 / 双轨校验 / stars=level / 双输入）。"""
import pytest

from app.fetchers import levistock_fetcher as lf
from app.fetchers import news_fetcher as nf


# ── 1. 地缘军事事件升级（§9.10.4 用例1） ─────────────────────────────────
def test_geo_political_escalated():
    """「特朗普下令对伊朗发动袭击」→ level ≥4（袭击= L5，军事词覆盖）。"""
    assert lf.classify_news_level("特朗普下令对伊朗发动袭击") >= 4
    assert lf.classify_news_level("油轮遭袭击引发市场恐慌") >= 4
    assert lf.classify_news_level("伊朗冲突推高商品价格") >= 4
    assert lf.classify_news_level("日元受干预提振") >= 3  # 干预 → L4，至少 ≥3


# ── 2. 个股停牌不再误判 L5（§9.10.4 用例2） ──────────────────────────────
def test_irrelevant_stock_suspension_not_L5():
    """「7月最牛股停牌」→ level ≤2（停牌已从 L5 移至 L2）。"""
    assert lf.classify_news_level("7月最牛股，停牌！") <= 2
    assert lf.classify_news_level("某公司宣布违约风险") == 3  # 违约 L3


# ── 3. 源 level 与本地分类分歧 ≥2 时以本地为准（§9.10.4 用例3） ─────────
def test_source_level_overridden_when_divergent(caplog):
    """mock 源 level=5 + 本地分类 L2（差≥2）→ 输出 L2 + WARNING 日志。"""
    with caplog.at_level("WARNING"):
        level = lf._level_of({"level": 5}, "7月最牛股，停牌！")
    assert level == 2, f"应采用本地分类，实际 {level}"
    assert any("level 分歧" in r.message for r in caplog.records), "应记录 WARNING 漂移日志"


# ── 4. stars = 新鲜度维度（round9 P2-1，替代旧「stars=level」语义） ──────
def test_stars_equal_level():
    """P2-1 (round9 §6.4): stars 独立「新鲜度」维度——与 level 解耦。

    旧语义「L3 恒 3★」已废弃：时间不可解析（如 "10:00"/空）回退 level（旧行为）；
    可解析且距今 >72h → 1★（无论 level）。
    """
    assert nf._compute_stars(3, "") == 3            # 无时间 → 回退 level
    assert nf._compute_stars(3, "10:00") == 3       # 无日期 → 回退 level
    assert nf._compute_stars(3, "2026-07-01 00:00:00") == 1  # 旧新闻（>72h）→ 1★ 新鲜度
    assert nf._compute_stars(5, "") == 5


# ── 5. 正文双输入（§9.10.4 用例5） ───────────────────────────────────────
def test_content_keyword_matches():
    """标题中性 + 正文含「军事行动」→ 命中 L5 词。"""
    assert lf.classify_news_level("某地举行例行演练", "官方称该行动属军事行动范畴") >= 4
    # 注：「公告/发布」已从 L2 词表删除（步骤A 删高频泛词），该标题应归 L1
    assert lf.classify_news_level("某公司发布公告") == 1


# ── 6. 跨级去重（§9.10.5 验收2） ─────────────────────────────────────────
def test_keywords_no_cross_level_duplicate():
    """每个词只属于一个 level（跨级重复 = 0）。"""
    # 词表本身已去重（_LEVEL_WORD_OWNERSHIP 构造时后者覆盖前者）；
    # 验证高频冲突词仅出现在预期 level：
    assert lf._LEVEL_WORD_OWNERSHIP.get("停牌") == 2
    assert lf._LEVEL_WORD_OWNERSHIP.get("违约") == 3
    assert lf._LEVEL_WORD_OWNERSHIP.get("制裁") == 4
    # 机构名不在 L4（步骤A: 从 L4 移除，仅 L2 作上下文）
    assert lf._LEVEL_WORD_OWNERSHIP.get("国务院") == 2
    assert lf._LEVEL_WORD_OWNERSHIP.get("发改委") == 2
