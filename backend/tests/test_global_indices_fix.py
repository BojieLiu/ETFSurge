"""TDD tests for global indices data source fixes.

Fixes:
1. S&P 500 Sina hq code: gb_$spx -> gb_$inx (verified working)
2. European indices: add Sina finance page scrape fallback (verified working)
"""
from unittest.mock import AsyncMock, patch, Mock

import pytest

from app.fetchers.china_market import _GLOBAL_SINA_SHORT
from app.services import market_service as ms


# ── Fix 1: S&P 500 Sina code ────────────────────────────────────

def test_sp500_sina_code_is_correct():
    """_GLOBAL_SINA_SHORT must map ^GSPC to gb_$inx (not gb_$spx)."""
    assert _GLOBAL_SINA_SHORT.get("^GSPC") == "gb_$inx", (
        "S&P 500 Sina code should be gb_$inx (gb_$spx returns empty data)"
    )


# ── Fix 2: Sina page scrap for European indices ──────────────────

def test_eu_indices_have_sina_page_mapping():
    """European index symbols must have a Sina page symbol mapping
    in the new _GLOBAL_SINA_PAGE dict."""
    from app.fetchers.china_market import _GLOBAL_SINA_PAGE
    for sym in ("^FTSE", "^GDAXI", "^FCHI", "^STOXX50E"):
        assert sym in _GLOBAL_SINA_PAGE, (
            f"European index {sym} missing from _GLOBAL_SINA_PAGE"
        )


async def test_fetch_sina_page_eu_returns_valid_data():
    """fetch_sina_page_global_index must parse title and return valid entry."""
    from app.fetchers.china_market import fetch_sina_page_global_index

    result = fetch_sina_page_global_index("^FTSE")
    assert result is not None, "Should return data for ^FTSE"
    assert result.get("price") is not None, "Price should not be None"
    assert result.get("change_pct") is not None, "change_pct should not be None"
    assert isinstance(result["price"], (int, float)), "Price must be numeric"
    assert result["available"] is True


async def test_fetch_sina_page_eu_unknown_symbol_returns_none():
    """fetch_sina_page_global_index must return None for unmapped symbols."""
    from app.fetchers.china_market import fetch_sina_page_global_index

    result = fetch_sina_page_global_index("^UNKNOWN")
    assert result is None


async def test_sina_page_fallback_in_foreign():
    """When Sina hq returns None for European index, Sina page should be tried."""
    defs = [("^FTSE", "英国富时100", "欧洲")]

    # Clear cache
    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0
    ms._global_indices_last_ok.clear()
    ms._global_indices_last_ok_ts = 0

    # Sina hq returns None (as it does for European symbols)
    def fake_sina(sym):
        return None

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime", return_value=[]), \
         patch("app.fetchers.china_market.fetch_sina_global_index",
               side_effect=fake_sina), \
         patch("app.fetchers.global_markets_fetcher.fetch_all", return_value={}), \
         patch("app.fetchers.global_markets_fetcher.fetch_hk_indices", return_value={}), \
         patch("app.fetchers.global_markets_fetcher.fetch_realtime", return_value=None):
        regions = await ms.get_global_indices()

    eu = [d for d in regions.get("欧洲", []) if d["symbol"] == "^FTSE"]
    assert len(eu) == 1, f"Expected 1 EU entry, got {len(eu)}"
    # Should still have data from Sina page fallback
    assert eu[0]["price"] is not None, "Price should not be None (Sina page fallback)"
    assert eu[0]["available"] is True


async def test_sina_page_does_not_break_us_indices():
    """Sina page fallback should not interfere with US indices that work via Sina hq."""
    defs = [
        ("^GSPC", "标普500", "美股"),
        ("^IXIC", "纳斯达克", "美股"),
        ("^DJI", "道琼斯", "美股"),
    ]

    ms._global_indices_cache.clear()
    ms._global_indices_cache_ts = 0
    ms._global_indices_last_ok.clear()
    ms._global_indices_last_ok_ts = 0

    def fake_sina(sym):
        if sym in ("^GSPC", "^IXIC", "^DJI"):
            return {"symbol": sym, "price": 10000.0, "change_pct": 0.5, "available": True}
        return None

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.china_market.fetch_index_realtime", return_value=[]), \
         patch("app.fetchers.china_market.fetch_sina_global_index",
               side_effect=fake_sina), \
         patch("app.fetchers.global_markets_fetcher.fetch_all", return_value={}), \
         patch("app.fetchers.global_markets_fetcher.fetch_hk_indices", return_value={}), \
         patch("app.fetchers.global_markets_fetcher.fetch_realtime", return_value=None):
        regions = await ms.get_global_indices()

    for sym in ("^GSPC", "^IXIC", "^DJI"):
        items = [d for d in regions.get("美股", []) if d["symbol"] == sym]
        assert len(items) == 1, f"Missing {sym}"
        assert items[0]["price"] is not None
        assert items[0]["available"] is True
