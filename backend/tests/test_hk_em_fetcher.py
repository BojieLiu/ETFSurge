"""TDD tests for P1: HK East Money data source.

All akshare calls are mocked; no network needed.
"""
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from app.fetchers.china_market import _em_hk_realtime


def _make_fake_hk_spot_df():
    """Simulate akshare stock_hk_spot_em() DataFrame with garbled (latin1) columns."""
    data = {
        "代码": ["00700", "00005", "09988"],
        "名称": ["腾讯控股", "汇丰控股", "阿里巴巴"],
        "最新价": [380.0, 68.5, 120.0],
        "涨跌幅": [2.5, -0.3, 1.8],
        "成交量": [25000000, 5000000, 18000000],
        "成交额": [9500000000, 342500000, 2160000000],
    }
    return pd.DataFrame(data)


def test_em_hk_returns_filtered_symbols():
    """_em_hk_realtime returns only requested symbols from EM HK spot data."""
    fake_df = _make_fake_hk_spot_df()

    with patch("akshare.stock_hk_spot_em", return_value=fake_df):
        results = _em_hk_realtime(["00700", "09988"])

    assert len(results) == 2
    symbols = {r["symbol"] for r in results}
    assert symbols == {"00700", "09988"}
    assert results[0]["price"] == 380.0
    assert results[0]["asset_type"] == "HK"


def test_em_hk_returns_none_on_empty():
    """_em_hk_realtime returns empty list when akshare fails."""
    with patch("akshare.stock_hk_spot_em", side_effect=Exception("API error")):
        results = _em_hk_realtime(["00700"])
    assert results == []


def test_em_hk_returns_empty_for_no_match():
    """_em_hk_realtime returns empty list when no symbols match."""
    fake_df = _make_fake_hk_spot_df()

    with patch("akshare.stock_hk_spot_em", return_value=fake_df):
        results = _em_hk_realtime(["99999"])
    assert results == []



