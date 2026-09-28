"""P3: 基本面采集 — 单元测试。所有外部调用必须 mock。"""

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from app.fetchers.fundamentals_fetcher import (
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
    @patch("app.fetchers.fundamentals_fetcher.fetch_fund_scale")
    @patch("app.fetchers.fundamentals_fetcher.fetch_fund_flow")
    @patch("app.fetchers.fundamentals_fetcher.fetch_hist_avg_volume")
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

    @patch("app.fetchers.fundamentals_fetcher.fetch_fund_scale")
    @patch("app.fetchers.fundamentals_fetcher.fetch_fund_flow")
    @patch("app.fetchers.fundamentals_fetcher.fetch_hist_avg_volume")
    def test_returns_nulls_when_all_fail(self, mock_hist, mock_flow, mock_scale):
        mock_scale.return_value = None
        mock_hist.return_value = None
        mock_flow.return_value = None
        result = fetch_fundamentals("159338")
        assert all(v is None for v in result.values())

    def test_skips_non_a(self):
        result = fetch_fundamentals("AAPL")
        assert all(v is None for v in result.values())


# ===================================================================
# merged from test_valuation_fetcher_v1.py (F1 baseline 归位, 2026-09-28)
# ===================================================================
"""L2 P0: valuation_fetcher 取数契约（mock akshare，无网络）。

D1 实测列名（2026-09-17 探针，R75 哨兵：mock 对齐真实响应）：
- ak.stock_zh_index_value_csindex: 日期/指数代码/指数中文全称/指数中文简称/
  指数英文全称/指数英文简称/市盈率1/市盈率2/股息率1/股息率2（近 20 日，无 PB）
- ak.stock_industry_pe_ratio_cninfo: 变动日期/行业分类/行业层级/行业编码/
  行业名称/公司数量/纳入计算公司数量/总市值-静态/净利润-静态/
  静态市盈率-加权平均/静态市盈率-中位数/静态市盈率-算术平均（无 PB/ROE）
"""
from app.fetchers import valuation_fetcher as vf


def _v_df(columns, rows):
    return pd.DataFrame(rows, columns=columns)


_V_INDEX_COLS = ["日期", "指数代码", "指数中文全称", "指数中文简称",
                 "指数英文全称", "指数英文简称",
                 "市盈率1", "市盈率2", "股息率1", "股息率2"]

_V_SECTOR_COLS = ["变动日期", "行业分类", "行业层级", "行业编码", "行业名称",
                  "公司数量", "纳入计算公司数量", "总市值-静态", "净利润-静态",
                  "静态市盈率-加权平均", "静态市盈率-中位数", "静态市盈率-算术平均"]


def test_index_history_normalized():
    """指数历史归一化：市盈率1/2+股息率1/2 原样透传（1/2 口径未定，不猜）。"""
    vf.sync_memory_cache.clear()
    fake = _v_df(_V_INDEX_COLS, [
        ["2026-09-16", 300, "沪深300指数", "沪深300",
         "CSI 300 Index", "CSI 300", 14.6, 16.82, 2.63, 2.34],
        ["2026-09-15", 300, "沪深300指数", "沪深300",
         "CSI 300 Index", "CSI 300", 14.5, 16.70, 2.61, 2.32],
    ])
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_index_value_csindex", return_value=fake):
        rows = vf.fetch_index_valuation_history("000300")
    assert len(rows) == 2
    assert rows[0] == {"date": "2026-09-16", "pe_1": 14.6, "pe_2": 16.82,
                       "div_1": 2.63, "div_2": 2.34}
    vf.sync_memory_cache.clear()


def test_index_empty_df_returns_empty():
    vf.sync_memory_cache.clear()
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_index_value_csindex",
               return_value=_v_df(_V_INDEX_COLS, [])):
        assert vf.fetch_index_valuation_history("000300") == []
    vf.sync_memory_cache.clear()


def test_index_failure_cached():
    """源异常 → [] + 失败缓存（二次调用不再触源，R4-26 模式）。"""
    vf.sync_memory_cache.clear()
    calls = {"n": 0}

    def _boom(**kw):
        calls["n"] += 1
        raise Exception("cninfo down")

    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_index_value_csindex", side_effect=_boom):
        assert vf.fetch_index_valuation_history("000300") == []
        assert vf.fetch_index_valuation_history("000300") == []
    assert calls["n"] == 1, f"失败缓存应阻止重复触源，实际 {calls['n']} 次"
    vf.sync_memory_cache.clear()


def test_sector_snapshot_normalized():
    """板块快照归一化：静态 PE 三口径透传，无 PB/ROE 不编。"""
    vf.sync_memory_cache.clear()
    fake = _v_df(_V_SECTOR_COLS, [
        ["2026-09-16", "证监会行业", "大类", "C39",
         "计算机、通信和其他电子设备制造业", 100, 98,
         1e12, 5e10, 20.5, 35.2, 40.1],
    ])
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_industry_pe_ratio_cninfo", return_value=fake):
        rows = vf.fetch_sector_pe_snapshot(date="20260916")
    assert len(rows) == 1
    assert rows[0] == {"ind_code": "C39",
                       "ind_name": "计算机、通信和其他电子设备制造业",
                       "pe_wavg": 20.5, "pe_median": 35.2, "pe_avg": 40.1,
                       "as_of": "2026-09-16"}
    vf.sync_memory_cache.clear()


def test_sector_failure_returns_empty():
    vf.sync_memory_cache.clear()
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_industry_pe_ratio_cninfo",
               side_effect=Exception("cninfo down")):
        assert vf.fetch_sector_pe_snapshot(date="20260916") == []
    vf.sync_memory_cache.clear()
