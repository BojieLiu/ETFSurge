"""TDD tests for issue 1 (portfolio totals/cash) and issue 2 (off-exchange price).

External data sources (akshare, yfinance) are mocked; no DB/network needed.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import portfolio_service as ps
from app.services.portfolio_service import calculate_allocation, calculate_daily_pnl


def _etf(**kw):
    return SimpleNamespace(**kw)


async def test_calculate_allocation_total_amount_non_normalized(dummy_portfolio_rows):
    """total_amount = sum(target_amounts); weights NOT normalized by weight_sum."""
    with patch("app.services.portfolio_service.fetch_a_stock_batch", return_value=[]), \
         patch("app.services.portfolio_service.fetch_fund_nav", return_value=None), \
         patch("app.services.portfolio_service.fetch_us_etf_realtime", return_value=None):
        result = await calculate_allocation(etfs=dummy_portfolio_rows, total_capital=500000)

    assert result["total_capital"] == 500000
    # weights 0.4 + 0.3 + 0.3 = 1.0 -> fully invested, no cash
    assert result["cash_weight"] == 0.0
    assert result["cash_amount"] == 0.0
    # NON-normalized: each amount = capital * raw weight
    amap = {a["symbol"]: a["target_amount"] for a in result["allocations"]}
    assert amap["159338"] == 200000.0
    assert amap["518880"] == 150000.0
    assert amap["022449"] == 150000.0
    # total_amount = sum of target amounts
    assert result["total_amount"] == 500000.0
    assert "allocations" in result


async def test_calculate_allocation_cash_when_underweight():
    """When weight_sum < 1, cash_weight = 1 - weight_sum and cash_amount matches."""
    etfs = [
        _etf(symbol="159338", name="A", short_name="A", asset_type="A",
             portfolio_type="on_exchange", target_weight=0.4, tracked_index=None),
        _etf(symbol="518880", name="B", short_name="B", asset_type="A",
             portfolio_type="on_exchange", target_weight=0.3, tracked_index=None),
    ]
    with patch("app.services.portfolio_service.fetch_a_stock_batch", return_value=[]), \
         patch("app.services.portfolio_service.fetch_fund_nav", return_value=None), \
         patch("app.services.portfolio_service.fetch_us_etf_realtime", return_value=None):
        result = await calculate_allocation(etfs=etfs, total_capital=500000)

    assert result["cash_weight"] == pytest.approx(0.3)
    assert result["cash_amount"] == pytest.approx(150000.0)
    assert result["total_amount"] == pytest.approx(350000.0)


async def test_calculate_daily_pnl_total_amount(dummy_portfolio_rows):
    with patch("app.services.portfolio_service.fetch_a_stock_batch", return_value=[]), \
         patch("app.services.portfolio_service.fetch_fund_nav", return_value=None), \
         patch("app.services.portfolio_service.fetch_us_etf_realtime", return_value=None):
        result = await calculate_daily_pnl(etfs=dummy_portfolio_rows, total_capital=500000)

    assert result["total_amount"] == pytest.approx(500000.0)
    assert "total_pnl" in result


async def test_off_exchange_price_gt_zero_via_nav():
    """Off-exchange OTC fund gets a real NAV (>0) via fund_open_fund_info_em."""
    etfs = [
        _etf(symbol="022449", name="A500联接C", short_name="A500联接C",
             asset_type="A", portfolio_type="off_exchange",
             target_weight=0.3, tracked_index="159338"),
    ]
    nav = (1.2345, 0.56)
    with patch("app.services.portfolio_service.fetch_fund_nav", return_value=nav), \
         patch("app.services.portfolio_service.fetch_a_stock_batch", return_value=[]), \
         patch("app.services.portfolio_service.fetch_us_etf_realtime", return_value=None):
        price_map = await ps.build_price_map(etfs)

    assert price_map["022449"][0] > 0
    assert price_map["022449"] == nav
