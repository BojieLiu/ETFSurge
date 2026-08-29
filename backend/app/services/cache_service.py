import asyncio
import json
import threading
import time
from typing import Any, Optional

from ..config import settings

# A4②: Redis 不可用降级累计 N 次后触发一次后台重探
_REPROBE_EVERY = 50


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
    """Redis 缓存（L2），跨进程共享；不可用时自动降级。

    round35 A4② (§13.4-A4)：旧实现仅在启动 lifespan 探测一次——若当时
    Redis 宕机则整个进程生命周期内永不重试。现在不可用状态下的每次降级
    都计数，累计达 ``_REPROBE_EVERY`` 触发一次**后台**重探（create_task，
    不阻塞当前调用），恢复连接后自动回到 L2 正常路径。
    """

    def __init__(self) -> None:
        self._client = None
        self._available = False
        self._skip_count = 0
        self._reprobe_scheduled = False

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

    def _schedule_reprobe(self) -> None:
        """不可用降级累计达阈值 → 后台重探一次（非阻塞）。"""
        self._skip_count += 1
        if self._skip_count < _REPROBE_EVERY or self._reprobe_scheduled:
            return
        self._skip_count = 0
        self._reprobe_scheduled = True

        async def _probe():
            try:
                await self.init()
            finally:
                self._reprobe_scheduled = False

        try:
            asyncio.get_running_loop().create_task(_probe())
        except RuntimeError:
            # 无运行中的事件循环（同步上下文调用）——放弃本轮，下次计数再试
            self._reprobe_scheduled = False

    async def get(self, key: str) -> Optional[Any]:
        if not self.available:
            self._schedule_reprobe()
            return None
        try:
            raw = await self._client.get(key)  # type: ignore[attr-defined]
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if not self.available:
            self._schedule_reprobe()
            return
        try:
            await self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)  # type: ignore[attr-defined]
        except Exception:
            pass

    async def mget(self, keys: list[str]) -> list[Optional[Any]]:
        if not keys:
            return []
        if not self.available:
            self._schedule_reprobe()
            return [None] * len(keys)
        try:
            raws = await self._client.mget(keys)  # type: ignore[attr-defined]
            return [json.loads(r) if r else None for r in raws]
        except Exception:
            return [None] * len(keys)

    async def mset(self, mapping: dict[str, Any], ttl: int) -> None:
        if not mapping:
            return
        if not self.available:
            self._schedule_reprobe()
            return
        try:
            async with self._client.pipeline() as pipe:  # type: ignore[attr-defined]
                for k, v in mapping.items():
                    pipe.set(k, json.dumps(v, ensure_ascii=False), ex=ttl)
                await pipe.execute()
        except Exception:
            pass


class RedisCacheSync:
    """同步 Redis 客户端包装 (round45 option C).

    用途: lifespan 1618 任务 _inject_nav 在 async 上下文里调同步 get_fund_nav,
    需要 sync Redis 读以避免 asyncio.run 阻塞. 短超时 + 失败 no-op 降级.

    行为契约:
    - 初始化 lazy (首次 get/set 才连), 不阻塞 import 期
    - 短超时 (connect 2s / op 2s), 失败返 None / 静默 set 失败
    - 与 async redis_cache 共享 URL 但不共享 client (sync redis 用 blocking socket)
    - value 序列化与 async client 一致 (json.dumps ensure_ascii=False)

    不做 (与 async 行为对齐):
    - 不做 mget / mset (lifespan 单 symbol 粒度足够)
    - 不做分布式锁 / pubsub (不在本轮 scope)
    - 不做 health check 周期 (依赖 on-demand ping)
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._available: bool = False
        self._init_lock = threading.Lock()
        self._init_done: bool = False

    def _ensure_client(self) -> None:
        """Lazy 初始化 sync client. 用 lock 防止并发初始化, 已初始化则跳过."""
        if self._init_done:
            return
        with self._init_lock:
            if self._init_done:
                return
            try:
                import redis  # sync client
                self._client = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                # ping 检查连通
                self._client.ping()
                self._available = True
            except Exception:
                self._client = None
                self._available = False
            finally:
                self._init_done = True  # 失败也算 done, 避免反复重试拖死调用方

    @property
    def available(self) -> bool:
        if not self._init_done:
            # 未初始化, 不主动连 (供 is_available 检查用)
            return False
        return self._available and self._client is not None

    def get(self, key: str) -> Any | None:
        """同步读. 命中返 decoded value, miss / 失败返 None.

        注: 失败时仅返 None, 不抛 (caller 走 fetch_fund_nav 降级).
        """
        try:
            self._ensure_client()
            if not self.available:
                return None
            raw = self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int = 86400) -> bool:
        """同步写. 返 True 成功 / False 失败 (含不可用). 失败静默.

        注: 不抛, 防止 caller 在 best-effort 路径上 crash.
        """
        try:
            self._ensure_client()
            if not self.available:
                return False
            payload = json.dumps(value, ensure_ascii=False)
            self._client.set(key, payload, ex=ttl)
            return True
        except Exception:
            return False

    def ping(self) -> bool:
        """健康检查 (用于 lifespan 后台预热任务前置 ping)."""
        try:
            self._ensure_client()
            if not self.available:
                return False
            return bool(self._client.ping())
        except Exception:
            return False


redis_cache = RedisCache()
redis_cache_sync = RedisCacheSync()


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
    """同步版 TTL 缓存（fetcher 层专用），**独立 store**。

    round35 A4① (§13.4-A4) 更正：旧 docstring 声称"与 ``memory_cache``
    共享同一进程空间"——不实。本类拥有自己的 ``_store``，与 async 的
    ``memory_cache`` **互不可见**（同步 fetcher 写入的条目，async 侧读不到，
    反之亦然）。这是有意的边界隔离：fetcher 层为同步函数，无法持有
    asyncio.Lock；两侧各自线程安全，但缓存不互通。
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
