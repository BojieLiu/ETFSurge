"""round49 A4-C: warmup_market_cache 两阶段预热 (fast 5s + slow 25s).

覆盖:
  - refresh_market_cache(phase='fast') 跳过 off_exchange, 写 cache
  - refresh_market_cache(phase='slow') 跑 off_exchange, 写 cache
  - refresh_market_cache(phase='all') 完整流程 (兼容旧)
  - get_portfolio_realtime(phase='fast') 不调 fetch_fund_nav
  - get_portfolio_realtime(phase='slow') 调 fetch_fund_nav
  - get_portfolio_realtime(phase='all') 调 fetch_fund_nav (默认)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_refresh_market_cache_phase_fast_skips_off_exchange():
    """phase='fast' 跳过 off_exchange 段."""
    from app.tasks.market_refresh import refresh_market_cache
    from app.services.market_data_hub import market_data_hub as _hub

    captured = {"phase": None}

    async def fake_get(phase="all"):
        captured["phase"] = phase
        return [{"symbol": "510050"}]

    with patch.object(_hub, "get_portfolio_realtime", new=fake_get, create=True):
        await refresh_market_cache(phase="fast")
    assert captured["phase"] == "fast"


@pytest.mark.asyncio
async def test_refresh_market_cache_phase_slow_runs_off_exchange():
    """phase='slow' 走 off_exchange."""
    from app.tasks.market_refresh import refresh_market_cache
    from app.services.market_data_hub import market_data_hub as _hub

    captured = {"phase": None}

    async def fake_get(phase="all"):
        captured["phase"] = phase
        return [{"symbol": "510050"}]

    with patch.object(_hub, "get_portfolio_realtime", new=fake_get, create=True):
        await refresh_market_cache(phase="slow")
    assert captured["phase"] == "slow"


@pytest.mark.asyncio
async def test_refresh_market_cache_default_phase_all():
    """默认 phase='all' (兼容旧调用方)."""
    from app.tasks.market_refresh import refresh_market_cache
    from app.services.market_data_hub import market_data_hub as _hub

    captured = {"phase": None}

    async def fake_get(phase="all"):
        captured["phase"] = phase
        return []

    with patch.object(_hub, "get_portfolio_realtime", new=fake_get, create=True):
        await refresh_market_cache()  # 不传 phase
    assert captured["phase"] == "all"


@pytest.mark.asyncio
async def test_refresh_market_cache_exception_swallowed():
    """get_portfolio_realtime 抛异常 → refresh_market_cache 不抛 (非阻塞)."""
    from app.tasks.market_refresh import refresh_market_cache
    from app.services.market_data_hub import market_data_hub as _hub

    async def fake_get(phase="all"):
        raise RuntimeError("simulated source failure")

    with patch.object(_hub, "get_portfolio_realtime", new=fake_get, create=True):
        # 不应抛
        await refresh_market_cache(phase="fast")


@pytest.mark.asyncio
async def test_get_portfolio_realtime_phase_fast_does_not_call_fetch_fund_nav():
    """phase='fast' → 不调 fetch_fund_nav (跳过 off_exchange 循环)."""
    from app.services import market_service

    # mock cache_get 返 None (强制走完整流程)
    captured = {"called": False}

    async def fake_fetch_fund_nav(symbol, *args, **kwargs):
        captured["called"] = True
        return {"nav": 1.0}

    # mock list_etfs 返 (on_exchange 有 1 个, off_exchange 有 1 个)
    class FakeEtf:
        def __init__(self, sym, kind):
            self.symbol = sym
            self.name = f"name_{sym}"
            self.short_name = f"short_{sym}"
            self.tracked_index = "000300" if kind == "off" else None
            self.portfolio_type = kind

    fake_on = [FakeEtf("510050", "on")]
    fake_off = [FakeEtf("161725", "off")]

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def __call__(self, *args, **kwargs):
            return self
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = fake_on + fake_off
            return r

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs", new=AsyncMock(side_effect=[fake_on, fake_off])), \
         patch.object(market_service, "get_realtime_batch", new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=AsyncMock(return_value=[])), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch("app.fetchers.china_market.fetch_fund_nav", new=fake_fetch_fund_nav), \
         patch.object(market_service, "async_session", return_value=FakeSession()):
        result = await market_service.get_portfolio_realtime(phase="fast")
    # fast 阶段不应调 fetch_fund_nav
    assert captured["called"] is False, "phase=fast 不应调 fetch_fund_nav"


@pytest.mark.asyncio
async def test_get_portfolio_realtime_phase_slow_runs_off_exchange():
    """phase='slow' 调 fetch_fund_nav."""
    from app.services import market_service

    captured = {"count": 0}

    async def fake_fetch_fund_nav(symbol, *args, **kwargs):
        captured["count"] += 1
        return {"nav": 1.0}

    # _call 内部按函数名区分返回: fetch_index_realtime 返 list, fetch_fund_nav 返 dict
    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, '__name__', str(fn))
        print(f"DEBUG fake_call fn_name={fn_name} args={args} kwargs={kwargs}", file=__import__('sys').stderr)
        if fn_name == "fetch_index_realtime":
            return []
        return await fake_fetch_fund_nav(fn_name, *args, **kwargs)

    class FakeEtf:
        def __init__(self, sym, kind):
            self.symbol = sym
            self.name = f"name_{sym}"
            self.short_name = f"short_{sym}"
            self.tracked_index = "000300"
            self.portfolio_type = kind

    fake_on = [FakeEtf("510050", "on")]
    fake_off = [FakeEtf("161725", "off")]

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def __call__(self, *args, **kwargs):
            return self
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = fake_on + fake_off
            return r

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs", new=AsyncMock(side_effect=[fake_on, fake_off])), \
         patch.object(market_service, "get_realtime_batch", new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session", return_value=FakeSession()):
        print(f"DEBUG before await: market_service._call = {market_service._call}", file=__import__('sys').stderr)
        result = await market_service.get_portfolio_realtime(phase="slow")
    # slow 阶段应至少调 1 次 fetch_fund_nav (off_exchange 1 个)
    assert captured["count"] >= 1, f"phase=slow 应调 fetch_fund_nav, 实调 {captured['count']} 次"


@pytest.mark.asyncio
async def test_get_portfolio_realtime_phase_all_default():
    """phase='all' (默认) 走完整流程 = 调 fetch_fund_nav."""
    from app.services import market_service

    captured = {"count": 0}

    async def fake_fetch_fund_nav(symbol, *args, **kwargs):
        captured["count"] += 1
        return {"nav": 1.0}

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, "__name__", str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        return await fake_fetch_fund_nav(fn, *args, **kwargs)

    class FakeEtf:
        def __init__(self, sym, kind):
            self.symbol = sym
            self.name = f"name_{sym}"
            self.short_name = f"short_{sym}"
            self.tracked_index = "000300"
            self.portfolio_type = kind

    fake_on = [FakeEtf("510050", "on")]
    fake_off = [FakeEtf("161725", "off")]

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def __call__(self, *args, **kwargs):
            return self
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = fake_on + fake_off
            return r

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs", new=AsyncMock(side_effect=[fake_on, fake_off])), \
         patch.object(market_service, "get_realtime_batch", new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session", return_value=FakeSession()):
        print(f"DEBUG before await: model_service._call = {market_service._call.__name__}", file=__import__('sys').stderr)
        await market_service.get_portfolio_realtime()  # 默认 all
    assert captured["count"] >= 1
