"""TDD tests for global indices — HK 3 major indices + expanded global coverage.

Mocks Sina (first-tier) and Stooq (fallback) instead of yfinance.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services import market_service as ms


async def test_global_indices_hk_three_included():
    """All three HK major indices (HSI, HSCE, HSTECH) must be present in response."""
    defs = [
        ("^HSI", "恒生指数", "港股"),
        ("^HSCE", "恒生国企指数", "港股"),
        ("^HSTECH", "恒生科技指数", "港股"),
    ]

    def fake_sina(sym):
        return {"symbol": sym, "price": 20000.0, "change_pct": 0.5}

    # Clear module-level cache before test
    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime", return_value=[]), \
         patch("app.fetchers.china_market.fetch_sina_global_index",
               side_effect=fake_sina):
        regions = await ms.get_global_indices()

    for sym, name in [("^HSI", "恒生指数"), ("^HSCE", "恒生国企指数"), ("^HSTECH", "恒生科技指数")]:
        items = [d for d in regions.get("港股", []) if d["symbol"] == sym]
        assert len(items) == 1, f"Missing HK index: {sym} ({name})"
        assert items[0]["price"] is not None, f"Price is None for {sym}"
    assert len(regions.get("港股", [])) >= 3


async def test_global_indices_foreign_returns_data():
    """HK/US/AP/EU index entries from Sina must have real price/change_pct."""
    defs = [
        ("^HSI", "恒生指数", "港股"),
        ("^GSPC", "标普500", "美股"),
        ("^N225", "日经225", "日经"),
        ("^FTSE", "英国富时100", "欧洲"),
    ]

    def fake_sina(sym):
        return {"symbol": sym, "price": 10000.0, "change_pct": 1.0, "available": True}

    # Clear module-level cache before test
    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime",
               return_value=[{"symbol": "000001", "price": 3000.0, "change_pct": 0.5}]), \
         patch("app.fetchers.china_market.fetch_sina_global_index",
               side_effect=fake_sina):
        regions = await ms.get_global_indices()

    for region_name in ("港股", "美股", "日经", "欧洲"):
        items = regions.get(region_name, [])
        assert len(items) > 0, f"Missing region: {region_name}"
        for item in items:
            assert item["price"] is not None, f"Price None for {item['symbol']}"
            assert item["change_pct"] is not None


async def test_global_indices_sina_fails_stooq_fallback():
    """When Sina fails, Stooq should serve as fallback for foreign indices."""
    defs = [("^GSPC", "标普500", "美股")]

    def fake_sina(sym):
        return None  # Sina fails

    def fake_stooq(sym, name, timeout):
        return {"symbol": sym, "name": name, "price": 4500.0, "change_pct": -0.2, "asset_type": "index", "available": True}

    # Clear module-level cache before test
    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime", return_value=[]), \
         patch("app.fetchers.china_market.fetch_sina_global_index",
               side_effect=fake_sina), \
         patch("app.fetchers.stooq_fetcher.fetch_global_index_realtime",
               side_effect=fake_stooq):
        regions = await ms.get_global_indices()

    us = [d for d in regions.get("美股", []) if d["symbol"] == "^GSPC"]
    assert len(us) == 1
    assert us[0]["price"] == 4500.0


async def test_global_indices_one_region_failure_isolated():
    """If one region's source fails, other regions should still return data."""
    defs = [("^HSI", "恒生指数", "港股"), ("^GSPC", "标普500", "美股")]

    def fake_sina(sym):
        if sym == "^HSI":
            return {"symbol": sym, "price": 25000.0, "change_pct": 0.3, "available": True}
        return None  # US fails

    def fake_stooq(sym, name, timeout):
        if sym == "^GSPC":
            return {"symbol": sym, "name": name, "price": 4500.0, "change_pct": -0.2, "asset_type": "index", "available": True}
        return None

    # Clear cache before test
    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime", return_value=[]), \
         patch("app.fetchers.china_market.fetch_sina_global_index",
               side_effect=fake_sina), \
         patch("app.fetchers.stooq_fetcher.fetch_global_index_realtime",
               side_effect=fake_stooq):
        regions = await ms.get_global_indices()

    hk = [d for d in regions.get("港股", []) if d["symbol"] == "^HSI"]
    assert len(hk) == 1
    assert hk[0]["available"] is True

    us = [d for d in regions.get("美股", []) if d["symbol"] == "^GSPC"]
    assert len(us) == 1
    assert us[0]["price"] == 4500.0


async def test_global_indices_all_sources_fail_graceful():
    """If all sources fail, index entries should still exist with available=False."""
    defs = [("^HSI", "恒生指数", "港股"), ("^GSPC", "标普500", "美股")]

    def fake_sina(sym):
        return None

    def fake_stooq(sym, name, timeout):
        return None

    # Clear cache before test
    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime", return_value=[]), \
         patch("app.fetchers.china_market.fetch_sina_global_index",
               side_effect=fake_sina), \
         patch("app.fetchers.stooq_fetcher.fetch_global_index_realtime",
               side_effect=fake_stooq):
        regions = await ms.get_global_indices()

    hk = [d for d in regions.get("港股", []) if d["symbol"] == "^HSI"]
    assert len(hk) == 1
    assert hk[0].get("available") is False


async def test_a_share_indices_have_placeholder_when_no_data():
    """When A-share data sources fail, placeholder entries must still be present."""
    defs = [
        ("000001", "上证指数", "A股"),
        ("399001", "深证成指", "A股"),
    ]

    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime",
               return_value=[]):  # Simulate no data from any source
        regions = await ms.get_global_indices()

    a_share = regions.get("A股", [])
    assert len(a_share) == 2, f"Expected 2 A-share placeholder entries, got {len(a_share)}"
    for item in a_share:
        assert item["symbol"] in ("000001", "399001"), f"Unexpected symbol: {item['symbol']}"
        assert item.get("available") is False, f"{item['symbol']} should be unavailable"
        assert item.get("price") is None
