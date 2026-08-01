"""TDD: F1-3/F1-4 — LLM 上下文数据缺失 + market 参数传导。

覆盖：
  1. build_full_context(market=HK) → index_realtime 取「港股」区域指数（含恒生）
  2. build_full_context(market=US) → 取「美股」区域
  3. build_full_context(market=A) → 用本地指数缓存（行为不变）
  4. 非 A 市场不采集板块动量（sector_momentum 为空）
  5. _build_market_context：index_realtime 为空时从全球指数兜底 + benchmark_stocks 填充
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeHub:
    """mock market_data_hub，只暴露测试关心的方法。"""

    def __init__(self):
        self._index_cache = [
            {"symbol": "000001", "name": "上证指数", "price": 3000.0, "asset_type": "index"},
            {"symbol": "399001", "name": "深证成指", "price": 10000.0, "asset_type": "index"},
            {"symbol": "399006", "name": "创业板指", "price": 2000.0, "asset_type": "index"},
        ]
        self._global_idx = {
            "A股": self._index_cache,
            "港股": [
                {"symbol": "^HSI", "name": "恒生指数", "price": 21000.0, "asset_type": "index"},
                {"symbol": "^HSTECH", "name": "恒生科技指数", "price": 4500.0, "asset_type": "index"},
            ],
            "美股": [
                {"symbol": "^GSPC", "name": "标普500", "price": 5500.0, "asset_type": "index"},
                {"symbol": "^IXIC", "name": "纳斯达克", "price": 18000.0, "asset_type": "index"},
            ],
        }

    def get_index_realtime(self):
        return self._index_cache

    async def get_global_indices(self):
        return self._global_idx

    def get_market_regime(self, market="A"):
        return "range_bound"

    def get_market_sentiment(self):
        return {"sentiment_index": 50, "sentiment_label": "中性"}

    def get_sector_momentum(self):
        return [{"sector_code": "BK1036", "sector_name": "半导体", "change_pct": 2.5},
                {"sector_code": "BK0475", "sector_name": "银行", "change_pct": -0.8}]

    def get_hot_plates(self):
        return []

    def get_sector_heat(self):
        return []

    async def get_all_realtime(self):
        return []

    async def get_commodities(self):
        return []

    def get_news_headlines(self):
        return []

    def get_news_macro(self):
        return []

    def get_pool(self, layer=None):
        return []

    def get_fund_flow(self, sym, timeout=8):
        return {"main_net_inflow": 100.0}

    def get_sector_stocks(self, code):
        return [{"stock_code": "688111", "stock_name": "金山办公"},
                {"stock_code": "600584", "stock_name": "长电科技"}]

    def get_by_code(self, code):
        return None


@pytest.mark.asyncio
async def test_context_market_hk_uses_hk_indices():
    """F1-4: market=HK → index_realtime 含恒生指数。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="HK",
        include_regime=False, include_sentiment=False, include_indices=True,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    names = [i.get("name") for i in ctx.get("index_realtime", [])]
    assert any("恒生" in n for n in names), f"HK 上下文应含恒生指数: {names}"


@pytest.mark.asyncio
async def test_context_market_us_uses_us_indices():
    """F1-4: market=US → index_realtime 含标普500。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="US",
        include_regime=False, include_sentiment=False, include_indices=True,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    names = [i.get("name") for i in ctx.get("index_realtime", [])]
    assert any("标普" in n or "纳斯达克" in n for n in names), f"US 上下文应含美股指数: {names}"


@pytest.mark.asyncio
async def test_context_market_a_uses_local_cache():
    """F1-4 回归: market=A 仍用本地指数缓存。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="A",
        include_regime=False, include_sentiment=False, include_indices=True,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    names = [i.get("name") for i in ctx.get("index_realtime", [])]
    assert any("上证" in n for n in names), f"A 上下文应含上证指数: {names}"


@pytest.mark.asyncio
async def test_non_a_market_no_sector_momentum():
    """F1-4: HK/US 市场不采集 A 股板块动量。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="HK",
        include_regime=False, include_sentiment=False, include_indices=False,
        include_sectors=True, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    assert ctx.get("sector_momentum") == [] or "sector_momentum" not in ctx


@pytest.mark.asyncio
async def test_build_market_context_index_fallback():
    """F1-3: 本地指数缓存为空 → 从全球指数分组兜底。"""
    from app.services.strategy_design import _build_market_context

    hub = _FakeHub()
    hub._index_cache = []  # 模拟缓存未刷新
    ctx = await _build_market_context(hub)
    assert len(ctx.get("index_realtime", [])) >= 3, f"index_realtime 应兜底非空: {ctx.get('index_realtime')}"


@pytest.mark.asyncio
async def test_build_market_context_benchmark_stocks():
    """F1-3: benchmark_stocks 不再恒为空（含领涨板块成分股）。"""
    from app.services.strategy_design import _build_market_context

    ctx = await _build_market_context(_FakeHub())
    bs = ctx.get("benchmark_stocks", [])
    assert len(bs) >= 1, f"benchmark_stocks 应有龙头股: {bs}"
    assert any("stock_name" in s or "name" in s for s in bs)
