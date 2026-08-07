"""
O28 (docs/archived/round7-rediagnosis.md §7 P28②): GET /market/fund-flow/{symbol} 端点。

P28②: 后端 get_fund_flow 已实现（market_data_hub.py，东财 fetch_fund_flow）但无
router 端点暴露、前端无 API 封装——热点股票技术分析弹窗「资金流入流出」未接通。

契约: api-contracts/market/fund-flow.md（v1.0）——成功返回东财资金流字段
（snake_case 直通）；数据源不可用返回 200 + available:false（不抛 500）。
"""

import pytest
from unittest.mock import patch

from app.routers import market as market_router


class _FakeFundFlow:
    """mock get_fund_flow 返回的东财资金流结构。"""
    def __init__(self, **kwargs):
        self.data = {
            "main_net_inflow": 123456789.0,
            "main_net_inflow_pct": 3.21,
            "main_inflow": 500000000.0,
            "main_outflow": 376543211.0,
        }
        self.data.update(kwargs)


@pytest.mark.asyncio
async def test_fund_flow_success_passthrough():
    """get_fund_flow 正常 → 字段直通（snake_case）。"""
    flow = _FakeFundFlow().data

    with patch("app.services.market_data_hub.market_data_hub.get_fund_flow", return_value=flow):
        result = await market_router.fund_flow("600519")

    assert result["symbol"] == "600519"
    assert result["main_net_inflow"] == 123456789.0
    assert result["main_net_inflow_pct"] == 3.21
    assert result["available"] is True


@pytest.mark.asyncio
async def test_fund_flow_none_returns_available_false():
    """get_fund_flow 返回 None（数据源不可用）→ 200 降级结构。"""
    with patch("app.services.market_data_hub.market_data_hub.get_fund_flow", return_value=None):
        result = await market_router.fund_flow("510300")

    assert result["symbol"] == "510300"
    assert result["main_net_inflow"] is None
    assert result["available"] is False


@pytest.mark.asyncio
async def test_fund_flow_exception_returns_available_false():
    """get_fund_flow 抛异常 → 200 降级（不抛 500）。"""
    def _boom(symbol):
        raise RuntimeError("source down")

    with patch("app.services.market_data_hub.market_data_hub.get_fund_flow", new=_boom):
        result = await market_router.fund_flow("600519")

    assert result["available"] is False
    assert result["main_net_inflow"] is None
