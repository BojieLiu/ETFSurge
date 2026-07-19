"""Tests for the new free US/global data source fetchers.

Tests mock the underlying HTTP calls to avoid rate limit consumption.
"""

from unittest.mock import patch, MagicMock
import pytest
import json


# ── Twelve Data Fetcher Tests ────────────────────────────────────

@pytest.fixture
def mock_td_response():
    """Sample Twelve Data quote response."""
    return {
        "symbol": "SPY",
        "close": "743.29000",
        "previous_close": "750.72000",
        "volume": "62569200",
        "high": "747.29000",
        "low": "740.80000",
        "open": "742.08000",
        "percent_change": "-0.98971560",
    }


@pytest.fixture
def mock_td_history():
    """Sample Twelve Data time_series response."""
    return {
        "meta": {"symbol": "SPY", "interval": "1day"},
        "values": [
            {"datetime": "2026-07-17", "open": "742.08", "high": "747.29",
             "low": "740.80", "close": "743.29", "volume": "62569200"},
            {"datetime": "2026-07-16", "open": "750.00", "high": "752.00",
             "low": "740.00", "close": "750.72", "volume": "60000000"},
        ],
        "status": "ok",
    }


class TestTwelveDataFetcher:
    def test_fetch_realtime_success(self, mock_td_response):
        from app.fetchers.twelvedata_fetcher import fetch_realtime

        with patch("app.fetchers.twelvedata_fetcher._request", return_value=mock_td_response):
            result = fetch_realtime("SPY")

        assert result is not None
        assert result["symbol"] == "SPY"
        assert result["price"] == 743.29
        assert result["change_pct"] == -0.99
        assert result["change_amount"] == -7.43
        assert result["volume"] == 62569200
        assert result["high"] == 747.29
        assert result["low"] == 740.8
        assert result["open"] == 742.08
        assert result["previous_close"] == 750.72

    def test_fetch_realtime_none_on_missing_close(self):
        from app.fetchers.twelvedata_fetcher import fetch_realtime

        with patch("app.fetchers.twelvedata_fetcher._request", return_value={"symbol": "SPY"}):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_realtime_none_on_error(self):
        from app.fetchers.twelvedata_fetcher import fetch_realtime

        with patch("app.fetchers.twelvedata_fetcher._request", return_value=None):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_history_success(self, mock_td_history):
        from app.fetchers.twelvedata_fetcher import fetch_history

        with patch("app.fetchers.twelvedata_fetcher._request", return_value=mock_td_history):
            result = fetch_history("SPY", days=60)

        assert result is not None
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-16"  # oldest first
        assert result[0]["close"] == 750.72
        assert result[1]["close"] == 743.29
        assert result[1]["volume"] == 62569200

    def test_fetch_history_none_on_error(self):
        from app.fetchers.twelvedata_fetcher import fetch_history

        with patch("app.fetchers.twelvedata_fetcher._request", return_value={"status": "error"}):
            result = fetch_history("SPY")
        assert result is None


# ── Finnhub Fetcher Tests ────────────────────────────────────────

@pytest.fixture
def mock_fh_response():
    """Sample Finnhub quote response."""
    return {
        "c": 743.29, "d": -7.43, "dp": -0.9897,
        "h": 747.29, "l": 740.8, "o": 742.08,
        "pc": 750.72, "t": 1784318400,
    }


@pytest.fixture
def mock_fh_candles():
    """Sample Finnhub candle response."""
    return {
        "c": [743.29, 750.72],
        "h": [747.29, 752.00],
        "l": [740.80, 740.00],
        "o": [742.08, 750.00],
        "s": "ok",
        "t": [1784318400, 1784232000],
        "v": [62569200, 60000000],
    }


class TestFinnhubFetcher:
    def test_fetch_realtime_success(self, mock_fh_response):
        from app.fetchers.finnhub_fetcher import fetch_realtime

        with patch("app.fetchers.finnhub_fetcher._request", return_value=mock_fh_response):
            result = fetch_realtime("SPY")

        assert result is not None
        assert result["symbol"] == "SPY"
        assert result["price"] == 743.29
        assert result["change_pct"] == -0.99
        assert result["change_amount"] == -7.43
        assert result["high"] == 747.29
        assert result["low"] == 740.8
        assert result["open"] == 742.08
        assert result["previous_close"] == 750.72

    def test_fetch_realtime_none_on_empty(self):
        from app.fetchers.finnhub_fetcher import fetch_realtime

        with patch("app.fetchers.finnhub_fetcher._request", return_value={}):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_candles_success(self, mock_fh_candles):
        from app.fetchers.finnhub_fetcher import fetch_candles

        with patch("app.fetchers.finnhub_fetcher._request", return_value=mock_fh_candles):
            result = fetch_candles("SPY", "D")

        assert result is not None
        assert len(result) == 2
        assert "date" in result[0]
        assert "close" in result[0]
        assert "volume" in result[0]

    def test_fetch_candles_none_on_error_status(self):
        from app.fetchers.finnhub_fetcher import fetch_candles

        with patch("app.fetchers.finnhub_fetcher._request", return_value={"s": "no_data"}):
            result = fetch_candles("INVALID")
        assert result is None


# ── Alpha Vantage Fetcher Tests ──────────────────────────────────

@pytest.fixture
def mock_av_response():
    """Sample Alpha Vantage GLOBAL_QUOTE response."""
    return {
        "Global Quote": {
            "01. symbol": "SPY",
            "02. open": "742.0800",
            "03. high": "747.2900",
            "04. low": "740.8000",
            "05. price": "743.2900",
            "06. volume": "62650961",
            "07. latest trading day": "2026-07-17",
            "08. previous close": "750.7200",
            "09. change": "-7.4300",
            "10. change percent": "-0.9897%",
        }
    }


@pytest.fixture
def mock_av_daily():
    """Sample Alpha Vantage TIME_SERIES_DAILY response."""
    return {
        "Meta Data": {"3. Last Refreshed": "2026-07-17"},
        "Time Series (Daily)": {
            "2026-07-17": {
                "1. open": "742.0800", "2. high": "747.2900",
                "3. low": "740.8000", "4. close": "743.2900",
                "5. volume": "62650961",
            },
            "2026-07-16": {
                "1. open": "750.0000", "2. high": "752.0000",
                "3. low": "740.0000", "4. close": "750.7200",
                "5. volume": "60000000",
            },
        },
    }


class TestAlphaVantageFetcher:
    def test_fetch_realtime_success(self, mock_av_response):
        from app.fetchers.alphavantage_fetcher import fetch_realtime

        with patch("app.fetchers.alphavantage_fetcher._request", return_value=mock_av_response):
            result = fetch_realtime("SPY")

        assert result is not None
        assert result["symbol"] == "SPY"
        assert result["price"] == 743.29
        assert result["change_pct"] == -0.99
        assert result["change_amount"] == -7.43
        assert result["latest_trading_day"] == "2026-07-17"

    def test_fetch_realtime_none_on_missing(self):
        from app.fetchers.alphavantage_fetcher import fetch_realtime

        with patch("app.fetchers.alphavantage_fetcher._request", return_value={}):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_daily_success(self, mock_av_daily):
        from app.fetchers.alphavantage_fetcher import fetch_daily

        with patch("app.fetchers.alphavantage_fetcher._request", return_value=mock_av_daily):
            result = fetch_daily("SPY", "compact")

        assert result is not None
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-16"  # oldest first
        assert result[0]["close"] == 750.72
        assert result[1]["close"] == 743.29

    def test_fetch_daily_none_on_error(self):
        from app.fetchers.alphavantage_fetcher import fetch_daily

        with patch("app.fetchers.alphavantage_fetcher._request", return_value={"Error Message": "rate limit"}):
            result = fetch_daily("SPY")
        assert result is None


# ── SourceRegistry Routing Tests ────────────────────────────────

class TestMarketServiceRouting:
    """Test that _route_us integrates new fetchers correctly."""

    @pytest.mark.asyncio
    async def test_route_us_uses_twelvedata_first(self):
        from app.services.market_service import _route_us

        # When Twelve Data returns, others should not be called
        with patch("app.services.market_service.registry") as mock_registry:
            mock_registry.route.return_value = {"symbol": "SPY", "price": 743.29}

            result = await _route_us("SPY")
            assert result is not None
            assert result["price"] == 743.29

    @pytest.mark.asyncio
    async def test_route_us_calls_registry(self):
        from app.services.market_service import _route_us

        with patch("app.services.market_service.registry") as mock_registry:
            mock_registry.route.return_value = None
            result = await _route_us("SPY")
            assert result is None

            # Verify registry was called with 4 sources in correct order
            call_args = mock_registry.route.call_args[0][0]
            source_names = [p[0] for p in call_args]
            assert source_names == ["twelvedata", "finnhub", "alphavantage", "yfinance"]
