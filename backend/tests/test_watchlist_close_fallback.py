"""round25 R29: 自选列表 5s 超时退化修复——T-1 收盘快照兜底 + 放开 A 股门控。

问题（round25 §2.6 实证）：watchlist GET 列表 5s 超时回退裸 DB 行（无 realtime / 无
realtime_unavailable / 无 realtime_note）→ 前端「行情加载中」永不翻回；A 股超时路径
不走 _last_close_fallback（仅 US/HK），直接空白。

修复（round25 R29-a/b/c）：
- R29-a: 超时回退改调 _watchlist_close_fallback（跨 A/HK/US 调 _last_close_fallback，
  is_estimated=True + as_of=T-1 收盘）；
- R29-b: _watchlist_enrich_items 内 A 股超时同样尝试 T-1 收盘兜底（不再仅 US/HK）；
- R29-c②: 批量匹配键归一化（去 .HK/.US 后缀）——自选 "02800.HK" 匹配批量返 "02800"；
- R29-c③: resolve_symbol_to_code 经 asyncio.to_thread 提交（2s 超时真实生效）。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import market as mkt
from app.routers.market import _norm_watchlist_symbol


class TestWatchlistCloseFallback:
    """R29-a: 超时回退行带 T-1 收盘快照（非裸 DB 行）。"""

    @pytest.mark.asyncio
    async def test_close_fallback_rows_have_estimated_realtime(self, monkeypatch):
        """回退行 realtime.is_estimated=True + as_of=T-1 收盘（负向：realtime:null → FAIL）。"""
        class _Item:
            id = 1
            symbol = "510300"
            name = "沪深300ETF"
            asset_type = "A"
            notes = ""
            created_at = None
            updated_at = None

        async def _fake_lc(symbol, at):
            return {"price": 4.05, "is_estimated": True, "estimate_source": "last_close",
                    "as_of": "2026-08-14"}
        monkeypatch.setattr("app.services.market_service._last_close_fallback", _fake_lc)

        out = await mkt._watchlist_close_fallback([_Item()])
        item = out[0]
        assert item["realtime"] is not None, "回退行不得 realtime=null（R29-a）"
        assert item["realtime"]["is_estimated"] is True
        assert item["realtime"]["as_of"] == "2026-08-14"
        # 有估值 → 不标 _degraded（前端显示「估」徽标，非「行情暂不可用」）
        assert item.get("_degraded") is not True

    @pytest.mark.asyncio
    async def test_hk_fallback_marks_unavailable(self, monkeypatch):
        """HK 回退行 realtime_unavailable=True + 收盘兜底。"""
        class _Item:
            id = 2
            symbol = "00700"
            name = "腾讯控股"
            asset_type = "HK"
            notes = ""
            created_at = None
            updated_at = None

        async def _fake_lc(symbol, at):
            return {"price": 475.2, "is_estimated": True, "estimate_source": "last_close",
                    "as_of": "2026-08-14"}
        monkeypatch.setattr("app.services.market_service._last_close_fallback", _fake_lc)

        out = await mkt._watchlist_close_fallback([_Item()])
        item = out[0]
        assert item["realtime_unavailable"] is True
        assert item["realtime"]["is_estimated"] is True
        assert item["realtime"]["price"] == 475.2

    @pytest.mark.asyncio
    async def test_fallback_miss_honest_degrade(self, monkeypatch):
        """收盘兜底失败 → 诚实降级（A: _degraded；HK/US: realtime_unavailable），不编造。"""
        class _Item:
            id = 3
            symbol = "AAPL"
            name = "Apple"
            asset_type = "US"
            notes = ""
            created_at = None
            updated_at = None

        async def _fake_lc(symbol, at):
            return None
        monkeypatch.setattr("app.services.market_service._last_close_fallback", _fake_lc)

        out = await mkt._watchlist_close_fallback([_Item()])
        item = out[0]
        assert item["realtime"] is None
        assert item["realtime_unavailable"] is True
        assert item["realtime_note"]

    @pytest.mark.asyncio
    async def test_a_share_fallback_miss_marks_degraded(self, monkeypatch):
        """A 股收盘兜底也失败 → _degraded=True（仅此时标注，有估值则不标）。"""
        class _Item:
            id = 7
            symbol = "510300"
            name = "沪深300ETF"
            asset_type = "A"
            notes = ""
            created_at = None
            updated_at = None

        async def _fake_lc(symbol, at):
            return None
        monkeypatch.setattr("app.services.market_service._last_close_fallback", _fake_lc)

        out = await mkt._watchlist_close_fallback([_Item()])
        item = out[0]
        assert item["realtime"] is None
        assert item["_degraded"] is True
        assert item.get("realtime_unavailable") is not True


class TestWatchlistAShareCloseFallback:
    """R29-b: A 股超时也走 T-1 收盘兜底（放开资产类型门控）。"""

    @pytest.mark.asyncio
    async def test_a_share_gets_close_fallback(self, monkeypatch):
        """A 股实时 None + 收盘兜底命中 → realtime 有值（旧实现恒 None → 前端空白）。"""
        from app.services import market_service as ms
        from app.services.market_data_hub import market_data_hub as hub

        class _Item:
            id = 4
            symbol = "510300"
            name = "沪深300ETF"
            asset_type = "A"
            notes = ""
            created_at = None
            updated_at = None

        async def _fake_batch(symbols, at):
            return []
        async def _fake_rt(symbol, at):
            return None
        async def _fake_lc(symbol, at):
            return {"price": 4.05, "is_estimated": True, "estimate_source": "last_close",
                    "as_of": "2026-08-14"}

        monkeypatch.setattr(ms, "get_realtime_batch", _fake_batch)
        monkeypatch.setattr(hub, "get_asset_realtime", _fake_rt)
        monkeypatch.setattr(ms, "_last_close_fallback", _fake_lc)

        out = await mkt._watchlist_enrich_items([_Item()])
        item = out[0]
        assert item["realtime"] is not None, "A 股实时缺失也应尝试 T-1 收盘兜底（R29-b）"
        assert item["realtime"]["is_estimated"] is True
        assert item["realtime"]["price"] == 4.05
        # A 股不标 realtime_unavailable（避免误报「该市场无实时」）
        assert item.get("realtime_unavailable") is not True
        # 有兜底价 → 不标 _degraded
        assert item.get("_degraded") is not True


class TestWatchlistSymbolNormalization:
    """R29-c②: 批量匹配键归一化（去 .HK/.US 后缀）。"""

    def test_strips_hk_suffix(self):
        assert _norm_watchlist_symbol("02800.HK") == "02800"
        assert _norm_watchlist_symbol("00700.HK") == "00700"

    def test_strips_us_suffix(self):
        assert _norm_watchlist_symbol("AAPL.US") == "AAPL"

    def test_pure_code_unchanged(self):
        assert _norm_watchlist_symbol("510300") == "510300"

    @pytest.mark.asyncio
    async def test_batch_map_normalized_matching(self, monkeypatch):
        """批量返 "02800" 与自选 "02800.HK" 经归一化匹配（健康标的不误入 per-item 慢路径）。"""
        from app.services import market_service as ms

        class _Item:
            id = 5
            symbol = "02800.HK"
            name = "盈富基金"
            asset_type = "HK"
            notes = ""
            created_at = None
            updated_at = None

        calls = {"per_item": 0}

        async def _fake_batch(symbols, at):
            return [{"symbol": "02800", "price": 19.5, "change_pct": 0.31}]
        async def _fake_rt(symbol, at):
            calls["per_item"] += 1
            return None

        monkeypatch.setattr(ms, "get_realtime_batch", _fake_batch)
        monkeypatch.setattr(hub_ms(), "get_asset_realtime", _fake_rt)
        monkeypatch.setattr("app.services.market_service._last_close_fallback", _fake_rt)

        out = await mkt._watchlist_enrich_items([_Item()])
        item = out[0]
        assert item["realtime"]["price"] == 19.5, "归一化后批量命中，无需 per-item 兜底"
        assert calls["per_item"] == 0, "健康标的不应误入 per-item 慢路径（R29-c②）"


def hub_ms():
    from app.services.market_data_hub import market_data_hub
    return market_data_hub


# ── folded from test_round27_r45_watchlist_fallback.py ──
"""round27 R45 (P1): watchlist 收盘兜底周末落空——第二层 Redis last-good 兜底 + 诚实「维护中」标注。

问题（round27 §2.6 / §15.1 R45）：R29 的 T-1 收盘兜底 `_last_close_fallback` 周末/源冷却时
自身也返 None → watchlist 0/23 带 realtime（R29 周末全 None 根因）。

修复（本轮）：
- `_watchlist_close_fallback` 在 `_last_close_fallback` 失败后再读 Redis last-good 报价
  （quote_key，24h TTL，周末存活）→ realtime 非 None + data_source="stale" + as_of；
- 三层全失败（realtime 缺 + 收盘兜底 None + last-good None）→ 诚实标注
  「非交易时段无行情（数据源维护中）」+ 显式时间戳，区分「没波动」vs「没数据」；

反假完成：每个测试都含负向断言——last-good 命中必须 data_source=="stale" 而非空白；
三层失败必须带「维护中」文案 + 时间戳而非静默 null 冒充。
"""

from app.services import market_service as ms
from app.services.cache_service import cache_get, cache_set, memory_cache
from app.services.market_service import quote_key, _LAST_GOOD_TTL


@pytest.fixture(autouse=True)
def _clear_caches():
    """隔离：清空跨测试持久的内存缓存，避免 last-good 注入污染「三层失败」用例。"""
    memory_cache._store.clear()
    ms._asset_realtime_cache.clear()
    yield


def _item(symbol, asset_type, id=1):
    class _Item:
        pass
    it = _Item()
    it.id = id
    it.symbol = symbol
    it.name = symbol
    it.asset_type = asset_type
    it.notes = ""
    it.created_at = None
    it.updated_at = None
    return it


class TestWatchlistLastGoodFallback:
    """R45: _last_close_fallback 失败时回退 Redis last-good（data_source=stale）。"""

    @pytest.mark.asyncio
    async def test_last_close_none_then_last_good_stale(self, monkeypatch):
        """收盘兜底 None + 注入 Redis last-good → realtime 非 None 且 data_source=='stale'。"""
        sym, at = "510300", "A"
        monkeypatch.setattr(
            "app.services.market_service._last_close_fallback",
            AsyncMock(return_value=None),
        )
        # 注入 last-good 报价（模拟上一个交易日成功写入）
        await cache_set(
            quote_key(sym, at),
            {"price": 4.02, "change_pct": 1.1, "volume": 9900000, "as_of": "2026-08-14T15:00:00+00:00"},
            _LAST_GOOD_TTL,
        )
        out = await mkt._watchlist_close_fallback([_item(sym, at)])
        item = out[0]
        assert item["realtime"] is not None, "last-good 兜底不得 realtime=null（R45）"
        assert item["realtime"]["data_source"] == "stale", "last-good 必须标注 data_source=stale（R45）"
        assert item["realtime"]["price"] == 4.02
        assert item["realtime"].get("as_of") == "2026-08-14T15:00:00+00:00"

    @pytest.mark.asyncio
    async def test_last_good_preferred_over_none_for_us_hk(self, monkeypatch):
        """US/HK 标的收盘兜底 None + last-good 命中 → realtime 非 None（非恒 unavailable）。"""
        sym, at = "SPX", "US"
        monkeypatch.setattr(
            "app.services.market_service._last_close_fallback",
            AsyncMock(return_value=None),
        )
        await cache_set(
            quote_key(sym, at),
            {"price": 5123.4, "change_pct": None, "volume": None, "as_of": "2026-08-14"},
            _LAST_GOOD_TTL,
        )
        out = await mkt._watchlist_close_fallback([_item(sym, at)])
        item = out[0]
        assert item["realtime"] is not None, "US 指数 last-good 必须兜底（R45）"
        assert item["realtime"]["data_source"] == "stale"

    @pytest.mark.asyncio
    async def test_last_close_hit_still_wins(self, monkeypatch):
        """收盘兜底命中时优先用收盘快照（估），不读 last-good。"""
        sym, at = "510300", "A"
        monkeypatch.setattr(
            "app.services.market_service._last_close_fallback",
            AsyncMock(return_value={"price": 4.05, "is_estimated": True,
                                     "estimate_source": "last_close", "as_of": "2026-08-14"}),
        )
        await cache_set(
            quote_key(sym, at),
            {"price": 99.99, "data_source": "stale", "as_of": "2026-08-13"},
            _LAST_GOOD_TTL,
        )
        out = await mkt._watchlist_close_fallback([_item(sym, at)])
        item = out[0]
        assert item["realtime"]["price"] == 4.05, "收盘快照优先于 last-good（R45）"
        assert item["realtime"].get("estimate_source") == "last_close"


class TestWatchlistTripleFailureHonest:
    """R45: 三层全失败 → 诚实「维护中」+ 时间戳，绝非空白冒充。"""

    @pytest.mark.asyncio
    async def test_triple_failure_honest_maintenance_label(self, monkeypatch):
        """收盘兜底 None + last-good 缺失 → _degraded + 维护中文案 + 时间戳（非空白）。"""
        sym, at = "510300", "A"
        monkeypatch.setattr(
            "app.services.market_service._last_close_fallback",
            AsyncMock(return_value=None),
        )
        # 不注入 last-good → 三层全失败
        out = await mkt._watchlist_close_fallback([_item(sym, at)])
        item = out[0]
        assert item["realtime"] is None, "三层全失败必须 realtime=None"
        assert item.get("_degraded") is True
        assert item.get("data_unavailable") is True
        assert "维护中" in (item.get("realtime_note") or ""), "三层失败必须诚实标注「维护中」（R45）"
        assert item.get("data_unavailable_since"), "必须带显式时间戳，杜绝空白冒充（R45）"

    @pytest.mark.asyncio
    async def test_triple_failure_us_hk_also_labels(self, monkeypatch):
        """US 标的三层全失败 → 维护中文案 + 时间戳（仍有 realtime_unavailable 区分）。"""
        sym, at = "SPX", "US"
        monkeypatch.setattr(
            "app.services.market_service._last_close_fallback",
            AsyncMock(return_value=None),
        )
        out = await mkt._watchlist_close_fallback([_item(sym, at)])
        item = out[0]
        assert item["realtime"] is None
        assert "维护中" in (item.get("realtime_note") or "")
        assert item.get("data_unavailable_since")
        assert item.get("realtime_unavailable") is True


class TestLastGoodWriteTTL:
    """R45: 成功取到实时价 → 写入 last-good 报价，TTL 24h（周末存活）。"""

    @pytest.mark.asyncio
    async def test_realtime_writes_last_good_with_24h_ttl(self, monkeypatch):
        """get_asset_realtime 成功 → cache_set 被调用且 TTL==24h（86400）。"""
        captured = {}

        async def _fake_set(key, val, ttl):
            captured[key] = ttl

        monkeypatch.setattr(ms, "cache_set", _fake_set)

        async def _fake_call(fn, *args, timeout=8):
            # fetch_index_realtime 返回 list[dict]，mock 必须返回列表（否则
            # 原分支 `for r in idx_rows` 会遍历 dict 的 key，导致 result 恒 None）。
            return [{"symbol": "SPX", "price": 5000.0, "change_pct": 1.0,
                     "change_amount": 50.0, "asset_type": "index"}]

        monkeypatch.setattr(ms, "_call", _fake_call)
        monkeypatch.setattr(ms, "_lookup_index_market", AsyncMock(return_value=""))

        res = await ms.get_asset_realtime("SPX", "index")
        assert res is not None
        assert any(t == 24 * 3600 for t in captured.values()), \
            "last-good 写入 TTL 必须为 24h（R45）"
        assert _LAST_GOOD_TTL == 24 * 3600, "last-good TTL 常量必须为 24h"

    @pytest.mark.asyncio
    async def test_last_good_key_readable_by_fallback(self, monkeypatch):
        """写入的 last-good 可被 _watchlist_close_fallback 读出（端到端链路）。"""
        sym, at = "159915", "A"
        monkeypatch.setattr(
            "app.services.market_service._last_close_fallback",
            AsyncMock(return_value=None),
        )
        # 模拟上一个交易日成功写入 last-good
        await cache_set(
            quote_key(sym, at),
            {"price": 1.23, "change_pct": 0.5, "volume": 100, "as_of": "2026-08-14"},
            _LAST_GOOD_TTL,
        )
        out = await mkt._watchlist_close_fallback([_item(sym, at)])
        assert out[0]["realtime"] is not None
        assert out[0]["realtime"]["data_source"] == "stale"