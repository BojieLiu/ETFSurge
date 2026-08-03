"""
R5-2-1: watchlist 实时行情提速——A 股多标的走 fetch_a_stock_batch 批量路径
（P3-3 原案），避免逐标的串行/并行 get_asset_realtime（慢源拖累、4525ms 退化）。

mock 慢源 + 断言批量接口被调用，无网络。
"""
import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import Base


@pytest.fixture
async def wl_db(tmp_path):
    """独立 SQLite 测试库：watchlist 表。"""
    from app.models.search import Watchlist

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_watchlist_perf.db'}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Watchlist.__table__])
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def async_client(wl_db):
    """Async test client with watchlist router DB patched to test DB."""
    from app.routers import market as market_router

    original_session = market_router.async_session
    market_router.async_session = wl_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    market_router.async_session = original_session


async def _insert_watchlist(session_factory, symbol, name, asset_type="A"):
    from app.models.search import Watchlist

    async with session_factory() as session:
        item = Watchlist(symbol=symbol, name=name, asset_type=asset_type)
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item.id


class TestWatchlistBatchRealtime:
    """R5-2-1: A 股多标的走批量行情路径（fetch_a_stock_batch）。"""

    @pytest.mark.asyncio
    async def test_multi_a_symbols_use_batch_path(self, async_client, wl_db):
        """5 个 A 股标的 → 断言 fetch_a_stock_batch 被调用（批量路径），
        且总耗时 < 3s（逐标的慢源路径会超时拖累）。"""
        for sym, name in [
            ("600519", "贵州茅台"), ("510300", "沪深300ETF"),
            ("601318", "中国平安"), ("000858", "五粮液"),
            ("512480", "半导体ETF"),
        ]:
            await _insert_watchlist(wl_db, sym, name)

        batch_calls = {"n": 0}

        def _fake_batch(symbols):
            batch_calls["n"] += 1
            return [
                {"symbol": s, "name": f"批量{s}", "price": 10.0,
                 "change_pct": 0.01, "volume": 100, "asset_type": "A"}
                for s in symbols
            ]

        # 慢源兜底：若走了逐标的路径，每次 get_asset_realtime 需 1s → 5 只 > 3s
        async def _slow_realtime(symbol, asset_type):
            await asyncio.sleep(1.0)
            return {"symbol": symbol, "price": 1.0, "change_pct": 0.0,
                    "volume": 1, "asset_type": asset_type}

        with patch("app.routers.market.market_data_hub.get_asset_realtime", _slow_realtime), \
             patch("app.fetchers.china_market.fetch_a_stock_batch", _fake_batch):
            _start = time.monotonic()
            resp = await async_client.get("/api/v1/market/watchlist")
            _dur = time.monotonic() - _start

        assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert len(body["items"]) == 5
        # 批量路径被调用（而非 5 次慢速单标的）
        assert batch_calls["n"] >= 1, "R5-2-1 应走 fetch_a_stock_batch 批量路径"
        assert _dur < 3.0, f"watchlist 5 标的耗时 {_dur:.2f}s ≥ 3s（批量路径未生效）"
        # 批量返回的名称被使用
        names = [it["name"] for it in body["items"]]
        assert any("批量" in n for n in names), f"批量行情未生效: {names}"
