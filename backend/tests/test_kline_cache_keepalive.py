# -*- coding: utf-8 -*-
"""round29 R68: K 线缓存落盘保活 + last-good 兜底 + long 池。

根因（§14.4.0 / Round 13 精确化）：
  ① `refresh_kline` 仅在 `updated > 0` 时落盘 → 全失败轮次磁盘 mtime 不刷新
     → `_load_kline_cache_sync` 24h TTL 判过期丢弃 → 冷启动循环放大；
  ② fetch 走默认 run_sync 池 → 池饱和时 refresh_kline 被饿死；
  ③ 单只 fetch 失败即丢缓存（无 last-good 保留）。

无网络：fetch_history 全部 monkeypatch。
"""
import os
import time

import pytest

from app.services.market_data_hub import MarketDataHub

_ROWS = [{"date": "2026-08-18", "open": 3.8, "high": 3.9, "low": 3.7, "close": 3.85, "volume": 100}]


@pytest.fixture
def hub(tmp_path):
    h = MarketDataHub()
    h._kline_cache_rows = {}
    h._kline_cache_ts = 0.0
    h._kline_cache_symbols = []
    h._KLINE_CACHE_PERSIST_PATH = str(tmp_path / "kline_cache.json")
    return h


@pytest.mark.asyncio
async def test_r68_persist_refreshes_mtime_even_when_all_fetch_fail(hub, monkeypatch):
    """全失败轮次也必须刷新磁盘 mtime（否则 24h TTL 把可用旧缓存判过期丢弃）。"""
    from app.fetchers import china_market

    hub._kline_cache_rows = {"510300": _ROWS}
    hub._kline_cache_ts = time.time()
    hub._persist_kline_cache_sync()
    path = hub._kline_cache_path()
    assert os.path.isfile(path)
    old_mtime = os.path.getmtime(path)
    os.utime(path, (old_mtime - 7200, old_mtime - 7200))
    stale_mtime = os.path.getmtime(path)

    monkeypatch.setattr(china_market, "fetch_history", lambda *a, **k: [])

    await hub.refresh_kline(["510300"])

    new_mtime = os.path.getmtime(path)
    assert new_mtime > stale_mtime, "全失败轮次未刷新 mtime → 磁盘缓存会被 TTL 判过期"


@pytest.mark.asyncio
async def test_r68_fetch_failure_keeps_last_good_rows(hub, monkeypatch):
    """单只 fetch 失败 → 保留旧缓存（last-good）并标 stale，不得清空。"""
    from app.fetchers import china_market

    hub._kline_cache_rows = {"510300": _ROWS}
    hub._kline_cache_ts = time.time()

    def _boom(*a, **k):
        raise RuntimeError("source down")

    monkeypatch.setattr(china_market, "fetch_history", _boom)

    await hub.refresh_kline(["510300"])

    assert hub.get_kline_rows_any("510300") == _ROWS
    assert hub.is_kline_stale("510300") is True


@pytest.mark.asyncio
async def test_r68_empty_fetch_marks_stale_not_deletes(hub, monkeypatch):
    """fetch 返回空 → 同样保留 last-good + 标 stale。"""
    from app.fetchers import china_market

    hub._kline_cache_rows = {"510300": _ROWS}
    hub._kline_cache_ts = time.time()
    monkeypatch.setattr(china_market, "fetch_history", lambda *a, **k: [])

    await hub.refresh_kline(["510300"])

    assert hub.get_kline_rows_any("510300") == _ROWS
    assert hub.is_kline_stale("510300") is True


@pytest.mark.asyncio
async def test_r68_success_clears_stale_flag(hub, monkeypatch):
    """成功刷新 → stale 标记清除（不得永久标脏）。"""
    from app.fetchers import china_market

    hub.mark_kline_stale("510300", True)
    monkeypatch.setattr(china_market, "fetch_history", lambda *a, **k: _ROWS)

    await hub.refresh_kline(["510300"])

    assert hub.is_kline_stale("510300") is False
    assert hub.get_kline_rows_any("510300") == _ROWS


@pytest.mark.asyncio
async def test_r68_fetch_uses_long_pool(hub, monkeypatch):
    """fetch 必须走 long 池（run_sync_long）——默认池饱和时不被主路径饿死。"""
    from app.fetchers import china_market
    from app.services.hub import _kline as kline_mod

    monkeypatch.setattr(china_market, "fetch_history", lambda *a, **k: _ROWS)

    used = {"long": 0, "default": 0}
    import app.core.async_utils as au
    _orig_long = au.run_sync_long
    _orig = au.run_sync

    async def _spy_long(call, *a, **k):
        used["long"] += 1
        return await _orig_long(call, *a, **k)

    async def _spy(call, *a, **k):
        used["default"] += 1
        return await _orig(call, *a, **k)

    monkeypatch.setattr(au, "run_sync_long", _spy_long)
    monkeypatch.setattr(au, "run_sync", _spy)

    await hub.refresh_kline(["510300", "510500"])

    assert used["long"] == 2, f"refresh_kline 未走 long 池: {used}"
    assert kline_mod is not None  # 模块存在性哨兵


@pytest.mark.asyncio
async def test_r68_no_persist_when_cache_empty(hub, monkeypatch):
    """缓存空（首次全失败）→ 不落盘空文件（不制造假缓存）。"""
    from app.fetchers import china_market

    monkeypatch.setattr(china_market, "fetch_history", lambda *a, **k: [])
    await hub.refresh_kline(["510300"])
    assert not os.path.isfile(hub._kline_cache_path())
