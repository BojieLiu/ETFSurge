from __future__ import annotations
"""Folded business tests (from early-round audit)."""

# folded-from audit: docs/test-redundancy-audit-and-plan.md


# ===== folded from test_z29_search.py =====
import pytest
import asyncio
from contextlib import contextmanager, ExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import market_service as ms
from app.routers import market as market_router
from app.services.market_data_hub import market_data_hub
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
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
def _norm(s: str) -> str:
    return s.split(".")[0].lower()
class _FakeInstrument:
    def __init__(self, symbol, name, market, asset_type="stock", pinyin="", first_letter=""):
        self.symbol = symbol
        self.name = name
        self.market = market
        self.asset_type = asset_type
        self.pinyin = pinyin
        self.first_letter = first_letter
        self.is_active = True
def _fake_session_rows(rows):
    """构造 async_session 的 fake：execute → scalars().all() → rows。"""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return cm
_client = TestClient(app)
class TestSearchHkUsLocalFallback:
    @pytest.mark.asyncio
    async def test_hk_instruments_fallback_when_spot_empty(self, monkeypatch):
        """HK spot 空 → 本地 instruments 表（HK 段）补搜 → 00700 可命中。"""
        from app.services.market_service import search_hk_us

        rows = [
            _FakeInstrument("00700", "腾讯控股", "HK", pinyin="tengxunkonggu", first_letter="tx"),
            _FakeInstrument("09988", "阿里巴巴", "HK"),
        ]
        monkeypatch.setattr(ms, "async_session", _fake_session_rows(rows))
        # 两段 spot 都空 → HK/US 均走本地表补搜
        monkeypatch.setattr(ms, "_call", AsyncMock(return_value=[]))

        results = await search_hk_us("00700", include_stocks=True)
        hits = [r for r in results if r["symbol"] == "00700"]
        assert hits, "HK 本地表补搜应命中 00700"
        assert hits[0]["name"] == "腾讯控股"
        assert hits[0]["market"] == "HK"

    @pytest.mark.asyncio
    async def test_hk_name_search_via_local_table(self, monkeypatch):
        """HK 名称（腾讯）经本地 instruments 表命中。"""
        from app.services.market_service import search_hk_us

        rows = [
            _FakeInstrument("00700", "腾讯控股", "HK", pinyin="tengxunkonggu", first_letter="tx"),
        ]
        monkeypatch.setattr(ms, "async_session", _fake_session_rows(rows))
        monkeypatch.setattr(ms, "_call", AsyncMock(return_value=[]))

        results = await search_hk_us("腾讯", include_stocks=True)
        assert any(r["name"] == "腾讯控股" for r in results)
class TestSearchSorting:
    """Z20: unified search sorting."""

    def _items(self):
        return [
            {"symbol": "510300", "name": "沪深300ETF", "market": "A", "asset_type": "etf", "type": "etf"},
            {"symbol": "510050", "name": "上证50ETF", "market": "A", "asset_type": "etf", "type": "etf"},
            {"symbol": "510880", "name": "红利ETF", "market": "A", "asset_type": "etf", "type": "etf"},
            {"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock"},
            {"symbol": "02800.HK", "name": "盈富基金", "market": "HK", "asset_type": "etf", "type": "etf"},
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "US", "asset_type": "etf", "type": "etf"},
        ]

    def test_exact_code_ranks_first(self):
        from app.services.market_service import _sort_search_results

        items = self._items()
        result = _sort_search_results(items, "600519")
        assert result[0]["symbol"] == "600519"

    def test_code_prefix_before_name_exact(self):
        from app.services.market_service import _sort_search_results

        # keyword "510300": symbol 510300 exact, but also matches 510 prefix for others
        result = _sort_search_results(self._items(), "510300")
        symbols = [i["symbol"] for i in result]
        # 510300 exact code first, then 510050/510880 (code prefix)
        assert symbols[0] == "510300"
        assert symbols[1] == "510050"
        assert symbols[2] == "510880"

    def test_name_exact_before_name_prefix_before_contains(self):
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "A", "name": "沪深300ETF", "market": "A", "asset_type": "etf"},
            {"symbol": "B", "name": "沪深300ETF联接A", "market": "A", "asset_type": "etf"},
            {"symbol": "C", "name": "沪深300价值ETF", "market": "A", "asset_type": "etf"},
            {"symbol": "D", "name": "中证沪深300指数", "market": "A", "asset_type": "etf"},
        ]
        result = _sort_search_results(items, "沪深300")
        # exact name (沪深300ETF) first, then prefix (沪深300ETF联接A), then contains
        assert result[0]["symbol"] == "A"
        assert result[1]["symbol"] == "B"
        # C and D are contains matches; 沪深300价值ETF vs 中证沪深300指数 both contain,
        # symbol lexicographic decides: C before D
        assert result[2]["symbol"] == "C"
        assert result[3]["symbol"] == "D"

    def test_etf_before_stock_same_tier(self):
        """Z20: 同档（同 tier）内 ETF 优先于个股。"""
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "600519", "name": "贵州茅台股", "market": "A", "asset_type": "stock", "type": "stock"},
            {"symbol": "510300", "name": "贵州茅台ETF", "market": "A", "asset_type": "etf", "type": "etf"},
        ]
        result = _sort_search_results(items, "贵州茅台")
        # 两者都是名称前缀匹配（tier 4）→ 同档内 ETF 在前
        assert result[0]["symbol"] == "510300"
        assert result[1]["symbol"] == "600519"

    def test_exact_name_beats_etf_priority(self):
        """Z20: 档位优先于 ETF 规则 — 精确名称(股票)排在名称前缀(ETF)之前。"""
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock"},
            {"symbol": "510300", "name": "贵州茅台ETF", "market": "A", "asset_type": "etf", "type": "etf"},
        ]
        result = _sort_search_results(items, "贵州茅台")
        assert result[0]["symbol"] == "600519"  # tier 3 (exact name)
        assert result[1]["symbol"] == "510300"  # tier 4 (name prefix)

    def test_market_order_and_symbol_lexicographic(self):
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "SPY", "name": "SPDR 美股", "market": "US", "asset_type": "etf"},
            {"symbol": "02800.HK", "name": "SPDR 港股", "market": "HK", "asset_type": "etf"},
            {"symbol": "510300", "name": "SPDR 概念", "market": "A", "asset_type": "etf"},
        ]
        result = _sort_search_results(items, "SPDR")
        markets = [i["market"] for i in result]
        assert markets == ["A", "HK", "US"]

    def test_ordering_deterministic(self):
        """Same input twice -> same output."""
        from app.services.market_service import _sort_search_results

        items = self._items()
        r1 = _sort_search_results(items, "510")
        r2 = _sort_search_results(items, "510")
        assert [i["symbol"] for i in r1] == [i["symbol"] for i in r2]
class TestSearchEtfSorting:
    """Z20: search_etf local-table path applies the sorting contract."""

    @pytest.mark.asyncio
    async def test_search_etf_sorted(self):
        from app.services import market_service as _ms
        from app.models.search import Instrument

        rows = [
            Instrument(symbol="510880", name="红利ETF", market="A", asset_type="etf"),
            Instrument(symbol="510300", name="沪深300ETF", market="A", asset_type="etf"),
            Instrument(symbol="510050", name="上证50ETF", market="A", asset_type="etf"),
        ]

        class FakeResult:
            def scalars(self):
                return self

            def all(self):
                return rows

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, stmt):
                return FakeResult()

        with patch.object(_ms, "async_session", lambda: FakeSession()):
            result = await _ms.search_etf("510")

        symbols = [r["symbol"] for r in result]
        # All three are code-prefix matches -> symbol lexicographic ascending
        assert symbols == ["510050", "510300", "510880"]
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
async def test_search_hk_us_english_static_base_no_spot():
    """P0-6 (round16 3.3): 英文名（Apple）在 spot 源不可用时仍能命中静态基座（name_en 兜底）。

    负向：静态基座无 name_en → Apple 搜索 0 命中 → FAIL。
    """
    with patch("app.fetchers.china_market.fetch_hk_spot_list",
               side_effect=RuntimeError("network down")), \
         patch("app.fetchers.china_market.fetch_us_spot_list",
               side_effect=RuntimeError("network down")):
        res = await ms.search_hk_us("Apple", include_stocks=True, enrich=False)
    assert any(r["symbol"] == "AAPL" for r in res), f"Apple 英文名静态基座未命中: {res}"
    hit = next(r for r in res if r["symbol"] == "AAPL")
    assert hit["market"] == "US"
@pytest.mark.asyncio
async def test_search_hk_us_etf_enrich_does_not_block_event_loop():
    """P0-21 (round16 3.22): US ETF 搜索 enrich 走 get_asset_realtime（P0-11 已改
    _route_us 线程池化）——enrich 期间事件循环保持响应（负向：同步阻塞则并发
    probe 延迟>1s → FAIL）。"""
    import time
    from app.services.market_service import search_hk_us

    async def _slow_realtime(symbol, asset_type):
        # 模拟慢实时源（async 等待，不阻塞事件循环——旧实现在此同步阻塞）
        await asyncio.sleep(1.5)
        return {"symbol": symbol, "price": 500.0, "change_pct": 1.2}

    async def _probe():
        t0 = time.monotonic()
        await asyncio.sleep(0.2)
        return time.monotonic() - t0

    with _patch_spot(us=_us_spot_rows()), \
         patch.object(ms, "get_asset_realtime", new=_slow_realtime):
        res, probe_cost = await asyncio.gather(
            search_hk_us("SPY", include_stocks=True, enrich=True),
            _probe(),
        )
    assert any(r["symbol"] == "SPY" for r in res), "SPY 应命中"
    assert probe_cost < 1.0, \
        f"负向：US ETF enrich 阻塞事件循环，probe 延迟 {probe_cost:.2f}s"
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
@pytest.mark.asyncio
async def test_search_hk_us_legacy_default_still_etf_only_offline():
    """Default (include_stocks=False) keeps old ETF-only behavior, no network."""
    res = await ms.search_hk_us("SPY", enrich=False)
    assert any(r["symbol"] == "SPY" for r in res)
    assert all(r["type"] == "etf" for r in res)
def test_us_spot_failure_falls_back_to_local_instruments(monkeypatch):
    """fetch_us_spot_list 失败/空 → 本地 instruments 表 US 段补搜（apple 非空）。"""
    us_rows = [
        type("R", (), {"symbol": "AAPL", "name": "苹果", "market": "US", "is_active": True})(),
        type("R", (), {"symbol": "MSFT", "name": "微软", "market": "US", "is_active": True})(),
    ]

    class _FakeSessionUsRows:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            return self

        def scalars(self):
            return self

        def all(self):
            return us_rows

    monkeypatch.setattr(ms, "async_session", lambda: _FakeSessionUsRows())
    # HK spot 正常返回空，US spot 失败（模拟限流）——search_hk_us 内部
    # `from ..fetchers.china_market import fetch_us_spot_list` 读模块属性
    monkeypatch.setattr("app.fetchers.china_market.fetch_us_spot_list", lambda: [])
    monkeypatch.setattr("app.fetchers.china_market.fetch_hk_spot_list", lambda: [])

    async def _go():
        # 直接调用 search_hk_us：include_stocks=True 触发 spot 段
        return await ms.search_hk_us("apple", include_stocks=True, enrich=False)

    import asyncio
    results = asyncio.run(_go())
    us_hits = [r for r in results if r.get("market") == "US" and r.get("type") == "stock"]
    assert any("apple" in (r.get("name") or "").lower() or r.get("symbol") == "AAPL"
               for r in us_hits), f"本地 US instruments 补搜应命中 apple, got {results[:5]}"
def test_cross_market_exact_symbol_first(monkeypatch):
    """search?keyword=SPY 首条为 SPY（即使 HK/US 段内还有其他模糊命中）。"""
    async def fake_search_etf(kw):
        return []  # SPY 非 A 股

    async def fake_search_hk_us(kw, enrich=False, include_stocks=False, market=None):
        # 模拟 US 段：模糊命中多个，SPY 不在首位（基座顺序）
        return [
            {"symbol": "SPYD", "name": "SPYD 分红ETF", "market": "US", "asset_type": "US", "type": "etf"},
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "US", "asset_type": "US", "type": "etf"},
            {"symbol": "SPX", "name": "标普500指数", "market": "US", "asset_type": "US", "type": "etf"},
        ]

    monkeypatch.setattr(market_router.market_data_hub, "search_etf", fake_search_etf)
    monkeypatch.setattr(market_router, "search_hk_us", fake_search_hk_us)
    monkeypatch.setattr(market_router, "_search_a_stocks", lambda kw: [])

    resp = _client.get("/api/v1/market/search?keyword=SPY")
    assert resp.status_code == 200
    items = resp.json()
    assert items and items[0]["symbol"] == "SPY", f"精确匹配应排首位，实际: {items[:2]}"
def test_cross_market_global_sort_applied(monkeypatch):
    """跨市场合并结果经 _sort_search_results 排序（精确代码 tier1 置顶）。"""
    async def fake_search_etf(kw):
        return [{"symbol": "510050", "name": "上证50ETF", "market": "A", "asset_type": "etf", "type": "etf"}]

    async def fake_search_hk_us(kw, enrich=False, include_stocks=False, market=None):
        return [
            {"symbol": "0050", "name": "元大台湾50", "market": "HK", "asset_type": "HK", "type": "etf"},
            {"symbol": "510050.HK", "name": "南方A50", "market": "HK", "asset_type": "HK", "type": "etf"},
        ]

    monkeypatch.setattr(market_router.market_data_hub, "search_etf", fake_search_etf)
    monkeypatch.setattr(market_router, "search_hk_us", fake_search_hk_us)
    monkeypatch.setattr(market_router, "_search_a_stocks", lambda kw: [])

    resp = _client.get("/api/v1/market/search?keyword=510050")
    items = resp.json()
    # 精确 symbol 命中（510050）应排在 HK 模糊命中之前
    assert items and items[0]["symbol"] == "510050", f"实际首位: {items[0] if items else None}"
def test_market_a_stock_levistock_fallback(monkeypatch):
    """instruments 表不可用 → 降级 levistock 返回茅台（而非直接 ETF 模式）。"""
    class _FakeSessionMaker:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(market_router, "async_session", _FakeSessionMaker())
    monkeypatch.setattr(market_router.market_data_hub, "get_all_stocks", lambda: [
        {"stock_code": "600519", "stock_name": "贵州茅台"},
        {"stock_code": "000001", "stock_name": "平安银行"},
    ])

    resp = _client.get("/api/v1/market/search?keyword=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&market=A")
    items = resp.json()
    assert resp.status_code == 200
    assert any(it.get("symbol") == "600519" and it.get("name") == "贵州茅台" for it in items), f"实际: {items[:3]}"
def test_budget_cash_within_15pct():
    """STRATEGY_META 三档 layer_budget 和 ≥ 0.85（现金 ≤ 15%）。"""
    from app.engine.budgets import STRATEGY_META

    for profile, meta in STRATEGY_META.items():
        total = sum(meta["layer_budget"].values())
        cash = 1.0 - total
        assert cash <= 0.1501, f"{profile} 现金 {cash:.1%} > 15%"
def test_range_bound_balanced_cash_limit():
    """range_bound 市态 balanced 方案现金 ≤ 15%（验收：balanced 方案现金 ≤ 15%）。"""
    from app.engine.budgets import dynamic_layer_budget

    budget = dynamic_layer_budget("balanced", "range_bound")
    cash = 1.0 - sum(budget.values())
    assert cash <= 0.1501, f"balanced range_bound 现金 {cash:.1%} 超限"
@pytest.mark.asyncio
async def test_us_realtime_name_filled(monkeypatch):
    """get_asset_realtime US 分支返回数据缺 name 时，从静态基座补全。"""
    async def fake_route_us(symbol):
        return {"symbol": "SPY", "price": 500.0, "change_pct": 1.0}  # 无 name

    monkeypatch.setattr(ms, "_route_us", fake_route_us)
    data = await ms.get_asset_realtime("SPY", "US")
    assert data is not None
    assert data.get("name"), f"应补全 name，实际: {data}"
    assert "SPY" in data["name"].upper() or "S&P" in data["name"].upper()
@pytest.mark.asyncio
async def test_us_realtime_keeps_existing_name(monkeypatch):
    """US 分支已有 name 时保持原值不覆盖。"""
    async def fake_route_us(symbol):
        return {"symbol": "AAPL", "name": "Apple Inc.", "price": 180.0}

    monkeypatch.setattr(ms, "_route_us", fake_route_us)
    data = await ms.get_asset_realtime("AAPL", "US")
    assert data["name"] == "Apple Inc."


# ===== R84 (round29): 美股搜索 TQQQ 经新浪 suggest type=41 兜底 =====
class TestSearchUsSinaSuggestR84:
    """R84: EM 美股 spot 纯股票不含 ETF、instruments US 段常失败 →
    TQQQ 类杠杆 ETF 经 sina suggest type=41 兜底补搜。"""

    @pytest.mark.asyncio
    async def test_tqqq_suggested_when_spot_and_instruments_empty(self, monkeypatch):
        from app.services.market_service import search_hk_us

        # ① spot 双源空 ② instruments US 段空 → 三级源全断
        monkeypatch.setattr(ms, "_call", AsyncMock(return_value=[]))
        monkeypatch.setattr(ms, "async_session", _fake_session_rows([]))
        # ④ sina suggest 兜底返回 TQQQ
        tqqq = {"symbol": "TQQQ", "name": "纳斯达克指数ETF-ProShares三倍做多",
                "market": "US", "asset_type": "US", "type": "etf"}
        monkeypatch.setattr(ms, "_us_suggest_fallback", AsyncMock(return_value=[tqqq]))

        results = await search_hk_us("TQQ", include_stocks=True, market="US")
        hits = [r for r in results if r["symbol"] == "TQQQ"]
        assert hits, "TQQQ 应经 sina suggest 兜底命中（R84 回归）"
        assert hits[0]["market"] == "US"

    @pytest.mark.asyncio
    async def test_sina_suggest_never_blocks_search_on_failure(self, monkeypatch):
        """sina suggest 失败（异常/超时）时搜索不得阻塞，仍正常返回（毫秒级降级）。"""
        from app.services.market_service import search_hk_us

        monkeypatch.setattr(ms, "_call", AsyncMock(return_value=[]))
        monkeypatch.setattr(ms, "async_session", _fake_session_rows([]))
        monkeypatch.setattr(ms, "_us_suggest_fallback", AsyncMock(side_effect=RuntimeError("net down")))

        # 不应抛异常，应安全返回（可能为空，但不阻塞）
        results = await search_hk_us("TQQ", include_stocks=True, market="US")
        assert isinstance(results, list)

    def test_fetch_us_suggest_fallback_parses_line(self, monkeypatch):
        """_fetch_us_suggest_sync 解析 sina GBK 行 → 含 ETF 标记。"""
        from app.services import market_service as _ms
        import urllib.request as _ur_req

        # R84: 真实响应带 `var suggestvalue="` 前缀 + 尾部分号/引号——解析必须剥离，
        # 否则 symbol 是 `var suggestvalue="TQQQ`（本地实测复现的 bug）。
        fake_line = ('var suggestvalue="TQQQ,41,tqqq,tqqq,纳斯达克指数ETF-ProShares三倍做多,,'
                     '纳斯达克指数ETF-ProShares三倍做多,99,1,,,";')

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return fake_line.encode("gb18030")

        monkeypatch.setattr(_ur_req, "urlopen", lambda *a, **k: _Resp())

        rows = _ms._fetch_us_suggest_sync("TQQ")
        assert any(r["symbol"] == "TQQQ" and r["type"] == "etf" for r in rows), rows
        assert not any("suggestvalue" in (r["symbol"] or "") for r in rows), rows

