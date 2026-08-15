from __future__ import annotations
"""
O8 (docs/archived/round7-rediagnosis.md §7 P11): /portfolio/etfs 补充实时 price + change_pct。

P11 问题: GET /portfolio/etfs 返回 ORM 条目，price 字段为 null（realtime 端点有价）——
前端持仓表格价格列「—」，与实时行情脱节。

修复: 路由层对 etfs 列表批量补充实时价格（build_price_map，{symbol: (price, change_pct)}），
失败时静默保留原条目（不阻塞列表加载）。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.routers import portfolio as portfolio_router
from app.routers.portfolio import _with_realtime_prices


class _FakeEtf:
    def __init__(self, symbol, name="测试ETF", asset_type="A"):
        self.symbol = symbol
        self.name = name
        self.asset_type = asset_type
        self.target_weight = 0.1
        self.portfolio_type = "on_exchange"
        self.short_name = None
        self.tracked_index = None
        self.avg_cost = None
        self.shares_held = None
        self.first_buy_date = None
        self.last_trade_date = None
        self.is_active = True
        self.id = 1


class TestEtfsWithRealtimePrice:
    @pytest.mark.asyncio
    async def test_price_injected_from_price_map(self):
        """price_map 命中 → ORM 对象注入 price/change_pct。"""
        etfs = [_FakeEtf("510300"), _FakeEtf("560600")]
        price_map = {"510300": (4.12, 0.85), "560600": (1.05, -0.32)}

        with patch("app.services.portfolio_service.build_price_map", new=AsyncMock(return_value=price_map)):
            result = await _with_realtime_prices(etfs)

        assert len(result) == 2
        assert result[0].price == 4.12
        assert result[0].change_pct == 0.85
        assert result[1].price == 1.05
        assert result[1].change_pct == -0.32

    @pytest.mark.asyncio
    async def test_missing_symbol_keeps_none(self):
        """price_map 未命中 → 不注入 price/change_pct（保持无字段，不崩溃）。"""
        etfs = [_FakeEtf("510300")]
        with patch("app.services.portfolio_service.build_price_map", new=AsyncMock(return_value={})):
            result = await _with_realtime_prices(etfs)
        assert not hasattr(result[0], "price"), "未命中不应注入 price"
        assert not hasattr(result[0], "change_pct"), "未命中不应注入 change_pct"

    @pytest.mark.asyncio
    async def test_failure_returns_original_list(self):
        """build_price_map 异常 → 静默返回原列表（列表加载不阻塞）。"""
        etfs = [_FakeEtf("510300")]
        with patch("app.services.portfolio_service.build_price_map",
                  new=AsyncMock(side_effect=RuntimeError("source down"))):
            result = await _with_realtime_prices(etfs)
        assert result == etfs


# ===== folded from test_round19_p3.py =====
from unittest.mock import AsyncMock, MagicMock
from app.services.portfolio_service import recompute_cost_after_trade
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
