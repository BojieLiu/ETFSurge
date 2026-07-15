"""P3: 基本面采集 — 单元测试。所有外部调用必须 mock。"""

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from app.fetchers.fundamental_fetcher import (
    fetch_fund_scale,
    fetch_fund_flow,
    fetch_hist_avg_volume,
    fetch_fundamentals,
)

# All akshare imports are lazy (inside functions), so we patch the module directly.
PREFIX = "akshare."


class TestFetchFundScale:
    @patch(PREFIX + "fund_etf_fund_info_em")
    def test_returns_scale_and_shares(self, mock_fn):
        df = pd.DataFrame([{"基金规模": 50.3, "基金份额": 45.2}])
        mock_fn.return_value = df
        result = fetch_fund_scale("159338")
        assert result is not None
        assert result["fund_scale"] == 50.3
        assert result["shares_outstanding"] == 45.2

    @patch(PREFIX + "fund_etf_fund_info_em")
    def test_returns_none_on_empty(self, mock_fn):
        mock_fn.return_value = pd.DataFrame()
        assert fetch_fund_scale("159338") is None

    @patch(PREFIX + "fund_etf_fund_info_em")
    def test_handles_exception_gracefully(self, mock_fn):
        mock_fn.side_effect = Exception("API error")
        assert fetch_fund_scale("159338") is None


class TestFetchFundFlow:
    @patch(PREFIX + "stock_individual_fund_flow")
    def test_returns_inflow(self, mock_fn):
        df = pd.DataFrame([{
            "主力净流入-净额": 12500000.0,
            "主力净流入-净占比": 4.7,
        }])
        mock_fn.return_value = df
        result = fetch_fund_flow("159338")
        assert result is not None
        assert result["main_net_inflow"] == 12500000.0
        assert result["main_net_inflow_pct"] == 4.7

    @patch(PREFIX + "stock_individual_fund_flow")
    def test_skips_non_a_stock(self, mock_fn):
        result = fetch_fund_flow("AAPL")
        assert result is None
        mock_fn.assert_not_called()

    @patch(PREFIX + "stock_individual_fund_flow")
    def test_returns_none_on_empty(self, mock_fn):
        mock_fn.return_value = pd.DataFrame()
        assert fetch_fund_flow("159338") is None

    @patch(PREFIX + "stock_individual_fund_flow")
    def test_handles_exception_gracefully(self, mock_fn):
        mock_fn.side_effect = Exception("API error")
        assert fetch_fund_flow("159338") is None


class TestFetchHistAvgVolume:
    @patch(PREFIX + "stock_zh_a_hist")
    def test_returns_avg_volume_and_pe_pb(self, mock_fn):
        df = pd.DataFrame([
            {"成交额": 2.0e8, "市盈率-动态": 12.5, "市净率": 1.3},
            {"成交额": 1.8e8, "市盈率-动态": 12.0, "市净率": 1.2},
        ])
        mock_fn.return_value = df
        result = fetch_hist_avg_volume("159338", days=20)
        assert result is not None
        assert result["avg_volume_20d"] == 190000000.0  # (2e8 + 1.8e8) / 2
        assert result["pe_ttm"] == 12.5  # latest row
        assert result["pb"] == 1.3

    @patch(PREFIX + "stock_zh_a_hist")
    def test_skips_non_a_stock(self, mock_fn):
        result = fetch_hist_avg_volume("AAPL")
        assert result is None
        mock_fn.assert_not_called()

    @patch(PREFIX + "stock_zh_a_hist")
    def test_returns_none_on_empty(self, mock_fn):
        mock_fn.return_value = pd.DataFrame()
        assert fetch_hist_avg_volume("159338") is None

    @patch(PREFIX + "stock_zh_a_hist")
    def test_handles_exception_gracefully(self, mock_fn):
        mock_fn.side_effect = Exception("API error")
        assert fetch_hist_avg_volume("159338") is None


class TestFetchFundamentals:
    @patch("app.fetchers.fundamental_fetcher.fetch_fund_scale")
    @patch("app.fetchers.fundamental_fetcher.fetch_fund_flow")
    @patch("app.fetchers.fundamental_fetcher.fetch_hist_avg_volume")
    def test_aggregates_all_sources(self, mock_hist, mock_flow, mock_scale):
        mock_scale.return_value = {"shares_outstanding": 45.2, "fund_scale": 50.3}
        mock_hist.return_value = {"avg_volume_20d": 1.9e8, "pe_ttm": 12.5, "pb": 1.3}
        mock_flow.return_value = {"main_net_inflow": 1.25e7, "main_net_inflow_pct": 4.7}
        result = fetch_fundamentals("159338")
        assert result["shares_outstanding"] == 45.2
        assert result["fund_scale"] == 50.3
        assert result["pe_ttm"] == 12.5
        assert result["pb"] == 1.3
        assert result["avg_volume_20d"] == 1.9e8
        assert result["main_net_inflow"] == 1.25e7
        assert result["main_net_inflow_pct"] == 4.7

    @patch("app.fetchers.fundamental_fetcher.fetch_fund_scale")
    @patch("app.fetchers.fundamental_fetcher.fetch_fund_flow")
    @patch("app.fetchers.fundamental_fetcher.fetch_hist_avg_volume")
    def test_returns_nulls_when_all_fail(self, mock_hist, mock_flow, mock_scale):
        mock_scale.return_value = None
        mock_hist.return_value = None
        mock_flow.return_value = None
        result = fetch_fundamentals("159338")
        assert all(v is None for v in result.values())

    def test_skips_non_a(self):
        result = fetch_fundamentals("AAPL")
        assert all(v is None for v in result.values())
