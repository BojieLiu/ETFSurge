"""
R5-3-4: 路由层集成测试（测试防护体系）。

- sector_analysis_stream: mock market_data_hub（行业+概念双表）+ agent →
  断言概念名映射成功、SSE 首包含板块行情段、无 404。
- watchlist_list: mock get_asset_realtime 慢源 → 断言并行化（慢源不拖累）。

mock 数据源与 agent，无网络。
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import analysis as ar


class _SectorReq:
    sector_code = "光模块"
    sector_type = "industry"
    sector_name = "光模块"
    market = "A"


class _SectorReqConcept:
    sector_code = "BK1036"
    sector_type = "industry"
    sector_name = "半导体"
    market = "A"


@pytest.mark.asyncio
async def test_sector_analysis_concept_mapped_via_combined_tables(monkeypatch):
    """概念名在行业表找不到 → 合并概念表后归一化成功，SSE 首包含板块行情段，无 404。"""
    captured = {}

    industry = [
        {"sector_code": "BK1036", "sector_name": "半导体",
         "price": 3500.5, "change_pct": 2.5, "amount": 1.2e11,
         "turnover_rate": 3.4, "main_inflow": 5.6e9,
         "up_count": 45, "down_count": 12,
         "lead_stock_name": "中芯国际", "lead_stock_code": "688981", "lead_stock_chg": 6.8},
    ]
    concept = [
        {"sector_code": "BK1234", "sector_name": "光模块",
         "price": 2800.0, "change_pct": 3.1, "amount": 8e10,
         "turnover_rate": 5.2, "main_inflow": 2.3e9,
         "up_count": 30, "down_count": 5,
         "lead_stock_name": "新易盛", "lead_stock_code": "300502", "lead_stock_chg": 9.9},
    ]

    def fake_industry(n=200):
        return industry

    def fake_concept(n=200):
        return concept

    def fake_stocks(code):
        return [{"stock_code": "300502", "stock_name": "新易盛"}]

    async def fake_stream(prompt):
        captured["prompt"] = prompt
        yield {"event": "done", "data": {"full_text": "ok"}}

    agent = AsyncMock()
    agent.run_stream = fake_stream
    monkeypatch.setattr(ar, "get_agent", lambda name: agent)
    monkeypatch.setattr(ar.market_data_hub, "get_sector_industry", fake_industry)
    monkeypatch.setattr(ar.market_data_hub, "get_sector_concept", fake_concept)
    monkeypatch.setattr(ar.market_data_hub, "get_sector_stocks", fake_stocks)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])

    resp = await ar.sector_analysis_stream(_SectorReq())
    chunks = [c async for c in resp.body_iterator]
    body = "".join(chunks)
    # 无 404（概念名经合并表归一化映射成功，落到 光模块/BK1234）
    assert "404" not in body, f"不应 404: {body[:200]}"
    assert "event: done" in body
    # prompt 含板块行情段（概念板块快照注入）
    prompt = captured.get("prompt", "")
    assert "板块实时行情" in prompt, "prompt 应含板块实时行情段"
    assert "2800.0" in prompt or "3500.5" in prompt, "板块点位应注入"
    assert "新易盛" in prompt or "中芯国际" in prompt, "领涨股应注入"


@pytest.mark.asyncio
async def test_watchlist_realtime_parallel_slow_source_not_blocking():
    """watchlist_list 并行化：慢源（4s）不拖累整体响应（R5 并行 + 3s 截断）。"""
    from app.routers import market as market_router
    from app.models.search import Watchlist
    from app.database import Base
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from httpx import AsyncClient, ASGITransport
    import time

    # 独立 SQLite 测试库
    import tempfile, os
    tmp = tempfile.mkdtemp()
    db_url = f"sqlite+aiosqlite:///{os.path.join(tmp, 'wl.db')}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Watchlist.__table__])
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        for sym in ["600519", "510300", "601318"]:
            session.add(Watchlist(symbol=sym, name=f"标的{sym}", asset_type="A"))
        await session.commit()

    async def _slow_realtime(symbol, asset_type):
        await asyncio.sleep(4.0)  # 慢源：单标的 4s > 3s 截断
        return {"symbol": symbol, "price": 10.0, "change_pct": 0.1,
                "volume": 100, "asset_type": asset_type}

    original_session = market_router.async_session
    market_router.async_session = factory
    try:
        with patch.object(market_router.market_data_hub, "get_asset_realtime", _slow_realtime), \
             patch("app.services.market_service.get_realtime_batch",
                   new_callable=AsyncMock, return_value=[]):
            transport = ASGITransport(app=ar.app if hasattr(ar, "app") else _get_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                _start = time.monotonic()
                resp = await client.get("/api/v1/market/watchlist")
                _dur = time.monotonic() - _start
    finally:
        market_router.async_session = original_session
        await engine.dispose()

    assert resp.status_code == 200, f"status {resp.status_code}"
    # 3 个慢源并行 + 3s 截断 → 总耗时 < 7s（含 app 首次启动开销；串行会 12s）
    assert _dur < 7.0, f"watchlist 3 标的并行耗时 {_dur:.2f}s ≥ 7s（串行化退化）"


def _get_app():
    from app.main import app
    return app
