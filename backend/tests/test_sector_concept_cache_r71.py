# -*- coding: utf-8 -*-
"""round29 R71: sectors/concept 补充分支入缓存 + TTL 1h + 后台 THS 同步走 long 池。

根因（§14.1 R71 / Round 13 归因拆分）：
  ① `/sectors/concept` 热路径 = `fetch_concept_sectors`——主源已 60s 缓存，但补充分支
     `_ak_concept_sectors_v2()` 在 `cached` 外每请求必跑 → 热态 17s；
  ② 预热 45.7s THS 热点来自 `_background_indices_meta_sync`（默认 to_thread 池）。

修复：
  ① v2 补充分支入缓存（1h TTL）；主源 TTL 60s→1h；
  ② THS 同步 4 个 fetch 改 run_sync_long（long 池）。

无网络：akshare / v2 全部 monkeypatch。
"""
import asyncio

import pytest

from app.services.cache_service import sync_memory_cache


def test_r71_supplement_v2_is_cached(monkeypatch):
    """补充分支只跑一次——第二次请求命中缓存，不再重复拉 v2（热路径 17s 消除）。"""
    from app.fetchers import sector_fetcher as sf

    calls = {"n": 0}

    def _v2():
        calls["n"] += 1
        return [{"sector_code": "BK9999", "sector_name": "测试概念"}]

    monkeypatch.setattr(sf, "_ak_concept_sectors_v2", _v2)
    # 主源返回空 → 必然走补充分支
    monkeypatch.setattr(sf, "_try_two", lambda *a, **k: [])
    monkeypatch.setattr(sf, "lv", type("LV", (), {"sector_em": lambda *a, **k: []})())

    sync_memory_cache.clear()
    r1 = sf.fetch_concept_sectors()
    r2 = sf.fetch_concept_sectors()
    assert calls["n"] == 1, f"v2 被重复调用 {calls['n']} 次（应命中缓存）"
    assert any(r.get("sector_code") == "BK9999" for r in r1 + r2)


def test_r71_supplement_failure_not_cached_as_success(monkeypatch):
    """v2 失败（返回 None/空）→ 缓存的是空列表，不反复重跑但也不制造假数据。"""
    from app.fetchers import sector_fetcher as sf

    calls = {"n": 0}

    def _v2():
        calls["n"] += 1
        return []

    monkeypatch.setattr(sf, "_ak_concept_sectors_v2", _v2)
    monkeypatch.setattr(sf, "_try_two", lambda *a, **k: [])
    monkeypatch.setattr(sf, "lv", type("LV", (), {"sector_em": lambda *a, **k: []})())

    sync_memory_cache.clear()
    sf.fetch_concept_sectors()
    sf.fetch_concept_sectors()
    assert calls["n"] == 1, "v2 失败也应缓存（1h 内不反复重跑）"


def test_r71_concept_ttl_now_1h():
    """sector_concept TTL 60s→1h（主源热路径不再 60s 重拉）。"""
    from app.core.ttl import CACHE_TTL

    assert CACHE_TTL.get("sector_concept") == 3600
    assert CACHE_TTL.get("sector_concept_v2") == 3600


def test_r71_ths_sync_uses_long_pool():
    """后台 THS 同步必须走 long 池（run_sync_long），默认池饱和时不被饿死。"""
    import inspect
    from app.fetchers import sync_indices_meta as sim

    for fn_name in ("_fetch_ths_industry_indices", "_fetch_ths_concept_indices"):
        src = inspect.getsource(getattr(sim, fn_name))
        assert "run_sync_long" in src, f"{fn_name} 仍用默认 to_thread（R71 未修）"
        assert "asyncio.to_thread" not in src, f"{fn_name} 仍用 asyncio.to_thread"


@pytest.mark.asyncio
async def test_r71_ths_fetch_runs_on_long_pool(monkeypatch):
    """运行时验证 THS fetch 经 run_sync_long 执行。"""
    from app.fetchers import sync_indices_meta as sim
    import app.core.async_utils as au

    used = {"long": 0}
    _orig = au.run_sync_long

    async def _spy(call, *a, **k):
        used["long"] += 1
        return await _orig(call, *a, **k)

    monkeypatch.setattr(au, "run_sync_long", _spy)
    # 让 akshare 返回最小 df
    import pandas as pd
    df = pd.DataFrame([{"指数代码": "885001", "指数名称": "测试行业"}])

    def _fake_ths(*a, **k):
        return df

    # R177 (round52 §8.4 方案B): 收集源换 stock_board_industry_name_ths——旧
    # stock_board_industry_index_ths 在 akshare 1.18.x 语义已漂移为单板块 K 线。
    # 守卫语义不变：THS fetch 必须经 run_sync_long（long pool）执行。
    monkeypatch.setattr("akshare.stock_board_industry_name_ths", _fake_ths)

    out = await sim._fetch_ths_industry_indices()
    assert used["long"] == 1
    assert out and out[0]["symbol"] == "885001"


# ── R203 (round61): 板块搜索不得返回伪造占位行；两源拆独立预算 ──────────────
def test_concept_sectors_no_placeholder_rows_on_source_failure(monkeypatch):
    """R203 负向：概念源全部失败时，fetch_concept_sectors 不得返回 sector_code 为空的占位行。

    旧实现遍历 POPULAR_CONCEPTS 对未命中项追加占位行（sector_code=""），
    40/40 全是伪造。修复后：源失败返回空列表，不制造假数据。
    """
    from app.fetchers import sector_fetcher as sf
    import app.services.cache_service as cs

    cs.sync_memory_cache.clear()

    # 主源 + 补充分支全部失败
    monkeypatch.setattr(sf, "_try_two", lambda *a, **k: [])
    monkeypatch.setattr(sf, "_ak_concept_sectors_v2", lambda: [])
    monkeypatch.setattr(sf, "lv", type("LV", (), {"sector_em": lambda *a, **k: []})())

    rows = sf.fetch_concept_sectors(limit=600)
    placeholder = [r for r in rows if not r.get("sector_code")]
    assert len(placeholder) == 0, \
        f"源失败时不得返回占位行，实际 {len(placeholder)} 个占位: {[r.get('sector_name') for r in placeholder]}"
    assert rows == [], f"源失败时应返回空列表，实际 {len(rows)} 行"


def test_search_sectors_sources_independent_run_sync(monkeypatch):
    """R203 负向：_search_sectors 将 industry/concept 两源拆为独立 run_sync，
    避免单源慢（concept 冷 25.9s）拖累另一源（industry 快）。

    旧实现两源共享一个 run_sync(timeout=10)，concept 慢时必超时，
    回落 sectors 表兜底（O30 起无写入者）→ 板块搜索恒 0。
    """
    from app.routers import market as market_router

    call_order = []

    def _fake_industry(limit=80):
        call_order.append("industry")
        return [{"sector_code": "BK0001", "sector_name": "银行", "price": 1.0}]

    def _fake_concept(limit=150):
        call_order.append("concept")
        import time as _t
        _t.sleep(0.05)  # 模拟概念源较慢
        return [{"sector_code": "BK0002", "sector_name": "半导体", "price": 2.0}]

    monkeypatch.setattr("app.fetchers.sector_fetcher.fetch_industry_sectors", _fake_industry)
    monkeypatch.setattr("app.fetchers.sector_fetcher.fetch_concept_sectors", _fake_concept)

    import asyncio
    result = asyncio.run(market_router._search_sectors("银行"))

    # 两源都应被调用（独立预算，慢源不拖累快源）
    assert "industry" in call_order, "industry 源应被调用"
    assert "concept" in call_order, "concept 源应被调用"
    # 搜索到「银行」应命中
    assert any(r["name"] == "银行" for r in result), f"应命中银行板块，实际: {result}"
