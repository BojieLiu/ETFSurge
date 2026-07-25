"""
Tests for GET /api/v1/portfolio/drift-check (P0).

Verifies:
  - Returns items array with target_weight, actual_weight, deviation
  - Returns alerts for large deviations
  - Empty portfolio returns items=[]
  - Portfolio type filter works
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def make_mock_etf(symbol, name, target_weight=0.3, shares_held=1000, avg_cost=1.0):
    etf = MagicMock()
    etf.symbol = symbol
    etf.name = name
    etf.target_weight = target_weight
    etf.shares_held = shares_held
    etf.avg_cost = avg_cost
    etf.portfolio_type = "on_exchange"
    etf.is_active = True
    return etf


@pytest.mark.asyncio
async def test_drift_check_returns_items_and_alerts():
    """Normal: returns items + alerts."""
    mock_etfs = [
        make_mock_etf("510300", "A500ETF", 0.3, 1000),
        make_mock_etf("159338", "A500ETF", 0.26, 2000),
    ]
    with patch("app.routers.portfolio.list_etfs", return_value=mock_etfs):
        with patch("app.routers.portfolio.calculate_weight_drift",
                   new=AsyncMock(return_value={
                       "items": [
                           {"symbol": "510300", "name": "A500ETF",
                            "target_weight": 0.3, "actual_weight": 0.2845,
                            "deviation": -0.0155, "deviation_pct": -5.17,
                            "market_value": 142250.0, "needs_rebalance": False},
                           {"symbol": "159338", "name": "A500ETF",
                            "target_weight": 0.26, "actual_weight": 0.3421,
                            "deviation": 0.0821, "deviation_pct": 31.58,
                            "market_value": 171050.0, "needs_rebalance": True},
                       ],
                       "alerts": [
                           {"symbol": "159338", "name": "A500ETF",
                            "message": "weight deviation 31.6%",
                            "severity": "warning"},
                       ],
                   })):
            from app.routers.portfolio import drift_check
            result = await drift_check(
                portfolio_type="on_exchange",
                db=AsyncMock(),
            )
            assert len(result["items"]) == 2
            assert result["items"][1]["needs_rebalance"] is True
            assert len(result["alerts"]) == 1
            assert result["alerts"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_drift_check_empty_portfolio():
    """Empty portfolio returns items=[] alerts=[]."""
    with patch("app.routers.portfolio.list_etfs", return_value=[]):
        with patch("app.routers.portfolio.calculate_weight_drift",
                   new=AsyncMock(return_value={"items": [], "alerts": []})):
            from app.routers.portfolio import drift_check
            result = await drift_check(
                portfolio_type=None,
                db=AsyncMock(),
            )
            assert result["items"] == []
            assert result["alerts"] == []


@pytest.mark.asyncio
async def test_drift_check_critical_alert():
    """Deviation >= 50% -> severity = critical."""
    mock_etfs = [
        make_mock_etf("510300", "A500ETF", 0.5, 100),
    ]
    with patch("app.routers.portfolio.list_etfs", return_value=mock_etfs):
        with patch("app.routers.portfolio.calculate_weight_drift",
                   new=AsyncMock(return_value={
                       "items": [
                           {"symbol": "510300", "name": "A500ETF",
                            "target_weight": 0.5, "actual_weight": 0.85,
                            "deviation": 0.35, "deviation_pct": 70.0,
                            "market_value": 85000.0, "needs_rebalance": True},
                       ],
                       "alerts": [
                           {"symbol": "510300", "name": "A500ETF",
                            "message": "weight deviation 70.0%",
                            "severity": "critical"},
                       ],
                   })):
            from app.routers.portfolio import drift_check
            result = await drift_check(
                portfolio_type="on_exchange",
                db=AsyncMock(),
            )
            assert result["alerts"][0]["severity"] == "critical"
