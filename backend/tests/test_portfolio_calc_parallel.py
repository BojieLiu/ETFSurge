# -*- coding: utf-8 -*-
"""F2-1: 组合计算并行 + 15s 行情缓存（calculate < 2s 验收的工程基础）。

- HK/US 多只标的分批拉取改为 asyncio.gather 并行（此前 for 循环串行是 8.2s 主因之一）。
- _build_price_map_async 增加 15s 模块级缓存（与 portfolio:realtime TTL 一致）。
"""
import asyncio
import time

import pytest

from app.services import portfolio_service as ps


@pytest.fixture(autouse=True)
def _clear_price_cache():
    ps._PRICE_MAP_CACHE.clear()
    yield
    ps._PRICE_MAP_CACHE.clear()


class _E:
    def __init__(self, symbol, asset_type="A", tracked_index=None):
        self.symbol = symbol
        self.name = f"ETF-{symbol}"
        self.short_name = symbol
        self.asset_type = asset_type
        self.tracked_index = tracked_index
        self.target_weight = 0.5
        self.portfolio_type = "on_exchange"


def _hk_etf(sym):
    return _E(sym, asset_type="HK")


# ── 1. HK/US 多只并行拉取 ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_hk_batch_parallel(monkeypatch):
    """3 只港股并行：总耗时 ≈ 单只耗时（而非 3 倍）。"""
    calls = []

    def fake_get_hk_realtime(symbol):
        time.sleep(0.25)  # 每只 250ms（线程池内真实阻塞）
        calls.append(symbol)
        return [{"price": 100.0, "change_pct": 1.0}]

    monkeypatch.setattr(ps.market_data_hub, "get_hk_stock_realtime", fake_get_hk_realtime)
    monkeypatch.setattr(ps.market_data_hub, "get_a_stock_batch", lambda symbols: [])
    monkeypatch.setattr(ps.market_data_hub, "get_us_etf_realtime", lambda s: None)
    monkeypatch.setattr(ps.market_data_hub, "get_index_realtime", lambda: [])
    monkeypatch.setattr(ps.market_data_hub, "get_fund_nav", lambda s: None)

    etfs = [_hk_etf("00700"), _hk_etf("09988"), _hk_etf("02800")]
    start = time.monotonic()
    m = await ps.build_price_map(etfs)
    elapsed = time.monotonic() - start

    assert elapsed < 0.8, f"HK 3 只应并行（<0.8s），实际 {elapsed:.2f}s"
    assert set(calls) == {"00700", "09988", "02800"}
    assert m["00700"] == (100.0, 1.0)


# ── 2. 15s 行情缓存 ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_price_map_15s_cache(monkeypatch):
    """15s 内第二次调用不重复拉行情（mock 计数验证）。"""
    count = {"n": 0}

    def fake_get_a_stock_batch(symbols):
        count["n"] += 1
        return [{"symbol": "510300", "price": 4.0, "change_pct": 1.5}]

    monkeypatch.setattr(ps.market_data_hub, "get_a_stock_batch", fake_get_a_stock_batch)
    monkeypatch.setattr(ps.market_data_hub, "get_hk_stock_realtime", lambda s: None)
    monkeypatch.setattr(ps.market_data_hub, "get_us_etf_realtime", lambda s: None)
    monkeypatch.setattr(ps.market_data_hub, "get_index_realtime", lambda: [])
    monkeypatch.setattr(ps.market_data_hub, "get_fund_nav", lambda s: None)

    etfs = [_E("510300")]
    m1 = await ps.build_price_map(etfs)
    m2 = await ps.build_price_map(etfs)
    assert count["n"] == 1, "第二次调用应命中 15s 缓存"
    assert m1 == m2


# ── 3. calculate_allocation 走缓存（组合计算加速） ────────────────────────
@pytest.mark.asyncio
async def test_calculate_allocation_cached(monkeypatch):
    """calculate_allocation 两次调用，第二次命中行情缓存（fetch 只发生一次）。"""
    count = {"n": 0}

    def fake_get_a_stock_batch(symbols):
        count["n"] += 1
        return [{"symbol": "510300", "price": 4.0, "change_pct": 1.5}]

    monkeypatch.setattr(ps.market_data_hub, "get_a_stock_batch", fake_get_a_stock_batch)
    monkeypatch.setattr(ps.market_data_hub, "get_hk_stock_realtime", lambda s: None)
    monkeypatch.setattr(ps.market_data_hub, "get_us_etf_realtime", lambda s: None)
    monkeypatch.setattr(ps.market_data_hub, "get_index_realtime", lambda: [])
    monkeypatch.setattr(ps.market_data_hub, "get_fund_nav", lambda s: None)
    monkeypatch.setattr(ps.market_data_hub, "get_fundamentals", lambda s, timeout=8: {})

    etfs = [_E("510300")]
    r1 = await ps.calculate_allocation(total_capital=100000, etfs=etfs)
    r2 = await ps.calculate_allocation(total_capital=100000, etfs=etfs)
    assert count["n"] == 1
    assert r1["allocations"][0]["current_price"] == 4.0
    assert r2["allocations"][0]["current_price"] == 4.0
