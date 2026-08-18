"""Allocation / weight-drift calculations — split from portfolio_service (Batch 1)."""

import asyncio
import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_utils import run_sync
from app.services.market_data_hub import market_data_hub
from app.models.portfolio import PortfolioETF
from app.services.portfolio.pricing import _FUNDAMENTALS_CACHE, _PRICE_MAP_TTL
from app.services.portfolio._facade_refs import list_etfs, build_price_map

logger = logging.getLogger(__name__)




async def calculate_allocation(
    db: AsyncSession | None = None,
    total_capital: float = 0.0,
    portfolio_type: str | None = None,
    etfs: list[PortfolioETF] | None = None,
    skip_fundamentals: bool = False,
) -> dict[str, Any]:
    if etfs is None:
        etfs = await list_etfs(db, portfolio_type)
    weight_sum = sum(e.target_weight for e in etfs)
    if weight_sum <= 0:
        return {"total_capital": total_capital, "allocations": []}

    price_map = await build_price_map(etfs)
    allocations = []
    total_amount = 0.0

    # 第一遍：构建不含基本面的 allocation 字典
    for e in etfs:
        target_amount = total_capital * e.target_weight
        total_amount += target_amount
        price, change_pct = price_map.get(e.symbol, (0, 0))
        is_estimated = False
        estimate_source = None
        if e.portfolio_type == "off_exchange" and e.tracked_index:
            _, change_pct = price_map.get(e.tracked_index, (0, 0))
            is_estimated = True
            estimate_source = "tracked_index"

        avg_cost = getattr(e, 'avg_cost', None)
        shares_held = getattr(e, 'shares_held', None)
        cost_basis = round(avg_cost * shares_held, 2) if (avg_cost is not None and shares_held is not None) else None

        allocations.append({
            "symbol": e.symbol,
            "name": e.name,
            "short_name": e.short_name or e.name,
            "asset_type": e.asset_type,
            "portfolio_type": e.portfolio_type,
            "target_weight": e.target_weight,
            "target_amount": round(target_amount, 2),
            "current_price": price,
            "change_pct": change_pct,
            "shares": round(target_amount / price, 2) if price else 0,
            "tracked_index": e.tracked_index,
            "is_estimated": is_estimated,
            "estimate_source": estimate_source,
            "avg_cost": avg_cost,
            "shares_held": shares_held,
            "cost_basis": cost_basis,
            "first_buy_date": getattr(e, 'first_buy_date', None).isoformat() if getattr(e, 'first_buy_date', None) else None,
            "last_trade_date": getattr(e, 'last_trade_date', None).isoformat() if getattr(e, 'last_trade_date', None) else None,
        })

    # 第二遍：并行获取 A 股 ETF 基本面数据（仅当 skip_fundamentals=False）
    if not skip_fundamentals:
        a_etf_indices = [i for i, e in enumerate(etfs) if e.asset_type == "A"]
        if a_etf_indices:
            symbols = [(idx, etfs[idx].symbol) for idx in a_etf_indices]
            _fkey = tuple(sorted(s for _, s in symbols))
            _now = time.monotonic()
            _fcached = _FUNDAMENTALS_CACHE.get(_fkey)
            if _fcached and (_now - _fcached[0]) < _PRICE_MAP_TTL:
                sym_task_map = _fcached[1]
            else:
                sym_task_map = {}
                async def _fetch_all_fundamentals():
                    nonlocal sym_task_map
                    # U5 R1/R2: 单标的 3s 快速失败（数据源 3s 无响应即返回空 dict，
                    # 不占满 8s）+ asyncio.Semaphore(4) 限并发（避免 10 路同打
                    # 同一数据源触发限流）——旧实现 8s×并发 gather + 10s 总预算
                    # 实测 8.2s（某标的 fundamentals 接近超时）
                    _sem = asyncio.Semaphore(4)

                    async def _one(sym: str) -> dict:
                        async with _sem:
                            try:
                                return await asyncio.wait_for(
                                    run_sync(market_data_hub.get_fundamentals, sym, timeout=8),
                                    timeout=3.0,
                                )
                            except (asyncio.TimeoutError, Exception):
                                return {}

                    results = await asyncio.gather(*[_one(sym) for _, sym in symbols])
                    sym_task_map = {sym: res for (_, sym), res in zip(symbols, results)}
                try:
                    await asyncio.wait_for(_fetch_all_fundamentals(), timeout=5.0)
                except Exception:
                    pass
                _FUNDAMENTALS_CACHE[_fkey] = (time.monotonic(), sym_task_map)
            for idx, sym in [(idx, etfs[idx].symbol) for idx in a_etf_indices]:
                result = sym_task_map.get(sym)
                if result and not isinstance(result, Exception):
                    allocations[idx].update(result)

    cash_weight = max(0.0, 1.0 - weight_sum)
    cash_amount = round(total_capital * cash_weight, 2)
    return {
        "total_capital": total_capital,
        "allocations": allocations,
        "total_amount": round(total_amount, 2),
        "cash_weight": cash_weight,
        "cash_amount": cash_amount,
    }


def recompute_cost_after_trade(
    old_shares: float | None,
    old_avg_cost: float | None,
    delta_shares: float,
    price: float,
) -> dict:
    """round19 P3-③ (2026-08-12): 仓位变更 = 买卖操作，加权平均重算成本价。

    - 买入（delta>0）: new_avg_cost = (old*old_avg + delta*price) / (old + delta)；realized_pnl = 0
    - 卖出（delta<0，new_shares ≥ 0）: new_avg_cost 不变；realized_pnl = (price - old_avg_cost) * (-delta)
    - 首仓（old_shares 空/0）: new_avg_cost = price
    - 边界: 卖出超份额 → ValueError（调用方 400）；price 缺失/无效 → ValueError（不用假价）

    纯函数无 I/O，供 PUT /etfs/{symbol} adjust 语义与存量迁移复用。
    """
    if delta_shares == 0:
        raise ValueError("delta_shares 不能为 0")
    if price is None or price <= 0:
        raise ValueError("成交价缺失/无效（不用假价兜底）")
    old_shares = old_shares or 0.0
    old_avg_cost = old_avg_cost or 0.0
    if delta_shares < 0 and old_shares + delta_shares < 0:
        raise ValueError(f"卖出份额 {abs(delta_shares)} 超过持仓 {old_shares}")
    if old_shares <= 0:
        # 首仓：成本 = 成交价
        new_avg_cost = price
        new_shares = delta_shares if delta_shares > 0 else 0.0
        realized_pnl = 0.0
    elif delta_shares > 0:
        new_avg_cost = (old_shares * old_avg_cost + delta_shares * price) / (old_shares + delta_shares)
        new_shares = old_shares + delta_shares
        realized_pnl = 0.0
    else:  # 卖出
        new_avg_cost = old_avg_cost
        new_shares = old_shares + delta_shares
        realized_pnl = (price - old_avg_cost) * (-delta_shares)
    return {
        "new_avg_cost": round(float(new_avg_cost), 6),
        "new_shares": round(float(new_shares), 6),
        "realized_pnl": round(float(realized_pnl), 4),
        "side": "buy" if delta_shares > 0 else "sell",
    }


async def calculate_weight_drift(
    db: AsyncSession,
    portfolio_type: str | None = None,
) -> dict[str, Any]:
    """
    Calculate actual vs target weight deviation for each holding.
    """
    etfs = await list_etfs(db, portfolio_type)
    if not etfs:
        return {"items": [], "alerts": []}
    
    price_map = await build_price_map(etfs)
    
    # Calculate total portfolio value
    total_value = 0.0
    for e in etfs:
        price, _ = price_map.get(e.symbol, (0.0, 0.0))
        if e.shares_held and e.shares_held > 0:
            total_value += e.shares_held * price
        else:
            # Use target_amount as fallback
            total_value += total_value * e.target_weight if total_value > 0 else 0
    
    items = []
    alerts = []
    
    for e in etfs:
        price, change_pct = price_map.get(e.symbol, (0.0, 0.0))
        shares = e.shares_held or 0
        market_value = shares * price
        actual_weight = (market_value / total_value) if total_value > 0 else 0
        target_weight = e.target_weight
        deviation = actual_weight - target_weight
        deviation_pct = (deviation / target_weight * 100) if target_weight > 0 else 0
        
        item = {
            "symbol": e.symbol,
            "name": e.name,
            "target_weight": target_weight,
            "actual_weight": round(actual_weight, 4),
            "deviation": round(deviation, 4),
            "deviation_pct": round(deviation_pct, 2),
            "market_value": round(market_value, 2),
            "needs_rebalance": abs(deviation_pct) > 20,  # Alert threshold: 20%
        }
        items.append(item)
        
        if abs(deviation_pct) > 20:
            alerts.append({
                "symbol": e.symbol,
                "name": e.name,
                "message": f"权重偏离 {deviation_pct:.1f}% (目标 {target_weight:.1%}, 实际 {actual_weight:.1%})",
                "severity": "warning" if abs(deviation_pct) < 50 else "critical",
            })
    
    return {"items": items, "alerts": alerts}
