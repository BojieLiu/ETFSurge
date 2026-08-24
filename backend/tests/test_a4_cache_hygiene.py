"""round35 A4 缓存断点收敛（docs/round35-architecture-review.md §13.4-A4）。

覆盖三项：
- A4② Redis 不可用降级累计达阈值 → 后台重探一次（非阻塞）；
  阈值前不重探；重探挂起期间不重复调度；空 keys/mapping 不计数。
- A4① SyncMemoryCache 与 async memory_cache 是**独立 store**（docstring
  说真话的配套行为断言：同步写入 async 读不到，反之亦然）。

A4③ database.py 死代码删除由全量测试兜底（import 失败即红）。
"""

import asyncio
import threading

from app.services import cache_service
from app.services.cache_service import (
    MemoryCache,
    RedisCache,
    SyncMemoryCache,
    memory_cache,
    sync_memory_cache,
)


def _unavailable_redis(monkeypatch) -> RedisCache:
    rc = RedisCache()
    rc._available = False
    rc._client = None
    return rc


async def test_reprobe_fires_only_at_threshold(monkeypatch):
    rc = _unavailable_redis(monkeypatch)
    calls: list[int] = []

    async def fake_init():
        calls.append(1)

    monkeypatch.setattr(rc, "init", fake_init)
    for i in range(cache_service._REPROBE_EVERY - 1):
        await rc.set(f"k{i}", i, 60)
    assert calls == [], "must NOT re-probe before threshold"

    await rc.set("trigger", 1, 60)
    await asyncio.sleep(0)  # 让 create_task 的探测协程跑起来
    assert len(calls) == 1, "threshold-crossing call must schedule exactly one re-probe"


async def test_reprobe_not_duplicated_while_pending(monkeypatch):
    rc = _unavailable_redis(monkeypatch)
    calls: list[int] = []

    async def fake_init():
        await asyncio.sleep(0.05)  # 模拟 ping 耗时，制造挂起窗口
        calls.append(1)

    monkeypatch.setattr(rc, "init", fake_init)
    for _ in range(cache_service._REPROBE_EVERY + 10):  # 阈值后继续降级调用
        await rc.get("k")
        await asyncio.sleep(0)
    await asyncio.sleep(0.1)  # 让挂起的探测协程（0.05s）真正完成
    assert len(calls) == 1, "pending probe must suppress further scheduling"


async def test_empty_keys_and_mapping_do_not_count_as_degradation(monkeypatch):
    rc = _unavailable_redis(monkeypatch)
    monkeypatch.setattr(rc, "init", _async_noop)
    await rc.mget([])
    await rc.mset({}, 60)
    assert rc._skip_count == 0, "empty batch is not a Redis degradation event"


async def _async_noop():
    return None


async def test_sync_and_async_memory_caches_are_isolated():
    """A4① 行为面：两个 store 互不可见（docstring 契约的行为证据）。"""
    assert isinstance(memory_cache, MemoryCache)
    assert isinstance(sync_memory_cache, SyncMemoryCache)
    assert sync_memory_cache._store is not getattr(memory_cache, "_store", None)

    sync_memory_cache.clear()
    key = "a4-isolation-probe"
    sync_memory_cache.set(key, {"v": 1}, ttl=60)
    assert await memory_cache.get(key) is None, (
        "sync write must NOT be visible to the async cache (separate stores)"
    )
    # 反向：async 写，sync 读不到
    await memory_cache.set(f"{key}-rev", {"v": 2}, ttl=60)
    assert sync_memory_cache.get(f"{key}-rev") is None
    sync_memory_cache.clear()


async def test_sync_memory_cache_thread_safety_smoke():
    """并发 set/get 不崩、TTL 过期返回 None（独立 store 自身行为正确）。"""
    cache = SyncMemoryCache()
    errors: list[Exception] = []

    def worker(i: int):
        try:
            for j in range(50):
                cache.set(f"k{i}-{j}", j, ttl=60)
                cache.get(f"k{i}-{j}")
        except Exception as e:  # noqa: BLE001 - 测试收集线程
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    expired = SyncMemoryCache()
    expired._store["old"] = (__import__("time").time() - 1, "stale")
    assert expired.get("old") is None
