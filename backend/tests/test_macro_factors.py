"""
round13 §3.1 P2: 宏观环境因子（MARKET_LEVEL 类）+ LLM 上下文。

契约: api-contracts/factors/macro-factors.md

- 4 个 compute 函数: macro.m2_trend / macro.pmi_level / macro.lpr_direction / macro.gdp_trend
- 注册两处: factor_registry._BUILTIN_COMPUTERS + routers/factors.MARKET_LEVEL_FACTOR_CODES
- /factors/active: status="static" + reason「市场级因子」
- LLM 上下文: domestic_macro 含 pmi_gdp + macro_snapshot（真实值非占位）

mock akshare，无网络。
"""
import datetime

import pandas as pd
import pytest
from unittest.mock import patch

from app.factors.factor_registry import registry
from app.fetchers import macro_fetcher
from app.services import llm_context
from app.services.cache_service import sync_memory_cache

MACRO_CODES = {
    "macro.m2_trend",
    "macro.pmi_level",
    "macro.lpr_direction",
    "macro.gdp_trend",
}


def _rt(fn, timeout=15):
    return fn()


def _clear():
    sync_memory_cache.clear()


def _m2_df():
    return pd.DataFrame([
        ["2026年04月份", 100, 7.2, 0.1, 50, 1.0, 0.0, 20, 3.0, 0.0],
        ["2026年05月份", 101, 7.0, 0.1, 51, 1.1, 0.0, 21, 3.0, 0.0],
        ["2026年06月份", 102, 6.8, 0.1, 52, 1.2, 0.0, 22, 3.0, 0.0],
    ], columns=[
        "月份", "货币和准货币(M2)-数量(亿元)", "货币和准货币(M2)-同比增长",
        "货币和准货币(M2)-环比增长", "货币(M1)-数量(亿元)", "货币(M1)-同比增长",
        "货币(M1)-环比增长", "流通中的现金(M0)-数量(亿元)", "流通中的现金(M0)-同比增长",
        "流通中的现金(M0)-环比增长",
    ])


def _pmi_df():
    return pd.DataFrame([
        ["中国官方制造业PMI", datetime.date(2026, 6, 30), 50.1, 50.0, 49.9],
        ["中国官方制造业PMI", datetime.date(2026, 7, 31), 49.5, 50.0, 50.1],
    ], columns=["商品", "日期", "今值", "预测值", "前值"])


def _gdp_df():
    return pd.DataFrame([
        ["中国GDP年率报告", datetime.date(2025, 4, 16), 5.4, 5.2, 5.4],
        ["中国GDP年率报告", datetime.date(2025, 7, 15), 5.2, None, 5.4],
        ["中国GDP年率报告", datetime.date(2025, 10, 17), 4.8, None, 5.2],
        ["中国GDP年率报告", datetime.date(2026, 1, 16), 4.6, None, 4.8],
        ["中国GDP年率报告", datetime.date(2026, 4, 16), 5.0, None, 4.6],
    ], columns=["商品", "日期", "今值", "预测值", "前值"])


def _lpr_df():
    return pd.DataFrame([
        [datetime.date(2025, 7, 20), 3.45, 3.95, 4.35, 4.9],
        [datetime.date(2026, 7, 20), 3.0, 3.5, 4.35, 4.9],
    ], columns=["TRADE_DATE", "LPR1Y", "LPR5Y", "RATE_1", "RATE_2"])


def _macro_patch():
    """返回 ExitStack 上下文管理器（嵌套 patch，避免 tuple 不可用问题）。"""
    import contextlib
    stack = contextlib.ExitStack()
    stack.enter_context(patch("akshare.macro_china_money_supply", side_effect=lambda: _m2_df()))
    stack.enter_context(patch("akshare.macro_china_pmi_yearly", side_effect=lambda: _pmi_df()))
    stack.enter_context(patch("akshare.macro_china_gdp_yearly", side_effect=lambda: _gdp_df()))
    stack.enter_context(patch("akshare.macro_china_lpr", side_effect=lambda: _lpr_df()))
    stack.enter_context(patch.object(macro_fetcher, "run_in_thread", _rt))
    return stack


# ── 注册两处 ───────────────────────────────────────────────────
def test_macro_codes_registered_in_computers():
    """factor_registry._computers 含 4 个宏观因子 code。"""
    for code in MACRO_CODES:
        assert code in registry._computers, f"{code} 未注册 compute 函数"


def test_macro_codes_in_market_level_set():
    """routers/factors.MARKET_LEVEL_FACTOR_CODES 含 4 code（/factors/active static 标注）。"""
    from app.routers.factors import MARKET_LEVEL_FACTOR_CODES
    for code in MACRO_CODES:
        assert code in MARKET_LEVEL_FACTOR_CODES, f"{code} 不在 MARKET_LEVEL_FACTOR_CODES"


def test_macro_codes_have_yaml_definition():
    """YAML 定义存在且 category="macro"、频率正确。"""
    freq = {"macro.m2_trend": "monthly", "macro.pmi_level": "monthly",
            "macro.lpr_direction": "monthly", "macro.gdp_trend": "quarterly"}
    for code, f in freq.items():
        d = registry.get_factor(code)
        assert d is not None, f"{code} 无 YAML 定义"
        assert d.category == "macro", f"{code} category 应为 macro，实际 {d.category}"
        assert d.frequency == f, f"{code} 频率应为 {f}，实际 {d.frequency}"


def test_macro_codes_static_status():
    """4 code 在 /factors/active 语义中为 static + 市场级因子 reason。"""
    from app.routers.factors import _status_of
    for code in MACRO_CODES:
        status, reason = _status_of(code, None, 0.02)
        assert status == "static", f"{code} 应为 static，实际 {status}"
        assert "市场级因子" in reason, f"{code} reason 应含「市场级因子」: {reason}"


# ── compute 函数逻辑 ───────────────────────────────────────────
def test_compute_m2_trend():
    fn = registry._computers["macro.m2_trend"]
    assert fn({"macro_snapshot": {"m2_direction": -1}}) == -1.0
    assert fn({"macro_snapshot": {"m2_direction": 1}}) == 1.0
    assert fn({"macro_snapshot": {"m2_direction": 0}}) == 0.0
    assert fn({}) == 0.0, "snapshot 缺失 → 0（诚实降级）"


def test_compute_pmi_level():
    fn = registry._computers["macro.pmi_level"]
    assert fn({"macro_snapshot": {"pmi_value": 50.0}}) == 1.0, "PMI=50 → 荣枯线上 = 1"
    assert fn({"macro_snapshot": {"pmi_value": 49.5}}) == 0.0
    assert fn({"macro_snapshot": {"pmi_value": None}}) == 0.0


def test_compute_lpr_direction():
    fn = registry._computers["macro.lpr_direction"]
    assert fn({"macro_snapshot": {"lpr_direction": 1}}) == 1.0, "降息周期 = +1"
    assert fn({"macro_snapshot": {"lpr_direction": -1}}) == -1.0
    assert fn({}) == 0.0


def test_compute_gdp_trend_percentile():
    """GDP 分位：高于 75 分位 → +1，低于 25 分位 → -1，中间 → 0。"""
    fn = registry._computers["macro.gdp_trend"]
    series = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5]
    assert fn({"macro_gdp_series": series + [6.9]}) == 1.0, "末值高于 75 分位 → +1"
    assert fn({"macro_gdp_series": series + [2.9]}) == -1.0, "末值低于 25 分位 → -1"
    assert fn({"macro_gdp_series": series + [4.8]}) == 0.0, "中位 → 0"
    assert fn({}) == 0.0, "序列缺失 → 0"
    assert fn({"macro_gdp_series": [1.0, 2.0]}) == 0.0, "样本 <4 → 0（季频样本不足诚实降级）"


# ── 数据注入（_fetch_market_data 组装 macro_snapshot）──────────
@pytest.mark.asyncio
async def test_macro_snapshot_injected_into_data():
    """_inject_macro_data：data["macro_snapshot"] 注入真实 snapshot + gdp 序列（非每标的重复拉取）。"""
    _clear()
    data = {"510300": {}, "588000": {}}
    with _macro_patch():
        await registry._inject_macro_data(data, list(data.keys()))
    for sym in data:
        snap = data[sym].get("macro_snapshot")
        assert snap is not None, f"{sym} 应注入 macro_snapshot"
        assert snap["pmi_value"] == 49.5
        assert snap["macro_direction"] == -1
        assert data[sym].get("macro_gdp_series") == [5.4, 5.2, 4.8, 4.6, 5.0], \
            "GDP 序列应注入（季频 gdp_trend 用）"


# ── LLM 上下文（domestic_macro 扩展）───────────────────────────
class _FakeHubMin:
    def get_market_regime(self, market="A"):
        return "range_bound"

    def get_market_sentiment(self):
        return {}

    def get_index_realtime(self):
        return []

    async def get_global_indices(self):
        return {}

    def get_sector_momentum(self):
        return []

    def get_hot_plates(self):
        return []

    def get_sector_heat(self):
        return []

    async def get_all_realtime(self):
        return []

    async def get_news(self):
        return []

    def get_news_headlines(self):
        return []

    def get_news_macro(self):
        return []

    async def get_commodities(self):
        return []

    async def get_portfolio(self):
        return []

    async def get_fund_flow(self, sym, timeout=8):
        return {}

    async def get_market_fundamentals(self, symbol):
        return None

    async def get_global_liquidity(self):
        return {}


@pytest.mark.asyncio
async def test_context_macro_has_pmi_gdp_and_snapshot(monkeypatch):
    """domestic_macro 含 pmi_gdp（PMI/GDP 真实值）+ macro_snapshot（方向标注）。"""
    _clear()
    with _macro_patch():
        ctx = await llm_context.build_full_context(
            _FakeHubMin(), market="A",
            include_regime=False, include_sentiment=False, include_indices=False,
            include_sectors=False, include_news=False, include_portfolio=False,
            include_fund_flow=False, include_commodities=False, include_global_liquidity=False,
        )
    macro = ctx.get("domestic_macro")
    assert macro is not None
    pmi_gdp = macro.get("pmi_gdp") or {}
    assert pmi_gdp.get("pmi", {}).get("value") == 49.5, "PMI 真实值（非占位）"
    assert pmi_gdp.get("gdp", {}).get("value") == 5.0, "GDP 真实值（非占位）"
    snap = macro.get("macro_snapshot") or {}
    assert snap.get("pmi_direction") == -1
    assert snap.get("lpr_direction") == 1
    assert snap.get("macro_direction") == -1, "方向标注应随真实数据聚合"
