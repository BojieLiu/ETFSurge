"""
N04/U9 (round3-diagnosis-and-optimization-plan.md N04 / round2-unfixed-fix-plan.md U9):
HK/US 研判报告混入 A 股数据。

- build_full_context 第 5 步 market_data 按 market 过滤（旧 get_all_realtime() 全量 A 股指数）。
- _build_market_overview 标题动态化（### {market}市场，不再硬编码 A股市场）。

无网络，mock 数据源。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.analysis.llm import _build_market_overview


class _FakeHub:
    """mock market_data_hub——get_all_realtime 模拟返回 A 股指数（污染源）。"""

    def __init__(self):
        self._global_idx = {
            "港股": [
                {"symbol": "^HSI", "name": "恒生指数", "price": 21000.0, "asset_type": "index"},
                {"symbol": "^HSTECH", "name": "恒生科技指数", "price": 4500.0, "asset_type": "index"},
            ],
            "美股": [
                {"symbol": "^GSPC", "name": "标普500", "price": 5500.0, "asset_type": "index"},
                {"symbol": "^IXIC", "name": "纳斯达克", "price": 18000.0, "asset_type": "index"},
            ],
        }

    async def get_all_realtime(self):
        # 模拟 A 股指数污染源（旧逻辑对 HK/US 报告也注入这些）
        return [
            {"symbol": "399006", "name": "创业板指", "price": 2000.0, "asset_type": "index"},
            {"symbol": "000016", "name": "上证50", "price": 2600.0, "asset_type": "index"},
        ]

    async def get_global_indices(self):
        return self._global_idx

    def get_market_regime(self, market="A"):
        return "range_bound"

    def get_market_sentiment(self):
        return {}

    def get_index_realtime(self):
        return []

    async def get_commodities(self):
        return []

    def get_news_headlines(self):
        return []

    def get_news_macro(self):
        return []

    def get_sector_momentum(self):
        return []

    def get_hot_plates(self):
        return []

    def get_sector_heat(self):
        return []


@pytest.mark.asyncio
async def test_context_hk_market_data_no_a_stocks():
    """N04: market=HK → market_data 不含创业板/上证50，含港股指数。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="HK",
        include_regime=False, include_sentiment=False, include_indices=False,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    md = ctx.get("market_data", [])
    names = [m.get("name", "") for m in md]
    assert not any("创业板" in n or "上证50" in n for n in names), \
        f"HK 报告不得混入 A 股指数: {names}"
    assert any("恒生" in n for n in names), f"HK 报告应含港股指数: {names}"


@pytest.mark.asyncio
async def test_context_us_market_data_no_a_stocks():
    """N04: market=US → market_data 不含 A 股指数，含美股指数。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="US",
        include_regime=False, include_sentiment=False, include_indices=False,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    md = ctx.get("market_data", [])
    names = [m.get("name", "") for m in md]
    assert not any("创业板" in n or "上证50" in n for n in names), \
        f"US 报告不得混入 A 股指数: {names}"
    assert any("标普" in n or "纳斯达克" in n for n in names), f"US 报告应含美股指数: {names}"


@pytest.mark.asyncio
async def test_context_a_market_data_keeps_a_indices():
    """U9 回归: market=A 的 market_data 保持 A 股指数（行为不变）。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="A",
        include_regime=False, include_sentiment=False, include_indices=False,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    names = [m.get("name", "") for m in ctx.get("market_data", [])]
    assert any("创业板" in n for n in names), f"A 上下文应保留 A 股指数: {names}"


class TestMarketOverviewTitle:
    def test_hk_overview_title_dynamic(self):
        """N04: _build_market_overview(market=HK) 标题为「港股市场」。"""
        overview = _build_market_overview(
            [{"symbol": "^HSI", "name": "恒生指数", "price": 21000.0, "change_pct": 0.5}],
            [], [], [], [], market="HK",
        )
        assert "### 港股市场" in overview, overview
        assert "### A股市场" not in overview, "HK 报告不得硬编码 A股市场 标题"

    def test_us_overview_title_dynamic(self):
        """N04: market=US → 「美股市场」。"""
        overview = _build_market_overview([], [], [], [], [], market="US")
        assert "### 美股市场" in overview, overview
        assert "### A股市场" not in overview

    def test_a_overview_title_default(self):
        """U9 回归: market=A（默认）→ 「A股市场」。"""
        overview = _build_market_overview([], [], [], [], [])
        assert "### A股市场" in overview, overview
