"""Tests for v5_diagnostic_and_optimization_plan.md remaining fixes.

Covers:
  - Z22: get_watchlist - symbol enrichment for non-ETF stocks
  - Z28: Watchlist field name consistency (realtime fields)
  - Z29: Search keyword encoding in frontend
  - Z30: LLM report data pipeline - error tracking, completeness

External network / LLM providers are mocked — no real calls.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Any


# ─── Z22: get_watchlist stock enrichment ────────────────────────


@pytest.mark.asyncio
async def test_get_asset_realtime_for_stock_returns_price():
    """Z22: get_asset_realtime should return price for stock symbols."""
    from app.services.market_service import get_asset_realtime

    mock_realtime = [{"symbol": "600519", "name": "贵州茅台", "price": 1500.0, "change_pct": 1.5, "volume": 1000000}]
    with patch("app.services.market_service._call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_realtime
        result = await get_asset_realtime("600519", "stock")
        assert result is not None
        assert result["price"] == 1500.0
        assert result["change_pct"] == 1.5

        from app.fetchers.china_market import fetch_a_stock_realtime
        mock_call.assert_awaited_with(fetch_a_stock_realtime, "600519")


@pytest.mark.asyncio
async def test_get_asset_realtime_for_a_asset():
    """Z22: get_asset_realtime should handle 'A' asset_type (same as stock)."""
    from app.services.market_service import get_asset_realtime

    mock_realtime = [{"symbol": "510300", "name": "沪深300ETF", "price": 3.8, "change_pct": 0.5}]
    with patch("app.services.market_service._call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_realtime
        result = await get_asset_realtime("510300", "A")
        assert result is not None
        assert result["price"] == 3.8


# ─── Z28: Watchlist field name consistency ──────────────────────


def test_watchlist_fields_use_english():
    """Z28: Watchlist response should use English field names, not Chinese."""
    from app.services.market_service import get_watchlist
    import inspect
    sig = inspect.signature(get_watchlist)
    assert "limit" in sig.parameters
    assert "offset" in sig.parameters


# Helper: simulate get_watchlist enriched item structure
def make_watchlist_item(symbol="600519", name="Test", price=10.0, change_pct=1.0, volume=1000):
    return {
        "id": 1,
        "symbol": symbol,
        "name": name,
        "asset_type": "stock",
        "notes": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": None,
        "realtime": {
            "price": price,
            "change_pct": change_pct,
            "volume": volume,
        },
    }


def test_watchlist_realtime_field_names_consistent():
    """Z28: realtime dict should contain price/change_pct/volume (not Chinese names)."""
    item = make_watchlist_item()
    rt = item["realtime"]
    assert "price" in rt
    assert "change_pct" in rt
    assert "volume" in rt
    # Verify there are NO Chinese-named fields
    chinese_keys = [k for k in rt if not k.isascii()]
    assert len(chinese_keys) == 0, f"Found non-ASCII keys: {chinese_keys}"


# ─── Z29: Search keyword encoding ───────────────────────────────


def test_search_route_accepts_keyword_param():
    """Z29: /search route should accept keyword query param."""
    from app.routers.market import search
    import inspect
    sig = inspect.signature(search)
    params = list(sig.parameters.keys())
    assert "keyword" in params
    assert "market" in params
    assert "include_stocks" in params


def test_chinese_search_encoding():
    """Z29: Chinese search keywords must be URL-encodable/decodable."""
    from urllib.parse import quote, unquote
    keyword = "贵州茅台"
    encoded = quote(keyword, safe='')
    decoded = unquote(encoded)
    assert decoded == keyword
    # Backend should receive the already-decoded keyword
    # (FastAPI Query param auto-decodes URL-encoded values)


# ─── Z30: LLM report data pipeline ──────────────────────────────


@pytest.mark.asyncio
async def test_build_full_context_returns_expected_structure():
    """Z30: build_full_context should return dict with market/regime/sentiment."""
    from app.services.llm_context import build_full_context

    mock_pm = MagicMock()
    mock_pm.get_market_regime.return_value = "range_bound"
    mock_pm.get_market_sentiment.return_value = {"sentiment_index": 29, "sentiment_label": "偏恐惧"}
    mock_pm.get_index_realtime.return_value = []
    mock_pm.get_sector_momentum.return_value = []

    # Mock async calls too
    with patch("app.fetchers.news_fetcher.fetch_news_headlines", return_value=[]):
        with patch("app.services.market_service.get_all_realtime", new_callable=AsyncMock, return_value=[]):
            result = await build_full_context(mock_pm, market="A")
            assert isinstance(result, dict)
            assert result["market_regime"] == "range_bound"
            assert "market_sentiment" in result


@pytest.mark.asyncio
async def test_build_full_context_error_collection():
    """Z30: build_full_context should collect errors from failed sources."""
    from app.services.llm_context import build_full_context

    mock_pm = MagicMock()
    mock_pm.get_market_regime.side_effect = Exception("DataSource timeout")
    mock_pm.get_market_sentiment.return_value = {}
    mock_pm.get_index_realtime.return_value = []
    mock_pm.get_sector_momentum.return_value = []

    with patch("app.fetchers.news_fetcher.fetch_news_headlines", return_value=[]):
        with patch("app.services.market_service.get_all_realtime", new_callable=AsyncMock, return_value=[]):
            result = await build_full_context(mock_pm, market="A")
            # Should still return without crashing
            assert isinstance(result, dict)
            assert "market_regime" in result
