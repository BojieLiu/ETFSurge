"""TDD tests for P0: free US market data sources (Alpha Vantage, Finnhub).

All HTTP calls are mocked; no network needed.
"""
from unittest.mock import patch, MagicMock
import pytest

from app.fetchers.free_us_fetcher import (
    fetch_alphav_realtime,
    fetch_finnhub_realtime,
)

_FAKE_KEY = "fake_key_123"


# ── Alpha Vantage ────────────────────────────────────────────────


def test_alphav_returns_single_symbol():
    """Alpha Vantage returns correct shape for a single US symbol."""
    fake_resp = {
        "Meta Data": {"3. Last Refreshed": "2026-07-15"},
        "Time Series (5min)": {
            "2026-07-15 16:00:00": {
                "1. open": "500.00",
                "2. high": "501.00",
                "3. low": "499.00",
                "4. close": "500.50",
                "5. volume": "1000000",
            }
        },
    }

    def fake_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = fake_resp
        return r

    with patch("requests.get", side_effect=fake_get), \
         patch("app.fetchers.free_us_fetcher._apikey", return_value=_FAKE_KEY):
        result = fetch_alphav_realtime("SPY")
        assert result is not None
        assert result["symbol"] == "SPY"
        assert result["price"] == 500.50
        assert result["asset_type"] == "US"
        assert result["volume"] == 1000000


def test_alphav_returns_none_on_empty():
    """Alpha Vantage returns None when API response is empty."""
    fake_resp = {}

    def fake_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = fake_resp
        return r

    with patch("requests.get", side_effect=fake_get), \
         patch("app.fetchers.free_us_fetcher._apikey", return_value=_FAKE_KEY):
        result = fetch_alphav_realtime("SPY")
        assert result is None


def test_alphav_returns_none_on_error():
    """Alpha Vantage returns None on HTTP error."""
    def fake_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 429  # rate limited
        return r

    with patch("requests.get", side_effect=fake_get), \
         patch("app.fetchers.free_us_fetcher._apikey", return_value=_FAKE_KEY):
        result = fetch_alphav_realtime("SPY")
        assert result is None


def test_alphav_returns_none_without_key():
    """Alpha Vantage returns None when API key is not set."""
    with patch("app.fetchers.free_us_fetcher._apikey", return_value=None):
        result = fetch_alphav_realtime("SPY")
        assert result is None


# ── Finnhub ──────────────────────────────────────────────────────


def test_finnhub_returns_single_symbol():
    """Finnhub returns correct shape for a single US symbol."""
    fake_quote = {
        "c": 450.25,  # current price
        "d": 5.50,    # change
        "dp": 1.23,   # percent change
        "h": 452.00,
        "l": 448.00,
        "o": 449.00,
        "pc": 444.75,  # previous close
        "t": 1721000000,
    }

    def fake_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = fake_quote
        return r

    with patch("requests.get", side_effect=fake_get), \
         patch("app.fetchers.free_us_fetcher._apikey", return_value=_FAKE_KEY):
        result = fetch_finnhub_realtime("AAPL")
        assert result is not None
        assert result["symbol"] == "AAPL"
        assert result["price"] == 450.25
        assert result["change_pct"] == 1.23
        assert result["asset_type"] == "US"


def test_finnhub_returns_none_on_empty():
    """Finnhub returns None when quote is empty."""
    def fake_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {}
        return r

    with patch("requests.get", side_effect=fake_get), \
         patch("app.fetchers.free_us_fetcher._apikey", return_value=_FAKE_KEY):
        result = fetch_finnhub_realtime("AAPL")
        assert result is None


def test_finnhub_returns_none_without_key():
    """Finnhub returns None when API key is not set."""
    with patch("app.fetchers.free_us_fetcher._apikey", return_value=None):
        result = fetch_finnhub_realtime("AAPL")
        assert result is None
