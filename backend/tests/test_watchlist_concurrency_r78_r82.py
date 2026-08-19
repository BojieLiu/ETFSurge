# -*- coding: utf-8 -*-
"""round29 R78 / R82: 自选并发治理 + 美股批量窗口。

R78（§14.6.1）：收盘兜底并发 ≤3 + 成功收盘行写 quote 缓存（24h last-good）+
            A 批量 quote TTL 统一 24h + _last_close_fallback 补 change_pct/volume。
R82（§14.6.4）：US 批量窗口 2s→7s + 批量取消后后台线程仍写 last-good +
            finnhub 配额护栏（预算内跳过）。

无网络：_last_close_fallback / cache / _route_us / finnhub 全部 monkeypatch。
"""
import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest


# ---------------- R78: 收盘兜底并发收敛 ----------------

class TestR78CloseFallbackConcurrency:
    @pytest.mark.asyncio
    async def test_close_fallback_concurrency_le_3(self, monkeypatch):
        """22 条自选 → 收盘兜底并发 ≤3（不得 22 路洪泛 Sina）。"""
        from app.routers import market

        items = []
        for i in range(22):
            it = type("W", (), {
                "id": i, "symbol": f"6000{i:02d}", "name": f"标的{i}",
                "asset_type": "A", "notes": None,
                "created_at": None, "updated_at": None,
            })()
            items.append(it)

        inflight = {"n": 0, "max": 0}

        async def _mock_close(sym, at):
            # 入口即计数（在锁/等待之前）——真实并发 = 同时进入的函数数
            inflight["n"] += 1
            inflight["max"] = max(inflight["max"], inflight["n"])
            try:
                await asyncio.sleep(0.01)
            finally:
                inflight["n"] -= 1
            return {"symbol": sym, "price": 3.0, "is_estimated": True, "as_of": "2026-08-18"}

        monkeypatch.setattr("app.services.market_service._last_close_fallback", _mock_close)

        out = await market._watchlist_close_fallback(items)
        assert inflight["max"] <= 3, f"并发 {inflight['max']} > 3（22 路洪泛未收敛）"
        assert len(out) == 22

    @pytest.mark.asyncio
    async def test_close_fallback_writes_quote_cache(self, monkeypatch):
        """成功拉到的收盘行 → 写 quote 缓存（24h last-good），缓存命中不再回源。"""
        from app.routers import market
        from app.services import market_service as ms

        writes = {}
        async def _set(key, val, ttl):
            writes[key] = (val, ttl)
        monkeypatch.setattr("app.services.cache_service.cache_set", _set)

        async def _mock_close(sym, at):
            return {"symbol": sym, "price": 3.5, "is_estimated": True, "as_of": "2026-08-18",
                    "change_pct": 1.2, "volume": 1000}

        monkeypatch.setattr("app.services.market_service._last_close_fallback", _mock_close)

        items = [type("W", (), {"id": 1, "symbol": "510300", "name": "300ETF",
                                "asset_type": "A", "notes": None,
                                "created_at": None, "updated_at": None})()]

        await market._watchlist_close_fallback(items)
        # _watchlist_close_fallback 内部用 market_service.quote_key + cache_set
        key = ms.quote_key("510300", "A")
        assert key in writes, f"收盘行未写 quote 缓存: keys={list(writes)}"
        _val, _ttl = writes[key]
        assert _ttl == 24 * 3600
        assert _val.get("price") == 3.5

    @pytest.mark.asyncio
    async def test_quote_cache_hit_skips_realtime_fetch(self, monkeypatch):
        """quote 缓存命中（price 非 None）→ 不再触发 _last_close_fallback（缓存读取路径）。"""
        from app.routers import market

        calls = {"n": 0}

        async def _mock_close(sym, at):
            calls["n"] += 1
            return None

        monkeypatch.setattr("app.services.market_service._last_close_fallback", _mock_close)

        items = [type("W", (), {"id": 1, "symbol": "510300", "name": "300ETF",
                                "asset_type": "A", "notes": None,
                                "created_at": None, "updated_at": None})()]

        # 预写缓存（close-snapshot 形态——R78 短路条件：estimate_source=last_close）
        from app.services.cache_service import memory_cache
        from app.services import market_service as ms
        await memory_cache.set(ms.quote_key("510300", "A"),
                               {"price": 3.8, "change_pct": 0.5, "volume": 999,
                                "estimate_source": "last_close"}, 3600)

        out = await market._watchlist_close_fallback(items)
        # 无 _last_close_fallback 调用也不写新缓存（旧缓存命中直接读取）
        assert calls["n"] == 0, "缓存命中仍触发了回源"
        rt = out[0].get("realtime") or {}
        assert rt.get("price") == 3.8


class TestR78LastCloseFields:
    @pytest.mark.asyncio
    async def test_last_close_fallback_fills_change_pct_volume(self, monkeypatch):
        """_last_close_fallback 补 change_pct（前收差分）与 volume（末根）。"""
        from app.services import market_service as ms

        rows = [
            {"date": "2026-08-14", "close": 3.0, "volume": 800},
            {"date": "2026-08-17", "close": 3.1, "volume": 900},
            {"date": "2026-08-18", "close": 3.2, "volume": 1000},
        ]

        def _fake_fetch(*a, **k):
            return rows

        monkeypatch.setattr("app.fetchers.china_market.fetch_history", _fake_fetch)
        out = await ms._last_close_fallback("510300", "A")
        assert out is not None
        assert out["price"] == 3.2
        assert out["change_pct"] is not None, "change_pct 应来自前收差分"
        assert abs(out["change_pct"] - round((3.2 - 3.1) / 3.1 * 100, 2)) < 0.01
        assert out["volume"] == 1000


class TestR78QuoteTTL24h:
    @pytest.mark.asyncio
    async def test_a_batch_quote_uses_24h_ttl(self, monkeypatch):
        """get_realtime_batch A 段成功价写 24h last-good（盘后直接可作 stale 兜底）。"""
        from app.services import market_service as ms

        writes = {}
        async def _set(key, val, ttl):
            writes[key] = ttl
        # market_service 模块级 cache_set 绑定——必须 patch 模块名而非 cache_service
        monkeypatch.setattr(ms, "cache_set", _set)
        async def _no_cache(keys):
            return [None] * len(keys)
        monkeypatch.setattr(ms, "cache_mget", _no_cache)

        def _fake_batch(symbols, **k):
            return [{"symbol": s, "price": 3.5, "change_pct": 0.1, "volume": 1} for s in symbols]

        monkeypatch.setattr("app.fetchers.china_market.fetch_a_stock_batch", _fake_batch)

        await ms.get_realtime_batch(["510300", "510500"], "A")
        for key, ttl in writes.items():
            assert ttl == 24 * 3600, f"quote {key} TTL={ttl} ≠ 24h"


# ---------------- R82: 美股批量窗口 + last-good 补写 ----------------

class TestR82BatchWindow:
    def test_us_batch_uses_7s_window(self):
        """US 批量窗口 2s→7s（twelvedata 实测 2-6s 延迟容纳）——源码级断言。"""
        import inspect
        from app.routers import market

        src = inspect.getsource(market._watchlist_enrich_items)
        # US 分组批量调用必须带 timeout=7（`_batch_for(_us_items, "US", timeout=7)`）
        assert 'timeout=7' in src, "US 批量窗口未放宽到 7s（R82 未修）"
        # 无 US 分组（A/HK）保持默认 2s 不回归
        assert '_batch_for(_a_items, "A")' in src and '_batch_for(_hk_items, "HK")' in src

    def test_outer_timeout_widens_with_us(self):
        """外层联动：US 组存在 → enrich 超时 8s；无 US → 5s。"""
        import inspect
        from app.routers import market

        src = inspect.getsource(market.watchlist_list)
        assert "8 if _has_us else 5" in src


class TestR82LastGoodOnCancel:
    @pytest.mark.asyncio
    async def test_cancelled_us_route_writes_last_good_in_background(self, monkeypatch):
        """批量取消后后台线程返回成功结果 → 仍写 quote 缓存（AAPL 不再每次重复退化）。"""
        from app.services import market_service as ms

        writes = {}
        async def _set(key, val, ttl):
            writes[key] = (val, ttl)
        # market_service 模块级 cache_set 绑定——patch 模块名
        monkeypatch.setattr(ms, "cache_set", _set)
        monkeypatch.setattr(ms, "_asset_realtime_cache", {})

        started = asyncio.Event()

        async def _slow_route(symbol):
            started.set()
            await asyncio.sleep(0.3)
            return {"symbol": symbol, "price": 310.0, "change_pct": 1.5, "volume": 100}

        monkeypatch.setattr(ms, "_route_us", _slow_route)

        # 构造批量取消：wait_for 0.05s 触发 CancelledError
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ms.get_asset_realtime("AAPL", "US"), timeout=0.05)
        await started.wait()
        # 等后台写 last-good（≤1s）
        for _ in range(20):
            if writes:
                break
            await asyncio.sleep(0.05)
        assert ms.quote_key("AAPL", "US") in writes, "取消后未后台写 last-good"
        _val, _ttl = writes[ms.quote_key("AAPL", "US")]
        assert _ttl == 24 * 3600
        assert _val.get("price") == 310.0


class TestR82FinnhubQuotaGuard:
    def test_finnhub_quota_skipped_when_budget_exhausted(self, monkeypatch):
        """finnhub 配额护栏：预算耗尽 → 直接返回 None（不调 HTTP），诚实降级。"""
        from app.fetchers import global_markets_fetcher as gmf

        monkeypatch.setattr(gmf, "_finnhub_quota_available", lambda: False)
        called = {"n": 0}
        monkeypatch.setattr(gmf, "_request", lambda *a, **k: (called.__setitem__("n", called["n"] + 1) or {}))
        monkeypatch.setattr(gmf, "_get_apikey", lambda: "test-key")

        out = gmf.fetch_realtime("AAPL")
        assert out is None
        assert called["n"] == 0, "配额耗尽仍调了 finnhub"

    def test_finnhub_quota_allows_within_budget(self, monkeypatch):
        """预算内 → 正常调用。"""
        from app.fetchers import global_markets_fetcher as gmf

        monkeypatch.setattr(gmf, "_finnhub_quota_available", lambda: True)
        monkeypatch.setattr(gmf, "_request", lambda *a, **k: {"c": 200.0, "pc": 198.0, "dp": 1.01, "h": 201, "l": 197, "o": 198})
        monkeypatch.setattr(gmf, "_get_apikey", lambda: "test-key")

        out = gmf.fetch_realtime("AAPL")
        assert out is not None and out["price"] == 200.0
