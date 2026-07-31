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
    """Patch market_data_hub.get_asset_realtime with deterministic dispatch."""
    from app.services.market_data_hub import market_data_hub
    original = market_data_hub.get_asset_realtime
    market_data_hub.get_asset_realtime = _mock_realtime_dispatch(original)
    yield
    market_data_hub.get_asset_realtime = original


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])