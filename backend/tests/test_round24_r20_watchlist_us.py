"""round24 R20: 美股/HK 自选无实时显式降级（realtime_unavailable + T-1 收盘兜底）。

问题（round24 §4 步骤5 实证）：watchlist 中 QQQ/AAPL/SPY `realtime.price=null`——
前端只显示「行情加载中」，用户无法分辨「没波动」vs「没数据」（F21 未实施）。

修复（docs/round24 §12.3 R20）：
- `_enrich_watchlist_item` 在 US/HK 实时不可用时 → `realtime_unavailable=true` +
  `realtime_note`（前端「暂无实时」，非静默 null）；
- 尝试 `_last_close_fallback`（F39 K 线源）取 T-1 收盘价 → is_estimated=true 标「估」；
- A 股实时不可用保持原行为（不标 realtime_unavailable，避免误报）。
"""

import pytest


class TestWatchlistUsRealtimeUnavailable:
    """R20: 美股/HK 自选实时不可用 → 显式降级标识 + T-1 收盘兜底。

    注意：真实 GET /watchlist 路径走 routers/market._watchlist_enrich_items
    （非 market_service.get_watchlist，后者已删），故本测试直测该 live 函数。
    """

    @pytest.mark.asyncio
    async def test_us_null_realtime_flagged_unavailable(self, monkeypatch):
        """US 标的批量+逐标的实时均 None → realtime_unavailable=true + 收盘兜底（负向：
        静默 null 无标注 → FAIL）。"""
        from app.routers import market as mkt
        from app.services import market_service as ms
        from app.services.market_data_hub import market_data_hub as hub

        class _Item:
            id = 1
            symbol = "QQQ"
            name = "Invesco QQQ"
            asset_type = "US"
            notes = ""
            created_at = None
            updated_at = None

        async def _fake_batch(symbols, at):
            return []
        async def _fake_rt(symbol, at):
            return None

        monkeypatch.setattr(ms, "get_realtime_batch", _fake_batch)
        monkeypatch.setattr(hub, "get_asset_realtime", _fake_rt)
        calls = {"lc": 0}

        async def _fake_lc(symbol, at):
            calls["lc"] += 1
            return {"price": 500.0, "is_estimated": True, "estimate_source": "last_close"}
        monkeypatch.setattr(ms, "_last_close_fallback", _fake_lc)

        out = await mkt._watchlist_enrich_items([_Item()])
        item = out[0]
        assert item["realtime_unavailable"] is True
        assert item.get("realtime_note")
        assert calls["lc"] == 1, "US 实时不可用应尝试 T-1 收盘兜底"
        assert item["realtime"]["price"] == 500.0
        assert item["realtime"]["is_estimated"] is True

    @pytest.mark.asyncio
    async def test_a_share_null_not_flagged_unavailable(self, monkeypatch):
        """A 股实时不可用 → 标 _degraded（不标 realtime_unavailable，避免误报）。"""
        from app.routers import market as mkt
        from app.services import market_service as ms
        from app.services.market_data_hub import market_data_hub as hub

        class _Item:
            id = 3
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

        monkeypatch.setattr(ms, "get_realtime_batch", _fake_batch)
        monkeypatch.setattr(hub, "get_asset_realtime", _fake_rt)

        out = await mkt._watchlist_enrich_items([_Item()])
        item = out[0]
        assert item.get("realtime_unavailable") is not True
        assert item.get("_degraded") is True
        assert item["realtime"] is None

    @pytest.mark.asyncio
    async def test_hk_null_flagged_and_fallback(self, monkeypatch):
        """HK 与 US 同路径：实时 null → 显式标注 + 收盘兜底。"""
        from app.routers import market as mkt
        from app.services import market_service as ms
        from app.services.market_data_hub import market_data_hub as hub

        class _Item:
            id = 4
            symbol = "00700"
            name = "腾讯控股"
            asset_type = "HK"
            notes = ""
            created_at = None
            updated_at = None

        async def _fake_batch(symbols, at):
            return []
        async def _fake_rt(symbol, at):
            return None

        monkeypatch.setattr(ms, "get_realtime_batch", _fake_batch)
        monkeypatch.setattr(hub, "get_asset_realtime", _fake_rt)
        async def _fake_lc_hk(symbol, at):
            return {"price": 461.6, "is_estimated": True,
                    "estimate_source": "last_close", "as_of": "2026-08-14"}
        monkeypatch.setattr(ms, "_last_close_fallback", _fake_lc_hk)

        out = await mkt._watchlist_enrich_items([_Item()])
        item = out[0]
        assert item["realtime_unavailable"] is True
        assert item["realtime"]["price"] == 461.6
        assert item["realtime"]["as_of"] == "2026-08-14"


class TestLastCloseFallback:
    """R20: _last_close_fallback 取最近收盘价，失败返回 None。"""

    @pytest.mark.asyncio
    async def test_returns_last_close(self, monkeypatch):
        from app.services import market_service as ms

        rows = [
            {"date": "2026-08-13", "close": 490.0},
            {"date": "2026-08-14", "close": 500.5},
        ]

        async def _fake_run_sync(call, *args, timeout=8):
            return rows

        monkeypatch.setattr("app.services.market_service.run_sync", _fake_run_sync)

        out = await ms._last_close_fallback("QQQ", "US")
        assert out is not None
        assert out["price"] == 500.5
        assert out["is_estimated"] is True
        assert out["estimate_source"] == "last_close"
        assert out["as_of"] == "2026-08-14"

    @pytest.mark.asyncio
    async def test_empty_history_returns_none(self, monkeypatch):
        from app.services import market_service as ms

        async def _fake_run_sync(call, *args, timeout=8):
            return []

        monkeypatch.setattr("app.services.market_service.run_sync", _fake_run_sync)

        out = await ms._last_close_fallback("QQQ", "US")
        assert out is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, monkeypatch):
        from app.services import market_service as ms

        async def _boom(call, *args, timeout=8):
            raise RuntimeError("source down")

        monkeypatch.setattr("app.services.market_service.run_sync", _boom)

        out = await ms._last_close_fallback("QQQ", "US")
        assert out is None  # 兜底失败不抛错，调用方显示「暂无实时」