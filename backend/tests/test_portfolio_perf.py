"""
U5 (round2-unfixed-fix-plan.md U5): 组合计算性能。

- R1: fundamentals 单标的 3s 快速失败（不占满 8s）；总预算 10s → 5s。
- R2: asyncio.Semaphore(4) 限并发（避免 10 路同打同一数据源触发限流）。
- 验收: 数据源慢时 calculate 在 ~5s 内完成（旧实现 8.2s）。

mock 数据源，无网络。
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import portfolio_service as ps


def _etf(symbol, **kw):
    base = dict(
        symbol=symbol, name=symbol, short_name=symbol, asset_type="A",
        portfolio_type="on_exchange", target_weight=0.1,
        tracked_index=None, avg_cost=None, shares_held=None,
        first_buy_date=None, last_trade_date=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _ten_etfs():
    return [_etf(f"51030{i}") for i in range(1, 11)]


@pytest.mark.asyncio
async def test_slow_fundamentals_fast_fail():
    """U5 R1: 数据源慢（10s）→ 单标的 3s 快速失败，calculate 在 5.5s 内完成。"""
    ps._FUNDAMENTALS_CACHE.clear()
    etfs = _ten_etfs()

    def _slow(*args, **kwargs):
        time.sleep(10)
        return {}

    with patch("app.services.market_data_hub.market_data_hub.get_fundamentals",
               new=_slow), \
         patch("app.services.market_data_hub.market_data_hub.get_a_stock_batch",
               new=AsyncMock(return_value=[])), \
         patch("app.services.market_data_hub.market_data_hub.get_fund_nav",
               new=AsyncMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_us_etf_realtime",
               new=AsyncMock(return_value=None)):
        t0 = time.monotonic()
        result = await ps.calculate_allocation(etfs=etfs, total_capital=500000)
        elapsed = time.monotonic() - t0

    assert elapsed < 5.5, f"慢数据源下 calculate 应快速失败（3s/标的），实测 {elapsed:.1f}s"
    assert result["allocations"], "分配结果不应为空"


@pytest.mark.asyncio
async def test_fundamentals_semaphore_concurrency():
    """U5 R2: fundamentals 并发峰值 ≤4（Semaphore 生效）。"""
    ps._FUNDAMENTALS_CACHE.clear()
    etfs = _ten_etfs()
    _active = 0
    _peak = 0

    def _tracking(*args, **kwargs):
        nonlocal _active, _peak
        _active += 1
        _peak = max(_peak, _active)
        time.sleep(0.05)
        _active -= 1
        return {"pe": 1.0}

    with patch("app.services.market_data_hub.market_data_hub.get_fundamentals",
               new=_tracking), \
         patch("app.services.market_data_hub.market_data_hub.get_a_stock_batch",
               new=AsyncMock(return_value=[])), \
         patch("app.services.market_data_hub.market_data_hub.get_fund_nav",
               new=AsyncMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_us_etf_realtime",
               new=AsyncMock(return_value=None)):
        await ps.calculate_allocation(etfs=etfs, total_capital=500000)

    assert _peak <= 4, f"fundamentals 并发峰值 {_peak} 超限（Semaphore(4)）"


@pytest.mark.asyncio
async def test_fundamentals_timeout_returns_empty_not_exception():
    """U5 R1: 超时/异常标的返回 {} 而非 Exception（下游 update 不崩溃）。"""
    ps._FUNDAMENTALS_CACHE.clear()
    etfs = _ten_etfs()

    def _slow(*args, **kwargs):
        time.sleep(10)
        return {}

    with patch("app.services.market_data_hub.market_data_hub.get_fundamentals",
               new=_slow), \
         patch("app.services.market_data_hub.market_data_hub.get_a_stock_batch",
               new=AsyncMock(return_value=[])), \
         patch("app.services.market_data_hub.market_data_hub.get_fund_nav",
               new=AsyncMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_us_etf_realtime",
               new=AsyncMock(return_value=None)):
        result = await ps.calculate_allocation(etfs=etfs, total_capital=500000)

    # 超时标的不注入 fundamentals 字段（{} 不 update），但不崩溃
    assert all("pe" not in a for a in result["allocations"])


@pytest.mark.asyncio
async def test_fast_fundamentals_normal_path():
    """U5 回归: 数据源正常时 fundamentals 正常注入。"""
    ps._FUNDAMENTALS_CACHE.clear()
    etfs = _ten_etfs()

    def _fast(*args, **kwargs):
        return {"pe": 12.5, "pb": 1.2}

    with patch("app.services.market_data_hub.market_data_hub.get_fundamentals",
               new=_fast), \
         patch("app.services.market_data_hub.market_data_hub.get_a_stock_batch",
               new=AsyncMock(return_value=[])), \
         patch("app.services.market_data_hub.market_data_hub.get_fund_nav",
               new=AsyncMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_us_etf_realtime",
               new=AsyncMock(return_value=None)):
        result = await ps.calculate_allocation(etfs=etfs, total_capital=500000)

    assert all(a.get("pe") == 12.5 for a in result["allocations"]), \
        "正常路径 fundamentals 应注入"
