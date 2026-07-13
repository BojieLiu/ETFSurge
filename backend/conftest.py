"""Pytest fixtures for the ETF Surge backend.

Tests focus on pure service/logic functions (calculate_allocation, news
classification, LLM prompt building) with external data sources (akshare,
DeepSeek) mocked, so no DB/Redis/network is required for unit tests.
"""
import types

import pytest


def _make_etf(**kw):
    """Build a lightweight attribute-access object shaped like PortfolioETF."""
    return types.SimpleNamespace(**kw)


@pytest.fixture
def dummy_portfolio_rows():
    """A small in-memory ETF list shaped like portfolio.models.ETF.

    Objects expose attribute access (.symbol, .target_weight, ...) matching
    the way portfolio_service reads fields.
    """
    return [
        _make_etf(symbol="159338", name="中证A500ETF", short_name="A500ETF",
                  asset_type="A", portfolio_type="on_exchange",
                  target_weight=0.4, tracked_index=None),
        _make_etf(symbol="518880", name="黄金ETF", short_name="黄金ETF",
                  asset_type="A", portfolio_type="on_exchange",
                  target_weight=0.3, tracked_index=None),
        _make_etf(symbol="022449", name="A500联接C", short_name="A500联接C",
                  asset_type="A", portfolio_type="off_exchange",
                  target_weight=0.3, tracked_index="159338"),
    ]
