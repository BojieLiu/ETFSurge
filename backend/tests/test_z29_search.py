"""Tests for Z29 — cross-market search autocomplete (docs/v5_z15_z29_implementation_design.md).

Covers the reworked three-tier `search_hk_us` (static base + akshare spot + enrich)
and the reworked `/api/v1/market/search` route (cross-market default merge,
include_stocks per-branch semantics, asset_type = market code).

All external network / DB access is mocked — no real akshare / requests / SQLite.
"""
import pytest
from contextlib import contextmanager, ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import market_service as ms
from app.routers import market as market_router
from app.services.market_data_hub import market_data_hub


# ─── helpers ───────────────────────────────────────────────────


def _hk_spot_rows():
    return [
        {"symbol": "00700", "name": "腾讯控股", "market": "HK"},
        {"symbol": "09988", "name": "阿里巴巴-W", "market": "HK"},
        {"symbol": "02800", "name": "盈富基金", "market": "HK"},
    ]


def _us_spot_rows():
    return [
        {"symbol": "AAPL", "name": "苹果", "name_en": "Apple Inc", "market": "US"},
        {"symbol": "MSFT", "name": "微软", "name_en": "Microsoft Corp", "market": "US"},
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "name_en": "SPDR S&P 500 ETF Trust", "market": "US"},
    ]


@contextmanager
def _patch_spot(hk=None, us=None):
    """Patch both module-level spot fetchers (resolved per-call by function-level import)."""
    hk = _hk_spot_rows() if hk is None else hk
    us = _us_spot_rows() if us is None else us
    patches = [
        patch("app.fetchers.china_market.fetch_hk_spot_list", return_value=hk),
        patch("app.fetchers.china_market.fetch_us_spot_list", return_value=us),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    """Minimal async session fake: any query returns zero rows."""

    def __init__(self, rows=None):
        self._rows = rows or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        res = _EmptyResult()
        res.all = lambda: self._rows
        return res


# ─── search_hk_us unit tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_search_hk_us_stock_symbol_00700():
    """patch hk spot → search 00700 returns Tencent with HK market/asset_type/type=stock."""
    with _patch_spot():
        res = await ms.search_hk_us("00700", include_stocks=True, enrich=False)
    assert res, "00700 should be found"
    hit = next(r for r in res if r["symbol"] == "00700")
    assert hit["market"] == "HK"
    assert hit["asset_type"] == "HK"
    assert hit["type"] == "stock"


@pytest.mark.asyncio
async def test_search_hk_us_us_stock_aapl():
    """patch us spot → search AAPL returns Apple with US asset_type."""
    with _patch_spot():
        res = await ms.search_hk_us("AAPL", include_stocks=True, enrich=False)
    hit = next(r for r in res if r["symbol"] == "AAPL")
    assert hit["market"] == "US"
    assert hit["asset_type"] == "US"
    assert hit["type"] == "stock"


@pytest.mark.asyncio
async def test_search_hk_us_chinese_name():
    """Chinese-name match (腾讯控股) hits 00700."""
    with _patch_spot():
        res = await ms.search_hk_us("腾讯", include_stocks=True, enrich=False)
    assert any(r["symbol"] == "00700" for r in res)


@pytest.mark.asyncio
async def test_search_hk_us_english_name_us():
    """English-name (name_en) match hits AAPL — validates spot name_en matching."""
    with _patch_spot():
        res = await ms.search_hk_us("Apple", include_stocks=True, enrich=False)
    assert any(r["symbol"] == "AAPL" for r in res)


@pytest.mark.asyncio
async def test_search_hk_us_static_fallback_when_spot_fails():
    """Spot fetchers raising → static base (ETF + stock maps) still hits 00700/AAPL."""
    with patch("app.fetchers.china_market.fetch_hk_spot_list",
               side_effect=RuntimeError("network down")), \
         patch("app.fetchers.china_market.fetch_us_spot_list",
               side_effect=RuntimeError("network down")):
        res = await ms.search_hk_us("00700", include_stocks=True, enrich=False)
    assert any(r["symbol"] == "00700" for r in res)
    assert all(r["market"] == "HK" for r in res)


@pytest.mark.asyncio
async def test_search_hk_us_include_stocks_false_etf_only():
    """include_stocks=False → no individual stocks (00700 empty); True → found."""
    with _patch_spot():
        res_false = await ms.search_hk_us("00700", include_stocks=False, enrich=False)
    assert res_false == [], "ETF-only mode must not return individual stocks"
    with _patch_spot():
        res_true = await ms.search_hk_us("00700", include_stocks=True, enrich=False)
    assert any(r["symbol"] == "00700" for r in res_true)


@pytest.mark.asyncio
async def test_search_hk_us_dedup_base_first():
    """Base and spot both contain SPY → single result from base, type=='etf'."""
    with _patch_spot():
        res = await ms.search_hk_us("SPY", include_stocks=True, enrich=False)
    spy = [r for r in res if r["symbol"] == "SPY"]
    assert len(spy) == 1
    assert spy[0]["type"] == "etf"
    assert spy[0]["asset_type"] == "US"


@pytest.mark.asyncio
async def test_search_hk_us_dedup_hk_etf_suffix():
    """Spot row 02800 must be deduped against base 02800.HK → exactly one, ETF-typed."""
    with _patch_spot():
        res = await ms.search_hk_us("盈富基金", include_stocks=True, enrich=False)
    yf = [r for r in res if _norm(r["symbol"]) == "02800"]
    assert len(yf) == 1, f"expected exactly one 02800 row, got {res}"
    assert yf[0]["symbol"] == "02800.HK"
    assert yf[0]["type"] == "etf"


def _norm(s: str) -> str:
    return s.split(".")[0].lower()


@pytest.mark.asyncio
async def test_search_hk_us_asset_type_market_code():
    """Base ETF hits expose asset_type as market code ('HK'/'US'), type=='etf'."""
    with _patch_spot():
        res = await ms.search_hk_us("盈富", include_stocks=True, enrich=False)
    hit = next(r for r in res if r["symbol"] == "02800.HK")
    assert hit["asset_type"] == "HK"
    assert hit["type"] == "etf"
    res2 = await ms.search_hk_us("SPY", include_stocks=False, enrich=False)
    hit2 = next(r for r in res2 if r["symbol"] == "SPY")
    assert hit2["asset_type"] == "US"
    assert hit2["type"] == "etf"


@pytest.mark.asyncio
async def test_search_hk_us_spot_not_enriched_batch():
    """Spot (stock) hits are never enriched; only type=='etf' hits call get_asset_realtime."""
    big_hk = [{"symbol": f"0{i:04d}", "name": f"港股{i}", "market": "HK"} for i in range(20)]
    big_us = [{"symbol": f"T{i:03d}", "name": f"美股{i}", "market": "US"} for i in range(20)]
    mock_rt = AsyncMock(return_value=None)
    with _patch_spot(hk=big_hk, us=big_us), \
         patch.object(ms, "get_asset_realtime", new=mock_rt):
        res = await ms.search_hk_us("", include_stocks=True, enrich=True)
    etf_count = sum(1 for r in res if r["type"] == "etf")
    stock_rows = [r for r in res if r["type"] == "stock"]
    assert etf_count > 0
    assert len(stock_rows) > 0, "spot stocks should be included"
    assert mock_rt.await_count == etf_count, \
        "get_asset_realtime must be called only for ETF hits"
    assert all(r.get("price") is None for r in stock_rows), \
        "stock hits must not carry enriched price"


# ─── route-level tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_default_cross_market():
    """No market param → merged list; A-share ETF first; non-ETF rows filtered; total ≤ 30."""
    async def _fake_search_etf(kw):
        return [
            {"symbol": "510300", "name": "沪深300ETF", "market": "A", "asset_type": "etf", "type": "etf"},
            {"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock"},  # non-etf → filtered
        ]

    async def _fake_search_hk_us(kw, enrich=True, include_stocks=False, market=None):
        return [
            {"symbol": "02800.HK", "name": "盈富基金", "market": "HK", "asset_type": "HK", "type": "etf"},
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "US", "asset_type": "US", "type": "etf"},
        ]

    with patch.object(market_data_hub, "search_etf", new=_fake_search_etf), \
         patch.object(market_router, "search_hk_us", new=_fake_search_hk_us):
        res = await market_router.search(keyword="510300", market=None)
    assert isinstance(res, list) and len(res) <= 30
    assert res[0]["symbol"] == "510300", "A-share ETF must be first"
    assert all(r.get("market") == "A" for r in res if r["symbol"] == "510300")
    assert not any(r["symbol"] == "600519" for r in res), "non-ETF row must be filtered"
    assert any(r["symbol"] == "02800.HK" for r in res)
    assert any(r["symbol"] == "SPY" for r in res)
    # HK segment before US segment
    hk_pos = [i for i, r in enumerate(res) if r["market"] == "HK"]
    us_pos = [i for i, r in enumerate(res) if r["market"] == "US"]
    if hk_pos and us_pos:
        assert max(hk_pos) < min(us_pos)


@pytest.mark.asyncio
async def test_search_include_stocks_true_adds_a_stocks():
    """include_stocks=true in default branch appends A-share stocks via levistock fallback."""
    async def _fake_search_etf(kw):
        return [{"symbol": "510300", "name": "沪深300ETF", "market": "A", "asset_type": "etf", "type": "etf"}]

    async def _fake_search_hk_us(kw, enrich=True, include_stocks=False, market=None):
        return []

    fake_session = _FakeSession()  # instruments has no stock rows
    with patch.object(market_data_hub, "search_etf", new=_fake_search_etf), \
         patch.object(market_router, "search_hk_us", new=_fake_search_hk_us), \
         patch("app.routers.market.async_session", return_value=fake_session), \
         patch.object(market_data_hub, "get_all_stocks",
                      return_value=[{"stock_code": "600519", "stock_name": "贵州茅台"}]):
        res = await market_router.search(keyword="600519", market=None, include_stocks=True)
    moutai = [r for r in res if r["symbol"] == "600519"]
    assert moutai, "A-share stock must be appended when include_stocks=true"
    assert moutai[0]["market"] == "A"
    assert moutai[0]["asset_type"] == "stock"
    # F3-2: 跨市场合并后全局精确匹配置顶（keyword=600519 → 茅台第一，不再被段序压住）
    assert res[0]["symbol"] == "600519"


@pytest.mark.asyncio
async def test_search_route_hk_us_nonempty():
    """GET /search?keyword=00700&market=HK&include_stocks=true → 200 + list (route level)."""
    async def _fake_search_hk_us(kw, enrich=True, include_stocks=False, market=None):
        return [{"symbol": "00700", "name": "腾讯控股", "market": "HK",
                 "asset_type": "HK", "type": "stock"}]

    with patch.object(market_router, "search_hk_us", new=_fake_search_hk_us):
        res = await market_router.search(keyword="00700", market="HK", include_stocks=True)
    assert isinstance(res, list) and len(res) > 0
    assert res[0]["market"] == "HK"
    assert res[0]["asset_type"] == "HK"


# ─── Z29 contract regression: existing F3-style behavior ────────


@pytest.mark.asyncio
async def test_search_hk_us_legacy_default_still_etf_only_offline():
    """Default (include_stocks=False) keeps old ETF-only behavior, no network."""
    res = await ms.search_hk_us("SPY", enrich=False)
    assert any(r["symbol"] == "SPY" for r in res)
    assert all(r["type"] == "etf" for r in res)
