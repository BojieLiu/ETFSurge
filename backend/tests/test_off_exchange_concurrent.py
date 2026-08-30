"""R50: off_exchange fetch_fund_nav 并发 (治本 slow 阶段耗时).

覆盖:
  - get_portfolio_realtime(phase='slow'): off_exchange 走并发 (asyncio.gather)
  - Semaphore(8) 限流: 并发数 <= 8
  - 单只失败不阻塞其他 (best-effort)
  - 串行 vs 并发 耗时对比 (8 只 / 2s 每只: 串行 16s+ vs 并发 ~3s)
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. 并发数 = 8 (Semaphore 限流) ──────────────────────────────


@pytest.mark.asyncio
async def test_off_exchange_concurrency_limited_to_8():
    """N=20 只 off_exchange, 瞬时并发数 <= 8 (Semaphore 限流)."""
    from app.services import market_service

    in_flight = 0
    max_in_flight = 0
    fetch_started = []

    async def slow_fetch_fund_nav(sym, timeout=8):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        fetch_started.append(_time.time())
        await asyncio.sleep(0.2)  # 模拟 200ms 网络
        in_flight -= 1
        return {"nav": 1.0, "daily_change_pct": 0.0, "nav_date": "2026-08-29"}

    import time as _time

    class FakeEtf:
        def __init__(self, sym):
            self.symbol = sym
            self.name = f"name_{sym}"
            self.short_name = f"short_{sym}"
            self.tracked_index = "000300"  # 非 None + 非盘中 → 走 fetch_fund_nav 路径
            self.portfolio_type = "off_exchange"

    # 20 只 off_exchange
    fake_off = [FakeEtf(f"16{i:04d}") for i in range(20)]

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def __call__(self, *args, **kwargs):
            return self
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = fake_off
            return r

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, '__name__', str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        return await slow_fetch_fund_nav(*args, **kwargs)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], fake_off])), \
         patch.object(market_service, "get_realtime_batch", new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session", return_value=FakeSession()):
        await market_service.get_portfolio_realtime(phase="slow")
    # Semaphore(8): 20 只 / 8 并发 = ceil(20/8) = 3 批 → 瞬时并发 <= 8
    assert max_in_flight <= 8, f"Semaphore 限流失败, 实际 peak={max_in_flight}"
    assert max_in_flight >= 5, f"并发度过低 (peak={max_in_flight}), 期望至少 5"


# ── 2. 单只失败不阻塞其他 ─────────────────────────────────


@pytest.mark.asyncio
async def test_off_exchange_single_failure_does_not_block_others():
    """某只 off_exchange 抛异常, 其他正常完成."""
    from app.services import market_service

    success_count = 0
    fail_count = 0

    async def flaky_fetch_fund_nav(sym, timeout=8):
        nonlocal success_count, fail_count
        if sym == "161111":
            fail_count += 1
            raise RuntimeError("simulated source failure for 161111")
        success_count += 1
        return {"nav": 1.0, "daily_change_pct": 0.0, "nav_date": "2026-08-29"}

    class FakeEtf:
        def __init__(self, sym):
            self.symbol = sym
            self.name = f"name_{sym}"
            self.short_name = f"short_{sym}"
            self.tracked_index = "000300"
            self.portfolio_type = "off_exchange"

    fake_off = [FakeEtf("161000"), FakeEtf("161111"), FakeEtf("161222")]

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def __call__(self, *args, **kwargs):
            return self
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = fake_off
            return r

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, '__name__', str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        return await flaky_fetch_fund_nav(*args, **kwargs)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], fake_off])), \
         patch.object(market_service, "get_realtime_batch", new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session", return_value=FakeSession()):
        result = await market_service.get_portfolio_realtime(phase="slow")
    # 2 只成功 + 1 只 fail (但 fail 也走兜底, 仍写入 quotes with last_close)
    assert success_count == 2
    assert fail_count == 1
    # result 包含全部 3 只 (含兜底)
    assert len(result) >= 3


# ── 3. 串行 vs 并发 耗时对比 ──────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_faster_than_serial_simulation():
    """20 只 / 200ms/只: 串行 ~4s, 并发 ~600ms (8 并发)."""
    from app.services import market_service

    async def fake_fetch(sym, timeout=8):
        await asyncio.sleep(0.2)
        return {"nav": 1.0, "daily_change_pct": 0.0, "nav_date": "2026-08-29"}

    class FakeEtf:
        def __init__(self, sym):
            self.symbol = sym
            self.name = f"name_{sym}"
            self.short_name = f"short_{sym}"
            self.tracked_index = "000300"
            self.portfolio_type = "off_exchange"

    fake_off = [FakeEtf(f"16{i:04d}") for i in range(20)]

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def __call__(self, *args, **kwargs):
            return self
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = fake_off
            return r

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, '__name__', str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        return await fake_fetch(*args, **kwargs)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], fake_off])), \
         patch.object(market_service, "get_realtime_batch", new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session", return_value=FakeSession()):
        t0 = time.monotonic()
        await market_service.get_portfolio_realtime(phase="slow")
        elapsed = time.monotonic() - t0
    # 20 只 / 8 并发 = 3 批 × 0.2s = ~0.6s
    # 串行 20 × 0.2s = 4.0s
    # 断言并发显著快于 4s 串行基线
    assert elapsed < 2.0, f"并发失败, 耗时 {elapsed:.2f}s 应 < 2s (串行基线 4s)"
    print(f"\n[R50 性能验证] 20 只 / 200ms 模拟 fetch: {elapsed:.3f}s (串行基线 4.0s)")


# ── 4. source-of-truth 验证: 改回串行会立即失败 ─────────────


def test_source_of_truth_concurrent_off_exchange():
    """源码层面验证: off_exchange 走 asyncio.gather (不是 for 循环 await).

    防后人误改回串行, 立即 break 并发性能承诺.
    """
    from pathlib import Path
    main_py = Path(__file__).resolve().parent.parent / "app" / "services" / "market_service.py"
    text = main_py.read_text(encoding="utf-8", errors="replace")
    import re
    # 必须有 Semaphore(8) + asyncio.gather
    assert "Semaphore(8)" in text or "Semaphore(8)" in text.replace(" ", ""), \
        "off_exchange 应使用 Semaphore(8) 限流"
    assert "asyncio.gather" in text, "off_exchange 应使用 asyncio.gather 并发"
    # 注释提及 R50
    assert "R50" in text or "round50" in text, "应注释 R50 设计依据"
