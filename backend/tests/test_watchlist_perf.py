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


class TestWatchlistCoolingDegrade:
    """P1-2 (round17): 数据源冷却期——批量失败快速降级 DB-only，不逐只串行重试。

    实测（2026-08-12 非交易时段）：19 只自选含 3 美股，US 批量失败（twelvedata 429）
    → 逐美股 per-item 串行重试 429 + finnhub 各 2-5s → 叠加撞 5s 外层超时 →
    冷/热态均 7.4s 卡死。修复后：批量失败市场全部跳过 per-item，直接 DB-only（_degraded）。
    """

    @pytest.mark.asyncio
    async def test_batch_failure_skips_per_item_and_degrades(self, async_client, wl_db):
        """冷却期批量失败 → 不逐只重试 + 快速返回 + _degraded 标记（负向：仍 per-item → FAIL）。"""
        await _insert_watchlist(wl_db, "600519", "贵州茅台")
        await _insert_watchlist(wl_db, "AAPL", "苹果", asset_type="US")
        await _insert_watchlist(wl_db, "QQQ", "纳指ETF", asset_type="US")

        per_item_calls = {"n": 0}

        async def _fail_batch(symbols, asset_type):
            # 冷却期：批量接口不可用（超时/异常）→ 返回空
            await asyncio.sleep(0.01)
            return []

        async def _unexpected_realtime(symbol, asset_type):
            # per-item 不应被调用——旧实现 US 批量失败后逐美股串行重试
            per_item_calls["n"] += 1
            await asyncio.sleep(1.0)  # 慢源：若被调用会拖慢整体
            return {"symbol": symbol, "price": 1.0, "change_pct": 0.0,
                    "volume": 1, "asset_type": asset_type}

        with patch("app.services.market_service.get_realtime_batch", _fail_batch), \
             patch("app.routers.market.market_data_hub.get_asset_realtime", _unexpected_realtime):
            _start = time.monotonic()
            resp = await async_client.get("/api/v1/market/watchlist")
            _dur = time.monotonic() - _start

        assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert len(body["items"]) == 3
        # 负向断言：per-item 兜底未被调用（旧实现批量失败后逐只串行重试 → 7.4s 卡死）
        assert per_item_calls["n"] == 0, "P1-2 冷却期应跳过 per-item 直接 DB-only"
        # 冷却期快速返回 < 3s（verify_perf watchlist ≤3s 阈值）
        assert _dur < 3.0, f"watchlist 冷却期耗时 {_dur:.2f}s ≥ 3s（未快速降级）"
        # 批量失败市场标的显式 _degraded（realtime=null，前端可区分「加载中」与「已降级」）
        us_items = [it for it in body["items"] if it["asset_type"] == "US"]
        assert len(us_items) == 2
        assert all(it.get("_degraded") for it in us_items), "US 批量失败应标记 _degraded"

    @pytest.mark.asyncio
    async def test_batch_timeout_reduced_to_2s(self, async_client, wl_db):
        """P1-2: _batch_for 超时 4→2s——批量挂死时 2s 内降级（负向：仍等满 4s → FAIL）。"""
        await _insert_watchlist(wl_db, "510300", "沪深300ETF")

        async def _hang_batch(symbols, asset_type):
            # 模拟批量接口挂死（不返回）——_batch_for 超时应快速降级
            await asyncio.sleep(10)

        async def _fast_realtime(symbol, asset_type):
            return {"symbol": symbol, "price": 1.0, "change_pct": 0.0,
                    "volume": 1, "asset_type": asset_type}

        with patch("app.services.market_service.get_realtime_batch", _hang_batch), \
             patch("app.routers.market.market_data_hub.get_asset_realtime", _fast_realtime):
            _start = time.monotonic()
            resp = await async_client.get("/api/v1/market/watchlist")
            _dur = time.monotonic() - _start

        assert resp.status_code == 200
        # 批量挂死（超时 2s 降级）→ 该市场 skip per-item → DB-only（_degraded）或
        # quote-cache 兜底——快速返回（不再等满 4s 批量 + 逐只重试）
        assert _dur < 3.0, f"批量挂死时耗时 {_dur:.2f}s ≥ 3s（_batch_for 超时未降至 2s）"
        body = resp.json()
        assert body["items"][0]["realtime"] is not None or body["items"][0].get("_degraded") is True

    @pytest.mark.asyncio
    async def test_batch_ok_symbol_mismatch_still_per_item(self, async_client, wl_db):
        """P1-2 review 修复: 批量**成功**但 symbol 格式不匹配（自选存 "02800.HK"、
        批量返回 "02800"）→ 不得按「0 精确命中」误判整市场降级——走 per-item 兜底
        （健康市场不误标 _degraded）。"""
        await _insert_watchlist(wl_db, "02800.HK", "盈富基金", asset_type="HK")

        batch_calls = {"n": 0}

        async def _ok_batch(symbols, asset_type):
            # 批量调用成功但返回格式不同（HK 批量无 .HK 后缀）
            batch_calls["n"] += 1
            return [{"symbol": "02800", "name": "盈富基金", "price": 12.0,
                     "change_pct": 0.5, "volume": 100, "asset_type": "HK"}]

        async def _per_item(symbol, asset_type):
            # per-item 兜底：归一化命中（健康市场应走此路径，不跳过）
            return {"symbol": symbol, "name": "盈富基金", "price": 12.0,
                    "change_pct": 0.5, "volume": 100, "asset_type": asset_type}

        with patch("app.services.market_service.get_realtime_batch", _ok_batch), \
             patch("app.routers.market.market_data_hub.get_asset_realtime", _per_item):
            resp = await async_client.get("/api/v1/market/watchlist")

        assert resp.status_code == 200, f"status {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        item = body["items"][0]
        # 批量调用成功 → 不 skip per-item → per-item 归一化命中 → realtime 有值且非 _degraded
        assert batch_calls["n"] == 1
        assert item.get("_degraded") is not True, \
            "批量成功但 symbol 格式不匹配时不得误标 _degraded（review 修复）"
        assert item["realtime"] is not None
