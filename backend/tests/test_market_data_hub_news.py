"""Phase 1 (v6 plan): MarketDataHub news aggregation tests.

Verifies:
  - get_news_headlines/macro/global return labeled buckets
  - _news_bucket lazily refreshes when cache is empty/stale
  - get_news() still returns merged list (backward compat)
  - get_news_stock / get_akshare_pool_stats delegate safely on failure
"""
import pytest
from unittest.mock import patch


def _make_hub():
    from app.services.market_data_hub import MarketDataHub
    hub = MarketDataHub.__new__(MarketDataHub)
    hub._news_cache = None
    hub._news_buckets = None
    hub._news_cache_ts = 0.0
    hub.NEWS_TTL = 120
    return hub


def test_get_news_headlines_returns_bucket():
    """get_news_headlines should return only headlines after refresh."""
    hub = _make_hub()
    mock_headlines = [{"title": "h1", "level": "利好"}]
    mock_macro = [{"title": "m1", "level": "宏观"}]
    mock_global = [{"title": "g1"}]

    # Hub does lazy import inside refresh_news from ..fetchers.news_fetcher
    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               return_value=mock_headlines) as mh:
        with patch("app.fetchers.news_fetcher.fetch_macro_news",
                   return_value=mock_macro):
            with patch("app.fetchers.news_fetcher.fetch_global_news",
                       return_value=mock_global):
                hub.refresh_news()
                mh.assert_called_once()

    assert hub.get_news_headlines() == mock_headlines
    assert hub.get_news_macro() == mock_macro
    assert hub.get_news_global() == mock_global
    # Merged view backward compat
    assert hub.get_news() == mock_headlines + mock_macro + mock_global
    # Cache is now populated; getters should NOT re-fetch
    with patch("app.fetchers.news_fetcher.fetch_news_headlines") as mh2:
        assert hub.get_news_headlines() == mock_headlines
        mh2.assert_not_called()


def test_lazy_refresh_on_empty_bucket():
    """_news_bucket should trigger a refresh when buckets are uninitialized."""
    hub = _make_hub()
    mock_headlines = [{"title": "fresh"}]

    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               return_value=mock_headlines):
        with patch("app.fetchers.news_fetcher.fetch_macro_news",
                   return_value=[]):
            with patch("app.fetchers.news_fetcher.fetch_global_news",
                       return_value=[]):
                result = hub.get_news_headlines()

    assert result == mock_headlines
    assert hub._news_buckets is not None


def test_news_bucket_returns_empty_on_fetch_failure():
    """Buckets should be empty (not crash) when all fetchers fail."""
    hub = _make_hub()
    with patch("app.fetchers.news_fetcher.fetch_news_headlines",
               side_effect=Exception("network down")):
        with patch("app.fetchers.news_fetcher.fetch_macro_news",
                   side_effect=Exception("network down")):
            with patch("app.fetchers.news_fetcher.fetch_global_news",
                       side_effect=Exception("network down")):
                assert hub.get_news_headlines() == []
                assert hub.get_news() == []


def test_get_news_stock_delegates():
    """get_news_stock should delegate to fetch_stock_news."""
    hub = _make_hub()
    with patch("app.fetchers.news_fetcher.fetch_stock_news",
               return_value=[{"title": "s1"}]) as m:
        assert hub.get_news_stock("510300") == [{"title": "s1"}]
        m.assert_called_once_with("510300")


def test_get_news_stock_returns_empty_on_failure():
    """get_news_stock should return [] (not crash) on fetch failure."""
    hub = _make_hub()
    with patch("app.fetchers.news_fetcher.fetch_stock_news",
               side_effect=Exception("down")):
        assert hub.get_news_stock("510300") == []


def test_get_akshare_pool_stats_delegates():
    """get_akshare_pool_stats should delegate to fetcher."""
    hub = _make_hub()
    with patch("app.fetchers.news_fetcher.get_akshare_pool_stats",
               return_value={"etf_count": 100}) as m:
        assert hub.get_akshare_pool_stats() == {"etf_count": 100}
        m.assert_called_once()


def test_get_akshare_pool_stats_returns_empty_on_failure():
    """get_akshare_pool_stats should return {} on fetch failure."""
    hub = _make_hub()
    with patch("app.fetchers.news_fetcher.get_akshare_pool_stats",
               side_effect=Exception("down")):
        assert hub.get_akshare_pool_stats() == {}
