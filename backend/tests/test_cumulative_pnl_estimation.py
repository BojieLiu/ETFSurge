"""
F18 R64-R67 (combination-design-review.md F18): 累计盈亏估算修复。

- R64: 有 avg_cost 无 shares_held → 按 target_weight 估算份额，cost_basis = 估算份额 × avg_cost
       （不用 current price，否则累计盈亏恒为 0），has_real_data=True，estimated=true。
- R65: summary/by_type 提供估算占比 estimated_ratio（estimated_cost_basis / total_cost_basis）。
- R67⑤: avg_cost 非 None 但 capital/price/weight 任一为 0 → 跳过估算但仍计入 has_real_data。
- 回归: shares_held 有值路径不受影响；无 avg_cost 保持旧估算（price 当成本、PnL=0、不置 has_real_data）。

无网络，纯 mock。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.portfolio_service import calculate_cumulative_pnl


class FakeEtf:
    def __init__(self, symbol="510300", name="沪深300ETF", short_name="300ETF",
                 asset_type="etf", portfolio_type="on_exchange",
                 target_weight=0.3, avg_cost=None, shares_held=None,
                 cost_basis=None, first_buy_date=None, last_trade_date=None):
        self.symbol = symbol
        self.name = name
        self.short_name = short_name
        self.asset_type = asset_type
        self.portfolio_type = portfolio_type
        self.target_weight = target_weight
        self.avg_cost = avg_cost
        self.shares_held = shares_held
        self.cost_basis = cost_basis
        self.first_buy_date = first_buy_date
        self.last_trade_date = last_trade_date


async def _run(etfs, total_capital=100000, price_map=None):
    db = AsyncMock()
    with patch("app.services.portfolio_service.list_etfs", AsyncMock(return_value=etfs)), \
         patch("app.services.portfolio_service.build_price_map",
               AsyncMock(return_value=price_map or {e.symbol: (2.0, 0.0) for e in etfs})):
        return await calculate_cumulative_pnl(db, total_capital=total_capital)


class TestR64AvgCostWithoutShares:
    async def test_estimates_shares_and_uses_avg_cost(self):
        """R64 主路径: 有 avg_cost 无份额 → 估算份额、成本按 avg_cost、PnL ≠ 0。"""
        etf = FakeEtf(avg_cost=1.5, shares_held=None, target_weight=0.3)
        result = await _run([etf], total_capital=100000, price_map={"510300": (2.0, 0.0)})

        # est_shares = 100000*0.3/2.0 = 15000; cost_basis = 15000*1.5 = 22500
        h = result["holdings"][0]
        assert h["shares_held"] == 15000.0
        assert h["avg_cost"] == 1.5, "avg_cost 必须用用户录入值（不能用 current price）"
        assert h["cost_basis"] == 22500.0
        assert h["current_price"] == 2.0
        assert h["market_value"] == 30000.0
        assert h["cumulative_pnl"] == 7500.0, "累计盈亏必须 ≠ 0（旧 bug：恒为 0）"
        assert h["cumulative_pnl_pct"] == pytest.approx(33.33, abs=0.01)
        assert h["estimated"] is True
        assert result["summary"]["has_cost_basis_data"] is True

    async def test_no_avg_cost_keeps_old_behavior(self):
        """回归: 无 avg_cost → 旧估算（price 当成本、PnL=0、不置 has_real_data）。"""
        etf = FakeEtf(avg_cost=None, shares_held=None, target_weight=0.3)
        result = await _run([etf], total_capital=100000, price_map={"510300": (2.0, 0.0)})

        h = result["holdings"][0]
        assert h["avg_cost"] == 2.0
        assert h["cumulative_pnl"] == 0.0
        assert h["estimated"] is True
        assert result["summary"]["has_cost_basis_data"] is False

    async def test_real_shares_untouched(self):
        """回归: shares_held 有值 → 真实路径不受影响。"""
        etf = FakeEtf(avg_cost=1.5, shares_held=1000, target_weight=0.3)
        result = await _run([etf], total_capital=100000, price_map={"510300": (2.0, 0.0)})

        h = result["holdings"][0]
        assert h["shares_held"] == 1000
        assert h["cost_basis"] == 1500.0
        assert h["estimated"] is False
        assert result["summary"]["has_cost_basis_data"] is True


class TestR65EstimatedRatio:
    async def test_summary_estimated_ratio_present(self):
        """R65: summary 含 estimated_ratio（估算成本占比）。"""
        etfs = [
            FakeEtf(symbol="510300", avg_cost=1.5, shares_held=None, target_weight=0.3),  # 估算
            FakeEtf(symbol="510500", avg_cost=2.0, shares_held=1000, target_weight=0.3),  # 真实
        ]
        result = await _run(etfs, total_capital=100000, price_map={"510300": (2.0, 0.0), "510500": (2.5, 0.0)})

        summary = result["summary"]
        assert "estimated_ratio" in summary
        assert 0 < summary["estimated_ratio"] < 1
        # estimated_cost_basis = 15000*1.5 = 22500; total_cost_basis = 22500 + 2000 = 24500
        assert summary["estimated_ratio"] == pytest.approx(22500 / 24500, abs=0.001)

    async def test_by_type_estimated_ratio(self):
        """R65: by_type 每个类型也含估算占比。"""
        etfs = [
            FakeEtf(symbol="510300", portfolio_type="on_exchange", avg_cost=1.5, shares_held=None),
            FakeEtf(symbol="159915", portfolio_type="off_exchange", avg_cost=1.0, shares_held=500),
        ]
        result = await _run(etfs, total_capital=100000, price_map={"510300": (2.0, 0.0), "159915": (1.5, 0.0)})
        by_type = result["summary"]["by_type"]
        assert "estimated_ratio" in by_type["on_exchange"]
        assert by_type["on_exchange"]["estimated_ratio"] == pytest.approx(1.0)
        assert by_type["off_exchange"]["estimated_ratio"] == 0.0

    async def test_no_estimate_ratio_zero(self):
        """R65: 全真实数据 → estimated_ratio=0。"""
        etf = FakeEtf(avg_cost=1.5, shares_held=1000)
        result = await _run([etf], total_capital=100000, price_map={"510300": (2.0, 0.0)})
        assert result["summary"]["estimated_ratio"] == 0.0


class TestR67Edge:
    async def test_avg_cost_but_capital_zero_still_real_data(self):
        """R67⑤: avg_cost 非 None 但 total_capital=0 → 跳过估算但仍计入 has_real_data。"""
        etf = FakeEtf(avg_cost=1.5, shares_held=None, target_weight=0.3)
        result = await _run([etf], total_capital=0, price_map={"510300": (2.0, 0.0)})
        assert result["holdings"] == [], "无法估算 → 不产出估算持仓"
        assert result["summary"]["has_cost_basis_data"] is True, "有 avg_cost 仍计入 has_real_data"

    async def test_avg_cost_but_price_zero_skips(self):
        """R67⑤: avg_cost 非 None 但 price=0 → 跳过估算但仍计入 has_real_data。"""
        etf = FakeEtf(avg_cost=1.5, shares_held=None, target_weight=0.3)
        result = await _run([etf], total_capital=100000, price_map={"510300": (0.0, 0.0)})
        assert result["holdings"] == []
        assert result["summary"]["has_cost_basis_data"] is True
