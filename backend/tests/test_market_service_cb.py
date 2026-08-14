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
