from __future__ import annotations
"""
round36 §8-A: 设计管线重计算段 run_sync 下放——循环响应性负向测试。

D1 探针证据（scripts/probe_design_pipeline_results.json）：相关性阶段是设计管线
唯一显著循环阻塞段（健康日 2.67s×3；降级日内部 5s 超时网络拉取可放大到分钟级），
_kline_change_pct 为同模式兜底路径。修复 = 该两段经 run_sync_long 下放长任务
线程池，事件循环保持响应。

负向断言口径（旧实现——循环上直跑——下必红）：
  1. 接线检测：generate_enhanced_design 必须经 sd.run_sync_long 执行重段；
  2. 响应性：慢相关性计算（0.6s 同步 sleep）期间，并发心跳任务的最大间隔
     必须 <0.35s（旧实现下心跳被冻结 ≈0.6s）。
"""

import time
from unittest.mock import patch

import pytest


def _cand(layer: str, sym: str, name: str) -> dict:
    return {"symbol": sym, "name": name, "layer": layer,
            "tracked_index": f"idx_{sym}", "industry": "测试",
            "asset_type": "A"}


def _factor_matrix(syms: list[str]) -> dict:
    return {
        s: {"technical": 0.6, "momentum": 0.4, "valuation": 0.1,
            "sentiment": 0.2, "etf_quality": 0.3}
        for s in syms
    }


class _HubPatches:
    """hermetic hub 桩：非空池 + 非空因子矩阵 + 全部网络口短路。"""

    def __init__(self, syms_by_layer: dict[str, list[str]]):
        self._syms = syms_by_layer

    def __enter__(self):
        import app.services.market_data_hub as hub_mod

        pool = {layer: [_cand(layer, s, f"ETF{s}") for s in syms]
                for layer, syms in self._syms.items()}
        all_syms = [s for syms in self._syms.values() for s in syms]

        async def _noop_refresh(*a, **k):
            return None

        p = [
            patch.object(hub_mod.market_data_hub, "refresh", side_effect=_noop_refresh),
            patch.object(hub_mod.market_data_hub, "get_pool",
                         side_effect=lambda layer=None: pool if layer is None else pool.get(layer, [])),
            patch.object(hub_mod.market_data_hub, "get_factor_matrix",
                         return_value=_factor_matrix(all_syms)),
            patch.object(hub_mod.market_data_hub, "get_market_regime",
                         return_value="range_bound"),
            patch.object(hub_mod.market_data_hub, "get_market_sentiment",
                         return_value={"sentiment_index": 50}),
            patch.object(hub_mod.market_data_hub, "get_index_realtime", return_value=[]),
            patch.object(hub_mod.market_data_hub, "get_sector_momentum", return_value=[]),
            # S6 注入层：pool 直供 change_pct/price → 短路 K 线/快照兜底（无网络）
            patch.object(hub_mod.market_data_hub, "get_by_code",
                         side_effect=lambda code: {"change_pct": 0.5, "price": 1.0}),
            # 市场上下文整体桩（避开全球指数 15s 兜底路径）
            patch("app.services.strategy_design._build_market_context",
                  new=_fake_ctx),
        ]
        for x in p:
            x.start()
        self._p = p
        return self

    def __exit__(self, *exc):
        for x in self._p:
            x.stop()


async def _fake_ctx(hub):
    return {}


def _design_patches():
    """进入引擎路径的最小候选集（core+satellite 各 2 只，防全现金）。"""
    return _HubPatches({
        "core": ["510300", "510500"],
        "satellite": ["512100", "512760"],
        "defense": ["518880"],
    })


async def _run_design() -> dict:
    from app.services.strategy_design import generate_enhanced_design

    with _design_patches():
        return await generate_enhanced_design(capital=100000)


# ── 1. 接线检测：重段必须经 run_sync_long 下放 ──────────────────────


@pytest.mark.asyncio
async def test_corr_stage_offloaded_via_run_sync_long():
    """负向断言核心：旧实现（循环直跑相关性段）下 recorder 不被调用 → 必红。"""
    import app.services.strategy_design as sd

    calls: list[str] = []
    real_run_sync_long = sd.run_sync_long

    async def _recorder(fn, *a, **k):
        calls.append(getattr(fn, "__name__", repr(fn)))
        return await real_run_sync_long(fn, *a, **k)

    with patch.object(sd, "run_sync_long", side_effect=_recorder):
        result = await _run_design()

    assert len(result.get("strategies", [])) == 3
    assert calls, (
        "设计管线未将重计算段经 run_sync_long 下放——事件循环仍会被阻塞"
    )


# ── 2. 循环响应性：慢相关性段期间心跳不得冻结 ────────────────────────


@pytest.mark.asyncio
async def test_loop_stays_responsive_during_slow_correlation_stage():
    """慢相关性（0.6s 同步 sleep）期间心跳最大间隔 <0.35s。

    旧实现：_correlation_medians_for 在循环上直跑 → 心跳冻结 ≈0.6s → 本断言红。
    新实现：下放线程池 → 心跳间隔 ≈ tick 周期，保持 <0.35s。
    """
    import asyncio

    import app.services.strategy_design as sd

    real_medians = sd._correlation_medians_for

    def _slow_medians(allocs, candidates):
        time.sleep(0.6)  # 模拟降级日内部 5s 超时网络的循环占用（缩尺）
        return {}

    gaps: list[float] = []

    async def _heartbeat(stop: asyncio.Event):
        loop = asyncio.get_running_loop()
        last = loop.time()
        while not stop.is_set():
            await asyncio.sleep(0.02)
            now = loop.time()
            gaps.append(now - last)
            last = now

    with patch.object(sd, "_correlation_medians_for", side_effect=_slow_medians), \
         patch.object(sd, "_correlation_matrix_for", side_effect=lambda a, c: {}):
        stop = asyncio.Event()
        hb = asyncio.ensure_future(_heartbeat(stop))
        try:
            result = await _run_design()
        finally:
            stop.set()
            await hb

    assert len(result.get("strategies", [])) == 3
    assert gaps, "心跳任务未运行"
    max_gap = max(gaps)
    assert max_gap < 0.35, (
        f"事件循环在慢相关性段被冻结：最大心跳间隔 {max_gap:.3f}s ≥ 0.35s "
        f"（重计算段未下放线程池）"
    )


# ── 3. §8-A2: 共享 SSL 上下文（py-spy 现行取证：每客户端重建阻塞循环）──


def test_shared_ssl_context_cached():
    """负向断言：_shared_ssl_context 必须返回同一对象（旧实现无此函数必红）。

    py-spy 实录（2026-08-25）：llm_complete_with_system → httpx.AsyncClient()
    → ssl.create_default_context 在主线程 active 帧——每调用每候选重建。
    收敛为进程级单例后，httpx verify= 直接复用，循环零重建。
    """
    import app.analysis.llm.client as llm_client

    ctx1 = llm_client._shared_ssl_context()
    ctx2 = llm_client._shared_ssl_context()
    assert ctx1 is ctx2, "SSL 上下文必须进程级缓存（每次新建会阻塞事件循环）"
    import ssl as _ssl

    assert isinstance(ctx1, _ssl.SSLContext)


# ── 4. §8-A3: 板块成分股拉取下放（py-spy 冻结窗实测 future.result() 阻塞
#    循环 64-66s/板块——_build_market_context 直呼同步 get_sector_stocks）──


@pytest.mark.asyncio
async def test_loop_stays_responsive_during_slow_sector_stocks():
    """慢板块成分股（0.6s 同步 sleep）期间心跳最大间隔 <0.35s。

    旧实现：_build_market_context 在循环上直呼 get_sector_stocks →
    future.result() 冻结 ≈0.6s×板块数（降级日实测 64s+）→ 本断言红。
    """
    import asyncio

    import app.services.market_data_hub as hub_mod

    real_gss = hub_mod.market_data_hub.get_sector_stocks

    def _slow_gss(code):
        time.sleep(0.6)
        return []

    gaps: list[float] = []

    async def _heartbeat(stop: asyncio.Event):
        loop = asyncio.get_running_loop()
        last = loop.time()
        while not stop.is_set():
            await asyncio.sleep(0.02)
            now = loop.time()
            gaps.append(now - last)
            last = now

    with _design_patches():
        # 触发 benchmark_stocks 分支：需要非空 sector_momentum（top_sectors ≥1）
        p_momentum = patch.object(
            hub_mod.market_data_hub, "get_sector_momentum",
            return_value=[{"sector_code": "BK1", "sector_name": "测试板块",
                           "change_pct": 3.0}],
        )
        p_stocks = patch.object(hub_mod.market_data_hub, "get_sector_stocks",
                                side_effect=_slow_gss)
        p_momentum.start()
        p_stocks.start()
        stop = asyncio.Event()
        hb = asyncio.ensure_future(_heartbeat(stop))
        try:
            result = await _run_design()
        finally:
            stop.set()
            await hb
            p_momentum.stop()
            p_stocks.stop()

    assert len(result.get("strategies", [])) == 3
    assert gaps, "心跳任务未运行"
    max_gap = max(gaps)
    assert max_gap < 0.35, (
        f"事件循环在慢板块成分股段被冻结：最大心跳间隔 {max_gap:.3f}s ≥ 0.35s"
    )
