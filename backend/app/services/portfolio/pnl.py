"""Daily / cumulative P&L — split from portfolio_service (Batch 1)."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioETF
from app.services.portfolio._facade_refs import (
    build_price_map,
    calculate_allocation,
    list_etfs,
)

logger = logging.getLogger(__name__)




async def calculate_daily_pnl(
    db: AsyncSession | None = None,
    total_capital: float = 0.0,
    portfolio_type: str | None = None,
    etfs: list[PortfolioETF] | None = None,
) -> dict[str, Any]:
    """返回每只基金的当日盈亏和汇总。场外基金使用跟踪指数的涨跌幅作为预估收益。"""
    if etfs is None:
        etfs = await list_etfs(db, portfolio_type)
    allocation = await calculate_allocation(db, total_capital, portfolio_type, etfs, skip_fundamentals=True)
    pnl_items = []
    total_pnl = 0.0
    total_amount = 0.0
    weighted_change_sum = 0.0

    for a in allocation["allocations"]:
        price = a["current_price"]
        change_pct = a["change_pct"]
        target_amount = a["target_amount"]
        # R175 (round52 §7.3 方案C): 行情不可用（change_pct=None）→ daily_pnl=None
        # 诚实空值——不参与 total_pnl/weighted 汇总（不可用 ≠ 盈亏为 0）。
        daily_pnl = (target_amount * change_pct / 100.0) if change_pct is not None else None
        total_pnl += daily_pnl or 0.0
        total_amount += target_amount
        if target_amount and change_pct is not None:
            weighted_change_sum += change_pct * target_amount
        pnl_items.append({
            "symbol": a["symbol"],
            "name": a["name"],
            "short_name": a["short_name"],
            "asset_type": a["asset_type"],
            "portfolio_type": a["portfolio_type"],
            "target_amount": target_amount,
            "current_price": price,
            "change_pct": change_pct,
            "daily_pnl": round(daily_pnl, 2) if daily_pnl is not None else None,
            "tracked_index": a.get("tracked_index"),
            "is_estimated": a.get("is_estimated", False),
            "estimate_source": a.get("estimate_source"),
            "shares_outstanding": a.get("shares_outstanding"),
            "fund_scale": a.get("fund_scale"),
            "pe_ttm": a.get("pe_ttm"),
            "pb": a.get("pb"),
            "main_net_inflow": a.get("main_net_inflow"),
            "main_net_inflow_pct": a.get("main_net_inflow_pct"),
        })

    weighted_change_pct = (weighted_change_sum / total_amount) if total_amount else 0.0
    return {
        "items": pnl_items,
        "total_pnl": round(total_pnl, 2),
        "total_amount": round(total_amount, 2),
        "weighted_change_pct": round(weighted_change_pct, 2),
    }


async def calculate_cumulative_pnl(
    db: AsyncSession,
    portfolio_type: str | None = None,
    period: str = "all",
    total_capital: float = 0.0,
) -> dict[str, Any]:
    """
    Calculate cumulative P&L based on cost basis and shares held.
    When cost basis data is missing, estimate from target allocation if total_capital is provided.
    """
    etfs = await list_etfs(db, portfolio_type)
    if not etfs:
        return {"summary": {}, "holdings": [], "daily_series": []}

    price_map = await build_price_map(etfs)

    holdings_pnl = []
    total_cost_basis = 0.0
    total_market_value = 0.0
    has_real_data = False
    # R65: 估算成本累计（估算占比 = estimated_cost_basis / total_cost_basis）
    estimated_cost_basis = 0.0
    est_cost_by_type = {"on_exchange": 0.0, "off_exchange": 0.0}

    for e in etfs:
        price, _ = price_map.get(e.symbol, (0.0, 0.0))

        # Only calculate if we have cost basis data
        if e.avg_cost is not None and e.shares_held is not None and e.shares_held > 0:
            cost_basis = e.cost_basis or (e.avg_cost * e.shares_held)
            market_value = e.shares_held * price
            cumulative_pnl = market_value - cost_basis
            cumulative_pnl_pct = (cumulative_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
            has_real_data = True

            total_cost_basis += cost_basis
            total_market_value += market_value

            holdings_pnl.append({
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "shares_held": e.shares_held,
                "avg_cost": e.avg_cost,
                "cost_basis": round(cost_basis, 2),
                "current_price": price,
                "market_value": round(market_value, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
                "first_buy_date": e.first_buy_date.isoformat() if e.first_buy_date else None,
                "last_trade_date": e.last_trade_date.isoformat() if e.last_trade_date else None,
                "estimated": False,
            })
        elif e.avg_cost is not None and total_capital > 0 and e.target_weight > 0:
            # R64: 有 avg_cost 但无份额——按目标权重估算份额，成本用用户录入的 avg_cost
            # （旧逻辑用 current price 当成本 → 累计盈亏恒为 0、成本价零贡献）
            target_amount = total_capital * e.target_weight
            pt = e.portfolio_type or ""
            if pt == "off_exchange":
                # P1-6 (R4-21): 场外累计盈亏口径修复——联接基金不再混用
                # 「场内 ETF 实时价折算份额」与「联接基金净值成本」（两者量级差
                # 2-5 倍：半导体联接C avg_cost=3.534 vs 场内 0.67，成本被错误放大）。
                # 唯一口径：份额按联接净值折算 → 成本=投入本金；市值按跟踪指数
                # 涨跌幅估算（场内对应 ETF change_pct 作代理）；无涨跌幅时降级
                # market_value=本金（盈亏 0，标注「净值变动暂缺」）。
                if e.avg_cost > 0:
                    est_shares = target_amount / e.avg_cost
                    cost_basis = target_amount
                    _, change_pct = price_map.get(e.symbol, (0.0, 0.0))
                    has_chg = isinstance(change_pct, (int, float)) and abs(change_pct) > 1e-9
                    market_value = target_amount * (1 + change_pct / 100.0) if has_chg else target_amount
                    cumulative_pnl = market_value - cost_basis
                    cumulative_pnl_pct = (cumulative_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
                    estimate_note = "" if has_chg else "净值变动暂缺"
                    # 019633 avg_cost=3.534 经用户确认为真实申购成本（a94c0af 决策）
                    # ——非录入错误，无需 WARN 提示核对；新口径（联接净值折算）下
                    # 单只盈亏率即真实语义。
                else:
                    # avg_cost 异常（<=0）→ 无法按净值折算，降级按本金估算（盈亏 0）
                    est_shares = 0.0
                    cost_basis = target_amount
                    market_value = target_amount
                    cumulative_pnl = 0.0
                    cumulative_pnl_pct = 0.0
                    estimate_note = "净值变动暂缺"
            elif price > 0:
                # on_exchange：场内价与场内 avg_cost 同单位，无错配（保持原口径）
                est_shares = target_amount / price
                cost_basis = est_shares * e.avg_cost
                market_value = est_shares * price
                cumulative_pnl = market_value - cost_basis
                cumulative_pnl_pct = (cumulative_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
                estimate_note = ""
            else:
                # R67⑤: on_exchange 且 price=0 → 无法估算，但仍计入 has_real_data
                has_real_data = True
                continue
            has_real_data = True
            estimated_cost_basis += cost_basis
            if pt in est_cost_by_type:
                est_cost_by_type[pt] += cost_basis

            total_cost_basis += cost_basis
            total_market_value += market_value

            holdings_pnl.append({
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "shares_held": round(est_shares, 2),
                "avg_cost": e.avg_cost,
                "cost_basis": round(cost_basis, 2),
                "current_price": price,
                "market_value": round(market_value, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
                "first_buy_date": getattr(e, 'first_buy_date', None).isoformat() if getattr(e, 'first_buy_date', None) else None,
                "last_trade_date": getattr(e, 'last_trade_date', None).isoformat() if getattr(e, 'last_trade_date', None) else None,
                "estimated": True,
                "estimate_note": estimate_note,
            })
        elif total_capital > 0 and price > 0 and e.target_weight > 0:
            # 无 avg_cost——旧估算逻辑（price 当成本，PnL 从 0 起，不置 has_real_data）
            est_shares = (total_capital * e.target_weight) / price
            # Use current price as estimated avg cost (cumulative PnL starts at 0)
            cost_basis = est_shares * price
            market_value = est_shares * price
            cumulative_pnl = 0.0
            cumulative_pnl_pct = 0.0

            total_cost_basis += cost_basis
            total_market_value += market_value

            holdings_pnl.append({
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "shares_held": round(est_shares, 2),
                "avg_cost": price,
                "cost_basis": round(cost_basis, 2),
                "current_price": price,
                "market_value": round(market_value, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
                "first_buy_date": getattr(e, 'first_buy_date', None).isoformat() if getattr(e, 'first_buy_date', None) else None,
                "last_trade_date": getattr(e, 'last_trade_date', None).isoformat() if getattr(e, 'last_trade_date', None) else None,
                "estimated": True,
            })
        elif e.avg_cost is not None:
            # R67⑤: 有 avg_cost 但无法估算（capital/price/weight 任一为 0）→
            # 跳过估算但仍计入 has_real_data（前端据此显示盈亏区而非"需输入成本"）
            has_real_data = True

    total_cumulative_pnl = total_market_value - total_cost_basis
    total_cumulative_pnl_pct = (total_cumulative_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0

        # Build by_type summary: aggregate PnL by portfolio_type
    by_type = {"on_exchange": {"cumulative_pnl": 0.0, "cumulative_pnl_pct": 0.0,
                                "estimated_cost_basis": 0.0, "estimated_ratio": 0.0},
               "off_exchange": {"cumulative_pnl": 0.0, "cumulative_pnl_pct": 0.0,
                                "estimated_cost_basis": 0.0, "estimated_ratio": 0.0}}
    on_cost = 0.0
    off_cost = 0.0
    for h in holdings_pnl:
        pt = h.get("portfolio_type", "")
        pnl = h.get("cumulative_pnl", 0.0)
        cost = h.get("cost_basis", 0.0) or 0.0
        if pt == "on_exchange":
            by_type["on_exchange"]["cumulative_pnl"] += pnl
            on_cost += cost
        elif pt == "off_exchange":
            by_type["off_exchange"]["cumulative_pnl"] += pnl
            off_cost += cost
    by_type["on_exchange"]["cumulative_pnl_pct"] = round((by_type["on_exchange"]["cumulative_pnl"] / on_cost * 100), 2) if on_cost > 0 else 0.0
    by_type["off_exchange"]["cumulative_pnl_pct"] = round((by_type["off_exchange"]["cumulative_pnl"] / off_cost * 100), 2) if off_cost > 0 else 0.0
    # R65: by_type 估算占比（estimated_cost_basis / total_cost_basis）
    by_type["on_exchange"]["estimated_cost_basis"] = round(est_cost_by_type["on_exchange"], 2)
    by_type["on_exchange"]["estimated_ratio"] = round(est_cost_by_type["on_exchange"] / on_cost, 4) if on_cost > 0 else 0.0
    by_type["off_exchange"]["estimated_cost_basis"] = round(est_cost_by_type["off_exchange"], 2)
    by_type["off_exchange"]["estimated_ratio"] = round(est_cost_by_type["off_exchange"] / off_cost, 4) if off_cost > 0 else 0.0

    daily_series = []

    return {
        "summary": {
            "total_cost_basis": round(total_cost_basis, 2),
            "total_market_value": round(total_market_value, 2),
            "total_cumulative_pnl": round(total_cumulative_pnl, 2),
            "total_cumulative_pnl_pct": round(total_cumulative_pnl_pct, 2),
            "annualized_return": None,
            "max_drawdown": None,
            "sharpe_ratio": None,
            "has_cost_basis_data": has_real_data,
            # R65: 估算占比——前端据此显示"含估算成本"提示
            "estimated_cost_basis": round(estimated_cost_basis, 2),
            "estimated_ratio": round(estimated_cost_basis / total_cost_basis, 4) if total_cost_basis > 0 else 0.0,
            "by_type": by_type,
        },
        "holdings": holdings_pnl,
        "daily_series": daily_series,
    }
