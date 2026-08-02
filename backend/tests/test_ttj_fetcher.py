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


# ── fetch_etf_shares (F17 R61 修复后走真实 push2delay API) ──────────────


class TestFetchEtfShares:
    def test_stub_returns_none(self):
        """F17 R61: fetch_etf_shares 修复后不再因 import 缺失静默返回 None——
        改为 mock 网络验证解析逻辑（真实网络不依赖）。"""
        import urllib.request
        from unittest.mock import MagicMock

        fake_resp = MagicMock()
        fake_resp.read.return_value = (
            b'{"data": {"diff": [{"f85": 1234567.0}]}}'
        )

        with patch.object(urllib.request, "urlopen", return_value=fake_resp) as mock_open:
            result = fetch_etf_shares("510050")

        assert result == {"shares": 1234567.0, "shares_date": "latest"}
        assert mock_open.call_count == 1
        # 请求 URL 使用集中常量域名（F17 R61）
        req = mock_open.call_args[0][0]
        assert "push2delay.eastmoney.com" in req.full_url, req.full_url

    def test_fetch_fails_returns_none(self):
        """F17 R61: 网络失败/解析失败仍返回 None（fallback 路径保持）。"""
        import urllib.request
        with patch.object(urllib.request, "urlopen", side_effect=RuntimeError("down")):
            result = fetch_etf_shares("510050")
        assert result is None
