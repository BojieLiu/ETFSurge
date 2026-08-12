"""
round19 P3（问题 3：增持/仓位变更按买卖操作重算成本价）测试（2026-08-12 实施）：
- recompute_cost_after_trade 三分支（买入加权/卖出成本不变+realized_pnl/首仓=price；
  负向：卖出超份额不报错 → FAIL）
- update_etf adjust 语义（PUT delta_shares → 重算 + 联动 target_weight + 互斥校验）
- 阶段 2：selectSearch 自动填当前价（前端源码断言）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.portfolio_service import recompute_cost_after_trade


class TestRecomputeCostAfterTrade:
    """round19 P3-③: 买卖加权平均重算纯函数。"""

    def test_buy_weighted_average(self):
        """买入加权: old=100@1.0 + 100@2.0 → avg=1.5。"""
        r = recompute_cost_after_trade(100, 1.0, 100, 2.0)
        assert r["new_avg_cost"] == pytest.approx(1.5)
        assert r["new_shares"] == 200
        assert r["realized_pnl"] == 0
        assert r["side"] == "buy"

    def test_sell_cost_unchanged_realized_pnl(self):
        """卖出: 成本不变 + realized_pnl = (price-avg)×(-delta)。"""
        r = recompute_cost_after_trade(1000, 4.5, -300, 5.0)
        assert r["new_avg_cost"] == pytest.approx(4.5)
        assert r["new_shares"] == 700
        assert r["realized_pnl"] == pytest.approx(150.0)  # (5.0-4.5)×300
        assert r["side"] == "sell"

    def test_first_position_avg_is_price(self):
        """首仓（old_shares 空/0）: avg_cost = price。"""
        r = recompute_cost_after_trade(None, None, 500, 4.75)
        assert r["new_avg_cost"] == pytest.approx(4.75)
        assert r["new_shares"] == 500

    def test_sell_exceeding_shares_raises(self):
        """卖出超份额 → ValueError（负向: 不报错 → FAIL）。"""
        with pytest.raises(ValueError):
            recompute_cost_after_trade(100, 4.5, -300, 5.0)

    def test_zero_delta_and_bad_price_raise(self):
        with pytest.raises(ValueError):
            recompute_cost_after_trade(100, 4.5, 0, 5.0)
        with pytest.raises(ValueError):
            recompute_cost_after_trade(100, 4.5, 100, None)
        with pytest.raises(ValueError):
            recompute_cost_after_trade(100, 4.5, 100, 0)


class TestUpdateEtfAdjustSemantics:
    """round19 P3-③: update_etf adjust 语义（delta_shares → 重算 + 联动权重）。"""

    class _FakeEtf:
        symbol = "510300"
        name = "沪深300ETF"
        avg_cost = 4.5
        shares_held = 1000
        target_weight = 0.1
        is_active = True
        portfolio_type = "on_exchange"
        short_name = None
        tracked_index = None
        asset_type = "A"
        first_buy_date = None
        last_trade_date = None

    @pytest.mark.asyncio
    async def test_adjust_buy_recomputes_and_links_weight(self, monkeypatch):
        from app.services import portfolio_service as ps

        etf = self._FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf))
        db.refresh = AsyncMock()

        # 组合总市值: 本标的 1000×4.5 + 其它 1000×5.0 = 9500
        other = self._FakeEtf()
        other.symbol = "518880"
        other.shares_held = 1000
        other.avg_cost = 5.0
        other.target_weight = 0.2

        async def _fake_list(db, pt=None):
            return [etf, other]

        async def _fake_price_map(etfs):
            return {e.symbol: (5.0 if e.symbol == "518880" else 4.5, 0.1) for e in etfs}

        monkeypatch.setattr(ps, "list_etfs", _fake_list)
        monkeypatch.setattr(ps, "build_price_map", _fake_price_map)

        data = MagicMock()
        data.delta_shares = 500
        data.price = 5.0
        data.avg_cost = None
        data.shares_held = None
        data.name = None
        data.target_weight = None
        data.is_active = None
        data.portfolio_type = None
        data.short_name = None
        data.tracked_index = None
        data.first_buy_date = None
        data.last_trade_date = None

        result = await ps.update_etf(db, "510300", data)
        # 加权: (1000×4.5 + 500×5.0)/1500 = 4.6667
        assert result.avg_cost == pytest.approx(4.666667, abs=1e-5)
        assert result.shares_held == 1500
        # 权重联动: 新市值 1500×5.0 = 7500；总市值 = 7500 + 1000×5.0 = 12500
        assert result.target_weight == pytest.approx(7500 / 12500, abs=1e-4)
        meta = getattr(result, "_adjust_meta", None)
        assert meta is not None
        assert meta["realized_pnl"] == 0
        assert meta["trade"]["side"] == "buy"

    @pytest.mark.asyncio
    async def test_adjust_sell_returns_realized_pnl(self, monkeypatch):
        from app.services import portfolio_service as ps

        etf = self._FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf))
        db.refresh = AsyncMock()

        async def _fake_list(db, pt=None):
            return [etf]

        async def _fake_price_map(etfs):
            return {etf.symbol: (4.8, 0.0)}

        monkeypatch.setattr(ps, "list_etfs", _fake_list)
        monkeypatch.setattr(ps, "build_price_map", _fake_price_map)

        data = MagicMock()
        data.delta_shares = -200
        data.price = 4.8
        data.avg_cost = None
        data.shares_held = None
        data.name = None
        data.target_weight = None
        data.is_active = None
        data.portfolio_type = None
        data.short_name = None
        data.tracked_index = None
        data.first_buy_date = None
        data.last_trade_date = None

        result = await ps.update_etf(db, "510300", data)
        assert result.shares_held == 800
        assert result.avg_cost == 4.5  # 卖出成本不变
        meta = getattr(result, "_adjust_meta", None)
        assert meta["realized_pnl"] == pytest.approx((4.8 - 4.5) * 200)
        assert meta["trade"]["side"] == "sell"

    @pytest.mark.asyncio
    async def test_adjust_mutually_exclusive_with_cost_fields(self, monkeypatch):
        """delta_shares 与 avg_cost/shares_held 同传 → HTTPException 400（review: 原
        ValueError 无 handler → 实际 500，改为显式 400）。"""
        from fastapi import HTTPException
        from app.services import portfolio_service as ps

        etf = self._FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf))
        data = MagicMock()
        data.delta_shares = 100
        data.price = 5.0
        data.avg_cost = 4.5  # 与 delta 同传
        data.shares_held = None
        with pytest.raises(HTTPException) as ei:
            await ps.update_etf(db, "510300", data)
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_adjust_price_missing_uses_realtime(self, monkeypatch):
        """price 缺省 → 实时价兜底；实时价不可用 → HTTPException 400（不用假价）。"""
        from fastapi import HTTPException
        from app.services import portfolio_service as ps

        etf = self._FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf))
        db.refresh = AsyncMock()

        async def _fake_rt(db, e):
            return None  # 实时价不可用

        async def _fake_list(db, pt=None):
            return [etf]

        monkeypatch.setattr(ps, "_fetch_realtime_price", _fake_rt)
        monkeypatch.setattr(ps, "list_etfs", _fake_list)

        data = MagicMock()
        data.delta_shares = 100
        data.price = None
        data.avg_cost = None
        data.shares_held = None
        data.name = None
        data.target_weight = None
        data.is_active = None
        data.portfolio_type = None
        data.short_name = None
        data.tracked_index = None
        data.first_buy_date = None
        data.last_trade_date = None
        with pytest.raises(HTTPException) as ei:
            await ps.update_etf(db, "510300", data)
        assert ei.value.status_code == 400


class TestP3FrontendSource:
    """round19 P3-②: 前端 selectSearch 自动填当前价即成本（源码断言）。"""

    def _src(self):
        import os
        p = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                         "components", "PortfolioManager.vue")
        if not os.path.exists(p):
            p = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src",
                             "components", "PortfolioManager.vue")
        return open(p, encoding="utf-8").read()

    def test_select_search_fills_avg_cost_from_realtime(self):
        src = self._src()
        assert "r?.realtime?.price ?? null" in src, "selectSearch 应自动填当前价即成本"
        assert "默认自动填入当前价" in src, "成本价 placeholder 应提示自动填入"

    def test_adjust_shares_entry_exists(self):
        src = self._src()
        assert "saveAdjustShares" in src
        assert "startAdjustShares" in src
        assert "delta_shares" in src, "adjust 语义应传 delta_shares/price"

    def test_store_update_returns_response(self):
        import os
        p = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                         "stores", "portfolio.js")
        if not os.path.exists(p):
            p = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src",
                             "stores", "portfolio.js")
        src = open(p, encoding="utf-8").read()
        assert "return res.data || res" in src, "updateEtf 应返回 adjust 响应（realized_pnl）"
