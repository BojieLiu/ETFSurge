"""
P1-6 (R4-21): 场外累计盈亏口径修复。

- off_exchange 估算：est_shares = 目标金额 / avg_cost（联接净值折算），
  cost_basis = 目标金额（成本=投入本金）——不再混用「场内 ETF 实时价折算份额」。
- market_value = 目标金额 × (1 + 跟踪指数涨跌幅)；无涨跌幅 → 本金（盈亏 0 +
  estimate_note「净值变动暂缺」）。
- 回归：on_exchange 原口径不变（场内价与场内 avg_cost 同单位无错配）。

mock 数据源，无网络。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.portfolio_service import calculate_cumulative_pnl


class FakeEtf:
    def __init__(self, symbol="019633", name="半导体联接C", short_name="半导体C",
                 asset_type="ETF", portfolio_type="off_exchange",
                 target_weight=0.1, avg_cost=None, shares_held=None,
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


async def _run(etfs, total_capital=500000, price_map=None):
    db = AsyncMock()
    with patch("app.services.portfolio_service.list_etfs", AsyncMock(return_value=etfs)), \
         patch("app.services.portfolio_service.build_price_map",
               AsyncMock(return_value=price_map or {e.symbol: (0.0, 0.0) for e in etfs})):
        return await calculate_cumulative_pnl(db, total_capital=total_capital)


class TestOffExchangePnlCaliber:
    async def test_avg_cost_scale_mismatch_no_amplification(self):
        """P1-6: avg_cost(3.534) 与场内价(0.67) 量级差 5 倍 → 成本=本金，pnl% 不再放大。"""
        etf = FakeEtf(avg_cost=3.534, shares_held=None, target_weight=0.1)
        # 场内对应 ETF 涨跌幅 +2%（跟踪指数变动代理）
        result = await _run([etf], total_capital=500000,
                            price_map={"019633": (0.67, 2.0)})

        h = result["holdings"][0]
        target = 500000 * 0.1  # 50000
        assert h["cost_basis"] == target, \
            f"成本应=投入本金 {target}，实际 {h['cost_basis']}（旧口径会按场内价放大）"
        assert h["shares_held"] == pytest.approx(target / 3.534, rel=1e-6)
        assert h["market_value"] == pytest.approx(target * 1.02, rel=1e-6)
        # pnl% = (1.02 - 1) = +2%，语义 = 跟踪指数变动，而非量级错配的 ±179%/-81%
        assert h["cumulative_pnl_pct"] == pytest.approx(2.0, abs=0.01)

    async def test_no_change_pct_falls_back_to_principal(self):
        """P1-6: 跟踪指数无涨跌幅 → market_value=本金（盈亏 0）+「净值变动暂缺」。"""
        etf = FakeEtf(avg_cost=1.041, shares_held=None, target_weight=0.1)
        result = await _run([etf], total_capital=500000,
                            price_map={"019633": (0.0, 0.0)})

        h = result["holdings"][0]
        target = 500000 * 0.1
        assert h["cost_basis"] == target
        assert h["market_value"] == target
        assert h["cumulative_pnl"] == 0.0
        assert h["estimate_note"] == "净值变动暂缺"

    async def test_positive_change_pct_scales_market_value(self):
        """P1-6: 涨跌幅为正时市值按指数变动放大。"""
        etf = FakeEtf(avg_cost=1.041, shares_held=None, target_weight=0.1)
        result = await _run([etf], total_capital=500000,
                            price_map={"019633": (3.304, -3.5)})

        h = result["holdings"][0]
        target = 500000 * 0.1
        assert h["market_value"] == pytest.approx(target * (1 - 0.035), rel=1e-6)
        assert h["cumulative_pnl_pct"] == pytest.approx(-3.5, abs=0.01)

    async def test_on_exchange_caliber_unchanged(self):
        """回归: on_exchange 场内口径不变（est_shares=目标/场内价，cost=份额×avg_cost）。"""
        etf = FakeEtf(symbol="510300", name="沪深300ETF", portfolio_type="on_exchange",
                      avg_cost=1.5, shares_held=None, target_weight=0.3)
        result = await _run([etf], total_capital=100000,
                            price_map={"510300": (2.0, 1.0)})

        h = result["holdings"][0]
        assert h["shares_held"] == 15000.0
        assert h["cost_basis"] == 22500.0
        assert h["market_value"] == 30000.0
        assert h["cumulative_pnl"] == 7500.0
