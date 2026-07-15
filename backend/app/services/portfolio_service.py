from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from ..models.portfolio import PortfolioETF
from ..models.schemas import PortfolioETFCreate, PortfolioETFUpdate
from ..fetchers.china_market import fetch_a_stock_batch, fetch_fund_nav, fetch_hk_stock_realtime, fetch_index_realtime
from ..fetchers.yfinance_fetcher import fetch_us_etf_realtime
from ..fetchers.fundamental_fetcher import fetch_fundamentals
from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news
from ..analysis.indicators import compute_all_indicators
from ..analysis.signal import generate_signal
from .market_service import get_history, get_indices, get_commodities

PORTFOLIO_TYPES = {"on_exchange": "场内", "off_exchange": "场外"}


async def list_etfs(db: AsyncSession, portfolio_type: str | None = None) -> list[PortfolioETF]:
    q = select(PortfolioETF).where(PortfolioETF.is_active == True)
    if portfolio_type:
        q = q.where(PortfolioETF.portfolio_type == portfolio_type)
    result = await db.execute(q)
    return list(result.scalars().all())


async def add_etf(db: AsyncSession, data: PortfolioETFCreate) -> PortfolioETF:
    etf = PortfolioETF(
        symbol=data.symbol,
        name=data.name,
        short_name=data.short_name or data.name,
        asset_type=data.asset_type,
        target_weight=data.target_weight,
        portfolio_type=data.portfolio_type,
        tracked_index=data.tracked_index,
    )
    db.add(etf)
    await db.commit()
    await db.refresh(etf)
    return etf


async def update_etf(db: AsyncSession, symbol: str, data: PortfolioETFUpdate) -> PortfolioETF | None:
    result = await db.execute(select(PortfolioETF).where(
        PortfolioETF.symbol == symbol, PortfolioETF.is_active == True
    ))
    etf = result.scalar_one_or_none()
    if not etf:
        return None
    if data.name is not None:
        etf.name = data.name
    if data.target_weight is not None:
        etf.target_weight = data.target_weight
    if data.is_active is not None:
        etf.is_active = data.is_active
    if data.portfolio_type is not None:
        etf.portfolio_type = data.portfolio_type
    if data.short_name is not None:
        etf.short_name = data.short_name
    if data.tracked_index is not None:
        etf.tracked_index = data.tracked_index
    await db.commit()
    await db.refresh(etf)
    return etf


async def remove_etf(db: AsyncSession, symbol: str) -> bool:
    result = await db.execute(select(PortfolioETF).where(
        PortfolioETF.symbol == symbol, PortfolioETF.is_active == True
    ))
    etf = result.scalar_one_or_none()
    if not etf:
        return False
    etf.is_active = False
    await db.commit()
    return True


async def build_price_map(etfs: list[PortfolioETF | dict]) -> dict[str, tuple[float, float]]:
    """公开包装器，将同步 _build_price_map 放入线程池执行。"""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _build_price_map, etfs)


def _build_price_map(etfs: list[PortfolioETF | dict]) -> dict[str, tuple[float, float]]:
    """批量获取一组持仓的实时价格，返回 {symbol: (price, change_pct)} 映射表。"""
    from ..fetchers.china_market import (
        fetch_a_stock_batch, fetch_fund_nav, fetch_hk_stock_realtime, fetch_index_realtime,
    )

    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)

    a_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "A" and _get_attr(e, "symbol", "")[:1] in ("1", "5", "6")]
    hk_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "HK"]
    us_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "US"]
    # 离岸/场外 ETF 按 tracked_index 获取实时行情
    tracked_a = [_get_attr(e, "tracked_index") for e in etfs if _get_attr(e, "tracked_index") and _get_attr(e, "tracked_index", "")[:1] in ("1", "5", "6")]
    a_symbols = a_symbols + tracked_a
    m: dict[str, tuple[float, float]] = {}

    if a_symbols:
        try:
            all_a = fetch_a_stock_batch(a_symbols)
            for item in all_a:
                m[item["symbol"]] = (item["price"], item["change_pct"])
        except Exception:
            pass

    if hk_symbols:
        try:
            for s in hk_symbols:
                items = fetch_hk_stock_realtime(s)
                if items:
                    item = items[0]
                    m[s] = (item["price"], item["change_pct"])
        except Exception:
            pass

    for s in us_symbols:
        try:
            data = fetch_us_etf_realtime(s)
            if data:
                m[s] = (data["price"], data["change_pct"])
        except Exception:
            pass

    # Also fetch tracked indices for off-exchange funds
    tracked = list({_get_attr(e, "tracked_index") for e in etfs if _get_attr(e, "tracked_index") and _get_attr(e, "tracked_index") not in m})
    if tracked:
        try:
            all_idx = fetch_index_realtime()
            for item in all_idx:
                if item["symbol"] in tracked:
                    m[item["symbol"]] = (item["price"], item["change_pct"])
        except Exception:
            pass
        # Fallback: compute change from NAV if still missing
        for t in tracked:
            if t not in m:
                try:
                    nav_data = fetch_fund_nav(t)
                    if nav_data:
                        # Handle both tuple (price, change_pct) and dict return
                        if isinstance(nav_data, tuple) and len(nav_data) >= 1:
                            m[t] = (float(nav_data[0]), float(nav_data[1]) if len(nav_data) > 1 else 0.0)
                        elif isinstance(nav_data, dict) and nav_data.get("nav") and nav_data.get("nav_date"):
                            from datetime import datetime, timedelta
                            nav = float(nav_data["nav"])
                            nav_date = datetime.strptime(nav_data["nav_date"], "%Y-%m-%d")
                            if (datetime.now() - nav_date).days <= 3:
                                m[t] = (nav, 0.0)
                except Exception:
                    pass

    # Map tracked_index prices to fund symbols for off-exchange funds
    for e in etfs:
        sym = _get_attr(e, "symbol")
        ti = _get_attr(e, "tracked_index")
        if ti and ti in m and sym not in m:
            m[sym] = m[ti]

    return m


async def calculate_allocation(
    db: AsyncSession | None = None,
    total_capital: float = 0.0,
    portfolio_type: str | None = None,
    etfs: list[PortfolioETF] | None = None,
) -> dict[str, Any]:
    if etfs is None:
        etfs = await list_etfs(db, portfolio_type)
    weight_sum = sum(e.target_weight for e in etfs)
    if weight_sum <= 0:
        return {"total_capital": total_capital, "allocations": []}

    price_map = _build_price_map(etfs)
    allocations = []
    total_amount = 0.0
    for e in etfs:
        # 注意：使用原始权重（不按 weight_sum 归一化），使 cash 权重 = 1 - weight_sum 有意义
        target_amount = total_capital * e.target_weight
        total_amount += target_amount
        price, change_pct = price_map.get(e.symbol, (0, 0))
        is_estimated = False
        estimate_source = None
        # For off-exchange with tracked index, use tracked_index change
        if e.portfolio_type == "off_exchange" and e.tracked_index:
            _, change_pct = price_map.get(e.tracked_index, (0, 0))
            is_estimated = True
            estimate_source = "tracked_index"

        # 基本面数据（A 股 ETF）
        fundamentals = {}
        if e.asset_type == "A":
            try:
                fundamentals = fetch_fundamentals(e.symbol)
            except Exception:
                pass

        alloc = {
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
            **fundamentals,
        }
        allocations.append(alloc)

    cash_weight = max(0.0, 1.0 - weight_sum)
    cash_amount = round(total_capital * cash_weight, 2)
    return {
        "total_capital": total_capital,
        "allocations": allocations,
        "total_amount": round(total_amount, 2),
        "cash_weight": cash_weight,
        "cash_amount": cash_amount,
    }


async def calculate_daily_pnl(
    db: AsyncSession | None = None,
    total_capital: float = 0.0,
    portfolio_type: str | None = None,
    etfs: list[PortfolioETF] | None = None,
) -> dict[str, Any]:
    """返回每只基金的当日盈亏和汇总。场外基金使用跟踪指数的涨跌幅作为预估收益。"""
    if etfs is None:
        etfs = await list_etfs(db, portfolio_type)
    allocation = await calculate_allocation(db, total_capital, portfolio_type, etfs)
    etf_map = {e.symbol: e for e in etfs}
    etf_map = {e.symbol: e for e in etfs}
    pnl_items = []
    total_pnl = 0.0
    total_amount = 0.0
    weighted_change_sum = 0.0

    for a in allocation["allocations"]:
        e = etf_map.get(a["symbol"])
        price = a["current_price"]
        change_pct = a["change_pct"]
        target_amount = a["target_amount"]
        daily_pnl = target_amount * change_pct / 100.0
        total_pnl += daily_pnl
        total_amount += target_amount
        if target_amount:
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
            "daily_pnl": round(daily_pnl, 2),
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


async def strategy_check(db: AsyncSession, total_capital: float, design_data: dict | None = None) -> dict[str, Any]:
    from ..analysis.llm import generate_strategy_suggestions
    
    # Use design_data if provided, otherwise fall back to DB ETFs
    use_design = False
    if design_data and design_data.get("plans"):
        plan = design_data["plans"][0] if design_data["plans"] else None
        if plan and plan.get("allocations"):
            etfs = []
            for alloc in plan["allocations"]:
                etfs.append({
                    "symbol": alloc.get("symbol"),
                    "name": alloc.get("name", alloc.get("symbol")),
                    "short_name": alloc.get("short_name", alloc.get("symbol")),
                    "asset_type": "ETF",
                    "portfolio_type": "on_exchange",
                    "target_weight": alloc.get("target_weight", 0),
                })
            use_design = True
        else:
            etfs = await list_etfs(db)
    else:
        etfs = await list_etfs(db)
    
    if not etfs:
        return {"summary": "组合为空，请先添加ETF或生成组合方案", "suggestions": []}
    
    # Build price map - handle both SQLAlchemy objects and dicts
    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)
    
    price_map = await _build_price_map(etfs)
    market_data = []
    indicators = {}
    for e in etfs:
        symbol = _get_attr(e, "symbol")
        price, change_pct = price_map.get(symbol, (0, 0))
        market_data.append({
            "symbol": symbol,
            "name": _get_attr(e, "name", symbol),
            "short_name": _get_attr(e, "short_name", symbol),
            "price": price, "change_pct": change_pct,
            "asset_type": _get_attr(e, "asset_type", "ETF"),
            "portfolio_type": _get_attr(e, "portfolio_type", "on_exchange"),
            "target_weight": _get_attr(e, "target_weight", 0),
            "target_amount": round(total_capital * _get_attr(e, "target_weight", 0) / sum(_get_attr(ee, "target_weight", 0) for ee in etfs), 2),
        })
        try:
            hist = await get_history(symbol, _get_attr(e, "asset_type", "ETF"))
            ind = compute_all_indicators(hist)
            sig = generate_signal(ind)
            if ind:
                ind["signal"] = sig
                indicators[symbol] = ind
        except Exception:
            continue

    indices = await get_indices()
    commodities = await get_commodities()
    news = fetch_news_headlines()[:8]
    macro_news_raw = []
    try:
        macro_news_raw = fetch_macro_news()[:5]
        news.extend(macro_news_raw)
    except Exception:
        pass

    llm_result = await generate_strategy_suggestions(market_data, indicators, news, macro_news_raw, indices, commodities)
    return {
        "summary": llm_result.get("summary", ""),
        "suggestions": llm_result.get("suggestions", []),
        "raw_llm": str(llm_result),
    }


# 应用策略
async def apply_strategy_suggestions(db: AsyncSession, suggestions: list) -> dict[str, Any]:
    """应用策略建议到持仓"""
    try:
        # 获取所有持仓
        etfs = await list_etfs(db)
        if not etfs:
            return {"symbols": [], "applied_suggestions": suggestions, "message": "无持仓可应用策略"}

        etf_dict = {etf.symbol: etf for etf in etfs}

        applied = []
        for s in suggestions:
            action = s.get("action")
            symbol = s.get("symbol")
            suggested_weight = s.get("suggested_weight", s.get("target_weight", 0))
            if symbol in etf_dict:
                e = etf_dict[symbol]
                if action == "increase" or action == "decrease" or action == "adjust_weight":
                    e.target_weight = max(0, min(0.5, suggested_weight))
                    applied.append({"symbol": symbol, "name": e.name, "target_weight": e.target_weight, "portfolio_type": e.portfolio_type, "action": "updated"})
                elif action == "remove":
                    e.is_active = False
                    applied.append({"symbol": symbol, "name": e.name, "portfolio_type": e.portfolio_type, "action": "removed"})

        await db.commit()
        updated = await list_etfs(db)
        return {"symbols": [{"symbol": e.symbol, "name": e.name, "target_weight": e.target_weight, "portfolio_type": e.portfolio_type} for e in updated], "applied": applied}
    except Exception as e:
        await db.rollback()
        raise e


async def apply_portfolio_design(db: AsyncSession, design: dict) -> dict[str, Any]:
    """根据组合设计应用持仓"""
    try:
        portfolio_type = design.get("portfolio_type", "on_exchange")
        symbols = design.get("symbols", [])
        weights = design.get("weights", {})
        if not symbols:
            return {"symbols": [], "message": "组合设计中没有指定持仓"}

        etfs = await list_etfs(db)
        etf_dict = {e.symbol: e for e in etfs}
        applied = []
        for symbol in symbols:
            w = max(0, min(0.5, weights.get(symbol, 0.1)))
            if symbol in etf_dict:
                e = etf_dict[symbol]
                e.target_weight = w
                e.portfolio_type = portfolio_type
                applied.append({"symbol": symbol, "name": e.name, "target_weight": w, "portfolio_type": portfolio_type, "action": "updated"})
            else:
                new_etf = PortfolioETF(symbol=symbol, name=f"{symbol} ETF", short_name=symbol, asset_type="ETF",
                    target_weight=w, portfolio_type=portfolio_type, tracked_index=None, is_active=True)
                db.add(new_etf)
                applied.append({"symbol": symbol, "name": new_etf.name, "target_weight": w, "portfolio_type": portfolio_type, "action": "added"})

        await db.commit()
        updated = await list_etfs(db)
        return {"symbols": [{"symbol": e.symbol, "name": e.name, "target_weight": e.target_weight, "portfolio_type": e.portfolio_type} for e in updated], "applied": applied}
    except Exception as e:
        await db.rollback()
        raise e