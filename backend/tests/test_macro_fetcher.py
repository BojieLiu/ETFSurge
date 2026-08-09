"""
R5-2-10: 国内宏观/流动性数据管道。

- fetch_lpr: LPR 取最后一行字段映射
- fetch_bond_yields: 中美利差计算
- fetch_cpi_ppi: 今值 nan/日期>3月 → stale=true
- akshare 异常 → None + 1h 失败缓存（二次调用不调源）
- 24h 成功缓存
- build_full_context: market='A' → domestic_macro；market='HK' → 无该段；4 源全失败 → unavailable=true

mock akshare，无网络。
"""
import asyncio
import pandas as pd
import pytest
from unittest.mock import patch

from app.fetchers import macro_fetcher
from app.services import llm_context
from app.services.cache_service import sync_memory_cache


def _rt(fn, timeout=15):
    return fn()


def _clear():
    sync_memory_cache.clear()


# ── fetch_lpr ───────────────────────────────────────────────
def test_lpr_last_row_mapping(monkeypatch):
    _clear()
    df = pd.DataFrame([
        ["2026-07-20", 3.0, 3.5],
        ["2026-07-21", 3.0, 3.45],
    ], columns=["日期", "LPR1Y", "LPR5Y"])

    def _fake_ak():
        return df

    with patch("akshare.macro_china_lpr", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_lpr()
    assert r["lpr_1y"] == 3.0
    assert r["lpr_5y"] == 3.45, "应取最后一行（最新一期）"
    assert r["date"] == "2026-07-21"
    assert r["stale"] is False


# ── fetch_bond_yields ───────────────────────────────────────
def test_bond_yields_spread_calc(monkeypatch):
    _clear()
    df = pd.DataFrame([
        ["2026-07-31", 1.7141, 4.75, 0.454],
    ], columns=["日期", "中国国债收益率10年", "美国国债收益率10年", "中国10年-2年期限利差"])

    def _fake_ak():
        return df

    with patch("akshare.bond_zh_us_rate", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_bond_yields()
    assert r["cn_10y"] == pytest.approx(1.7141)
    assert r["us_10y"] == pytest.approx(4.75)
    # (1.7141 - 4.75) * 100 = -303.59 bp
    assert r["spread_bp"] == pytest.approx(-303.59, abs=0.5), f"利差 {r['spread_bp']}"


# ── fetch_cpi_ppi stale ─────────────────────────────────────
def test_cpi_ppi_stale_when_nan(monkeypatch):
    _clear()
    cpi_df = pd.DataFrame([
        ["2026-07", 100.5, float("nan"), -0.1],
    ], columns=["月份", "全国-价格", "全国-同比增长", "全国-环比增长"])
    ppi_df = pd.DataFrame([
        ["2026-07", 103.5, float("nan")],
    ], columns=["月份", "指数", "当月同比增长"])

    def _fake_cpi():
        return cpi_df

    def _fake_ppi():
        return ppi_df

    with patch("akshare.macro_china_cpi", side_effect=_fake_cpi), \
         patch("akshare.macro_china_ppi", side_effect=_fake_ppi), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_cpi_ppi()
    assert r is not None
    assert r["stale"] is True, "今值 nan → stale=true"
    assert "滞后" in r["note"] or "缺失" in r["note"], f"note 应说明原因: {r['note']}"


def test_cpi_ppi_stale_when_old_date(monkeypatch):
    _clear()
    cpi_df = pd.DataFrame([
        ["2025-09", 100.2, 0.2, -0.1],  # > 3 个月前
    ], columns=["月份", "全国-价格", "全国-同比增长", "全国-环比增长"])
    ppi_df = pd.DataFrame([
        ["2025-09", 102.1, -2.1],
    ], columns=["月份", "指数", "当月同比增长"])

    def _fake_cpi():
        return cpi_df

    def _fake_ppi():
        return ppi_df

    with patch("akshare.macro_china_cpi", side_effect=_fake_cpi), \
         patch("akshare.macro_china_ppi", side_effect=_fake_ppi), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_cpi_ppi()
    assert r["stale"] is True, "日期>3个月 → stale=true"
    assert "2025-09" in r["note"], f"note 应含滞后日期: {r['note']}"


def test_cpi_ppi_real_values_from_wide_tables(monkeypatch):
    """round13 修正：宽表同比接口真实取值（cpi_yoy/ppi_yoy 各自独立，非共用月率）。

    回归守护：旧实现错用 monthly 长表（今值=CPI 月率）导致 cpi_yoy==ppi_yoy 假数据；
    此处 mock 降序宽表（最新行在首行）验证取值正确 + 升降序兼容。
    """
    _clear()
    cpi_df = pd.DataFrame([
        ["2026-07", 100.5, 0.5, -0.1],   # 最新（降序首行）
        ["2026-06", 101.0, 1.0, -0.3],
        ["2025-09", 100.2, 0.2, -0.1],   # 旧数据在后
    ], columns=["月份", "全国-价格", "全国-同比增长", "全国-环比增长"])
    ppi_df = pd.DataFrame([
        ["2026-07", 103.5, 3.5],         # 最新（降序首行）
        ["2026-06", 104.1, 4.1],
    ], columns=["月份", "指数", "当月同比增长"])

    with patch("akshare.macro_china_cpi", side_effect=lambda: cpi_df), \
         patch("akshare.macro_china_ppi", side_effect=lambda: ppi_df), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_cpi_ppi()
    assert r["cpi_yoy"] == 0.5, f"CPI 同比取最新行: {r}"
    assert r["ppi_yoy"] == 3.5, f"PPI 同比取最新行: {r}"
    assert r["cpi_yoy"] != r["ppi_yoy"], "cpi/ppi 必须独立取值（防月率共用假数据）"
    assert r["date"] == "2026-07"


# ── 失败缓存 / 成功缓存 ────────────────────────────────────
def test_fail_cached_1h_second_call_no_source(monkeypatch):
    """akshare 异常 → None + 1h 失败缓存（二次调用不调源）。"""
    _clear()
    calls = {"n": 0}

    def _fake_ak():
        calls["n"] += 1
        raise RuntimeError("source down")

    with patch("akshare.macro_china_lpr", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        assert macro_fetcher.fetch_lpr() is None
        assert macro_fetcher.fetch_lpr() is None
    assert calls["n"] == 1, f"失败缓存应阻止第二次触源，实际 {calls['n']} 次"


def test_success_cached_24h(monkeypatch):
    """24h 成功缓存——成功结果二次调用不触源。"""
    _clear()
    calls = {"n": 0}
    df = pd.DataFrame([["2026-07-20", 3.0, 3.5]], columns=["日期", "LPR1Y", "LPR5Y"])

    def _fake_ak():
        calls["n"] += 1
        return df

    with patch("akshare.macro_china_lpr", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r1 = macro_fetcher.fetch_lpr()
        r2 = macro_fetcher.fetch_lpr()
    assert r1 == r2
    assert calls["n"] == 1, "成功结果应命中 24h 缓存"


# ── build_full_context 集成 ─────────────────────────────────
class _FakeHubMin:
    """最小 hub（build_full_context 的其他段全返回空）。"""

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
async def test_context_a_includes_domestic_macro(monkeypatch):
    """market='A' → context 含 domestic_macro（含 LPR）。"""
    df = pd.DataFrame([["2026-07-20", 3.0, 3.5]], columns=["日期", "LPR1Y", "LPR5Y"])

    def _fake_lpr():
        return df

    with patch("akshare.macro_china_lpr", side_effect=_fake_lpr), \
         patch("akshare.bond_zh_us_rate", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_money_supply", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_cpi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_ppi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_pmi_yearly", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_gdp_yearly", side_effect=RuntimeError("down")), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        ctx = await llm_context.build_full_context(
            _FakeHubMin(), market="A",
            include_regime=False, include_sentiment=False, include_indices=False,
            include_sectors=False, include_news=False, include_portfolio=False,
            include_fund_flow=False, include_commodities=False, include_global_liquidity=False,
        )
    macro = ctx.get("domestic_macro")
    assert macro is not None, "A 股 context 应含 domestic_macro（R5-2-10）"
    assert macro["lpr"]["lpr_1y"] == 3.0
    assert macro["unavailable"] is False


@pytest.mark.asyncio
async def test_context_hk_omits_domestic_macro():
    """market='HK' → 无 domestic_macro 键。"""
    ctx = await llm_context.build_full_context(
        _FakeHubMin(), market="HK",
        include_regime=False, include_sentiment=False, include_indices=False,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False, include_global_liquidity=False,
    )
    assert "domestic_macro" not in ctx, "HK 上下文不应含 domestic_macro"


@pytest.mark.asyncio
async def test_context_all_macro_sources_down_unavailable(monkeypatch):
    """四源全失败 → domestic_macro.unavailable == true（LLM 显式写不可用，不编造）。"""
    _clear()
    with patch("akshare.macro_china_lpr", side_effect=RuntimeError("down")), \
         patch("akshare.bond_zh_us_rate", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_money_supply", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_cpi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_ppi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_pmi_yearly", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_gdp_yearly", side_effect=RuntimeError("down")), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        ctx = await llm_context.build_full_context(
            _FakeHubMin(), market="A",
            include_regime=False, include_sentiment=False, include_indices=False,
            include_sectors=False, include_news=False, include_portfolio=False,
            include_fund_flow=False, include_commodities=False, include_global_liquidity=False,
        )
    assert ctx.get("domestic_macro", {}).get("unavailable") is True, \
        f"四源全失败应 unavailable=true: {ctx.get('domestic_macro')}"

