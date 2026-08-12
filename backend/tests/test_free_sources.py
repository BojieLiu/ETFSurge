"""Tests for the new free US/global data source fetchers.

Tests mock the underlying HTTP calls to avoid rate limit consumption.
"""

from unittest.mock import patch, MagicMock
import pytest
import json
import asyncio


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
        from app.fetchers.global_markets_fetcher import fetch_realtime_twelvedata as fetch_realtime

        with patch("app.fetchers.global_markets_fetcher._td_request", return_value=mock_td_response):
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
        from app.fetchers.global_markets_fetcher import fetch_realtime_twelvedata as fetch_realtime

        with patch("app.fetchers.global_markets_fetcher._td_request", return_value={"symbol": "SPY"}):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_realtime_none_on_error(self):
        from app.fetchers.global_markets_fetcher import fetch_realtime_twelvedata as fetch_realtime

        with patch("app.fetchers.global_markets_fetcher._td_request", return_value=None):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_history_success(self, mock_td_history):
        from app.fetchers.global_markets_fetcher import fetch_history

        with patch("app.fetchers.global_markets_fetcher._td_request", return_value=mock_td_history):
            result = fetch_history("SPY", days=60)

        assert result is not None
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-16"  # oldest first
        assert result[0]["close"] == 750.72
        assert result[1]["close"] == 743.29
        assert result[1]["volume"] == 62569200

    def test_fetch_history_none_on_error(self):
        from app.fetchers.global_markets_fetcher import fetch_history

        with patch("app.fetchers.global_markets_fetcher._td_request", return_value={"status": "error"}):
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
        from app.fetchers.global_markets_fetcher import fetch_realtime

        with patch("app.fetchers.global_markets_fetcher._request", return_value=mock_fh_response):
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
        from app.fetchers.global_markets_fetcher import fetch_realtime

        with patch("app.fetchers.global_markets_fetcher._request", return_value={}):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_candles_success(self, mock_fh_candles):
        from app.fetchers.global_markets_fetcher import fetch_candles

        with patch("app.fetchers.global_markets_fetcher._request", return_value=mock_fh_candles):
            result = fetch_candles("SPY", "D")

        assert result is not None
        assert len(result) == 2
        assert "date" in result[0]
        assert "close" in result[0]
        assert "volume" in result[0]

    def test_fetch_candles_none_on_error_status(self):
        from app.fetchers.global_markets_fetcher import fetch_candles

        with patch("app.fetchers.global_markets_fetcher._request", return_value={"s": "no_data"}):
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
        from app.fetchers.global_markets_fetcher import fetch_realtime_alphavantage as fetch_realtime

        with patch("app.fetchers.global_markets_fetcher._av_request", return_value=mock_av_response):
            result = fetch_realtime("SPY")

        assert result is not None
        assert result["symbol"] == "SPY"
        assert result["price"] == 743.29
        assert result["change_pct"] == -0.99
        assert result["change_amount"] == -7.43
        assert result["latest_trading_day"] == "2026-07-17"

    def test_fetch_realtime_none_on_missing(self):
        from app.fetchers.global_markets_fetcher import fetch_realtime_alphavantage as fetch_realtime

        with patch("app.fetchers.global_markets_fetcher._av_request", return_value={}):
            result = fetch_realtime("SPY")
        assert result is None

    def test_fetch_daily_success(self, mock_av_daily):
        from app.fetchers.global_markets_fetcher import fetch_daily_alphavantage as fetch_daily

        with patch("app.fetchers.global_markets_fetcher._av_request", return_value=mock_av_daily):
            result = fetch_daily("SPY", "compact")

        assert result is not None
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-16"  # oldest first
        assert result[0]["close"] == 750.72
        assert result[1]["close"] == 743.29

    def test_fetch_daily_none_on_error(self):
        from app.fetchers.global_markets_fetcher import fetch_daily_alphavantage as fetch_daily

        with patch("app.fetchers.global_markets_fetcher._av_request", return_value={"Error Message": "rate limit"}):
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

            # Verify registry was called with 3 sources in correct order
            # round13 §3.2 P1: 链尾加 tickflow（TwelveData 日额度耗尽/Finnhub 失败时切入）
            call_args = mock_registry.route.call_args[0][0]
            source_names = [p[0] for p in call_args]
            assert source_names == ["twelvedata", "finnhub", "tickflow"]

    @pytest.mark.asyncio
    async def test_route_us_does_not_block_event_loop(self):
        """P0-11 (round16 3.12): _route_us 改 asyncio.to_thread——慢源同步阻塞时
        事件循环保持响应（负向：同步阻塞则并发 ping 延迟>1s → FAIL）。"""
        import time
        from app.services.market_service import _route_us

        def _slow_route(*args, **kwargs):
            time.sleep(2.0)  # 模拟慢源同步阻塞
            return None

        async def _probe():
            t0 = time.monotonic()
            await asyncio.sleep(0.2)  # 事件循环轮转任务
            return time.monotonic() - t0

        with patch("app.services.market_service.registry") as mock_registry:
            mock_registry.route.side_effect = _slow_route
            # 并发发起慢 _route_us + 快速 probe
            res = await asyncio.gather(
                _route_us("SPY"),
                _probe(),
            )
        _blocked_cost = res[1]
        assert _blocked_cost < 1.0, \
            f"负向：_route_us 同步阻塞事件循环，probe 延迟 {_blocked_cost:.2f}s"


# ── 天天基金 Fetcher Tests ──────────────────────────────────────

class TestFundFetcher:
    def test_fetch_fund_nav_success(self):
        from app.fetchers.fund_fetcher import fetch_fund_nav
        mock_data = {"nav": 1.2345, "daily_change_pct": 0.56}
        with patch("app.fetchers.fund_fetcher._fetch_nav", return_value=mock_data):
            result = fetch_fund_nav("000001")
        assert result is not None
        assert result["nav"] == 1.2345
        assert result["daily_change_pct"] == 0.56

    def test_fetch_fund_nav_none_on_empty(self):
        from app.fetchers.fund_fetcher import fetch_fund_nav
        with patch("app.fetchers.fund_fetcher._fetch_nav", return_value=None):
            result = fetch_fund_nav("000001")
        assert result is None

    def test_fetch_fund_nav_none_on_missing_list(self):
        from app.fetchers.fund_fetcher import fetch_fund_nav
        with patch("app.fetchers.fund_fetcher._fetch_nav", return_value=None):
            result = fetch_fund_nav("000001")
        assert result is None


# ── 两融余额 Fetcher Tests ──────────────────────────────────────

class TestMarginFetcher:
    def test_fetch_margin_balance_success(self):
        from app.fetchers.fundamentals_fetcher import fetch_margin_balance
        with patch("app.fetchers.fundamentals_fetcher._fetch_szse", return_value=123456789012.34):
            result = fetch_margin_balance()
        assert result is not None
        assert result == 123456789012.34

    def test_fetch_margin_balance_none_on_szse_fail(self):
        from app.fetchers.fundamentals_fetcher import fetch_margin_balance
        with patch("app.fetchers.fundamentals_fetcher._fetch_szse", return_value=None) as m_szse:
            from app.fetchers.fundamentals_fetcher import fetch_margin_balance
            with patch("app.fetchers.fundamentals_fetcher._fetch_sse", return_value=987654321098.76):
                result = fetch_margin_balance()
        assert result is not None
        assert result == 987654321098.76

    def test_fetch_margin_balance_none_on_all_fail(self):
        from app.fetchers.fundamentals_fetcher import fetch_margin_balance
        with patch("app.fetchers.fundamentals_fetcher._fetch_szse", return_value=None):
            with patch("app.fetchers.fundamentals_fetcher._fetch_sse", return_value=None):
                result = fetch_margin_balance()
        assert result is None
