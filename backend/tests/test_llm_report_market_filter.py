"""
P0-2 (R4-13 / N04 补全): HK/US llm-report 指数过滤。

- _filter_indices_for_market: HK/US 报告 indices 按 market_ctx.index_symbols 白名单过滤
  （^ 前缀归一化），A/GLOBAL 保持全量。
- _filter_commodities_for_market: HK/US 不注入 A 股期货商品数据。
- 完整 llm_report 路径：market=HK + mock indices 含 A/HK → 传入 prompt 的 indices 仅 HK。

mock 数据源与 LLM，无网络。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.market_context import resolve_market_context
from app.routers.analysis import (
    _filter_commodities_for_market,
    _filter_indices_for_market,
)

_INDICES_A_HK = [
    {"symbol": "000001", "name": "上证指数", "price": 3832.26, "change_pct": 0.72},
    {"symbol": "399001", "name": "深证成指", "price": 12000.0, "change_pct": 0.5},
    {"symbol": "000300", "name": "沪深300", "price": 4100.0, "change_pct": 0.3},
    {"symbol": "^HSI", "name": "恒生指数", "price": 23000.0, "change_pct": 0.8},
    {"symbol": "^HSTECH", "name": "恒生科技指数", "price": 4829.22, "change_pct": 0.53},
]


def test_filter_indices_hk_excludes_a_stock():
    """P0-2: HK 报告 indices 只保留恒生系，A 股指数全部排除。"""
    mctx = resolve_market_context("HK")
    filtered = _filter_indices_for_market(mctx, _INDICES_A_HK)
    syms = {i["symbol"] for i in filtered}
    assert syms == {"^HSI", "^HSTECH"}, f"HK 过滤结果: {syms}"
    names = [i["name"] for i in filtered]
    assert not any("上证" in n or "深证" in n or "沪深" in n for n in names), \
        "A 股指数仍混入 HK 报告"


def test_filter_indices_hk_tolerates_bare_symbol():
    """P0-2: 数据侧无 ^ 前缀（HSI）与配置侧 ^HSI 等价。"""
    mctx = resolve_market_context("HK")
    data = [{"symbol": "HSI", "name": "恒生指数", "price": 1.0, "change_pct": 0.0},
            {"symbol": "000001", "name": "上证指数", "price": 1.0, "change_pct": 0.0}]
    filtered = _filter_indices_for_market(mctx, data)
    assert [i["symbol"] for i in filtered] == ["HSI"]


def test_filter_indices_us():
    """P0-2: US 报告只保留美股指数。"""
    mctx = resolve_market_context("US")
    data = _INDICES_A_HK + [
        {"symbol": "^GSPC", "name": "标普500", "price": 5500.0, "change_pct": 0.5},
        {"symbol": "^IXIC", "name": "纳斯达克", "price": 18000.0, "change_pct": 0.9},
    ]
    filtered = _filter_indices_for_market(mctx, data)
    syms = {i["symbol"] for i in filtered}
    assert syms == {"^GSPC", "^IXIC"}, f"US 过滤结果: {syms}"


def test_filter_indices_a_keeps_all():
    """P0-2: A 市场报告保持全量（含日经/美股等关联信息，不回归）。"""
    mctx = resolve_market_context("A")
    data = _INDICES_A_HK + [{"symbol": "^N225", "name": "日经225", "price": 39000.0, "change_pct": 1.0}]
    filtered = _filter_indices_for_market(mctx, data)
    assert len(filtered) == len(data)


def test_filter_commodities_market():
    """P0-2: HK/US 不注入 A 股期货商品；A/GLOBAL 保留。"""
    comms = [{"name": "沪金", "price": 800.0, "change_pct": 0.2}]
    assert _filter_commodities_for_market(resolve_market_context("HK"), comms) == []
    assert _filter_commodities_for_market(resolve_market_context("US"), comms) == []
    assert _filter_commodities_for_market(resolve_market_context("A"), comms) == comms
    assert _filter_commodities_for_market(resolve_market_context("GLOBAL"), comms) == comms


@pytest.mark.asyncio
async def test_llm_report_hk_prompt_receives_hk_only_indices():
    """P0-2: llm_report 完整路径——market=HK 时 generate_market_report 收到过滤后 indices。"""
    from app.routers import analysis as analysis_mod

    captured: dict = {}

    async def _fake_report(indices, commodities, market_data, indicators, news, macro_news, market="A"):
        captured["indices"] = indices
        captured["commodities"] = commodities
        return "HK 报告：恒生指数(HSTECH): 4829.22"

    with patch.object(analysis_mod.market_data_hub, "get_all_realtime",
                      new_callable=AsyncMock,
                      return_value=[{"symbol": "513010", "name": "恒生科技ETF",
                                     "asset_type": "ETF", "price": 0.628,
                                     "change_pct": 0.5}]), \
         patch.object(analysis_mod.market_data_hub, "get_indices",
                      new_callable=AsyncMock, return_value=_INDICES_A_HK), \
         patch.object(analysis_mod.market_data_hub, "get_commodities",
                      new_callable=AsyncMock,
                      return_value=[{"name": "沪金", "price": 800.0, "change_pct": 0.2}]), \
         patch.object(analysis_mod.market_data_hub, "get_news_headlines",
                      new=MagicMock(return_value=[])), \
         patch.object(analysis_mod.market_data_hub, "get_news_macro",
                      new=MagicMock(return_value=[])), \
         patch.object(analysis_mod.market_data_hub, "get_market_regime",
                      return_value="range_bound"), \
         patch.object(analysis_mod.market_data_hub, "get_market_sentiment",
                      return_value={"sentiment_index": 40, "sentiment_label": "偏悲观"}), \
         patch.object(analysis_mod, "generate_market_report",
                      new=AsyncMock(side_effect=_fake_report)):
        resp = await analysis_mod.llm_report(analysis_mod.LLMReportRequest(
            symbols=["513010"], market="HK"))

    assert resp["report"].startswith("HK 报告")
    idx_syms = {i["symbol"] for i in captured["indices"]}
    assert idx_syms == {"^HSI", "^HSTECH"}, f"prompt indices 应仅 HK: {idx_syms}"
    assert captured["commodities"] == [], "HK 报告不应注入 A 股期货商品"
