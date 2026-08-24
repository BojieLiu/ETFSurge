# -*- coding: utf-8 -*-
"""round35 B3-F7 (docs/round35-architecture-review.md §6.3) —
taxonomy 分类器历史事故案例入册（每条都曾引发真实误判/回归）：

- 中证1000/国证2000 含「中证100」等子串但属中盘小盘 → 排除词优先，不算大盘宽基族；
- 裸 A500/A50（无「中证」前缀）→ 必须命中大盘宽基族（round19 P1-②）；
- 科创芯片 industry=半导体 → 明确非宽基行业直接判否成长宽基（行业字段优先）；
- 中证500 纳入大盘族计数（R101 边界漏洞：中证500×沪深300=0.857 实测）；
- 公司名剥除：长名优先，「A500ETF华泰柏瑞」不残留「柏瑞」（round19 P1-② 根治后口径）。
"""
import pytest

from app.engine.allocation_engine import (
    _extract_index_concept,
    _is_growth_wide_basis,
    _is_large_cap_wide_basis,
    _is_wide_basis,
    _normalize_segment,
)


def test_zz1000_excluded_from_large_cap_family():
    c = {"name": "中证1000ETF", "tracked_index": "中证1000"}
    # 排除词优先于「中证100」子串命中
    assert _is_large_cap_wide_basis(c) is False


def test_gz2000_zz2000_excluded_from_large_cap_family():
    for name in ("国证2000ETF", "中证2000ETF"):
        assert _is_large_cap_wide_basis({"name": name}) is False, name


def test_bare_a500_a50_hit_large_cap_family():
    assert _is_large_cap_wide_basis({"name": "A500ETF华泰柏瑞"}) is True
    assert _is_large_cap_wide_basis({"name": "A50ETF"}) is True


def test_chip_etf_industry_beats_growth_keyword():
    """科创芯片 industry=半导体：主题 ETF 非宽基（历史事故口径）。
    双层覆盖：① 名称「科创芯片」本就不含成长关键词（科创50/100/200 等精确族）；
    ② 行业守卫优先——即便名称命中成长关键词（科创50），明确非宽基行业仍判否。"""
    c = {"name": "科创芯片ETF", "tracked_index": "科创芯片", "industry": "半导体"}
    assert _is_growth_wide_basis(c) is False
    assert _is_growth_wide_basis({"name": "科创芯片ETF"}) is False
    assert _is_growth_wide_basis({"name": "科创50ETF", "industry": "半导体"}) is False
    # 对照：无行业字段 + 关键词命中 → 成长宽基
    assert _is_growth_wide_basis({"name": "科创50ETF"}) is True


def test_zz500_in_large_cap_family_r101():
    assert _is_large_cap_wide_basis({"name": "中证500ETF"}) is True
    assert _is_large_cap_wide_basis({"name": "中证500价值ETF"}) is True  # 子串命中细分


def test_growth_keywords_hit_growth_style():
    for name in ("科创50ETF", "创业板ETF", "双创50ETF"):
        assert _is_growth_wide_basis({"name": name}) is True, name


def test_company_name_stripping_long_first():
    """「华泰柏瑞」整体剥除，不残留「柏瑞」（len 降序根治 round19 P1-②）。"""
    assert _extract_index_concept("A500ETF华泰柏瑞") == "A500"
    assert _extract_index_concept("科创100ETF汇添富") == "科创100"
    assert _extract_index_concept("沪深300ETF华夏") == "沪深300"


def test_segment_normalization_families():
    assert _normalize_segment("科创100") == "科创"
    assert _normalize_segment("中证500价值") == "中证500"
    assert _normalize_segment("沪深300增强") == "沪深300"
    assert _normalize_segment("中证A500") == "中证A500"  # 不归并进沪深300/中证500


def test_wide_basis_semantics_branches():
    # industry 显式宽基
    assert _is_wide_basis({"name": "XETF", "industry": "宽基指数"}) is True
    # 名称兜底（industry 缺失）
    assert _is_wide_basis({"name": "中证800ETF"}) is True
    # 中证1000 经由「中证100」子串命中宽基（M5 口径：宽基含中盘），仅大盘族排除它
    assert _is_wide_basis({"name": "中证1000ETF"}) is True
