"""Tests for app/fetchers/ttj_fetcher.py — TTJ IOPV & shares fetcher."""

from unittest.mock import MagicMock, patch

import pytest

from app.fetchers.ttj_fetcher import fetch_etf_iopv, fetch_etf_shares


# ── Mock fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_source_registry():
    """Mock source_registry to avoid circuit breaker side effects."""
    with patch("app.fetchers.ttj_fetcher._source_registry") as mock_reg:
        h_mock = MagicMock()
        h_mock.available.return_value = True
        mock_reg._health.return_value = h_mock
        yield mock_reg


@pytest.fixture
def mock_run_in_thread():
    with patch("app.fetchers.ttj_fetcher.run_in_thread") as mock_run:
        yield mock_run


# ── fetch_etf_iopv ──────────────────────────────────────────────────────


class TestFetchEtfIopv:
    def test_success(self, mock_run_in_thread, mock_source_registry):
        """Successful IOPV fetch returns expected data."""
        mock_run_in_thread.return_value = {"iopv": 1.234, "last_nav": 1.220}
        result = fetch_etf_iopv("510050")
        assert result == {"iopv": 1.234, "last_nav": 1.220}
        mock_run_in_thread.assert_called_once()
        h = mock_source_registry._health.return_value
        h.record_success.assert_called_once()

    def test_network_error(self, mock_run_in_thread, mock_source_registry):
        """Network error returns None and records failure."""
        mock_run_in_thread.side_effect = ConnectionError("Network timeout")
        result = fetch_etf_iopv("510050")
        assert result is None
        h = mock_source_registry._health.return_value
        h.record_failure.assert_called_once()

    def test_empty_result(self, mock_run_in_thread, mock_source_registry):
        """Empty result returns None and records failure."""
        mock_run_in_thread.return_value = None
        result = fetch_etf_iopv("510050")
        assert result is None
        h = mock_source_registry._health.return_value
        h.record_failure.assert_called_once()

    def test_circuit_open(self, mock_source_registry):
        """When circuit breaker is open, skip fetch and return None."""
        h = mock_source_registry._health.return_value
        h.available.return_value = False
        result = fetch_etf_iopv("510050")
        assert result is None
        # Should not call record_success or record_failure when skipping
        h.record_success.assert_not_called()
        h.record_failure.assert_not_called()


# ── fetch_etf_shares (stub) ─────────────────────────────────────────────


class TestFetchEtfShares:
    def test_stub_returns_none(self):
        """Share fetcher stub currently returns None."""
        result = fetch_etf_shares("510050")
        assert result is None
