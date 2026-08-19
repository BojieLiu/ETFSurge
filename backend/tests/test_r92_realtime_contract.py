# -*- coding: utf-8 -*-
"""round30 R92: watchlist realtime 固定 7 字段（三形态并存修复）。

根因（§4/§14.3）：两条 enrich 路径各自拼装 realtime，同一「T-1 收盘估值」语义
被编码成 `estimate_source` vs `is_estimated` 两种形状 → 前端只读 is_estimated 时
形态①（estimate_source="last_close_cache"）「估」徽标漏显。

修复（A' 已决策）：realtime 非 null 时恒含 7 字段
{price, change_pct, volume, as_of, is_estimated, estimate_source, data_source}，
两条路径统一经 `_normalize_watchlist_realtime` 归一化。

无网络：monkeypatch。
"""
import pytest

_REALTIME_7FIELDS = {
    "price", "change_pct", "volume", "as_of",
    "is_estimated", "estimate_source", "data_source",
}


class TestNormalizeRealtimeR92:
    def test_normalize_fills_missing_keys(self):
        """归一化补全 7 键（缺省 null/false）。"""
        from app.routers.market import _normalize_watchlist_realtime
        rt = _normalize_watchlist_realtime({"price": 1.23, "change_pct": 0.5})
        assert set(rt.keys()) == _REALTIME_7FIELDS
        assert rt["is_estimated"] is False
        assert rt["estimate_source"] is None
        assert rt["data_source"] is None
        assert rt["as_of"] is None

    def test_normalize_keeps_estimate_shape(self):
        """形态①（estimate_source 有值无 is_estimated）→ 补 is_estimated=true。"""
        from app.routers.market import _normalize_watchlist_realtime
        rt = _normalize_watchlist_realtime({
            "price": 2.5, "change_pct": -1.2, "volume": 100,
            "data_source": "stale", "as_of": "2026-08-19",
            "estimate_source": "last_close_cache",
        })
        assert set(rt.keys()) == _REALTIME_7FIELDS
        assert rt["is_estimated"] is True
        assert rt["estimate_source"] == "last_close_cache"

    def test_normalize_real_realtime(self):
        """实时形态 → is_estimated=false + estimate_source=null。"""
        from app.routers.market import _normalize_watchlist_realtime
        rt = _normalize_watchlist_realtime({
            "price": 3.1, "change_pct": 0.2, "volume": 9999, "data_source": "sina",
        })
        assert rt["is_estimated"] is False
        assert rt["estimate_source"] is None
        assert rt["data_source"] == "sina"

    def test_normalize_none_returns_none(self):
        """realtime=None → 返回 None（顶层语义保留）。"""
        from app.routers.market import _normalize_watchlist_realtime
        assert _normalize_watchlist_realtime(None) is None


class TestEnrichRealtimeContractR92:
    @pytest.mark.asyncio
    async def test_enrich_batch_realtime_has_7_fields(self, monkeypatch):
        """_watchlist_enrich_items 批量实时路径 → realtime 恒含 7 字段。"""
        from app.routers import market
        from app.services import market_service

        class _Item:
            def __init__(self, symbol, asset_type="A"):
                self.id = 1
                self.symbol = symbol
                self.asset_type = asset_type
                self.name = "测试"
                self.notes = ""
                self.created_at = None
                self.updated_at = None

        # 批量路径命中：A 股走 get_realtime_batch
        async def _fake_batch(symbols, asset_type):
            return [{"symbol": symbols[0], "price": 3.0, "change_pct": 0.1, "volume": 100}]
        monkeypatch.setattr(market_service, "get_realtime_batch", _fake_batch)
        # 防止 fallback 干扰
        monkeypatch.setattr(market_data_hub_fake := market_service, "get_asset_realtime",
                            lambda *a, **k: {"price": 3.0, "change_pct": 0.1, "volume": 100})
        from app.services.market_data_hub import market_data_hub
        monkeypatch.setattr(market_data_hub, "get_asset_realtime",
                            lambda *a, **k: {"price": 3.0, "change_pct": 0.1, "volume": 100})

        out = await market._watchlist_enrich_items([_Item("510300")])
        assert len(out) == 1
        rt = out[0].get("realtime")
        assert rt is not None
        assert set(rt.keys()) == _REALTIME_7FIELDS, f"批量路径 realtime 缺字段: {rt}"
        assert rt["is_estimated"] is False

    @pytest.mark.asyncio
    async def test_close_fallback_realtime_has_7_fields(self, monkeypatch):
        """_watchlist_close_fallback 缓存命中分支 → realtime 含 is_estimated=true。"""
        from app.routers import market
        from app.services import market_service

        class _Item:
            id = 1
            symbol = "AAPL"
            asset_type = "US"
            name = "苹果"
            notes = ""
            created_at = None
            updated_at = None

        # 命中 close 缓存（形态①旧形状：无 is_estimated）
        async def _fake_cache_get(key):
            return {"price": 210.5, "change_pct": -0.3, "volume": 500,
                    "as_of": "2026-08-19", "estimate_source": "last_close"}
        monkeypatch.setattr("app.services.cache_service.cache_get", _fake_cache_get)

        out = await market._watchlist_close_fallback([_Item()])
        rt = out[0]["realtime"]
        assert set(rt.keys()) == _REALTIME_7FIELDS, f"close 兜底 realtime 缺字段: {rt}"
        assert rt["is_estimated"] is True
        assert rt["estimate_source"] == "last_close_cache"

    @pytest.mark.asyncio
    async def test_last_good_fallback_has_7_fields(self, monkeypatch):
        """last-good 兜底分支 → is_estimated=true（last_good）。"""
        from app.routers import market

        class _Item:
            id = 1
            symbol = "600519"
            asset_type = "A"
            name = "贵州茅台"
            notes = ""
            created_at = None
            updated_at = None

        from app.services.market_service import _last_close_fallback as _real
        async def _fake_lc(*a, **k):
            return None
        monkeypatch.setattr("app.services.market_service._last_close_fallback", _fake_lc)
        # close 缓存 miss，last-good 命中
        async def _fake_cache_get(key):
            return {"price": 1300.0, "change_pct": 0.5, "volume": 1000,
                    "as_of": "2026-08-19"}
        monkeypatch.setattr("app.services.cache_service.cache_get", _fake_cache_get)

        out = await market._watchlist_close_fallback([_Item()])
        rt = out[0]["realtime"]
        assert set(rt.keys()) == _REALTIME_7FIELDS
        assert rt["is_estimated"] is True
        assert rt["estimate_source"] == "last_good"
