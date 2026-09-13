"""F23-3: factor_registry._fetch_market_data gather 整体超时保护。

背景（round6 §17.2 + tests/ROOT_CAUSE.md）：`asyncio.gather(*tasks)` 无整体超时，
单个 mootdx socket 卡死会把线程池耗尽 → asyncio.run 永不返回 → pytest 卡死 ~1 小时。
修复：gather 外包 `asyncio.wait_for(..., timeout=_fetch_history_budget(n))`，
预算 = 单任务 25s × N / 8 并发 + 15s 缓冲（下限 30s）。
"""
import time

import pytest

from app.factors import factor_registry as fr
from app.services.market_data_hub import market_data_hub as hub


def _fake_history_rows(symbol, market="A", period="daily", timeout=20):
    """构造 ≥5 根 K 线（fetch_one 正常路径所需）。"""
    closes = [10.0 + i * 0.1 for i in range(60)]
    rows = [{"close": c, "high": c + 0.05, "low": c - 0.05, "volume": 1000}
            for c in closes]
    rows[-1]["total_mv"] = 5e9
    rows[-1]["float_mv"] = 3e9
    return rows


def _patch_hub_quiet(monkeypatch):
    """mock hub 数据管道（无网络、无 sentiment 注入副作用）。"""
    monkeypatch.setattr(hub, "get_history", lambda symbol, market="A", period="daily": [])
    monkeypatch.setattr(hub, "get_market_sentiment", lambda: {})
    monkeypatch.setattr(hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(hub, "get_fund_nav", lambda sym, **kw: {})
    # round13 §3.1 P2: mock macro 注入（_inject_macro_data）——避免真实 akshare 网络
    monkeypatch.setattr("app.fetchers.macro_fetcher.fetch_macro_snapshot", lambda: None)
    monkeypatch.setattr("app.fetchers.macro_fetcher.fetch_gdp_series", lambda n=8: [])


@pytest.fixture(autouse=True)
def _reset_factor_history_circuit():
    """R188 (round55 §4.2 方案D): 隔离全局 SourceRegistry 熔断。

    factor.history 熔断器是进程级单例，`-n auto` 同 worker 内先行用例
    熔断后会污染本文件用例（KeyError: 'close' 偶发 FAIL，单跑绿）。
    每个用例前后复位，跨用例污染不再发生。
    """
    fr._source_registry.reset_source("factor.history")
    yield
    fr._source_registry.reset_source("factor.history")


def test_fetch_history_budget_bounds():
    """预算下限 30s，并按 25s/8 并发线性增长。"""
    assert fr._fetch_history_budget(1) == 30.0
    assert fr._fetch_history_budget(8) == 40.0
    assert fr._fetch_history_budget(9) == 43.125
    assert fr._fetch_history_budget(16) == 65.0
    assert fr._fetch_history_budget(17) == 68.125


async def test_fetch_market_data_overall_timeout(monkeypatch):
    """run_sync 永久挂起（mootdx socket 卡死模拟）时，整体预算内返回、不卡死、不抛异常。"""
    from app.core import async_utils

    _patch_hub_quiet(monkeypatch)
    calls = {"n": 0}

    async def _stuck(call, *args, timeout=None, **kwargs):
        if call is hub.get_history:
            calls["n"] += 1
            await asyncio_sleep_forever()  # 永不返回 → 触发整体超时
        return call(*args, **kwargs)  # IOPV/NAV 段直接执行（已被 mock，无网络）

    monkeypatch.setattr(async_utils, "run_sync", _stuck)
    # 缩短预算使测试快速完成（生产预算见 test_fetch_history_budget_bounds）
    monkeypatch.setattr(fr, "_fetch_history_budget", lambda n: 0.5)
    # 绕过 K 线缓存，确保走 gather 路径
    monkeypatch.setattr(fr, "_get_cached_kline", lambda symbols: None)

    reg = fr.FactorRegistry()
    t0 = time.time()
    data = await reg._fetch_market_data(["159338", "518880", "510300"])
    elapsed = time.time() - t0

    assert elapsed < 5, f"应在整体预算内返回, 实际 {elapsed:.1f}s"
    assert isinstance(data, dict)
    # 超时降级：无 K 线数据（不抛异常，上游可继续走降级链）
    assert all("close" not in (data.get(s) or {}) for s in ["159338", "518880", "510300"])


async def test_fetch_market_data_success_still_works(monkeypatch):
    """正常数据获取路径不受 wait_for 影响（回归防护）。"""
    from app.core import async_utils

    _patch_hub_quiet(monkeypatch)
    monkeypatch.setattr(hub, "get_history", _fake_history_rows)

    async def _direct(call, *args, timeout=None, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(async_utils, "run_sync", _direct)
    monkeypatch.setattr(fr, "_get_cached_kline", lambda symbols: None)

    reg = fr.FactorRegistry()
    data = await reg._fetch_market_data(["159338"])
    assert "159338" in data
    assert data["159338"]["close"]


async def asyncio_sleep_forever():
    """模块级辅助：永久挂起，便于被 wait_for 取消。"""
    import asyncio
    await asyncio.sleep(3600)


async def test_open_circuit_returns_empty_then_reset_restores(monkeypatch):
    """R188 负向：先强制熔断 factor.history → 成功路径返回空（旧实现必 FAIL）；
    复位（fixture 同款动作）后同一路径恢复正常。

    锁定「熔断跨用例污染」的因果链：空数据来自熔断器开路，非取数逻辑回归。
    """
    from app.core import async_utils

    _patch_hub_quiet(monkeypatch)
    monkeypatch.setattr(hub, "get_history", _fake_history_rows)

    async def _direct(call, *args, timeout=None, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(async_utils, "run_sync", _direct)
    monkeypatch.setattr(fr, "_get_cached_kline", lambda symbols: None)

    reg = fr.FactorRegistry()
    # 强制开路：模拟同 worker 先行用例熔断后的污染态
    fr._source_registry.health("factor.history").record_hard_failure(
        time.time(), error_message="R188 negative probe")
    poisoned = await reg._fetch_market_data(["159338"])
    assert poisoned.get("159338") == {}, \
        f"开路时应返回空数据，实际: {poisoned.get('159338')}"
    # 复位后恢复（旧实现无 fixture 时此断言 FAIL）
    fr._source_registry.reset_source("factor.history")
    data = await reg._fetch_market_data(["159338"])
    assert "159338" in data
    assert data["159338"]["close"]
