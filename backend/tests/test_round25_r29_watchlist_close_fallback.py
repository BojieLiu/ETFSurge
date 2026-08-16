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