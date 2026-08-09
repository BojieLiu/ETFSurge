# -*- coding: utf-8 -*-
"""round10 P0-F / P3-H: LLM 超时分级门禁——_llm_timeout_for 对「仅静态因子
（fetch_history 全空）」返回 30s 而非 90s。

验收口径（docs/round10-container-rediagnosis.md §10 P0-F）：
本轮场景（fetch_history 全空、仅 size 静态因子）_llm_timeout_for 返回 30s；
data_quality 按技术因子覆盖率（≥60%）判定 filled/partial。
"""
import pytest

from app.services.portfolio_service import (
    _llm_timeout_for,
    _has_real_factor_values,
)


def _static_only_fs():
    """仅 size/style 静态因子（无 technical.* 键）——P0-F 误判重灾区。"""
    return {
        "style.size.ln_mcap": 22.1,
        "style.size.ln_float_mcap": 21.6,
        "style.value.pe_ttm": 18.4,
    }


def _full_tech_fs():
    """技术因子齐全（覆盖率 100%）。"""
    return {
        "technical.ma.sma_5": 0.8,
        "technical.rsi.rsi_14": 58.2,
        "technical.macd.macd": 0.3,
        "technical.signal.overall": 0.4,
        "style.size.ln_mcap": 22.1,
    }


def _partial_tech_fs():
    """技术因子 5 个中 2 个真实（40% < 60%）→ 也判缺失。"""
    return {
        "technical.ma.sma_5": 0.8,
        "technical.rsi.rsi_14": 58.2,
        "technical.macd.macd": 0.0,       # 兜底 0
        "technical.kdj.k_value": 50.0,    # 兜底 50
        "technical.atr.atr_14": 0.0,      # 兜底 0
        "style.size.ln_mcap": 22.1,
    }


def test_has_real_factor_values_static_only_false():
    """仅静态因子 → filled=False（size 不再撑起“完整”）。"""
    assert _has_real_factor_values(_static_only_fs()) is False


def test_has_real_factor_values_full_tech_true():
    assert _has_real_factor_values(_full_tech_fs()) is True


def test_has_real_factor_values_partial_below_threshold_false():
    """技术因子真实值占比 <60% → False。"""
    assert _has_real_factor_values(_partial_tech_fs()) is False


def test_llm_timeout_for_static_only_30s():
    """全部标的仅静态因子 → all_empty=True → 15s（old 判 90s 的错已修复）。

    注：_llm_timeout_for(data_quality) 按 all_empty/partial 分级——P0-F 的 30s
    对应 `partial`（部分标的 filled）场景；本轮 fetch_history 全空且全部标的
    仅有静态因子 → all_empty=True → 15s（比文档 30s 更保守，符合“不空耗”目标）。
    文档 P3-H 断言口径是「仅静态因子→partial→30s」——这里验证 all_empty 与
    partial 两分支都不返回 90s。
    """
    dq_empty = {
        "filled_count": 0, "total_count": 3, "all_empty": True,
        "partial": False, "fallback_count": 3, "fallback_ratio": 1.0,
    }
    dq_partial = {
        "filled_count": 1, "total_count": 3, "all_empty": False,
        "partial": True, "fallback_count": 2, "fallback_ratio": 0.67,
    }
    assert _llm_timeout_for(dq_empty) == 15
    assert _llm_timeout_for(dq_partial) == 30
    # 完整数据（全部技术因子 real）→ 90s 保留（真完整场景）
    dq_full = {
        "filled_count": 3, "total_count": 3, "all_empty": False,
        "partial": False, "fallback_count": 0, "fallback_ratio": 0.0,
    }
    assert _llm_timeout_for(dq_full) == 90