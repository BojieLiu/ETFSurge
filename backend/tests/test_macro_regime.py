"""
round13 §3.1 P1: 市态判定宏观增强（fetch_pmi_gdp / fetch_macro_snapshot / detect_market_regime macro 参数）。

契约: api-contracts/market/macro-regime.md

- fetch_pmi_gdp: PMI + GDP 两源（macro_china_pmi_yearly / macro_china_gdp_yearly），列名 商品/日期/今值
- fetch_macro_snapshot: 聚合 M2 同比 3 月斜率 / PMI / LPR 1Y 同比 → 方向标注（-1/0/+1）
- detect_market_regime(macro=...): 同向叠加/顺势修正、冲突保持、缺失不动

mock akshare，无网络。
"""
import asyncio
import datetime

import pandas as pd
import pytest
from unittest.mock import patch

from app.fetchers import macro_fetcher
from app.services import market_trends
from app.services.cache_service import sync_memory_cache


def _rt(fn, timeout=15):
    return fn()


def _clear():
    sync_memory_cache.clear()


def _pmi_df(*rows):
    return pd.DataFrame(rows, columns=["商品", "日期", "今值", "预测值", "前值"])


def _gdp_df(*rows):
    return pd.DataFrame(rows, columns=["商品", "日期", "今值", "预测值", "前值"])


def _m2_df(*rows):
    return pd.DataFrame(rows, columns=[
        "月份", "货币和准货币(M2)-数量(亿元)", "货币和准货币(M2)-同比增长",
        "货币和准货币(M2)-环比增长", "货币(M1)-数量(亿元)", "货币(M1)-同比增长",
        "货币(M1)-环比增长", "流通中的现金(M0)-数量(亿元)", "流通中的现金(M0)-同比增长",
        "流通中的现金(M0)-环比增长",
    ])


def _lpr_df(*rows):
    return pd.DataFrame(rows, columns=["TRADE_DATE", "LPR1Y", "LPR5Y", "RATE_1", "RATE_2"])


# ── fetch_pmi_gdp ─────────────────────────────────────────────
def test_fetch_pmi_gdp_returns_both(monkeypatch):
    _clear()
    pmi = _pmi_df(
        ["中国官方制造业PMI", datetime.date(2025, 7, 31), 49.3, 49.7, 49.7],
        ["中国官方制造业PMI", datetime.date(2025, 8, 31), 49.4, 49.5, 49.3],
    )
    gdp = _gdp_df(
        ["中国GDP年率报告", datetime.date(2025, 4, 16), 5.4, 5.2, 5.4],
        ["中国GDP年率报告", datetime.date(2025, 7, 15), 5.2, None, 5.4],
    )
    with patch("akshare.macro_china_pmi_yearly", side_effect=lambda: pmi), \
         patch("akshare.macro_china_gdp_yearly", side_effect=lambda: gdp), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_pmi_gdp()
    assert r is not None
    assert r["pmi"]["value"] == 49.4, "PMI 取最后一行今值"
    assert r["gdp"]["value"] == 5.2, "GDP 取最后一行今值（同比增速）"
    assert r["pmi"]["date"] == "2025-08-31"


def test_fetch_pmi_gdp_all_down_returns_none(monkeypatch):
    _clear()
    with patch("akshare.macro_china_pmi_yearly", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_gdp_yearly", side_effect=RuntimeError("down")), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        assert macro_fetcher.fetch_pmi_gdp() is None


# ── fetch_macro_snapshot ───────────────────────────────────────
def _default_mocks(monkeypatch):
    m2 = _m2_df(
        ["2026年04月份", 100, 7.2, 0.1, 50, 1.0, 0.0, 20, 3.0, 0.0],
        ["2026年05月份", 101, 7.0, 0.1, 51, 1.1, 0.0, 21, 3.0, 0.0],
        ["2026年06月份", 102, 6.8, 0.1, 52, 1.2, 0.0, 22, 3.0, 0.0],
    )
    pmi = _pmi_df(
        ["中国官方制造业PMI", datetime.date(2026, 6, 30), 50.1, 50.0, 49.9],
        ["中国官方制造业PMI", datetime.date(2026, 7, 31), 49.5, 50.0, 50.1],
    )
    lpr = _lpr_df(
        [datetime.date(2025, 7, 20), 3.45, 3.95, 4.35, 4.9],
        [datetime.date(2026, 7, 20), 3.0, 3.5, 4.35, 4.9],
    )
    return {
        "akshare.macro_china_money_supply": lambda: m2,
        "akshare.macro_china_pmi_yearly": lambda: pmi,
        "akshare.macro_china_lpr": lambda: lpr,
    }


def test_fetch_macro_snapshot_aggregates_directions(monkeypatch):
    """三指标聚合：M2 斜率下行(-1) + PMI<50(-1) + LPR 降息(+1) → macro_direction=-1。"""
    _clear()
    mocks = _default_mocks(monkeypatch)
    with patch("akshare.macro_china_money_supply", side_effect=mocks["akshare.macro_china_money_supply"]), \
         patch("akshare.macro_china_pmi_yearly", side_effect=mocks["akshare.macro_china_pmi_yearly"]), \
         patch("akshare.macro_china_lpr", side_effect=mocks["akshare.macro_china_lpr"]), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        snap = macro_fetcher.fetch_macro_snapshot()
    assert snap is not None
    assert snap["m2_yoy_now"] == 6.8
    assert snap["m2_yoy_3m_ago"] == 7.2
    assert snap["m2_slope"] == pytest.approx(-0.4)
    assert snap["m2_direction"] == -1
    assert snap["pmi_value"] == 49.5
    assert snap["pmi_direction"] == -1
    assert snap["lpr_1y_now"] == 3.0
    assert snap["lpr_1y_12m_ago"] == 3.45
    assert snap["lpr_direction"] == 1, "LPR 同比下调 = 降息周期 = +1"
    assert snap["macro_direction"] == -1, "sign(-1 + -1 + 1) = -1"


def test_fetch_macro_snapshot_all_down_returns_none(monkeypatch):
    _clear()
    with patch("akshare.macro_china_money_supply", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_pmi_yearly", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_lpr", side_effect=RuntimeError("down")), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        assert macro_fetcher.fetch_macro_snapshot() is None


def test_fetch_macro_snapshot_cached_24h(monkeypatch):
    """snapshot 复用 24h 缓存——二次调用不触源。"""
    _clear()
    mocks = _default_mocks(monkeypatch)
    calls = {"n": 0}
    orig = mocks["akshare.macro_china_money_supply"]

    def counting():
        calls["n"] += 1
        return orig()

    with patch("akshare.macro_china_money_supply", side_effect=counting), \
         patch("akshare.macro_china_pmi_yearly", side_effect=mocks["akshare.macro_china_pmi_yearly"]), \
         patch("akshare.macro_china_lpr", side_effect=mocks["akshare.macro_china_lpr"]), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        macro_fetcher.fetch_macro_snapshot()
        macro_fetcher.fetch_macro_snapshot()
    assert calls["n"] == 1, "成功结果应命中 24h 缓存"


# ── detect_market_regime macro 修正 ────────────────────────────
def _regime(**kw):
    """默认中性参数，避免趋势/情绪路径干扰（range_bound 基准）。"""
    base = dict(
        trends={"000001": {"return_1m": 0.01, "return_3m": 0.02, "ma_bias_20": 0.01}},
        broad_index_code="000001",
        sentiment_index=55.0,
        adv_ratio=0.55,
    )
    base.update(kw)
    return market_trends.detect_market_regime(**base)


def test_macro_none_behavior_unchanged():
    """macro=None → 行为与既有实现一致（range_bound 基准）。"""
    assert _regime() == "range_bound"
    assert _regime(macro=None) == "range_bound"


def test_macro_pmi_below_50_defensive():
    """PMI<50（macro_direction=-1）+ 中性市态 → defensive_rotate。"""
    macro = {"macro_direction": -1, "pmi_value": 49.5, "pmi_direction": -1}
    assert _regime(macro=macro) == "defensive_rotate"


def test_macro_bullish_neutral_to_weakening():
    """宏观偏上（macro_direction=+1）+ 中性市态 → bull_weakening。"""
    macro = {"macro_direction": 1, "lpr_direction": 1}
    assert _regime(macro=macro) == "bull_weakening"


def test_macro_conflict_keeps_regime():
    """宏观偏上 + bear（冲突）→ 保持 bear（宏观不主导快变量）。

    注：core 需输出 bear —— 满足 sentiment≥50（避开 defensive_rotate）、
    ret_1m≥-0.05（避开 correction）、ret_3m<-0.10。
    """
    macro = {"macro_direction": 1, "lpr_direction": 1}
    assert _regime(
        trends={"000001": {"return_1m": -0.02, "return_3m": -0.15, "ma_bias_20": 0.0}},
        sentiment_index=55.0, adv_ratio=0.5,
        macro=macro,
    ) == "bear"


def test_macro_same_direction_strengthens():
    """宏观偏下 + defensive_rotate（同向）→ 强化为 bear。"""
    macro = {"macro_direction": -1, "pmi_value": 48.0, "pmi_direction": -1}
    assert _regime(
        trends={"000001": {"return_1m": -0.01, "return_3m": -0.05, "ma_bias_20": -0.03}},
        sentiment_index=45.0, adv_ratio=0.45,
        macro=macro,
    ) == "bear"


def test_macro_neutral_keeps_regime():
    """macro_direction=0（三指标互抵/全 None）→ 行为不变。"""
    macro = {"macro_direction": 0, "sources": []}
    assert _regime(macro=macro) == "range_bound"
    assert _regime(macro={}) == "range_bound"


@pytest.mark.asyncio
async def test_update_market_regime_passes_macro(monkeypatch):
    """调用点：update_market_regime("A") 组装 macro snapshot 传入 detect_market_regime。"""
    from app.services.market_data_hub import market_data_hub

    captured = {}

    def fake_detect(**kwargs):
        captured.update(kwargs)
        return "range_bound"

    def fake_snapshot():
        return {"macro_direction": -1, "pmi_value": 49.0}

    with patch("app.services.market_trends.detect_market_regime", fake_detect), \
         patch("app.fetchers.macro_fetcher.fetch_macro_snapshot", side_effect=fake_snapshot):
        await market_data_hub.update_market_regime("A")
    assert captured.get("macro") == {"macro_direction": -1, "pmi_value": 49.0}, \
        f"update_market_regime 应传 macro snapshot: {captured}"


@pytest.mark.asyncio
async def test_update_market_regime_snapshot_failure_degrades(monkeypatch):
    """macro snapshot 失败 → macro=None 传入（降级）。"""
    from app.services.market_data_hub import market_data_hub

    captured = {}

    def fake_detect(**kwargs):
        captured.update(kwargs)
        return "range_bound"

    with patch("app.services.market_trends.detect_market_regime", fake_detect), \
         patch("app.fetchers.macro_fetcher.fetch_macro_snapshot", side_effect=RuntimeError("down")):
        await market_data_hub.update_market_regime("A")
    assert captured.get("macro") is None
