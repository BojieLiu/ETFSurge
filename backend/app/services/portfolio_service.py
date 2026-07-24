from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import asyncio
import logging

logger = logging.getLogger(__name__)

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
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _build_price_map, etfs),
            timeout=30.0
        )
    except (asyncio.TimeoutError, Exception):
        return {}


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

    # 第二遍：并行获取 A 股 ETF 基本面数据（在线程池运行，总超时 15 秒）
    a_etf_indices = [i for i, e in enumerate(etfs) if e.asset_type == "A"]
    if a_etf_indices:
        loop = asyncio.get_event_loop()
        async def _fetch_all_fundamentals():
            tasks = {}
            for idx in a_etf_indices:
                sym = etfs[idx].symbol
                fut = loop.run_in_executor(None, fetch_fundamentals, sym)
                tasks[sym] = fut
            done, _ = await asyncio.wait(tasks.values(), timeout=12.0)
            for idx in a_etf_indices:
                sym = etfs[idx].symbol
                fut = tasks[sym]
                if fut in done:
                    try:
                        result = fut.result()
                        if result:
                            allocations[idx].update(result)
                    except Exception:
                        pass
        try:
            await asyncio.wait_for(_fetch_all_fundamentals(), timeout=15.0)
        except Exception:
            pass

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


import time as _time
_strategy_check_cache: dict[str, tuple[float, dict]] = {}  # key -> (timestamp, result)

async def strategy_check(
    db: AsyncSession,
    total_capital: float,
    design_data: dict | None = None,
    portfolio_type: str | None = None,
) -> dict[str, Any]:
    """v2: 因子评分 + regime 感知 + 结构化输出（60s LRU 缓存避免重复采集）。"""
    from ..analysis.llm import generate_strategy_check_report
    from ..factors.factor_registry import registry as factor_registry
    
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
            etfs = await list_etfs(db, portfolio_type)
    else:
        etfs = await list_etfs(db, portfolio_type)
    
    if not etfs:
        return {"summary": "组合为空，请先添加ETF或生成组合方案", "suggestions": []}
    
    # Build price map - handle both SQLAlchemy objects and dicts
    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)
    
    # 组合持仓计算缓存 key（按 symbol 列表 + capital 去重）
    symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "symbol") != "CASH"]
    cache_key = "_".join(sorted(symbols) if symbols else ["empty"])
    cached = _strategy_check_cache.get(cache_key)
    if cached and _time.monotonic() - cached[0] < 60:
        logger.debug("[strategy_check] returning cached result")
        return cached[1]
    
    # 并行采集（带 30s 总超时，任一失败不影响整体结果）
    indicators_task = _compute_indicators(symbols)
    factor_task = factor_registry.compute(symbols)

    try:
        indicators, factor_scores = await asyncio.wait_for(
            asyncio.gather(indicators_task, factor_task, return_exceptions=True),
            timeout=30,
        )
    except asyncio.TimeoutError:
        logger.warning("[strategy_check] data collection timed out after 30s, using partial results")
        indicators, factor_scores = {}, {}

    indicators = indicators if isinstance(indicators, dict) else {}
    factor_scores = factor_scores if isinstance(factor_scores, dict) else {}

    # 市场状态统一从 pool_manager 读取（与设计管线一致，避免双套判定）
    try:
        from ..services.pool_manager import pool_manager
        regime = pool_manager.get_market_regime() or "range_bound"
    except Exception:
        regime = "range_bound"
    trends = {}
    index_realtime = []
    
    # 构建 market_data with allocation info
    price_map = await build_price_map(etfs)
    market_data = []
    factor_breakdowns = {}
    for e in etfs:
        symbol = _get_attr(e, "symbol")
        price, change_pct = price_map.get(symbol, (0, 0))
        target_w = _get_attr(e, "target_weight", 0)
        market_data.append({
            "symbol": symbol, "name": _get_attr(e, "name", symbol),
            "short_name": _get_attr(e, "short_name", symbol),
            "price": price, "change_pct": change_pct,
            "asset_type": _get_attr(e, "asset_type", "ETF"),
            "portfolio_type": _get_attr(e, "portfolio_type", "on_exchange"),
            "target_weight": target_w,
            "target_amount": round(total_capital * target_w, 2),
        })
        
        if symbol != "CASH":
            fb = factor_scores.get(symbol, {}) if isinstance(factor_scores, dict) else {}
            ind = indicators.get(symbol, {})
            sig = ind.get("signal", {}) if isinstance(ind, dict) else {}
            drift = None
            if market_data:
                pass
            factor_breakdowns[symbol] = {
                "factor_scores": fb if isinstance(fb, dict) else {},
                "technical_indicators": ind if isinstance(ind, dict) else {},
                "technical_signal": sig if isinstance(sig, dict) else {"signal": "hold"},
                "weight_drift": drift,
            }
    
    # 统计因子数据质量
    filled_factor_count = sum(
        1 for fb in factor_breakdowns.values()
        if fb.get("factor_scores") and any(v != 0 for v in fb["factor_scores"].values())
    )
    total_factor_count = len(factor_breakdowns)
    data_quality = {
        "filled_count": filled_factor_count,
        "total_count": total_factor_count,
        "all_empty": filled_factor_count == 0,
        "partial": 0 < filled_factor_count < total_factor_count,
    }

    # LLM 分析（provider timeout 负责，不再额外包裹 asyncio.wait_for）
    try:
        llm_result = await generate_strategy_check_report(
            market_data=market_data,
            factor_breakdowns=factor_breakdowns,
            regime=regime,
            data_quality=data_quality,
        )
    except asyncio.TimeoutError:
        logger.warning("[strategy_check] LLM analysis timed out, returning partial data")
        llm_result = {
            "summary": f"LLM 分析超时（基于 {len(market_data)} 只标的因子数据，未完成深度分析）",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
    except Exception as e:
        logger.warning("[strategy_check] LLM analysis failed: %s", e)
        llm_result = {
            "summary": f"LLM 分析暂不可用（{e}），返回因子数据摘要",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
    
    result = {
        "summary": llm_result.get("summary", ""),
        "suggestions": llm_result.get("suggestions", []),
        "holdings_analysis": llm_result.get("holdings_analysis", []),
        "risk_warnings": llm_result.get("risk_warnings", []),
        "market_regime": regime,
        "raw_llm": str(llm_result),
    }
    # 缓存 60s
    if cache_key:
        _strategy_check_cache[cache_key] = (_time.monotonic(), result)
    return result


async def _compute_indicators(symbols: list[str]) -> dict:
    """并行计算每只持仓的技术指标 + 信号。
    
    从 pool_manager 获取预计算的因子分矩阵传给 compute_all_indicators，
    避免重复计算 RSI/KDJ/MACD。
    """
    from .market_service import get_history
    from ..analysis.indicators import compute_all_indicators
    from ..analysis.signal import generate_signal

    # 复用 pool_manager 的因子分，免去重新计算 RSI/KDJ/MACD
    try:
        from ..services.pool_manager import pool_manager
        factor_matrix = pool_manager.get_factor_matrix()
    except Exception:
        factor_matrix = {}

    results = {}
    hist_data = await asyncio.gather(
        *[get_history(sym, "A") for sym in symbols],
        return_exceptions=True,
    )
    for sym, hist in zip(symbols, hist_data):
        if isinstance(hist, list) and hist:
            try:
                sym_factors = factor_matrix.get(sym, {})
                ind = compute_all_indicators(hist, factor_scores=sym_factors)
                sig = generate_signal(ind)
                ind["signal"] = sig
                results[sym] = ind
            except Exception:
                continue
    return results


async def _detect_regime(symbols: list[str]) -> tuple[dict, list, str]:
    """并行获取 trend + index → detect_market_regime。"""
    from .market_trends import compute_etf_trends, detect_market_regime
    from ..fetchers.china_market import fetch_index_realtime
    
    trends, index_realtime = await asyncio.gather(
        compute_etf_trends(symbols, ("5d", "1m", "3m")),
        asyncio.to_thread(fetch_index_realtime),
        return_exceptions=True,
    )
    trends = trends if isinstance(trends, dict) else {}
    index_realtime = index_realtime if isinstance(index_realtime, list) else []
    
    regime = detect_market_regime(
        trends=trends,
        broad_index_code="510300",
        index_realtime=index_realtime,
    )
    return trends, index_realtime, regime


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


# ── Cumulative P&L History / 累计盈亏历史 ──────────────────────────

async def calculate_cumulative_pnl(
    db: AsyncSession,
    portfolio_type: str | None = None,
    period: str = "all",
) -> dict[str, Any]:
    """
    Calculate cumulative P&L based on cost basis and shares held.
    """
    etfs = await list_etfs(db, portfolio_type)
    if not etfs:
        return {"summary": {}, "holdings": [], "daily_series": []}
    
    price_map = await build_price_map(etfs)
    
    holdings_pnl = []
    total_cost_basis = 0.0
    total_market_value = 0.0
    
    for e in etfs:
        price, _ = price_map.get(e.symbol, (0.0, 0.0))
        
        # Only calculate if we have cost basis data
        if e.avg_cost is not None and e.shares_held is not None and e.shares_held > 0:
            cost_basis = e.cost_basis or (e.avg_cost * e.shares_held)
            market_value = e.shares_held * price
            cumulative_pnl = market_value - cost_basis
            cumulative_pnl_pct = (cumulative_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
            
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
            })
    
    total_cumulative_pnl = total_market_value - total_cost_basis
    total_cumulative_pnl_pct = (total_cumulative_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0
    
    # TODO: For daily_series, we would need historical price data
    # For now, return empty array - can be enhanced with historical price fetching
    daily_series = []
    
    return {
        "summary": {
            "total_cost_basis": round(total_cost_basis, 2),
            "total_market_value": round(total_market_value, 2),
            "total_cumulative_pnl": round(total_cumulative_pnl, 2),
            "total_cumulative_pnl_pct": round(total_cumulative_pnl_pct, 2),
            "annualized_return": None,  # Requires historical data
            "max_drawdown": None,        # Requires historical data
            "sharpe_ratio": None,        # Requires historical data
        },
        "holdings": holdings_pnl,
        "daily_series": daily_series,
    }


# ── Portfolio Export / Import / 组合导出导入 ──────────────────────────

async def export_portfolio(
    db: AsyncSession,
    portfolio_type: str | None = None,
    format: str = "csv",
) -> str | list[dict]:
    """
    Export portfolio holdings to CSV or JSON format.
    """
    etfs = await list_etfs(db, portfolio_type)
    
    if format == "json":
        return [
            {
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "portfolio_type": e.portfolio_type,
                "target_weight": e.target_weight,
                "tracked_index": e.tracked_index,
                "avg_cost": e.avg_cost,
                "shares_held": e.shares_held,
                "cost_basis": e.cost_basis,
                "first_buy_date": e.first_buy_date.isoformat() if e.first_buy_date else None,
                "last_trade_date": e.last_trade_date.isoformat() if e.last_trade_date else None,
            }
            for e in etfs
        ]
    
    # CSV format
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "symbol", "name", "short_name", "asset_type", "portfolio_type",
        "target_weight", "tracked_index", "avg_cost", "shares_held",
        "cost_basis", "first_buy_date", "last_trade_date"
    ])
    
    for e in etfs:
        writer.writerow([
            e.symbol,
            e.name,
            e.short_name or "",
            e.asset_type,
            e.portfolio_type,
            e.target_weight,
            e.tracked_index or "",
            e.avg_cost if e.avg_cost is not None else "",
            e.shares_held if e.shares_held is not None else "",
            e.cost_basis if e.cost_basis is not None else "",
            e.first_buy_date.isoformat() if e.first_buy_date else "",
            e.last_trade_date.isoformat() if e.last_trade_date else "",
        ])
    
    return output.getvalue()


async def import_portfolio(
    db: AsyncSession,
    csv_content: str,
    portfolio_type: str = "on_exchange",
    mode: str = "merge",
    skip_invalid: bool = True,
) -> dict[str, Any]:
    """
    Import portfolio holdings from CSV content.
    """
    import csv
    import io
    from datetime import date
    
    reader = csv.DictReader(io.StringIO(csv_content))
    required_fields = {"symbol", "name", "asset_type", "portfolio_type"}
    
    # Check headers
    headers = reader.fieldnames or []
    missing = required_fields - set(headers)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    imported = 0
    skipped = 0
    errors = []
    holdings = []
    
    for row_num, row in enumerate(reader, start=2):  # 1-based, +1 for header
        try:
            # Validate required fields
            if not row.get("symbol") or not row.get("name"):
                raise ValueError("Missing required field: symbol or name")
            
            symbol = row["symbol"].strip()
            name = row["name"].strip()
            asset_type = row.get("asset_type", "ETF").strip()
            pt = row.get("portfolio_type", portfolio_type).strip()
            short_name = row.get("short_name") or name
            tracked_index = row.get("tracked_index") or None
            
            # Parse numeric fields
            target_weight = float(row["target_weight"]) if row.get("target_weight") else 0.1
            avg_cost = float(row["avg_cost"]) if row.get("avg_cost") else None
            shares_held = float(row["shares_held"]) if row.get("shares_held") else None
            first_buy_date = None
            last_trade_date = None
            
            if row.get("first_buy_date"):
                try:
                    first_buy_date = date.fromisoformat(row["first_buy_date"])
                except ValueError:
                    pass
            if row.get("last_trade_date"):
                try:
                    last_trade_date = date.fromisoformat(row["last_trade_date"])
                except ValueError:
                    pass
            
            if mode == "replace" and imported == 0:
                # Soft delete all existing of this type
                existing = await list_etfs(db, pt)
                for e in existing:
                    e.is_active = False
            
            # Upsert
            existing_etfs = await list_etfs(db, pt)
            existing_dict = {e.symbol: e for e in existing_etfs}
            
            if symbol in existing_dict:
                e = existing_dict[symbol]
                e.name = name
                e.short_name = short_name
                e.asset_type = asset_type
                e.target_weight = target_weight
                e.tracked_index = tracked_index
                e.avg_cost = avg_cost
                e.shares_held = shares_held
                e.first_buy_date = first_buy_date
                e.last_trade_date = last_trade_date
                e.is_active = True
            else:
                e = PortfolioETF(
                    symbol=symbol,
                    name=name,
                    short_name=short_name,
                    asset_type=asset_type,
                    target_weight=target_weight,
                    portfolio_type=pt,
                    tracked_index=tracked_index,
                    avg_cost=avg_cost,
                    shares_held=shares_held,
                    first_buy_date=first_buy_date,
                    last_trade_date=last_trade_date,
                    is_active=True,
                )
                db.add(e)
            
            await db.flush()
            
            holdings.append({
                "id": e.id,
                "symbol": e.symbol,
                "name": e.name,
                "short_name": e.short_name,
                "asset_type": e.asset_type,
                "target_weight": e.target_weight,
                "portfolio_type": e.portfolio_type,
                "tracked_index": e.tracked_index,
                "avg_cost": e.avg_cost,
                "shares_held": e.shares_held,
                "first_buy_date": e.first_buy_date.isoformat() if e.first_buy_date else None,
                "last_trade_date": e.last_trade_date.isoformat() if e.last_trade_date else None,
                "is_active": e.is_active,
            })
            imported += 1
            
        except Exception as exc:
            skipped += 1
            errors.append({
                "row": row_num,
                "symbol": row.get("symbol", "UNKNOWN"),
                "error": str(exc)
            })
            if not skip_invalid:
                await db.rollback()
                raise
    
    await db.commit()
    
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "holdings": holdings,
    }


# ── Weight Drift Check / 权重偏离检查 ────────────────────────────────

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