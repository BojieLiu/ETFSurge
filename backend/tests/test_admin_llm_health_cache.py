"""B6 收尾 / round36 §9 残余项：/admin/llm/health 60s TTL 缓存。

背景（四路仪器取证，2026-08-25）：供应商全死日单次探针持连 9-19s，
e2e 尾部连环调用形成长持连请求簇 → 内核 backlog 瞬时溢出 → WinError 10061
连发（看门狗零转储、哨兵零卡顿、探针窗口零拒连——拒连全部落在无监控尾部）。
缓存语义见 api-contracts/admin/llm-health.md 增补段。
"""
import pytest


@pytest.mark.asyncio
async def test_llm_health_cache_ttl_and_refresh(monkeypatch):
    """负向断言：60s 内重复调用必须命中缓存（旧实现每次真探针必红）；
    refresh=true 绕过缓存；过期后自动重探。"""
    import app.analysis.llm as llm_pkg
    from app.routers.admin import get_llm_health

    # 隔离：清掉函数属性缓存态
    for attr in ("_cache", "_lock"):
        if hasattr(get_llm_health, attr):
            delattr(get_llm_health, attr)

    calls = {"n": 0}

    async def fake_probe(timeout: float = 15.0) -> dict:
        calls["n"] += 1
        return {"status": "ok", "checked_at": 1756100000.0 + calls["n"],
                "has_api_key": True, "providers": []}

    monkeypatch.setattr(llm_pkg, "llm_health_check", fake_probe)

    r1 = await get_llm_health(timeout=15.0, refresh=False)
    r2 = await get_llm_health(timeout=15.0, refresh=False)
    assert calls["n"] == 1, f"60s 内重复调用必须命中缓存（实际探测 {calls['n']} 次）"
    assert r2 is r1, "命中缓存应返回同一结果对象"

    r3 = await get_llm_health(timeout=15.0, refresh=True)
    assert calls["n"] == 2, "refresh=true 必须绕过缓存强制实时探测"
    assert r3["checked_at"] > r1["checked_at"]

    # TTL 过期 → 下次调用重新探测
    get_llm_health._cache["ts"] -= 61
    r4 = await get_llm_health(timeout=15.0, refresh=False)
    assert calls["n"] == 3, "过期后必须重新探测"
    assert r4 is not r2


@pytest.mark.asyncio
async def test_llm_health_concurrent_miss_single_probe():
    """并发 miss 双重检查锁：N 个等待者只触发一次真探针（同 factor-health）。"""
    import asyncio

    import app.analysis.llm as llm_pkg
    from app.routers.admin import get_llm_health

    for attr in ("_cache", "_lock"):
        if hasattr(get_llm_health, attr):
            delattr(get_llm_health, attr)

    calls = {"n": 0}

    async def slow_probe(timeout: float = 15.0) -> dict:
        calls["n"] += 1
        await asyncio.sleep(0.05)  # 模拟持连探测窗口
        return {"status": "degraded", "checked_at": 1.0, "has_api_key": True,
                "providers": []}

    monkeypatch_freeze = slow_probe
    import app.routers.admin as admin_mod

    orig = admin_mod

    async def runner():
        return await get_llm_health(timeout=15.0, refresh=False)

    # 直接替换包内符号（函数体内延迟导入解析到该属性）
    llm_pkg.llm_health_check = slow_probe
    try:
        results = await asyncio.gather(*(runner() for _ in range(8)))
    finally:
        # 还原为原实现引用，避免污染其它用例
        from importlib import reload

        reload(llm_pkg)

    assert calls["n"] == 1, f"8 个并发 miss 只应触发一次真探针（实际 {calls['n']}）"
    assert all(r["status"] == "degraded" for r in results)
