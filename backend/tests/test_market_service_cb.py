"""Tests for market_service circuit breaker integration (S1)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.market_service import _call_with_cb, get_all_realtime


# ── _call_with_cb ──────────────────────────────────────────────────────


class TestCallWithCb:
    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch("app.services.market_service.registry") as mock_reg:
            h_mock = MagicMock()
            h_mock.available.return_value = True
            mock_reg.health.return_value = h_mock
            yield mock_reg, h_mock

    @pytest.mark.asyncio
    async def test_success(self, mock_registry):
        """Normal call records success through circuit breaker."""
        mock_reg, h_mock = mock_registry
        fn = MagicMock(return_value="result")

        result = await _call_with_cb("test_source", fn)

        assert result == "result"
        fn.assert_called_once()
        h_mock.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_open(self, mock_registry):
        """When circuit is open, skip call and return None."""
        mock_reg, h_mock = mock_registry
        h_mock.available.return_value = False
        fn = MagicMock(return_value="should not call")

        result = await _call_with_cb("test_source", fn)

        assert result is None
        fn.assert_not_called()
        h_mock.record_success.assert_not_called()
        h_mock.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure(self, mock_registry):
        """Exception records failure and returns None."""
        mock_reg, h_mock = mock_registry
        fn = MagicMock(side_effect=ValueError("test error"))

        result = await _call_with_cb("test_source", fn)

        assert result is None
        fn.assert_called_once()
        h_mock.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_success(self, mock_registry):
        """Use cache_key to avoid duplicate calls when data is cached."""
        mock_reg, h_mock = mock_registry
        fn = MagicMock(return_value=[{"symbol": "000001", "price": 3.0}])

        # Call once to warm cache
        result1 = await _call_with_cb("test_source", fn, cache_key="test_cache", cache_ttl=30)
        assert result1 == [{"symbol": "000001", "price": 3.0}]
        fn.assert_called_once()

        # Call again while cache is warm
        fn.reset_mock()
        result2 = await _call_with_cb("test_source", fn, cache_key="test_cache", cache_ttl=30)
        assert result2 == [{"symbol": "000001", "price": 3.0}]
        fn.assert_not_called()  # Should use cache


# ── get_all_realtime ───────────────────────────────────────────────────


class TestGetAllRealtime:
    @pytest.mark.asyncio
    async def test_uses_circuit_breaker(self):
        """get_all_realtime now uses the circuit-breaker aware call."""
        with patch("app.services.market_service._call_with_cb") as mock_cb:
            mock_cb.return_value = [{"symbol": "000001", "price": 3.0}]
            with patch("app.services.market_service.get_portfolio_realtime") as mock_pr:
                mock_pr.return_value = []

                result = await get_all_realtime()

                assert len(result) > 0
                mock_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """Empty result from circuit breaker is handled gracefully."""
        with patch("app.services.market_service._call_with_cb") as mock_cb:
            mock_cb.return_value = None
            with patch("app.services.market_service.get_portfolio_realtime") as mock_pr:
                mock_pr.return_value = []

                result = await get_all_realtime()
                assert result == []


# ===================================================================
# merged from test_round28_fixes.py::TestR62InferMarketFromSymbol (S3.3 de-round, 2026-08-18)
# ===================================================================
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_mod
from app.services import market_service as ms
from app.services.market_data_hub import _rule_news_summary
from app.services.market_service import infer_market_from_symbol


class TestR62InferMarketFromSymbol:
    @pytest.mark.parametrize("symbol,expected", [
        ("00700", "HK"),          # 5 位数字 0 开头 → 港股
        ("02800", "HK"),
        ("00700.HK", "HK"),       # 显式后缀优先
        ("AAPL", "US"),           # 纯字母 → 美股
        ("SPY", "US"),
        ("510300", "A"),          # 6 位数字 → A 股
        ("600519", "A"),
        ("sh688981", "A"),        # 交易所前缀剥除后仍 A
        ("", "A"),                # 空 → 保守 A
    ])
    def test_infer(self, symbol, expected):
        assert infer_market_from_symbol(symbol) == expected, \
            f"{symbol} → 应推断为 {expected}"

    @pytest.mark.asyncio
    async def test_indicators_endpoint_infers_us_asset_type(self, monkeypatch):
        """/market/indicators/AAPL 默认 asset_type='A' → 自动推断为 US（R62）。"""
        from app.routers import market as market_router

        async def _fake_history(symbol, asset_type, period):
            # 40 根 K 线（≥30 满足 data_available）
            rows = [{"date": f"2026-08-{i:02d}", "open": 10 + i * 0.1,
                     "close": 10 + i * 0.1, "high": 10 + i * 0.2,
                     "low": 10 - i * 0.05, "volume": 1000} for i in range(1, 41)]
            return rows

        captured = {}

        async def _fake_get_market_history(symbol, asset_type, period):
            captured["asset_type"] = asset_type
            return await _fake_history(symbol, asset_type, period)

        with patch.object(market_router.market_data_hub,
                          "get_market_history", _fake_get_market_history), \
             patch.object(market_router.market_data_hub, "is_kline_stale",
                          lambda *a: False):
            result = await market_router.indicators("AAPL", asset_type="A")
        assert captured["asset_type"] == "US", \
            f"indicators(AAPL) 应推断 asset_type=US，实际 {captured['asset_type']}"
        assert result.get("asset_type") == "US", \
            f"响应 asset_type 应为 US，实际 {result.get('asset_type')}"
