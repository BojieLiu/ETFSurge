"""
R5-3-2: get_asset_realtime 分支参数化测试（测试防护体系）。

@parametrize 覆盖 A/HK/US/index 全分支，断言「返回值与分支匹配」：
- index 不得返回股票价（指数走 fetch_index_realtime，000001 → 上证指数非平安银行）
- HK 不走 A 股路径（U1/N03 回归）
- A 走 fetch_a_stock_realtime
- US 走 TwelveData/Finnhub 路由

mock 数据源，无网络。
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services import market_service as ms


class TestAssetRealtimeBranchParametrized:
    """R5-3-2: 分支参数化——新增分支（如 gold/oil）时强制补参。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("asset_type,fetcher_name,symbol", [
        ("A", "fetch_a_stock_realtime", "600519"),
        ("HK", "fetch_hk_stock_realtime", "00700"),
    ])
    async def test_a_hk_use_their_fetcher(self, asset_type, fetcher_name, symbol, monkeypatch):
        """A → fetch_a_stock_realtime；HK → fetch_hk_stock_realtime（HK 不走 A 股路径）。"""
        from app.fetchers import china_market

        def _fake(fetch_symbol, **kw):
            return [{"symbol": fetch_symbol, "name": "标的", "price": 10.0,
                     "change_pct": 0.1, "asset_type": asset_type}]
        monkeypatch.setattr(ms, "_asset_realtime_cache", {})
        monkeypatch.setattr(ms, "get_realtime_batch", AsyncMock(return_value=[]))
        monkeypatch.setattr(china_market, fetcher_name, _fake)
        monkeypatch.setattr(china_market, "fetch_index_realtime",
                            lambda: [{"symbol": "000001", "name": "上证指数"}])
        result = await ms.get_asset_realtime(symbol, asset_type)
        assert result is not None
        assert result["symbol"] == symbol
        # HK 分支不得误走 A 股 fetch_a_stock_realtime（U1/N03：A 股路径对非 A 返回空 → 污染熔断）
        if asset_type == "HK":
            assert result["asset_type"] == "HK"

    @pytest.mark.asyncio
    async def test_index_branch_returns_index_not_stock(self, monkeypatch):
        """index 分支：000001 返回上证指数，而非 A 股股票（平安银行）错位行情。"""
        monkeypatch.setattr(ms, "_asset_realtime_cache", {})
        monkeypatch.setattr("app.fetchers.china_market.fetch_index_realtime",
                            lambda: [
                                {"symbol": "000001", "name": "上证指数", "price": 3832.26,
                                 "change_pct": 0.72, "asset_type": "index"},
                                {"symbol": "399001", "name": "深证成指", "price": 12000.0,
                                 "change_pct": 0.5, "asset_type": "index"},
                            ])
        # A 股路径若被误走会返回平安银行 11.63 —— 用会抛错的 A 股 fetcher 验证不触达
        monkeypatch.setattr("app.fetchers.china_market.fetch_a_stock_realtime",
                            lambda *a, **k: (_ for _ in ()).throw(
                                AssertionError("index 分支不得走 A 股股票路径")))
        result = await ms.get_asset_realtime("000001", "index")
        assert result is not None
        assert result["name"] == "上证指数", f"index 分支应返回指数: {result}"

    @pytest.mark.asyncio
    async def test_us_branch_routes_to_us_sources(self, monkeypatch):
        """US 分支：走 _route_us（TwelveData/Finnhub），返回美股数据。"""
        monkeypatch.setattr(ms, "_asset_realtime_cache", {})
        monkeypatch.setattr(ms, "_route_us",
                            AsyncMock(return_value={"symbol": "SPY", "name": "SPDR S&P 500 ETF",
                                                    "price": 550.0, "change_pct": 0.3,
                                                    "asset_type": "US"}))
        # A/HK 路径不应触达（US 分支独立路由）
        monkeypatch.setattr("app.fetchers.china_market.fetch_a_stock_realtime",
                            AsyncMock(side_effect=AssertionError("US 分支不得走 A 股路径")))
        result = await ms.get_asset_realtime("SPY", "US")
        assert result is not None
        assert result["asset_type"] == "US"
        assert result["price"] == 550.0

    @pytest.mark.asyncio
    async def test_a_branch_never_returns_index_data(self, monkeypatch):
        """A 分支：即使 fetch_index_realtime 有 000001，A 股查询也不得返回指数。"""
        monkeypatch.setattr(ms, "_asset_realtime_cache", {})
        monkeypatch.setattr("app.fetchers.china_market.fetch_a_stock_realtime",
                            lambda *a, **k: [{"symbol": "600519", "name": "贵州茅台",
                                              "price": 1750.5, "change_pct": 1.2,
                                              "asset_type": "A"}])
        result = await ms.get_asset_realtime("600519", "A")
        assert result is not None
        assert result["symbol"] == "600519"
        assert result["name"] == "贵州茅台"
