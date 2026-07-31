# -*- coding: utf-8 -*-
"""ETF data source tests — Phase 2 前置检查。

P4-1: fetch_etf_net_value 返回有效 NAV 数据
P4-2: premium_discount 附加返回值
P4-3: shares_change 附加返回值

真实契约（china_market.py）：
  fetch_etf_net_value -> {"nav", "price", "premium_discount"} 或 None
  fetch_etf_shares_outstanding -> {"total_shares", "shares_change_20d"} 或 None

网络调用已 mock，测试确定性运行。
"""
import pytest
from unittest.mock import patch


def test_p4_fetch_etf_nav():
    """fetch_etf_net_value returns NAV-like data for ETF symbols."""
    from app.fetchers.china_market import fetch_etf_net_value

    # Mock Sina ETF quote response:
    # parts[3] = current price (4.661), parts[8] = IOPV / reference NAV (4.650)
    mock_sina_text = 'var hq_str_sh510300="510300,沪深300ETF,0,4.661,0,0,0,0,4.650,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"'
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = mock_open.return_value
        mock_resp.read.return_value = mock_sina_text.encode("gbk")
        nav = fetch_etf_net_value("510300")

    assert nav is not None, "510300 should have NAV data"
    assert isinstance(nav, dict), f"NAV should be dict, got {type(nav)}"
    assert "nav" in nav, f"NAV result should contain nav, got {list(nav.keys())}"
    assert "price" in nav, f"NAV result should contain price, got {list(nav.keys())}"
    assert "premium_discount" in nav
    # price 4.661, nav 4.650 -> premium_discount ~ +0.0024
    assert abs(nav["premium_discount"] - (4.661 - 4.650) / 4.650) < 0.01


def test_p4_fetch_etf_nav_failure_returns_none():
    """fetch_etf_net_value returns None when Sina response is malformed."""
    from app.fetchers.china_market import fetch_etf_net_value

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = mock_open.return_value
        mock_resp.read.return_value = b""
        nav = fetch_etf_net_value("510300")
    assert nav is None


def test_p4_fetch_etf_shares():
    """fetch_etf_shares_outstanding returns shares data for ETF symbols."""
    import pandas as pd
    from app.fetchers.china_market import fetch_etf_shares_outstanding

    # Mock akshare DataFrame with 份额 column (25 rows -> 20d change computable)
    df = pd.DataFrame({
        "日期": pd.date_range("2026-01-01", periods=25),
        "份额": [100.0 + i * 0.1 for i in range(25)],
    })
    with patch("app.fetchers.china_market.run_in_thread", return_value=df):
        shares = fetch_etf_shares_outstanding("510300")

    assert shares is not None, "510300 should have shares data"
    assert isinstance(shares, dict), f"Shares should be dict, got {type(shares)}"
    assert "total_shares" in shares, f"Result should contain total_shares, got {list(shares.keys())}"
    assert "shares_change_20d" in shares
    # latest=102.4 (row 24), prev at iloc[-20]=row 5 (100.5) -> change ~ +0.0189
    assert abs(shares["shares_change_20d"] - (102.4 - 100.5) / 100.5) < 0.01


def test_p4_fetch_etf_shares_failure_returns_none():
    """fetch_etf_shares_outstanding returns None when akshare fails."""
    from app.fetchers.china_market import fetch_etf_shares_outstanding

    with patch("app.fetchers.china_market.run_in_thread", return_value=None):
        shares = fetch_etf_shares_outstanding("510300")
    assert shares is None


def test_p4_premium_discount_nonzero():
    """premium_discount with real market_data returns non-zero value."""
    from app.factors.factor_registry import registry

    # Mock market_data with realistic NAV and price
    market_data = {
        "510300": {
            "total_mv": 500e9,
            "close": [4.0 + i * 0.01 for i in range(60)],
            "high": [4.1] * 60,
            "low": [3.9] * 60,
            "volume": [2_000_000] * 60,
        },
        "518880": {
            "total_mv": 200e9,
            "close": [6.0 + i * 0.02 for i in range(60)],
            "high": [6.1] * 60,
            "low": [5.9] * 60,
            "volume": [500_000] * 60,
        },
    }
