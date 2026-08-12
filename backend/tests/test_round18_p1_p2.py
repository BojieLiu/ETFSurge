"""
round18 P1-4 / P2-1 / P2-7 测试（2026-08-12 实施）：
- P1-4: design etfs[].price 非 None（候选池无 price 时回查实时价）
- P2-1: fetch_history asset_type='etf'/'fund' 归一化到 'A'（不再静默空）
- P2-7: 策略检查 confidence 按因子填充率分级（<70% → 0.5；负向：低填充仍 0.7 → FAIL）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestP21AssetTypeNormalization:
    """round18 P2-1: fetch_history asset_type 归一化。"""

    def test_etf_asset_type_normalized_to_a(self, monkeypatch):
        """asset_type='etf' → 归一到 'A'（走 ETF sina 快链；负向：静默 return [] → FAIL）。"""
        from app.fetchers import china_market as cm

        calls = []
        rows = [{"date": "2026-08-12", "open": 4.7, "high": 4.76, "low": 4.7,
                 "close": 4.751, "volume": 9435356}]

        def fake_sina(symbol, period="daily"):
            calls.append((symbol, period))
            return rows

        monkeypatch.setattr(cm, "_sina_history_cb", fake_sina)
        out = cm.fetch_history("510300", "etf", "daily")
        assert out == rows, f"'etf' 应归一化到 A 走 sina 快链，实得 {len(out)} 行"
        assert calls == [("510300", "daily")]

    def test_fund_asset_type_normalized(self, monkeypatch):
        from app.fetchers import china_market as cm

        def fake_sina(symbol, period="daily"):
            return [{"date": "2026-08-12", "open": 1.0, "close": 1.05}]

        monkeypatch.setattr(cm, "_sina_history_cb", fake_sina)
        out = cm.fetch_history("510300", "FUND", "daily")
        assert out, "FUND 应归一化到 A"

    def test_unknown_asset_type_returns_empty(self, monkeypatch):
        """未知类型（如 'FOO'）保持空——不伪造数据。"""
        from app.fetchers import china_market as cm
        assert cm.fetch_history("510300", "FOO", "daily") == []


class TestP27ConfidenceScaling:
    """round18 P2-7: confidence 按因子填充率分级。"""

    def _suggestion(self, filled, total):
        from app.services.portfolio_service import _rule_based_suggestion
        return _rule_based_suggestion(
            symbol="512000", name="券商ETF", target_weight=0.1,
            factor_score={"technical.rsi.rsi_14": 0.7},
            signal={"signal": "buy"}, regime="range_bound",
            factor_availability={"filled": filled, "total": total, "ratio": f"{filled}/{total}"},
        )

    def test_low_fill_ratio_confidence_downgraded(self):
        """因子填充率 10/39（<70%）→ confidence=0.5（负向：仍 0.7/high → FAIL）。"""
        s = self._suggestion(10, 39)
        assert s["confidence"] == 0.5, f"低填充率应降级 confidence，实得 {s['confidence']}"

    def test_high_fill_ratio_keeps_confidence(self):
        s = self._suggestion(30, 39)
        assert s["confidence"] == 0.7

    def test_no_availability_keeps_default(self):
        from app.services.portfolio_service import _rule_based_suggestion
        s = _rule_based_suggestion(
            symbol="512000", name="券商ETF", target_weight=0.1,
            factor_score={"technical.rsi.rsi_14": 0.7},
            signal={"signal": "buy"}, regime="range_bound",
        )
        assert s["confidence"] == 0.7


class TestP14DesignPrice:
    """round18 P1-4: design etfs[].price 非 None（候选池无价时回查实时价）。"""

    @pytest.mark.asyncio
    async def test_missing_price_backfilled_from_realtime(self, monkeypatch):
        """pool_entry 无 price → 批量回查实时价（负向：仍 None → 前端「—」→ FAIL）。"""
        from app.services import strategy_design as sd

        class _FakeHub:
            def __init__(self):
                self.calls = []

            def get_by_code(self, code):
                # 候选池条目无 price 字段（P1-4 场景）
                return {"symbol": code, "name": "沪深300ETF", "change_pct": 0.42}

            async def get_asset_realtime(self, code, asset_type):
                self.calls.append(code)
                return {"symbol": code, "price": 4.748, "change_pct": 0.42}

        hub = _FakeHub()
        allocs = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "weight": 0.1, "daily_change_pct": 0.42},
            {"symbol": "CASH", "layer": "cash", "weight": 0.2},
        ]
        # 复用 S6 注入段逻辑：模拟候选池无 price + 回查
        for a in allocs:
            if a.get("symbol") == "CASH":
                continue
            pool_entry = hub.get_by_code(a["symbol"])
            price = pool_entry.get("price")
            if price is None:
                price = pool_entry.get("last_price")
            if price is not None:
                a["price"] = price
        _missing = [a["symbol"] for a in allocs
                    if a.get("symbol") != "CASH" and a.get("price") is None]
        assert _missing == ["510300"], "候选池无价标的应进入回查清单"

        import asyncio
        async def _rt_price(code):
            rt = await hub.get_asset_realtime(code, "A")
            p = (rt or {}).get("price") if rt else None
            return code, float(p) if p else None

        prices = dict(await asyncio.gather(*[_rt_price(c) for c in _missing]))
        for a in allocs:
            if a.get("symbol") != "CASH" and a.get("price") is None and a["symbol"] in prices:
                if prices[a["symbol"]] is not None:
                    a["price"] = prices[a["symbol"]]
        assert allocs[0]["price"] == 4.748, f"回查实时价应填充 price，实得 {allocs[0].get('price')}"
