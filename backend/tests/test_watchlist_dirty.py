from __future__ import annotations
"""Test Z22: Watchlist dirty data fix (symbol stored as name).

Tests cover:
1. Historical dirty data: symbol=name (Chinese), resolve + auto-heal on GET
2. GET: resolve fails -> no realtime in response, DB unchanged
3. POST: Chinese symbol rejected (422, schema pattern)
4. POST: invalid code (no realtime) rejected (422)
5. POST: realtime name empty -> fallback to symbol
6. GET: auto-heal unique constraint conflict -> warning, response uses resolved data
7. resolve_symbol_to_code: instruments name match -> real code
"""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import Base


@pytest.fixture
async def wl_db(tmp_path):
    """独立 SQLite 测试库：watchlist + instruments 表（不碰开发库）。"""
    from app.models.search import Watchlist, Instrument

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_watchlist.db'}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Watchlist.__table__, Instrument.__table__],
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def async_client(wl_db):
    """Create async test client with watchlist router DB patched to test DB."""
    from app.routers import market as market_router
    original_session = market_router.async_session
    market_router.async_session = wl_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    market_router.async_session = original_session


def _mock_realtime_dispatch(original):
    """Return an AsyncMock-based get_asset_realtime replacement.

    - Chinese name symbol -> None (not found, triggers resolve)
    - '600519' -> realtime dict
    - '510300' -> realtime dict with empty name
    - 'INVALID123' -> None
    - otherwise -> delegate to original
    """
    async def dispatch(symbol, asset_type):
        if symbol == "贵州茅台":
            return None
        if symbol == "INVALID123":
            return None
        if symbol == "600519":
            return {
                "symbol": "600519",
                "name": "贵州茅台",
                "price": 1750.50,
                "change_pct": 1.25,
                "volume": 12345678,
                "asset_type": "A",
            }
        if symbol == "510300":
            return {
                "symbol": "510300",
                "name": "",
                "price": 3.845,
                "change_pct": 0.012,
                "volume": 1000000,
                "asset_type": "A",
            }
        return await original(symbol, asset_type)
    return dispatch


@pytest.fixture
def mock_realtime():
    """Patch market_data_hub.get_asset_realtime + get_realtime_batch with deterministic dispatch.

    round14 P2-AF/AH: watchlist enrich 单只也走批量（get_realtime_batch）——
    批量路径须一并 mock，否则测试落真实网络（mootdx 超时）。
    """
    from app.services.market_data_hub import market_data_hub
    from app.services import market_service as market_service_mod
    original = market_data_hub.get_asset_realtime
    original_batch = market_service_mod.get_realtime_batch
    dispatch = _mock_realtime_dispatch(original)
    market_data_hub.get_asset_realtime = dispatch

    async def _fake_batch(symbols, asset_type="A"):
        out = []
        for s in symbols:
            r = await dispatch(s, asset_type)
            if r:
                out.append(r)
        return out

    market_service_mod.get_realtime_batch = _fake_batch
    yield
    market_data_hub.get_asset_realtime = original
    market_service_mod.get_realtime_batch = original_batch


async def _insert_watchlist(session_factory, symbol, name, asset_type="A", notes=None):
    from app.models.search import Watchlist
    async with session_factory() as session:
        item = Watchlist(symbol=symbol, name=name, asset_type=asset_type, notes=notes)
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item.id


class TestWatchlistDirtyData:
    """Z22: Watchlist dirty data fix tests."""

    @pytest.mark.asyncio
    async def test_get_watchlist_dirty_data_auto_heal(self, async_client, wl_db, mock_realtime):
        """GET /watchlist: dirty data (symbol=Chinese name) auto-resolve + heal DB."""
        await _insert_watchlist(wl_db, "贵州茅台", "贵州茅台", notes="测试脏数据")

        with patch("app.routers.market.resolve_symbol_to_code", new_callable=AsyncMock, return_value="600519"):
            response = await async_client.get("/api/v1/market/watchlist")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        item = data["items"][0]

        # Response uses resolved code + realtime data
        assert item["symbol"] == "600519"
        assert item["name"] == "贵州茅台"
        assert item["realtime"] is not None
        assert item["realtime"]["price"] == 1750.50
        assert item["realtime"]["change_pct"] == 1.25
        assert item["realtime"]["volume"] == 12345678

        # DB auto-healed
        from app.models.search import Watchlist
        from sqlalchemy import select
        async with wl_db() as session:
            row = (await session.execute(select(Watchlist))).scalar_one()
            assert row.symbol == "600519"

    @pytest.mark.asyncio
    async def test_get_watchlist_resolve_fails_no_realtime(self, async_client, wl_db, mock_realtime):
        """GET /watchlist: resolve fails -> no realtime, DB unchanged."""
        await _insert_watchlist(wl_db, "不存在的股票", "不存在的股票")

        with patch("app.routers.market.resolve_symbol_to_code", new_callable=AsyncMock, return_value=None):
            response = await async_client.get("/api/v1/market/watchlist")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["symbol"] == "不存在的股票"
        assert item.get("realtime") is None

        # DB unchanged
        from app.models.search import Watchlist
        from sqlalchemy import select
        async with wl_db() as session:
            row = (await session.execute(select(Watchlist))).scalar_one()
            assert row.symbol == "不存在的股票"

    @pytest.mark.asyncio
    async def test_post_watchlist_chinese_symbol_rejected_422(self, async_client):
        """POST /watchlist: Chinese symbol rejected by schema pattern (422)."""
        response = await async_client.post(
            "/api/v1/market/watchlist",
            json={"symbol": "贵州茅台", "asset_type": "A", "notes": "测试"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_post_watchlist_invalid_code_rejected_422(self, async_client, mock_realtime):
        """POST /watchlist: code without realtime data rejected (422)."""
        response = await async_client.post(
            "/api/v1/market/watchlist",
            json={"symbol": "INVALID123", "asset_type": "A", "notes": "测试"},
        )
        assert response.status_code == 422
        assert "无法解析该标的" in response.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_post_watchlist_name_empty_fallback_to_symbol(self, async_client, mock_realtime):
        """POST /watchlist: realtime name='' -> name falls back to symbol."""
        response = await async_client.post(
            "/api/v1/market/watchlist",
            json={"symbol": "510300", "asset_type": "A", "notes": "测试"},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "510300"

    @pytest.mark.asyncio
    async def test_post_watchlist_response_includes_realtime(self, async_client, mock_realtime):
        """R5: POST 响应携带 realtime——添加后前端立即可显示价格（不等全量 GET）。"""
        response = await async_client.post(
            "/api/v1/market/watchlist",
            json={"symbol": "600519", "asset_type": "A", "notes": "测试"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["symbol"] == "600519"
        assert body["realtime"] is not None
        assert body["realtime"]["price"] == 1750.50
        assert body["realtime"]["change_pct"] == 1.25
        assert body["realtime"]["volume"] == 12345678

    @pytest.mark.asyncio
    async def test_get_watchlist_auto_heal_unique_conflict(self, async_client, wl_db, mock_realtime):
        """GET /watchlist: heal hits unique conflict -> warning, response still resolved, DB unchanged."""
        await _insert_watchlist(wl_db, "600519", "贵州茅台")  # pre-existing resolved code
        dirty_id = await _insert_watchlist(wl_db, "贵州茅台", "贵州茅台")

        with patch("app.routers.market.resolve_symbol_to_code", new_callable=AsyncMock, return_value="600519"):
            response = await async_client.get("/api/v1/market/watchlist")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2

        # Dirty item shows resolved realtime in response
        dirty_item = next(i for i in data["items"] if i["id"] == dirty_id)
        assert dirty_item["realtime"]["price"] == 1750.50

        # DB: dirty item NOT changed (unique conflict prevented heal)
        from app.models.search import Watchlist
        from sqlalchemy import select
        async with wl_db() as session:
            dirty = (await session.execute(select(Watchlist).where(Watchlist.id == dirty_id))).scalar_one()
            assert dirty.symbol == "贵州茅台"


class TestResolveSymbolToCode:
    """Z22: resolve_symbol_to_code unit tests."""

    @pytest.mark.asyncio
    async def test_resolve_instruments_exact_name(self, wl_db):
        """Exact name match in instruments -> symbol."""
        from app.models.search import Instrument
        async with wl_db() as session:
            session.add(Instrument(symbol="510300", name="沪深300ETF", market="A", asset_type="etf"))
            await session.commit()

        with patch("app.services.market_service.async_session", wl_db):
            from app.services.market_service import resolve_symbol_to_code
            code = await resolve_symbol_to_code("沪深300ETF")
        assert code == "510300"

    @pytest.mark.asyncio
    async def test_resolve_instruments_contains_name(self, wl_db):
        """Contains name match -> shortest symbol."""
        from app.models.search import Instrument
        async with wl_db() as session:
            session.add(Instrument(symbol="510300", name="沪深300ETF", market="A", asset_type="etf"))
            session.add(Instrument(symbol="510330", name="沪深300ETF联接A", market="A", asset_type="etf"))
            await session.commit()

        with patch("app.services.market_service.async_session", wl_db):
            from app.services.market_service import resolve_symbol_to_code
            code = await resolve_symbol_to_code("沪深300")
        assert code == "510300"

    @pytest.mark.asyncio
    async def test_resolve_stock_fallback_all_stocks(self, wl_db):
        """Instruments miss -> fetch_all_stocks name match."""
        with patch("app.services.market_service.async_session", wl_db):
            with patch("app.services.market_data_hub.market_data_hub.get_all_stocks", return_value=[
                {"stock_code": "600519", "stock_name": "贵州茅台"},
                {"stock_code": "000858", "stock_name": "五粮液"},
            ]):
                from app.services.market_service import resolve_symbol_to_code
                code = await resolve_symbol_to_code("贵州茅台")
        assert code == "600519"

    @pytest.mark.asyncio
    async def test_resolve_no_match_returns_none(self, wl_db):
        """No match anywhere -> None."""
        with patch("app.services.market_service.async_session", wl_db):
            with patch("app.services.market_data_hub.market_data_hub.get_all_stocks", return_value=[]):
                from app.services.market_service import resolve_symbol_to_code
                code = await resolve_symbol_to_code("未知标的")
        assert code is None


class TestR28R29AddWithName:
    """F9 R28/R29: watchlist_add 优先用前端传入 name，realtime 空但不 422。"""

    @pytest.mark.asyncio
    async def test_add_with_provided_name_no_realtime(self, async_client, wl_db):
        """R29: realtime 空但 name 已提供 → 200（不再 422），name 入库。"""
        from app.services.market_data_hub import market_data_hub
        original = market_data_hub.get_asset_realtime
        market_data_hub.get_asset_realtime = AsyncMock(return_value=None)
        try:
            response = await async_client.post(
                "/api/v1/market/watchlist",
                json={"symbol": "159338", "name": "中证A500ETF", "asset_type": "A"},
            )
            assert response.status_code == 201, f"实际 {response.status_code}: {response.text}"
            body = response.json()
            assert body["name"] == "中证A500ETF"
        finally:
            market_data_hub.get_asset_realtime = original

    @pytest.mark.asyncio
    async def test_add_no_name_no_realtime_422(self, async_client, wl_db):
        """R29: name 与 realtime 都拿不到 → 仍 422。"""
        from app.services.market_data_hub import market_data_hub
        original = market_data_hub.get_asset_realtime
        market_data_hub.get_asset_realtime = AsyncMock(return_value=None)
        try:
            response = await async_client.post(
                "/api/v1/market/watchlist",
                json={"symbol": "159338", "asset_type": "A"},
            )
            assert response.status_code == 422
        finally:
            market_data_hub.get_asset_realtime = original

    @pytest.mark.asyncio
    async def test_add_realtime_name_fallback(self, async_client, wl_db):
        """R29: 未传 name 时回退 realtime.name。"""
        from app.services.market_data_hub import market_data_hub
        original = market_data_hub.get_asset_realtime
        market_data_hub.get_asset_realtime = AsyncMock(
            return_value={"symbol": "510300", "name": "沪深300ETF", "price": 3.9}
        )
        try:
            response = await async_client.post(
                "/api/v1/market/watchlist",
                json={"symbol": "510300", "asset_type": "A"},
            )
            assert response.status_code == 201
            assert response.json()["name"] == "沪深300ETF"
        finally:
            market_data_hub.get_asset_realtime = original


class TestR30NameAutoHeal:
    """F9 R30: 合法代码但 name=脏数据（=symbol）时自动回填真实名称。"""

    @pytest.mark.asyncio
    async def test_list_heals_dirty_name(self, async_client, wl_db, mock_realtime):
        """GET /watchlist: name==symbol（脏）→ 回填 realtime.name + DB UPDATE。"""
        await _insert_watchlist(wl_db, "600519", "600519")  # 脏 name
        response = await async_client.get("/api/v1/market/watchlist")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["name"] == "贵州茅台"  # 显示真实名称

        # DB 已回填
        from app.models.search import Watchlist
        from sqlalchemy import select
        async with wl_db() as session:
            row = (await session.execute(select(Watchlist))).scalar_one()
            assert row.name == "贵州茅台"

    @pytest.mark.asyncio
    async def test_list_keeps_clean_name(self, async_client, wl_db, mock_realtime):
        """R30: name 已是真实名称 → 不回填（保持）。"""
        await _insert_watchlist(wl_db, "600519", "贵州茅台")  # 已干净
        response = await async_client.get("/api/v1/market/watchlist")
        assert response.status_code == 200
        assert response.json()["items"][0]["name"] == "贵州茅台"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ===== folded from test_round14_p2_market.py =====
import asyncio
from types import SimpleNamespace
from app.factors import factor_registry as fr_mod
from app.factors.factor_registry import FactorRegistry
from app.fetchers import hk_hot_fetcher
from app.routers import market as market_router
def _item(symbol, asset_type, name="x"):
    return SimpleNamespace(id=1, symbol=symbol, name=name, asset_type=asset_type,
                           notes="", created_at=None, updated_at=None)
class TestWatchlistGroupedBatch:
    @pytest.mark.asyncio
    async def test_stock_asset_type_routes_to_a_batch(self):
        """P2-AF: asset_type='stock'（301317 江波龙）→ 走 A 股批量 get_realtime_batch。"""
        items = [_item("301317", "stock", "江波龙")]
        calls = {"a": 0, "hk": 0, "us": 0}

        async def _fake_batch(symbols, asset_type):
            calls[asset_type.lower()] += 1
            return [{"symbol": s, "price": 42.0, "change_pct": 0.5, "volume": 100} for s in symbols]

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fake_batch), \
             patch("app.routers.market.async_session"):
            result = await market_router._watchlist_enrich_items(items)
        assert calls["a"] == 1, "stock 应走 A 股批量路径"
        assert result[0]["realtime"]["price"] == 42.0

    @pytest.mark.asyncio
    async def test_hk_symbols_use_hk_batch(self):
        """P2-AH: HK 标的三只 → get_realtime_batch(...,'HK')（修复前 per-item 截断）。"""
        items = [_item("00700", "HK"), _item("09988", "HK"), _item("03690", "HK")]
        calls = {"a": 0, "hk": 0, "us": 0}

        async def _fake_batch(symbols, asset_type):
            calls[asset_type.lower()] += 1
            return [{"symbol": s, "price": 100.0, "change_pct": 0.1, "volume": 1000} for s in symbols]

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fake_batch):
            result = await market_router._watchlist_enrich_items(items)
        assert calls["hk"] == 1
        assert all(it["realtime"]["price"] == 100.0 for it in result)

    @pytest.mark.asyncio
    async def test_degraded_marker_injected_when_all_sources_fail(self):
        """P0-D: 全源失败 → realtime 显式 null + _degraded:true（不再丢键）。

        加固（防 xdist 并行污染）：同一 worker 内其他测试可能把真实行情写进
        cache_service 单例 _store / market_service._asset_realtime_cache，导致
        get_realtime_batch 命中真实缓存返回 600519 实时价（1293.09）而非走 mock。
        此处再阻断 cache_mget（强制 miss）+ 网络叶子 fetch_a_stock_batch（强制抛错），
        无论 get_realtime_batch 绑定是否被污染，批量必失败 → 走降级，断言稳定。
        """
        items = [_item("600519", "A", "贵州茅台")]

        async def _fail_batch(symbols, asset_type):
            raise asyncio.TimeoutError("slow source")

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fail_batch), \
             patch("app.services.cache_service.cache_get", new=AsyncMock(return_value=None)), \
             patch("app.services.cache_service.cache_mget", new=AsyncMock(return_value=[None])), \
             patch("app.fetchers.china_market.fetch_a_stock_batch", side_effect=asyncio.TimeoutError("slow source")):
            result = await market_router._watchlist_enrich_items(items)
        item = result[0]
        assert item["realtime"] is None
        assert item["_degraded"] is True

    @pytest.mark.asyncio
    async def test_single_a_symbol_still_batches(self):
        """P2-AF/AH: 去掉 len>=2 门槛——单只也走批量（不落 per-item）。"""
        items = [_item("510300", "A")]
        calls = {"a": 0}

        async def _fake_batch(symbols, asset_type):
            calls["a"] += 1
            return [{"symbol": s, "price": 3.8, "change_pct": 0.0, "volume": 1} for s in symbols]

        with patch("app.routers.market.market_data_hub.get_asset_realtime", new=AsyncMock(return_value=None)), \
             patch("app.services.market_service.get_realtime_batch", side_effect=_fake_batch):
            result = await market_router._watchlist_enrich_items(items)
        assert calls["a"] == 1
        assert result[0]["realtime"]["price"] == 3.8
class TestSearchIndicesMarketFilter:
    @pytest.mark.asyncio
    async def test_hk_market_filters_indices(self):
        """P2-AG: _search_indices(kw, market='HK') 只返回 HK 指数。"""
        class _FakeIndex:
            symbol = "HSI"
            name = "恒生指数"
            market = "HK"
            is_active = True
            pinyin = "hangsheng"
            first_letter = "HS"

        class _FakeResult:
            def scalars(self):
                return self
            def all(self):
                return [_FakeIndex()]

        class _FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def execute(self, stmt):
                # 捕获 SQL 以断言 market 过滤
                self._sql = str(stmt)
                return _FakeResult()

        sess = _FakeSession()
        with patch("app.routers.market.async_session", return_value=sess):
            result = await market_router._search_indices("恒生", market="HK")
        assert len(result) == 1
        assert result[0]["market"] == "HK"
        assert "market = :market_1" in sess._sql or "market = :" in sess._sql or "='HK'" in sess._sql
