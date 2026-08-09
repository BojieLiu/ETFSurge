"""
R5-0-1: 候选池强制标的二次校验（docs/round5-diagnosis-and-optimization-plan.md §十 P0）。

背景：`_ensure_mandatory` 在 MAX_PER_LAYER 截断前执行，截断（含行业均衡挤出）后
强制标的（159338 等）可能被挤出候选池 → P1-1 A500 缺失真实链路复验 FAIL。
修复：①截断时保护强制标的（截断前剔除 MANDATORY_CODES，截断后再补回）；
     ②截断后二次校验（MANDATORY_CODES ∪ CORE_REQUIRED 缺失时从 flat 找回注入 + WARNING）。

纯函数/轻量 mock 测试，无网络。
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.market_data_hub import (
    MarketDataHub,
    MANDATORY_CODES,
    LAYER_CORE,
    LAYER_SATELLITE,
    LAYER_DEFENSE,
)


def _make_hub():
    """轻量构造 hub 实例（不跑 __init__ 的 I/O 逻辑）。"""
    return MarketDataHub.__new__(MarketDataHub)


def _flat_with(code, name="test-etf", layer="core"):
    return {"symbol": code, "name": name, "layer": layer,
            "tracked_index": name, "industry": "宽基指数", "segment": name}


class TestTruncateProtectsMandatory:
    """R5-0-1 用例②：MAX_PER_LAYER 截断前剔除 MANDATORY_CODES，截断后再补回。"""

    def test_truncate_keeps_mandatory_beyond_max(self):
        """截断 max_n=3 时，排在末尾的强制标的 159338 必须保留。"""
        hub = _make_hub()
        balanced = [
            {"symbol": "588000", "name": "科创50ETF"},
            {"symbol": "159915", "name": "创业板ETF"},
            {"symbol": "510050", "name": "上证50ETF"},
            {"symbol": "159338", "name": "中证A500ETF"},  # 强制标的，排第 4
        ]
        result = hub._truncate_with_mandatory_protection(balanced, max_n=3)
        syms = [e["symbol"] for e in result]
        assert "159338" in syms, f"截断后强制标的 159338 被挤出: {syms}"
        # 非强制标的仍按 max_n 截断
        non_mandatory = [s for s in syms if s not in MANDATORY_CODES]
        assert len(non_mandatory) <= 3, f"非强制标的超过 max_n: {non_mandatory}"

    def test_truncate_no_mandatory_plain_slice(self):
        """池中无强制标的时，行为与普通截断一致。"""
        hub = _make_hub()
        balanced = [
            {"symbol": "588000"}, {"symbol": "159915"}, {"symbol": "510050"},
            {"symbol": "512480"}, {"symbol": "515030"},
        ]
        result = hub._truncate_with_mandatory_protection(balanced, max_n=3)
        assert [e["symbol"] for e in result] == ["588000", "159915", "510050"]


class TestRecheckMandatoryAfterTruncate:
    """R5-0-1 用例①：截断后二次校验，缺失强制标的从 flat 找回注入。"""

    def test_recheck_injects_missing_mandatory(self):
        """pool 截断后缺失 159338 → 二次校验从 flat 找回注入 core 层。"""
        hub = _make_hub()
        pool = {
            LAYER_CORE: [{"symbol": "510300", "name": "沪深300ETF"}],
            LAYER_SATELLITE: [],
            LAYER_DEFENSE: [],
        }
        flat = [_flat_with("159338", "中证A500ETF")]
        hub._recheck_mandatory_after_truncate(pool, flat)
        core_syms = [e["symbol"] for e in pool[LAYER_CORE]]
        assert "159338" in core_syms, f"二次校验未注入 159338: {core_syms}"

    def test_recheck_skips_when_present(self):
        """强制标的本就在池中 → 二次校验不重复注入、不抛异常。"""
        hub = _make_hub()
        pool = {
            LAYER_CORE: [{"symbol": "159338", "name": "中证A500ETF"}],
            LAYER_SATELLITE: [],
            LAYER_DEFENSE: [],
        }
        flat = [_flat_with("159338", "中证A500ETF")]
        hub._recheck_mandatory_after_truncate(pool, flat)
        core_syms = [e["symbol"] for e in pool[LAYER_CORE]]
        assert core_syms.count("159338") == 1, "强制标的被重复注入"

    def test_recheck_flat_empty_noop(self):
        """flat 为空（扫描失败）→ 不注入、不抛异常（与 _ensure_mandatory 语义一致）。"""
        hub = _make_hub()
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: []}
        hub._recheck_mandatory_after_truncate(pool, [])
        assert pool[LAYER_CORE] == []

    def test_recheck_missing_from_flat_warns_noop(self):
        """flat 中没有 159338 → 无法注入，但不抛异常（仅 WARNING）。"""
        hub = _make_hub()
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: []}
        flat = [_flat_with("588000", "科创50ETF")]
        # 不应抛异常
        hub._recheck_mandatory_after_truncate(pool, flat)
        assert pool[LAYER_CORE] == []


# ── News aggregation（合并自 test_market_data_hub_news.py）──────────────


def _make_hub_news():
    from app.services.market_data_hub import MarketDataHub
    hub = MarketDataHub.__new__(MarketDataHub)
    hub._news_cache = None
    hub._news_buckets = None
    hub._news_cache_ts = 0.0
    hub.NEWS_TTL = 120
    return hub


def test_get_news_headlines_returns_bucket():
    """get_news_headlines should return only headlines after refresh."""
    hub = _make_hub_news()
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
    hub = _make_hub_news()
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
    hub = _make_hub_news()
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
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.fetch_stock_news",
               return_value=[{"title": "s1"}]) as m:
        assert hub.get_news_stock("510300") == [{"title": "s1"}]
        m.assert_called_once_with("510300")


def test_get_news_stock_returns_empty_on_failure():
    """get_news_stock should return [] (not crash) on fetch failure."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.fetch_stock_news",
               side_effect=Exception("down")):
        assert hub.get_news_stock("510300") == []


def test_get_akshare_pool_stats_delegates():
    """get_akshare_pool_stats should delegate to fetcher."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.get_akshare_pool_stats",
               return_value={"etf_count": 100}) as m:
        assert hub.get_akshare_pool_stats() == {"etf_count": 100}
        m.assert_called_once()


def test_get_akshare_pool_stats_returns_empty_on_failure():
    """get_akshare_pool_stats should return {} on fetch failure."""
    hub = _make_hub_news()
    with patch("app.fetchers.news_fetcher.get_akshare_pool_stats",
               side_effect=Exception("down")):
        assert hub.get_akshare_pool_stats() == {}


# ── Realtime delegate（合并自 test_market_data_hub_realtime.py）─────────


def _make_hub_realtime():
    from app.services.market_data_hub import MarketDataHub
    hub = MarketDataHub.__new__(MarketDataHub)
    return hub


@pytest.mark.asyncio
async def test_get_realtime_forwards_to_market_service():
    """hub.get_realtime -> market_service.get_realtime_batch."""
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_realtime_batch",
               new=AsyncMock(return_value=[{"symbol": "510300"}])) as m:
        result = await hub.get_realtime(["510300"], "A")
        assert result == [{"symbol": "510300"}]
        m.assert_awaited_once_with(["510300"], "A")


@pytest.mark.asyncio
async def test_get_all_realtime_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_all_realtime",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_all_realtime()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_asset_realtime_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_asset_realtime",
               new=AsyncMock(return_value={"symbol": "600519"})) as m:
        result = await hub.get_asset_realtime("600519", "stock")
        assert result == {"symbol": "600519"}
        m.assert_awaited_once_with("600519", "stock")


@pytest.mark.asyncio
async def test_get_portfolio_realtime_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_portfolio_realtime",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_portfolio_realtime()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_indices_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_indices",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_indices()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_global_indices_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_global_indices",
               new=AsyncMock(return_value={"A": []})) as m:
        result = await hub.get_global_indices()
        assert result == {"A": []}
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_commodities_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_commodities",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_commodities()
        assert result == []
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_market_history_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.get_history",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.get_market_history("510300", "A", "daily")
        assert result == []
        m.assert_awaited_once_with("510300", "A", "daily")


@pytest.mark.asyncio
async def test_search_etf_forwards():
    hub = _make_hub_realtime()
    with patch("app.services.market_service.search_etf",
               new=AsyncMock(return_value=[])) as m:
        result = await hub.search_etf("300")
        assert result == []
        m.assert_awaited_once_with("300")


def test_hub_has_no_circular_import():
    """Importing both hub and market_service should not crash (lazy imports)."""
    import app.services.market_data_hub
    import app.services.market_service
    assert app.services.market_data_hub.market_data_hub is not None
    assert callable(app.services.market_service.get_all_realtime)
