from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from ..models.portfolio import PortfolioETF
from ..models.schemas import PortfolioETFCreate, PortfolioETFUpdate
from ..fetchers.akshare_fetcher import fetch_a_stock_realtime, fetch_hk_stock_realtime, fetch_news_headlines
from ..fetchers.yfinance_fetcher import fetch_us_etf_realtime
from ..fetchers.news_fetcher import fetch_macro_news
from ..analysis.indicators import compute_all_indicators
from ..analysis.signal import generate_signal
from .market_service import get_history, get_indices, get_commodities

PORTFOLIO_TYPES = {"on_exchange": "��", "off_exchange": "��"}

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

def _build_price_map(etfs: list[PortfolioETF]) -> dict[str, tuple[float, float]]:
    """批量获取一次行情数据，构建 {symbol: (price, change_pct)} 映射。"""
    from ..fetchers.akshare_fetcher import fetch_a_stock_batch, fetch_hk_stock_realtime, fetch_index_realtime

    a_symbols = [e.symbol for e in etfs if e.asset_type == "A"]
    hk_symbols = [e.symbol for e in etfs if e.asset_type == "HK"]
    us_symbols = [e.symbol for e in etfs if e.asset_type == "US"]
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
    tracked = list({e.tracked_index for e in etfs if e.tracked_index and e.tracked_index not in m})
    if tracked:
        try:
            all_idx = fetch_index_realtime()
            for item in all_idx:
                if item["symbol"] in tracked:
                    m[item["symbol"]] = (item["price"], item["change_pct"])
        except Exception:
            pass
        # Fallback: compute change_pct from last 2 daily bars for indices still missing
        from ..fetchers.akshare_fetcher import fetch_index_history
        missing = [s for s in tracked if s not in m]
        for sym in missing:
            try:
                bars = fetch_index_history(sym, "daily")
                if bars and len(bars) >= 2:
                    prev = float(bars[-2].get("收盘", 0) or 0)
                    curr = float(bars[-1].get("收盘", 0) or 0)
                    if prev:
                        m[sym] = (curr, round((curr - prev) / prev * 100, 2))
            except Exception:
                pass

    return m

async def calculate_allocation(
    db: AsyncSession, total_capital: float, portfolio_type: str | None = None
) -> dict[str, Any]:
    etfs = await list_etfs(db, portfolio_type)
    weight_sum = sum(e.target_weight for e in etfs)
    if weight_sum <= 0:
        return {"total_capital": total_capital, "allocations": []}

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

    # Calculate cash portion
    cash_weight = max(0.0, 1.0 - weight_sum)
    cash_amount = round(total_capital * cash_weight, 2)
    return {
        "total_capital": total_capital,
        "allocations": allocations,
        "cash_weight": cash_weight,
        "cash_amount": cash_amount,
    }


async def calculate_daily_pnl(
    db: AsyncSession, total_capital: float, portfolio_type: str | None = None
) -> dict[str, Any]:
    """返回每只基金的当日盈亏和汇总。场外基金使用跟踪指数的涨跌幅作为预估收益。"""
    allocation = await calculate_allocation(db, total_capital, portfolio_type)
    etfs = await list_etfs(db, portfolio_type)
    etf_map = {e.symbol: e for e in etfs}
    price_map = _build_price_map(etfs)
    pnl_items = []
    total_pnl = 0.0
    total_amount = 0.0

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
        total_pnl += daily_pnl

        pnl_items.append({
            "symbol": symbol,
            "name": item["name"],
            "short_name": item.get("short_name") or item["name"],
            "asset_type": item["asset_type"],
            "portfolio_type": etf.portfolio_type if etf else item["portfolio_type"],
            "tracked_index": item.get("tracked_index"),
            "target_amount": target_amount,
            "change_pct": change_pct,
            "daily_pnl": daily_pnl,
        })

    result = {
        "total_pnl": total_pnl,
        "total_amount": total_amount,
        "items": pnl_items,
    }
    return result


async def strategy_check(db: AsyncSession, total_capital: float) -> dict[str, Any]:
    allocation = await calculate_allocation(db, total_capital, "off_exchange")
    return {
        "allocations": allocation["allocations"],
        "cash_weight": allocation["cash_weight"],
        "cash_amount": allocation["cash_amount"],
    }