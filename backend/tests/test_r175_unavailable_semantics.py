# -*- coding: utf-8 -*-
"""R175 (round52 §7.3 方案C): pricing 3s 截断 → 空值语义（0 不再冒充真实涨跌）。

round52 §7.1 R175: `_a_batch` 对 A 股批量行情 3s 整批截断——超时即整批降级为空 →
`price_map` 无该批 symbol → `allocation.py:39 price_map.get(e.symbol, (0, 0))` →
场内+场外全部 change_pct=0 且 daily_pnl=0，15s 缓存后自愈。**0 与「行情暂不可用」
语义被混淆**（前端把 0 当真实涨跌渲染，违反「不静默降级」）。

方案C：`price_map` 命中失败的 symbol 在 allocation 输出诚实空值——
`current_price=None`、`change_pct=None`、`estimate_source="unavailable"`；
前端 `formatChange(null)` 已有「—」渲染路径（`changeClass(null)` 既有行为不变）。

负向断言（能失败的）：
- 批量行情整批失败时，allocation 的 change_pct 必须为 **None**（旧代码 0 → FAIL）；
- 有真实行情的 symbol 不受影响（change_pct 保持真实值）；
- estimate_source 标注 "unavailable"（真实值条目不标注）。

无网络：全部 mock。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.portfolio_service import calculate_allocation


@pytest.fixture(autouse=True)
def _isolated_price_caches():
    """隔离模块级 price/fundamentals 缓存——三用例共用同一 symbol 集合
    （相同 cache_key），不清缓存则首用例的空 price_map 会在 15s TTL 内
    污染后续用例（生产语义：截断后 15s 内诚实不可用；测试里必须隔离）。"""
    from app.services.portfolio import pricing

    pricing._PRICE_MAP_CACHE.clear()
    pricing._FUNDAMENTALS_CACHE.clear()
    yield
    pricing._PRICE_MAP_CACHE.clear()
    pricing._FUNDAMENTALS_CACHE.clear()


def _etf(**kw):
    return SimpleNamespace(**kw)


def _rows():
    return [
        _etf(symbol="510300", name="沪深300ETF", short_name="300ETF", asset_type="A",
             portfolio_type="on_exchange", target_weight=0.5, tracked_index=None,
             avg_cost=3.9, shares_held=10000, first_buy_date=None, last_trade_date=None),
        _etf(symbol="022449", name="A500联接C", short_name="A500联接", asset_type="A",
             portfolio_type="off_exchange", target_weight=0.5, tracked_index="159338",
             avg_cost=1.18, shares_held=50000, first_buy_date=None, last_trade_date=None),
    ]


@pytest.mark.asyncio
async def test_batch_failure_yields_none_not_zero():
    """负向核心：A 股批量整批失败 → change_pct/current_price 为 None（非 0 假值）。"""
    with patch("app.services.market_data_hub.market_data_hub.get_a_stock_batch",
               new=MagicMock(side_effect=RuntimeError("source down"))), \
         patch("app.services.market_data_hub.market_data_hub.get_fund_nav",
               new=MagicMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_us_etf_realtime",
               new=MagicMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_index_realtime",
               new=MagicMock(return_value=[])):
        result = await calculate_allocation(etfs=_rows(), total_capital=100000)

    amap = {a["symbol"]: a for a in result["allocations"]}
    assert amap["510300"]["change_pct"] is None, (
        f"批量失败必须输出 None（诚实不可用），实际 {amap['510300']['change_pct']}（0 = 假涨跌）"
    )
    assert amap["510300"]["current_price"] is None
    assert amap["510300"]["estimate_source"] == "unavailable"


@pytest.mark.asyncio
async def test_real_quotes_unaffected():
    """有真实行情的条目不受空值语义影响（回归守卫）。"""
    batch = [
        {"symbol": "510300", "price": 3.95, "change_pct": 0.64, "volume": 100},
        {"symbol": "159338", "price": 1.205, "change_pct": 0.5, "volume": 200},
    ]
    with patch("app.services.market_data_hub.market_data_hub.get_a_stock_batch",
               new=MagicMock(return_value=batch)), \
         patch("app.services.market_data_hub.market_data_hub.get_fund_nav",
               new=MagicMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_us_etf_realtime",
               new=MagicMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_index_realtime",
               new=MagicMock(return_value=[])):
        result = await calculate_allocation(etfs=_rows(), total_capital=100000)

    amap = {a["symbol"]: a for a in result["allocations"]}
    assert amap["510300"]["change_pct"] == pytest.approx(0.64)
    assert amap["510300"]["estimate_source"] is None
    # 场外经 tracked_index 估值
    assert amap["022449"]["change_pct"] == pytest.approx(0.5)
    assert amap["022449"]["estimate_source"] == "tracked_index"


@pytest.mark.asyncio
async def test_partial_batch_failure_marks_only_missing():
    """部分缺失（场外 ti 缺席且 nav 无数据）→ 仅缺失条目标 unavailable，真实值不动。"""
    batch = [{"symbol": "510300", "price": 3.95, "change_pct": 0.64, "volume": 100}]
    with patch("app.services.market_data_hub.market_data_hub.get_a_stock_batch",
               new=MagicMock(return_value=batch)), \
         patch("app.services.market_data_hub.market_data_hub.get_fund_nav",
               new=MagicMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_us_etf_realtime",
               new=MagicMock(return_value=None)), \
         patch("app.services.market_data_hub.market_data_hub.get_index_realtime",
               new=MagicMock(return_value=[])):
        result = await calculate_allocation(etfs=_rows(), total_capital=100000)

    amap = {a["symbol"]: a for a in result["allocations"]}
    assert amap["510300"]["change_pct"] == pytest.approx(0.64)
    assert amap["022449"]["estimate_source"] == "unavailable"
    assert amap["022449"]["change_pct"] is None
