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
        # For off-exchange with tracked index, use tracked_index change
        if e.portfolio_type == "off_exchange" and e.tracked_index:
            _, change_pct = price_map.get(e.tracked_index, (0, 0))
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
        })

    cash_weight = max(0.0, 1.0 - weight_sum)
    cash_amount = round(total_capital * cash_weight, 2)
    return {
        "total_capital": total_capital,
        "allocations": allocations,
        "total_amount": round(total_amount, 2),
        "cash_weight": cash_weight,
        "cash_amount": cash_amount,
    }

    price_map = _build_price_map(etfs)
    allocations = []
    for e in etfs:
        target_amount = total_capital * (e.target_weight / weight_sum)
        price, change_pct = price_map.get(e.symbol, (0, 0))
        # For off-exchange with tracked index, use tracked_index change
        if e.portfolio_type == "off_exchange" and e.tracked_index:
            _, change_pct = price_map.get(e.tracked_index, (0, 0))
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
        })

    cash_weight = max(0.0, 1.0 - weight_sum)
    cash_amount = round(total_capital * cash_weight, 2)
    return {
        "total_capital": total_capital,
        "allocations": allocations,
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
    price_map = _build_price_map(etfs)
    pnl_items = []
    total_pnl = 0.0
    total_amount = 0.0
    weighted_change_sum = 0.0

    for item in allocation["allocations"]:
        symbol = item["symbol"]
        etf = etf_map.get(symbol)
        target_amount = item["target_amount"]
        total_amount += target_amount

        # For off-exchange with tracked index, use index change_pct
        if etf and etf.portfolio_type == "off_exchange" and etf.tracked_index:
            _, change_pct = price_map.get(etf.tracked_index, (0, 0))
        else:
            _, change_pct = price_map.get(symbol, (0, 0))

        daily_pnl = round(target_amount * change_pct / 100, 2)
        weighted_change_sum += target_amount * change_pct
        total_pnl += daily_pnl

        pnl_items.append({
            "symbol": symbol,
            "name": item["name"],
            "short_name": item.get("short_name") or item["name"],
            "asset_type": item["asset_type"],
            "portfolio_type": item["portfolio_type"],
            "target_amount": target_amount,
            "current_price": item["current_price"],
            "change_pct": change_pct,
            "daily_pnl": daily_pnl,
            "tracked_index": etf.tracked_index if etf else None,
        })

    weighted_change_pct = round(weighted_change_sum / total_amount, 2) if total_amount else 0
    return {
        "items": pnl_items,
        "total_pnl": round(total_pnl, 2),
        "total_amount": round(total_amount, 2),
        "weighted_change_pct": weighted_change_pct,
    }


async def strategy_check(db: AsyncSession, total_capital: float) -> dict[str, Any]:
    from ..analysis.llm import generate_strategy_suggestions
    etfs = await list_etfs(db)
    if not etfs:
        return {"summary": "组合为空，请先添加ETF", "suggestions": []}

    price_map = _build_price_map(etfs)
    market_data = []
    indicators = {}
    for e in etfs:
        price, change_pct = price_map.get(e.symbol, (0, 0))
        market_data.append({
            "symbol": e.symbol, "name": e.name, "short_name": e.short_name or e.name,
            "price": price, "change_pct": change_pct,
            "asset_type": e.asset_type, "portfolio_type": e.portfolio_type,
            "target_weight": e.target_weight,
            "target_amount": round(total_capital * e.target_weight / sum(ee.target_weight for ee in etfs), 2),
        })
        try:
            hist = await get_history(e.symbol, e.asset_type)
            ind = compute_all_indicators(hist)
            sig = generate_signal(ind)
            if ind:
                ind["signal"] = sig
                indicators[e.symbol] = ind
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
            symbol = s.get("symbol")
            action = s.get("action")
            weight = s.get("weight")
            if not symbol or symbol not in etf_dict:
                applied.append({"symbol": symbol, "action": action, "status": "error", "message": f"ETF {symbol} 不存在"})
                continue
            etf = etf_dict[symbol]
            if action == "adjust_weight" and weight is not None:
                etf.target_weight = max(0, min(0.5, etf.target_weight + weight))
                applied.append({"symbol": symbol, "action": action, "status": "success", "message": f"已调整 {symbol} 权重"})
            elif action == "replace" and weight is not None:
                etf.target_weight = max(0, min(0.5, weight))
                applied.append({"symbol": symbol, "action": action, "status": "success", "message": f"已替换 {symbol} 权重"})
            elif action == "add" and weight is not None:
                etf.target_weight = max(0, min(0.5, weight))
                etf.is_active = True
                applied.append({"symbol": symbol, "action": action, "status": "success", "message": f"已添加 {symbol}"})
            else:
                applied.append({"symbol": symbol, "action": action, "status": "error", "message": f"不支持的操作 {action}"})

        await db.commit()
        updated = await list_etfs(db)
        return {"symbols": [{"symbol": e.symbol, "name": e.name, "target_weight": e.target_weight} for e in updated], "applied": applied}
    except Exception as e:
        await db.rollback()
        raise e


# 应用组合设计
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
