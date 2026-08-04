"""
O8 (docs/round7-rediagnosis.md §7 P11): /portfolio/etfs 补充实时 price + change_pct。

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
