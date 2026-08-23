import asyncio
import json
import threading
import time
from typing import Any, Optional

from ..config import settings


class MemoryCache:
    """进程内 TTL 缓存（L1），无外部依赖，始终可用。"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        now = time.time()
        async with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            ts, value = item
            if ts < now:
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self._lock:
            self._store[key] = (time.time() + ttl, value)

    async def mget(self, keys: list[str]) -> list[Optional[Any]]:
        """批量读取，单次锁获取，避免 mget 退化成 N 次独立 lock acquire。"""
        now = time.time()
        async with self._lock:
            results: list = []
            for k in keys:
                item = self._store.get(k)
                if not item:
                    results.append(None)
                else:
                    ts, value = item
                    if ts < now:
                        self._store.pop(k, None)
                        results.append(None)
                    else:
                        results.append(value)
            return results

    async def mset(self, mapping: dict[str, Any], ttl: int) -> None:
        async with self._lock:
            expire = time.time() + ttl
            for k, v in mapping.items():
                self._store[k] = (expire, v)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


memory_cache = MemoryCache()


class RedisCache:
    """Redis 缓存（L2），跨进程共享；不可用时自动降级。"""

    def __init__(self) -> None:
        self._client = None
        self._available = False

    async def init(self) -> None:
        """FIX-03: 初始化 Redis 客户端；若已连接则跳过。"""
        if self.available:
            return
        try:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(  # type: ignore[assignment]
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # 仅当真实连通才标记可用，避免不可用 Redis 拖慢每个缓存调用
            await asyncio.wait_for(self._client.ping(), timeout=2)  # type: ignore[attr-defined]
            self._available = True
        except Exception:
            self._available = False
            self._client = None

    @property
    def available(self) -> bool:
        return self._available and self._client is not None

    async def get(self, key: str) -> Optional[Any]:
        if not self.available:
            return None
        try:
            raw = await self._client.get(key)  # type: ignore[attr-defined]
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if not self.available:
            return
        try:
            await self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)  # type: ignore[attr-defined]
        except Exception:
            pass

    async def mget(self, keys: list[str]) -> list[Optional[Any]]:
        if not self.available or not keys:
            return [None] * len(keys)
        try:
            raws = await self._client.mget(keys)  # type: ignore[attr-defined]
            return [json.loads(r) if r else None for r in raws]
        except Exception:
            return [None] * len(keys)

    async def mset(self, mapping: dict[str, Any], ttl: int) -> None:
        if not self.available or not mapping:
            return
        try:
            async with self._client.pipeline() as pipe:  # type: ignore[attr-defined]
                for k, v in mapping.items():
                    pipe.set(k, json.dumps(v, ensure_ascii=False), ex=ttl)
                await pipe.execute()
        except Exception:
            pass


redis_cache = RedisCache()


async def cache_get(key: str) -> Optional[Any]:
    """先查 Redis，未命中查内存，再回源。"""
    val = await redis_cache.get(key)
    if val is not None:
        return val
    return await memory_cache.get(key)


async def cache_mget(keys: list[str]) -> list[Optional[Any]]:
    if not keys:
        return []
    vals = await redis_cache.mget(keys)
    for i, v in enumerate(vals):
        if v is None:
            vals[i] = await memory_cache.get(keys[i])
    return vals


async def cache_set(key: str, value: Any, ttl: int) -> None:
    await redis_cache.set(key, value, ttl)
    await memory_cache.set(key, value, ttl)


async def cache_mset(mapping: dict[str, Any], ttl: int) -> None:
    await redis_cache.mset(mapping, ttl)
    await memory_cache.mset(mapping, ttl)


# ── 同步缓存层（供同步的 fetcher 层使用） ─────────────────────


class SyncMemoryCache:
    """同步版 MemoryCache，底层与 ``memory_cache`` 共享同一进程空间。

    Fetcher 层为同步函数，无法直接使用 async 的 ``memory_cache.get/set``，
    此包装器提供等效的线程安全同步接口，行为一致。
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._store.get(key)
        if not item:
            return None
        ts, value = item
        if ts < time.time():
            with self._lock:
                self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._store[key] = (time.time() + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


sync_memory_cache = SyncMemoryCache()


def cached(
    key: str,
    producer,
    ttl_key: str | None = None,
    ttl: int | None = None,
    fail_ttl: int | None = None,
) -> Any:
    """统一同步缓存包装（round11 P1-1，收敛 4 处复制粘贴的 _cached）。

    - ttl_key: 从 CACHE_TTL 查表取 TTL（优先于 ttl 参数）
    - ttl: 直接指定 TTL（ttl_key 为 None 时使用；默认 120）
    - fail_ttl: 非 None 时启用「失败缓存」模式（macro_fetcher R4-26：
      producer 异常写失败缓存返回 None，避免反复触发慢源；读取时解包
      {"data": ...}）。None 时 producer 异常直接上抛（news/sector 语义）。
    """
    from ..core.ttl import CACHE_TTL

    _ttl = ttl if ttl is not None else CACHE_TTL.get(ttl_key or "", 120)
    hit = sync_memory_cache.get(key)
    if hit is not None:
        return hit.get("data") if fail_ttl is not None else hit
    try:
        data = producer()
    except Exception:
        if fail_ttl is not None:
            sync_memory_cache.set(key, {"data": None}, fail_ttl)
            return None
        raise
    sync_memory_cache.set(key, {"data": data} if fail_ttl is not None else data, _ttl)
    return data
