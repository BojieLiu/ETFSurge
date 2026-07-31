"""Phase 3 (v6 plan): MarketDataHub realtime delegate tests.

Verifies hub methods correctly forward args to market_service
(all mocked - no network).
"""
import pytest
from unittest.mock import AsyncMock, patch


def _make_hub():
    from app.services.market_data_hub import MarketDataHub
    hub = MarketDataHub.__new__(MarketDataHub)
    return hub


@pytest.mark.asyncio
async def test_get_realtime_forwards_to_market_service():
    """hub.get_realtime -> market_service.get_realtime_batch."""
    hub = _make_hub()
    with patch("app.services.market_service.get_realtime_batch",
               new=AsyncMock(return_value=[{"symbol": "510300"}])) as m:
        result = await hub.get_realtime(["510300"], "A")
        assert result == [{"symbol": "510300"}]
        m.assert_awaited_once_with(["510300"], "A")


@pytest.mark.asyncio
async def test_get_all_realtime_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.get_all_realtime",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_all_realtime()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_asset_realtime_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.get_asset_realtime",
               new=AsyncMock(return_value={"symbol": "600519"})) as m:
        result = await hub.get_asset_realtime("600519", "stock")
        assert result == {"symbol": "600519"}
        m.assert_awaited_once_with("600519", "stock")


@pytest.mark.asyncio
async def test_get_portfolio_realtime_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.get_portfolio_realtime",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_portfolio_realtime()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_indices_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.get_indices",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_indices()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_global_indices_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.get_global_indices",
               new=AsyncMock(return_value={"A": []})) as m:
        result = await hub.get_global_indices()
        assert result == {"A": []}
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_commodities_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.get_commodities",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_commodities()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_market_history_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.get_history",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_market_history("510300", "A", "daily")
        assert result == []
        m.assert_awaited_once_with("510300", "A", "daily")


@pytest.mark.asyncio
async def test_search_etf_forwards():
    hub = _make_hub()
    with patch("app.services.market_service.search_etf",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.search_etf("300")
        assert result == []
        m.assert_awaited_once_with("300")


def test_hub_has_no_circular_import():
    """Importing both hub and market_service should not crash (lazy imports)."""
    import app.services.market_data_hub
    import app.services.market_service
    assert app.services.market_data_hub.market_data_hub is not None
    assert callable(app.services.market_service.get_all_realtime)
