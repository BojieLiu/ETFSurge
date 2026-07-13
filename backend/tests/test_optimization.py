import asyncio
from unittest.mock import patch

import pytest

from app.services import market_service
from app.services import cache_service
from app.services.cache_service import memory_cache, cache_get, cache_set
from app.fetchers import akshare_fetcher
from app.main import app


def run(coro):
    return asyncio.run(coro)


# ── Cache (L1 in-memory) ───────────────────────────────────────────────

def test_memory_cache_basic():
    async def _run():
        await memory_cache.clear()
        await memory_cache.set("k", {"a": 1}, ttl=100)
        assert await memory_cache.get("k") == {"a": 1}
        await memory_cache.mset({"x": 1, "y": 2}, ttl=100)
        vals = await memory_cache.mget(["x", "y", "z"])
        assert vals == [1, 2, None]
        await memory_cache.clear()
        assert await memory_cache.get("x") is None
    run(_run())


def test_memory_cache_expiry():
    async def _run():
        await memory_cache.clear()
        await memory_cache.set("e", {"v": 1}, ttl=-1)
        assert await memory_cache.get("e") is None
    run(_run())


def test_cache_module_without_redis():
    async def _run():
        await memory_cache.clear()
        await cache_set("quote:A:510050", {"symbol": "510050", "price": 1.0}, ttl=100)
        assert await cache_get("quote:A:510050") == {"symbol": "510050", "price": 1.0}
    run(_run())


# ── quote_key / TTL config ─────────────────────────────────────────────

def test_quote_key_and_ttl():
    assert market_service.quote_key("510050", "A") == "quote:A:510050"
    assert market_service._QUOTE_TTL["A"] == 5
    assert market_service._QUOTE_TTL["index"] == 3
    assert market_service._QUOTE_TTL["US"] == 15


# ── get_realtime_batch caching ─────────────────────────────────────────

def test_get_realtime_batch_cache_hit():
    async def _run():
        await memory_cache.clear()
        with patch("app.fetchers.akshare_fetcher.fetch_a_stock_batch") as mock_batch:
            mock_batch.return_value = [{"symbol": "510050", "price": 2.5, "change_pct": 1.0}]
            r1 = await market_service.get_realtime_batch(["510050"], "A")
            r2 = await market_service.get_realtime_batch(["510050"], "A")
            assert mock_batch.call_count == 1
            assert r1 == r2 == [{"symbol": "510050", "price": 2.5, "change_pct": 1.0}]
    run(_run())


def test_get_realtime_batch_empty():
    async def _run():
        await memory_cache.clear()
        assert await market_service.get_realtime_batch([], "A") == []
    run(_run())


# ── get_portfolio_realtime ─────────────────────────────────────────────

class _FakeETF:
    def __init__(self, symbol, asset_type="A"):
        self.symbol = symbol
        self.asset_type = asset_type


def test_get_portfolio_realtime():
    async def _run():
        await memory_cache.clear()
        with patch("app.services.portfolio_service.list_etfs") as mock_list, \
             patch("app.fetchers.akshare_fetcher.fetch_a_stock_batch") as mock_batch, \
             patch("app.fetchers.akshare_fetcher.fetch_index_realtime") as mock_idx:
            mock_list.side_effect = [[_FakeETF("510050")], [_FakeETF("510300")]]
            mock_batch.return_value = [
                {"symbol": "510050", "price": 1.0},
                {"symbol": "510300", "price": 2.0},
            ]
            mock_idx.return_value = [{"symbol": "000001", "price": 3000.0}]
            result = await market_service.get_portfolio_realtime()
            assert len(result) == 3
            symbols = {q["symbol"] for q in result}
            assert symbols == {"510050", "510300", "000001"}
    run(_run())


def test_get_portfolio_realtime_empty():
    async def _run():
        await memory_cache.clear()
        with patch("app.services.portfolio_service.list_etfs") as mock_list:
            mock_list.side_effect = [[], []]
            assert await market_service.get_portfolio_realtime() == []
    run(_run())


# ── _resample_4h pure function ─────────────────────────────────────────

def test_resample_4h():
    rows = [{"日期": f"d{i}", "开盘": 1, "最高": i, "最低": 0, "收盘": i + 1, "成交量": 10} for i in range(8)]
    out = akshare_fetcher._resample_4h(rows)
    assert len(out) == 2
    assert out[0]["最高"] == 3
    assert out[0]["最低"] == 0
    assert out[0]["收盘"] == 4
    assert out[0]["成交量"] == 40


# ── fetch_history intraday routing ─────────────────────────────────────

def test_fetch_history_15m():
    # Sina 为分钟线主力源（eastmoney 分钟接口当前不稳定），akshare 仅兜底
    with patch("app.fetchers.akshare_fetcher._sina_history") as mock_sina, \
         patch("app.fetchers.akshare_fetcher._akshare_intraday_history") as mock_min:
        mock_sina.return_value = [{"日期": "d1", "开盘": 1, "最高": 2, "最低": 0.5, "收盘": 1.5, "成交量": 100}]
        result = akshare_fetcher.fetch_history("510050", "A", "15m")
        assert mock_sina.called
        assert not mock_min.called
        assert result[0]["收盘"] == 1.5


def test_fetch_history_4h_resample():
    # 4h 由 Sina 60 分钟线重采样得到
    with patch("app.fetchers.akshare_fetcher._sina_history") as mock_sina:
        mock_sina.return_value = [{"日期": f"d{i}", "开盘": 1, "最高": i, "最低": 0, "收盘": i + 1, "成交量": 10} for i in range(8)]
        result = akshare_fetcher.fetch_history("510050", "A", "4h")
        assert mock_sina.called
        assert len(result) == 2
        assert result[0]["最高"] == 3


# ── Router endpoints registered ────────────────────────────────────────

def test_router_endpoints_registered():
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/market/realtime/portfolio" in paths
    assert "/api/v1/market/realtime/batch" in paths


# ── RedisCache graceful degradation when unavailable ───────────────────

def test_redis_cache_unavailable_returns_none():
    async def _run():
        cache_service.redis_cache._available = False
        cache_service.redis_cache._client = None
        assert await cache_service.redis_cache.get("any") is None
        assert await cache_service.redis_cache.mget(["a", "b"]) == [None, None]
    run(_run())
