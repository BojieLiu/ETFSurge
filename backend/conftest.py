"""Pytest fixtures for the ETF Surge backend.

#6: 不在 conftest 层全局 mock 外部数据源。改为 pool_manager 的 _test_mode
属性来抑制 teardown 时的 HTTP 泄漏（见 pool_manager.py）。

Tests that need mock should use local pytest fixtures, avoiding session-level
side effects on test isolation.
"""
import types

import pytest

from pytest import fixture


def _make_etf(**kw):
    """Build a lightweight attribute-access object shaped like PortfolioETF."""
    return types.SimpleNamespace(**kw)


@pytest.fixture(autouse=True, scope="session")
def _prevent_pool_teardown_http():
    """#6: 用 pool_manager._test_mode 抑制 teardown 时的 HTTP 泄漏。

    不再全局 mock em_global_fetcher / sentiment_fetcher，
    让需要使用真实数据的测试能接触到原始数据源。
    """
    import app.services.pool_manager as pm
    pm.pool_manager._test_mode = True
    yield
    pm.pool_manager._test_mode = False


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
