"""TDD: F0-4 — A 股 K 线降级链增强。

覆盖：
  1. fetch_history A 股日线：mootdx → sina → netease 三级兜底
  2. get_history 全源失败 → 走 hub 过期缓存兜底（stale 标记）
  3. get_kline_rows_any 返回任意年龄缓存
  4. indicators 端点带 _stale 标记
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.fetchers.china_market import fetch_history
from app.services.market_data_hub import market_data_hub


# ── 1. fetch_history netease 兜底 ───────────────────────────────

def test_fetch_history_etf_netease_fallback(monkeypatch):
    """ETF 日线：sina 空 → netease 兜底。"""
    monkeypatch.setattr("app.fetchers.china_market._is_etf_code", lambda s: True)
    monkeypatch.setattr("app.fetchers.china_market._sina_history_cb",
                       lambda s, p: [])
    ne_rows = [{"date": "2026-01-05", "open": 1.0, "high": 1.1, "low": 0.9,
                "close": 1.05, "volume": 100}]
    monkeypatch.setattr("app.fetchers.china_market.fetch_history_netease",
                       lambda s, m, p: ne_rows)
    result = fetch_history("510300", "A", "daily")
    assert result == ne_rows


def test_fetch_history_stock_netease_fallback(monkeypatch):
    """个股日线：mootdx 空 → sina 空 → netease 兜底。"""
    monkeypatch.setattr("app.fetchers.china_market._is_etf_code", lambda s: False)
    monkeypatch.setattr("app.fetchers.china_market._mootdx_history",
                       lambda s, p: [])
    monkeypatch.setattr("app.fetchers.china_market._sina_history_cb",
                       lambda s, p: [])
    ne_rows = [{"date": "2026-01-05", "open": 1.0, "high": 1.1, "low": 0.9,
                "close": 1.05, "volume": 100}]
    monkeypatch.setattr("app.fetchers.china_market.fetch_history_netease",
                       lambda s, m, p: ne_rows)
    result = fetch_history("600519", "A", "daily")
    assert result == ne_rows


def test_fetch_history_sina_ok_no_netease(monkeypatch):
    """sina 有数据时不再走 netease。"""
    monkeypatch.setattr("app.fetchers.china_market._is_etf_code", lambda s: True)
    sina_rows = [{"date": "2026-01-05", "open": 1.0, "high": 1.1,
                  "low": 0.9, "close": 1.05, "volume": 100}]
    monkeypatch.setattr("app.fetchers.china_market._sina_history_cb",
                       lambda s, p: sina_rows)
    called = {"n": 0}

    def _ne(*a, **k):
        called["n"] += 1
        return []
    monkeypatch.setattr("app.fetchers.china_market.fetch_history_netease", _ne)
    result = fetch_history("510300", "A", "daily")
    assert result == sina_rows
    assert called["n"] == 0


# ── 2. get_history stale 缓存兜底 ───────────────────────────────

@pytest.mark.asyncio
async def test_get_history_stale_cache_fallback(monkeypatch):
    """全源失败 → 返回过期缓存并标记 stale + 记录 flag。"""
    from app.services import market_service

    stale_rows = [{"date": "2026-01-05", "open": 1.0, "high": 1.1, "low": 0.9,
                   "close": 1.05, "volume": 100}]

    async def _call(fn, *args, **kwargs):
        return []  # 模拟 fetch_history / get_k_data 全空

    monkeypatch.setattr(market_service, "_call", _call)

    # 注入过期缓存
    market_data_hub._kline_cache_rows["510300"] = stale_rows
    market_data_hub._kline_cache_ts = 0  # 早已过期

    with patch("app.services.market_service.logger") as mock_logger:
        result = await market_service.get_history("510300", "A", "daily")

    assert result == stale_rows
    assert market_data_hub.is_kline_stale("510300") is True
    # 日志含 stale 字样
    warning_msgs = " ".join(str(c.args[0]) for c in mock_logger.warning.call_args_list)
    assert "stale" in warning_msgs

    # 清理
    market_data_hub._kline_cache_rows.pop("510300", None)
    market_data_hub._kline_stale_flags.pop("510300", None)


@pytest.mark.asyncio
async def test_get_history_fresh_cache_first(monkeypatch):
    """新鲜缓存命中时优先返回，不走网络。"""
    from app.services import market_service

    fresh_rows = [{"date": "2026-07-30", "open": 1.0, "high": 1.1, "low": 0.9,
                   "close": 1.05, "volume": 100}]
    import time
    market_data_hub._kline_cache_rows["510300"] = fresh_rows
    market_data_hub._kline_cache_ts = time.time()

    network = {"called": 0}

    async def _call(fn, *args, **kwargs):
        network["called"] += 1
        return []

    monkeypatch.setattr(market_service, "_call", _call)
    result = await market_service.get_history("510300", "A", "daily")
    assert result == fresh_rows
    assert network["called"] == 0

    market_data_hub._kline_cache_rows.pop("510300", None)


# ── 3. get_kline_rows_any / stale flag ──────────────────────────

def test_get_kline_rows_any_returns_expired():
    """任意年龄缓存可读。"""
    rows = [{"date": "2026-01-05", "close": 1.0}]
    market_data_hub._kline_cache_rows["588000"] = rows
    market_data_hub._kline_cache_ts = 0
    assert market_data_hub.get_kline_rows_any("588000") == rows
    assert market_data_hub.get_kline_rows("588000", max_age=300) is None  # 新鲜度检查仍生效
    market_data_hub._kline_cache_rows.pop("588000", None)


def test_stale_flag_mark_and_query():
    market_data_hub.mark_kline_stale("510050", True)
    assert market_data_hub.is_kline_stale("510050") is True
    market_data_hub.mark_kline_stale("510050", False)
    assert market_data_hub.is_kline_stale("510050") is False
    assert market_data_hub.is_kline_stale("nonexistent") is False


# ── 4. indicators 端点 stale 标记 ───────────────────────────────

def test_indicators_router_stale_mark(monkeypatch):
    """indicators 端点响应带 _stale 标记。"""
    from app.routers import market as market_router

    market_data_hub._kline_stale_flags["510300"] = True

    async def _fake_history(*args, **kwargs):
        return [{"date": "2026-01-05", "open": 1.0, "high": 1.1, "low": 0.9,
                 "close": 1.05, "volume": 100}]

    monkeypatch.setattr(market_router.market_data_hub, "get_market_history",
                        _fake_history)

    import asyncio
    result = asyncio.run(market_router.indicators("510300", "A", "daily"))
    assert result.get("_stale") is True

    market_data_hub._kline_stale_flags.pop("510300", None)
