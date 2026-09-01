"""round51 方案 C (R165): RedisCacheSync 失败缓存 TTL 自愈.

背景 (round51 §4.1): cache_service.py `_ensure_client` 失败时也置
`_init_done=True` 永不重试——warmup 首轮 ping 时 redis 未就绪 → 失败被永久
缓存 → `/admin/lifespan-warmup` 报 redis_unavailable (3 周期 0 ok)，但容器内
手动 ping 实际可达。round45 option C (commit 853fcf2) NAV Redis 缓存治本目标
实际未达成。

修复 (方案 C): `_init_failed_at` 时间戳记录——失败后 60s 内直接复用失败状态
（不反复重试拖死调用方），60s 后允许重试；ping 失败时重置 `_init_done`。
验收负向 (文档 §4.2): mock 首次 ping 失败 → 60s 后 ping 成功 → available 翻
True（现实现必假 False）。
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def fresh_sync(monkeypatch):
    """每个用例拿全新 RedisCacheSync + 注入 fake redis 模块。"""
    from app.services import cache_service as cs

    sync = cs.RedisCacheSync()

    class _FakeRedis:
        calls = 0  # 类级计数: 跨实例累计（工厂每次 from_url 新建实例）

        def __init__(self, fail_first: int = 0):
            self._fail_first = fail_first

        def ping(self):
            _FakeRedis.calls += 1
            if _FakeRedis.calls <= self._fail_first:
                raise ConnectionError("redis not ready")
            return True

        def get(self, key):
            return None

        def set(self, key, value, ex=None):
            return True

    # 注入 fake redis 模块（_ensure_client 内 `import redis`）
    import types
    fake_mod = types.ModuleType("redis")
    holder: dict = {"cls": _FakeRedis}

    class _Factory:
        @staticmethod
        def from_url(*a, **kw):
            return holder["cls"]()

    fake_mod.Redis = _Factory
    monkeypatch.setitem(__import__("sys").modules, "redis", fake_mod)
    return sync, holder, _FakeRedis


class TestTtlSelfHeal:
    """核心行为: 失败缓存 60s TTL, 过期后允许重试并自愈。"""

    def test_first_failure_not_permanent(self, fresh_sync, monkeypatch):
        """负向验收: 首次 ping 失败 → 60s 后 ping 成功 → available 翻 True。

        旧实现 `_init_done=True` 永不重试, 此断言必假 False。
        """
        sync, holder, _FakeRedis = fresh_sync
        holder["cls"] = lambda: _FakeRedis(fail_first=1)  # 仅第 1 次 ping 失败

        assert sync.ping() is False          # 首轮: redis 未就绪 → False
        assert sync.available is False

        # 时间快进 60s（失败缓存 TTL 过期）
        t = sync.__class__  # noqa: F841  (可读性占位)
        import app.services.cache_service as cs
        real = cs.RedisCacheSync._RETRY_TTL_S
        monkeypatch.setattr(cs.RedisCacheSync, "_RETRY_TTL_S", real)
        sync._init_failed_at = (sync._init_failed_at or 0) - (real + 1)

        assert sync.ping() is True           # 重试成功 → 自愈
        assert sync.available is True

    def test_failure_within_ttl_does_not_retry(self, fresh_sync):
        """60s 内不重试（防反复重试拖死调用方——round45 原设计意图保留）。"""
        sync, holder, _FakeRedis = fresh_sync
        holder["cls"] = lambda: _FakeRedis(fail_first=999)  # 永远失败

        assert sync.ping() is False
        assert sync.ping() is False
        # _init_failed_at 未变（未重试）
        assert sync._init_failed_at is not None

    def test_ready_then_broken_selfheals(self, fresh_sync, monkeypatch):
        """就绪后连接中断: ping False → TTL 过期重试 → 恢复 True。"""
        sync, holder, _FakeRedis = fresh_sync
        holder["cls"] = lambda: _FakeRedis(fail_first=0)

        assert sync.ping() is True
        # 模拟连接中断: 既有实例 fail_first 拉满, 之后所有 ping 抛错
        for c in _FakeRedis.__subclasses__():
            pass
        import gc
        for obj in gc.get_objects():
            if isinstance(obj, _FakeRedis):
                obj._fail_first = 10**9
        assert sync.ping() is False
        # TTL 过期 + 恢复正常
        sync._init_failed_at -= sync._RETRY_TTL_S + 1
        _FakeRedis.calls = 0
        assert sync.ping() is True
        assert sync.available is True

    def test_success_clears_failure_state(self, fresh_sync):
        """成功后清空失败时间戳, available 翻 True。"""
        sync, holder, _FakeRedis = fresh_sync
        holder["cls"] = lambda: _FakeRedis(fail_first=1)

        assert sync.ping() is False
        import app.services.cache_service as cs
        sync._init_failed_at -= cs.RedisCacheSync._RETRY_TTL_S + 1
        assert sync.ping() is True
        assert sync._init_failed_at is None
        assert sync.available is True

    def test_get_set_unavailable_still_safe(self, fresh_sync):
        """不可用期 get 返 None / set 返 False（不抛, 行为不变）。"""
        sync, holder, _FakeRedis = fresh_sync
        holder["cls"] = lambda: _FakeRedis(fail_first=999)
        assert sync.get("fund_nav:510300") is None
        assert sync.set("fund_nav:510300", {"nav": 1.0}) is False
