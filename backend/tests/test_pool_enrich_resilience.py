"""
P2-1 延伸 (R4-16): 候选池 enrich 并发限制 + 总超时降级。

_enrich_symbol_extra 旧实现对全部 symbol 无限制 gather——NAV/份额数据源慢时
get_fund_nav 6s 超时 × 大量堆积 → POOL SATURATION → 候选池刷新永远失败
（verify_e2e 候选池类检查全 FAIL 的根因之一）。

- Semaphore(8) 限制并发（峰值并发 ≤8，不打满线程池）。
- wait_for 总超时（_ENRICH_TOTAL_TIMEOUT）——数据源慢时降级部分数据，不阻塞刷新。

mock 慢数据源，无网络。
"""

import asyncio

import pytest

from app.services import market_data_hub as mdh
from app.services.market_data_hub import market_data_hub


@pytest.mark.asyncio
async def test_enrich_total_timeout_degrades_partial(monkeypatch):
    """P2-1: 数据源慢（shares 不返回）→ 总超时降级部分数据，不卡死。"""
    market_data_hub._FUND_SHARES_CACHE.clear()
    # 把总超时缩到 0.5s 以便快速测试
    monkeypatch.setattr(market_data_hub, "_ENRICH_TOTAL_TIMEOUT", 0.5)

    async def _slow_history(symbol, asset_type="A", period="daily"):
        await asyncio.sleep(5)  # 慢：永不及时返回
        return []

    import app.fetchers.china_market as cm

    def _slow_shares(symbol):
        import time
        time.sleep(5)  # 慢：占线程
        return {"total_shares": 1e8, "shares_change_20d": 0.03}

    monkeypatch.setattr(market_data_hub, "get_market_history", _slow_history)
    monkeypatch.setattr(cm, "fetch_etf_shares_outstanding", _slow_shares)

    t0 = asyncio.get_event_loop().time()
    out = await market_data_hub._enrich_symbol_extra(
        ["510300", "588000", "512480"],
        {"510300": {"fund_scale": 100}, "588000": {"fund_scale": 50}, "512480": {}},
    )
    elapsed = asyncio.get_event_loop().time() - t0
    # 总超时 0.5s 生效——不无限等待慢数据源
    assert elapsed < 3, f"应受总超时约束，实际耗时 {elapsed:.1f}s"
    # 部分数据：base_extra 仍保留（未被清空）
    assert out["510300"]["fund_scale"] == 100
    assert out["588000"]["fund_scale"] == 50


@pytest.mark.asyncio
async def test_enrich_concurrency_bounded(monkeypatch):
    """P2-1: Semaphore(8) 限制并发——慢数据源下并发峰值 ≤8（不打满线程池）。"""
    market_data_hub._FUND_SHARES_CACHE.clear()
    # 缩短总超时，避免测试过慢
    monkeypatch.setattr(market_data_hub, "_ENRICH_TOTAL_TIMEOUT", 2.0)

    import app.fetchers.china_market as cm

    active = {"n": 0}
    peak = {"n": 0}

    def _slow_shares(symbol):
        import time
        active["n"] += 1
        peak["n"] = max(peak["n"], active["n"])
        time.sleep(0.3)  # 每个占用线程 0.3s
        active["n"] -= 1
        return {"total_shares": 1e8, "shares_change_20d": 0.03}

    async def _no_history(symbol, asset_type="A", period="daily"):
        return []

    monkeypatch.setattr(market_data_hub, "get_market_history", _no_history)
    monkeypatch.setattr(cm, "fetch_etf_shares_outstanding", _slow_shares)

    # 10 只标的 → 若无 Semaphore 限制，并发可达 10
    symbols = [f"51{i:04d}" for i in range(10)]
    out = await market_data_hub._enrich_symbol_extra(
        symbols,
        {s: {} for s in symbols},
    )
    assert peak["n"] <= 8, f"并发峰值 {peak['n']} > 8（Semaphore 未生效）"
