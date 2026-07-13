"""TDD tests for issue 3 (global indices empty for non-A regions).

Sources (akshare A-share, yfinance foreign) are mocked; no DB/network needed.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services import market_service as ms


async def test_global_indices_foreign_non_null():
    """HK and US index entries must have real price/change_pct when source returns data."""
    defs = [
        ("000001", "上证指数", "A股"),
        ("^HSI", "恒生指数", "港股"),
        ("^GSPC", "标普500", "美股"),
    ]

    def fake_yf(symbol):
        return {"symbol": symbol, "price": 12345.0, "change_pct": 1.25}

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.akshare_fetcher.fetch_index_realtime",
               return_value=[{"symbol": "000001", "price": 3000.0, "change_pct": 0.5}]), \
         patch("app.fetchers.yfinance_fetcher.fetch_index_realtime",
               side_effect=fake_yf):
        regions = await ms.get_global_indices()

    hk = [d for d in regions.get("港股", []) if d["symbol"] == "^HSI"][0]
    assert hk["available"] is True
    assert hk["price"] is not None
    assert hk["change_pct"] is not None

    us = [d for d in regions.get("美股", []) if d["symbol"] == "^GSPC"][0]
    assert us["available"] is True
    assert us["price"] is not None


async def test_global_indices_one_region_failure_isolated():
    """If the US source fails, HK should still return data (graceful per-region)."""
    defs = [("^HSI", "恒生指数", "港股"), ("^GSPC", "标普500", "美股")]

    def fake_yf(symbol):
        if symbol == "^GSPC":
            return None  # simulate failure
        return {"symbol": symbol, "price": 18000.0, "change_pct": -0.3}

    with patch.object(ms, "_global_index_defs", new=AsyncMock(return_value=defs)), \
         patch("app.fetchers.akshare_fetcher.fetch_index_realtime", return_value=[]), \
         patch("app.fetchers.yfinance_fetcher.fetch_index_realtime", side_effect=fake_yf):
        regions = await ms.get_global_indices()

    hk = [d for d in regions.get("港股", []) if d["symbol"] == "^HSI"][0]
    assert hk["available"] is True
    us = [d for d in regions.get("美股", []) if d["symbol"] == "^GSPC"][0]
    assert us["available"] is False
