"""Pytest fixtures for the ETF Surge backend.

Tests focus on pure service/logic functions (calculate_allocation, news
classification, LLM prompt building) with external data sources (akshare,
DeepSeek) mocked, so no DB/Redis/network is required for unit tests.

Autouse fixture _prevent_http_in_teardown patches slow external APIs
globally so teardown of singleton objects does not trigger real HTTP calls
(em_global index_spot, sentiment advance_decline, etc.).
"""
from unittest.mock import MagicMock
import types

import pytest


def _make_etf(**kw):
    """Build a lightweight attribute-access object shaped like PortfolioETF."""
    return types.SimpleNamespace(**kw)


@pytest.fixture(autouse=True, scope="session")
def _prevent_http_in_teardown():
    """Globally patch slow external HTTP sources to prevent teardown leaks.

    These patches are needed because PoolManager singleton cleanup sometimes
    triggers akshare / push2 HTTP calls after tests finish. Patching at
    session scope ensures the patches survive until ALL tests complete.
    """
    import app.fetchers.em_global_fetcher as egf
    import app.fetchers.sentiment_fetcher as sf

    orig_fetch_all = egf.fetch_all
    orig_fetch_sentiment = sf.fetch_market_sentiment

    egf.fetch_all = MagicMock(return_value={})
    sf.fetch_market_sentiment = MagicMock(return_value={
        "sentiment_index": 50, "sentiment_label": "中性",
        "advance_ratio": 0.5, "inst_consensus": 0.5,
    })

    yield

    egf.fetch_all = orig_fetch_all
    sf.fetch_market_sentiment = orig_fetch_sentiment


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
