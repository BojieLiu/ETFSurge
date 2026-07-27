import asyncio

from fastapi import APIRouter, Query
from ..core.logging import get_logger

logger = get_logger(__name__)
from typing import Any

from ..database import async_session
from ..services.market_service import (
    get_all_realtime, get_asset_realtime, get_history, search_etf,
    get_realtime_batch, get_portfolio_realtime, get_fundamentals,
    get_global_indices, get_sectors_local, get_indices_meta, search_indices,
    get_watchlist, add_watchlist, update_watchlist, remove_watchlist, batch_remove_watchlist,
)
from ..analysis.indicators import compute_all_indicators, compute_chart_data
from ..analysis.signal import generate_signal
from ..fetchers.levistock_fetcher import (
    fetch_market_emotion, fetch_sector_heat, fetch_market_wind,
)
from ..fetchers.sector_fetcher import (
    fetch_industry_sectors, fetch_concept_sectors, fetch_sector_stocks,
    fetch_hot_plates, fetch_stock_hot_rank, fetch_sector_popular_stocks,
    fetch_all_stocks, fetch_sector_history, fetch_sector_industry_cls,
)
from ..models.search import Watchlist
from ..models.schemas import WatchlistCreate, WatchlistUpdate, WatchlistResponse
from sqlalchemy import select
from fastapi import HTTPException

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/realtime")
async def realtime_all() -> list[dict[str, Any]]:
    return await get_all_realtime()


@router.get("/realtime/portfolio")
async def realtime_portfolio() -> list[dict[str, Any]]:
    return await get_portfolio_realtime()


@router.get("/realtime/batch")
async def realtime_batch(
    symbols: list[str] = Query(...),
    asset_type: str = Query("A"),
) -> list[dict[str, Any]]:
    return await get_realtime_batch(symbols, asset_type)


@router.get("/realtime/{symbol}")
async def realtime_asset(symbol: str, asset_type: str = Query("A")) -> dict | None:
    return await get_asset_realtime(symbol, asset_type)


@router.get("/indices/global")
async def global_indices() -> dict[str, Any]:
    return {"indices": await get_global_indices()}


@router.get("/history/{symbol}")
async def history(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> list[dict[str, Any]]:
    return await get_history(symbol, asset_type, period)


@router.get("/search")
async def search(
    keyword: str = Query(""),
    market: str | None = Query(None, description="Market filter: A/HK/US/global"),
    include_stocks: bool = Query(False, description="Also include individual stocks in results"),
) -> list[dict[str, Any]]:
    """Unified search: market=A searches stocks via instruments table, default searches ETFs."""
    from ..models.search import Instrument
    from sqlalchemy import select, or_

    if market and market.upper() == "A":
        try:
            async with async_session() as session:
                stmt = select(Instrument).where(
                    Instrument.is_active == True,
                    Instrument.market == "A",
                    Instrument.asset_type == "stock",
                )
                if keyword:
                    kw = keyword.lower()
                    stmt = stmt.where(
                        or_(
                            Instrument.symbol.ilike(f"%{kw}%"),
                            Instrument.name.ilike(f"%{kw}%"),
                            Instrument.pinyin.ilike(f"%{kw}%"),
                            Instrument.first_letter.ilike(f"%{kw}%"),
                        )
                    )
                stmt = stmt.limit(30)
                rows = (await session.execute(stmt)).scalars().all()
                if rows:
                    return [{
                        "symbol": r.symbol, "name": r.name,
                        "market": r.market, "asset_type": r.asset_type,
                        "type": "stock",
                    } for r in rows]
        except Exception as e:
            logger.warning("[search] stock search failed: %s", e)
        return []

    return await search_etf(keyword)


# TODO: 未接入前端
@router.get("/search/stocks")
async def search_stocks(keyword: str = Query("")) -> list[dict[str, Any]]:
    """搜索 A 股个股。优先查本地 instruments 表（毫秒级）。"""
    from ..models.search import Instrument
    from sqlalchemy import select, or_

    try:
        async with async_session() as session:
            stmt = select(Instrument).where(
                Instrument.is_active == True,  # noqa: E712
                Instrument.market == "A",
                Instrument.asset_type == "stock",
            )
            if keyword:
                kw = keyword.lower()
                stmt = stmt.where(
                    or_(
                        Instrument.symbol.ilike(f"%{kw}%"),
                        Instrument.name.ilike(f"%{kw}%"),
                        Instrument.pinyin.ilike(f"%{kw}%"),
                        Instrument.first_letter.ilike(f"%{kw}%"),
                    )
                )
            stmt = stmt.limit(30)
            rows = (await session.execute(stmt)).scalars().all()
            if rows:
                return [{"symbol": r.symbol, "name": r.name} for r in rows]
    except Exception as e:
        logger.warning(f"[search_stocks] local table failed: {e}")

    # 降级：levistock 全量
    full = await asyncio.to_thread(fetch_all_stocks)
    normalised = [
        {"symbol": s.get("stock_code") or s.get("symbol", ""),
         "name": s.get("stock_name") or s.get("name", "")}
        for s in full
    ]
    if not keyword:
        return normalised[:30]
    kw = keyword.lower()
    return [s for s in normalised if kw in s["symbol"].lower() or kw in s["name"].lower()][:30]


# TODO: 未接入前端
@router.get("/indices/meta")
async def indices_meta() -> list[dict[str, Any]]:
    """获取所有指数元数据（用于下拉/分组展示）。"""
    return await get_indices_meta()




@router.get("/indicators/{symbol}")
async def indicators(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    hist = await get_history(symbol, asset_type, period)
    return compute_all_indicators(hist)


@router.get("/signal/{symbol}")
async def signal(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    hist = await get_history(symbol, asset_type, period)
    ind = compute_all_indicators(hist)
    return generate_signal(ind)


@router.get("/signal/debug/{symbol}")
async def signal_debug(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    """信号诊断端点：返回完整的链路数据（history → indicators → signal），用于调试。
    #11 数据链静默失败时，通过此端点确认哪一步返回空。"""
    hist = await get_history(symbol, asset_type, period)
    ind = compute_all_indicators(hist) if hist else {}
    sig = generate_signal(ind) if ind else {"signal": "hold", "score": 0, "debug": "indicators_empty"}
    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "period": period,
        "history_count": len(hist),
        "history_last": hist[-1] if hist else None,
        "indicators": ind,
        "signal": sig,
    }


@router.get("/chart/{symbol}")
async def chart(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    hist = await get_history(symbol, asset_type, period)
    return compute_chart_data(hist)


# TODO: 未接入前端
@router.get("/fundamentals/{symbol}")
async def fundamentals(symbol: str) -> dict:
    """Tushare 增强数据(日线 + 主力资金流)。免费 token 积分有限,已长缓存。"""
    return await get_fundamentals(symbol)


# TODO: 未接入前端
@router.get("/sentiment")
async def sentiment() -> dict:
    """市场情绪(财联社/东财):涨跌分布、封板率、连板梯队、赚钱效应。"""
    return await asyncio.to_thread(fetch_market_emotion)




@router.get("/sectors/industry")
async def industry_sectors(limit: int = Query(80)) -> list[dict[str, Any]]:
    """行业板块列表（含实时行情）：优先 sector_fetcher 实时数据，本地 sectors 表作降级。"""
    realtime = await asyncio.to_thread(fetch_industry_sectors, limit)
    if realtime:
        return realtime[:limit]
    local = await get_sectors_local("industry")
    if local:
        return local[:limit]
    return []


@router.get("/sectors/concept")
async def concept_sectors(limit: int = Query(80)) -> list[dict[str, Any]]:
    """概念板块列表（含实时行情）：优先 sector_fetcher 实时数据，本地 sectors 表作降级。"""
    realtime = await asyncio.to_thread(fetch_concept_sectors, limit)
    if realtime:
        return realtime[:limit]
    local = await get_sectors_local("concept")
    if local:
        return local[:limit]
    return []


# TODO: 未接入前端
@router.get("/sectors/industry-cls")
async def sector_industry_cls_route(limit: int = Query(80)) -> list[dict[str, Any]]:
    """行业板块实时行情(财联社)。"""
    return await asyncio.to_thread(fetch_sector_industry_cls, limit)


# TODO: 未接入前端
@router.get("/sectors/{sector_code}/stocks")
async def sector_stocks_route(sector_code: str) -> list[dict[str, Any]]:
    """板块成分股(东方财富)。"""
    return await asyncio.to_thread(fetch_sector_stocks, sector_code)


# TODO: 未接入前端
@router.get("/sectors/{plate_code}/popular")
async def sector_popular(plate_code: str) -> list[dict[str, Any]]:
    """板块热门个股(财联社)。"""
    return await asyncio.to_thread(fetch_sector_popular_stocks, plate_code)


@router.get("/sectors")
async def unified_sectors(
    type: str = Query(..., description="Sector type: industry or concept"),
    limit: int = Query(200, description="Max results"),
    market: str = Query("A", description="Market filter"),
) -> list[dict[str, Any]]:
    """Unified sector endpoint. Delegates to industry or concept routes."""
    if type == "industry":
        return await industry_sectors(limit)
    elif type == "concept":
        return await concept_sectors(limit)
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid sector type: {type}. Use industry or concept.")


# Phase 6: 前端已接入（marketApi.getHotPlates）
@router.get("/hot-plates")
async def hot_plates(limit: int = Query(15)) -> list[dict[str, Any]]:
    """热点板块及涨停股(财联社)。"""
    return await asyncio.to_thread(fetch_hot_plates, limit)


# Phase 6: 前端已接入（marketApi.getStockHotRank）
@router.get("/stock-hot-rank")
async def stock_hot_rank(limit: int = Query(50)) -> list[dict[str, Any]]:
    """A股热门个股排名(同花顺)。"""
    return await asyncio.to_thread(fetch_stock_hot_rank, limit)


# Phase 6: 前端已接入（marketApi.getMarketWind）
@router.get("/wind")
async def wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""
    return await asyncio.to_thread(fetch_market_wind)


# ── Watchlist / 自选列表 ──────────────────────────────────────────────


@router.get("/watchlist", response_model=dict)
async def watchlist_list(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """获取自选列表（含实时行情快照）"""
    async with async_session() as session:
        # Get total count
        total_stmt = select(Watchlist.id)
        total_result = await session.execute(total_stmt)
        total = len(total_result.scalars().all())

        # Get paginated items
        stmt = select(Watchlist).order_by(Watchlist.created_at.desc()).offset(offset).limit(limit)
        result = await session.execute(stmt)
        items = result.scalars().all()

        # Enrich with realtime data
        enriched = []
        for item in items:
            realtime = await get_asset_realtime(item.symbol, item.asset_type)
            item_dict = {
                "id": item.id,
                "symbol": item.symbol,
                "name": item.name,
                "asset_type": item.asset_type,
                "notes": item.notes,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            if realtime:
                item_dict["realtime"] = {
                    "price": realtime.get("price"),
                    "change_pct": realtime.get("change_pct"),
                    "volume": realtime.get("volume"),
                }
            enriched.append(item_dict)

        return {
            "items": enriched,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.post("/watchlist", response_model=dict, status_code=201)
async def watchlist_add(data: WatchlistCreate) -> dict[str, Any]:
    """添加自选"""
    async with async_session() as session:
        # Check if already exists
        stmt = select(Watchlist).where(Watchlist.symbol == data.symbol)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="该标的已在自选列表中")

        # Get name from market data
        realtime = await get_asset_realtime(data.symbol, data.asset_type)
        name = realtime.get("name", data.symbol) if realtime else data.symbol

        item = Watchlist(
            symbol=data.symbol,
            name=name,
            asset_type=data.asset_type,
            notes=data.notes,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        return {
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name,
            "asset_type": item.asset_type,
            "notes": item.notes,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }


@router.put("/watchlist/{item_id}", response_model=dict)
async def watchlist_update(item_id: int, data: WatchlistUpdate) -> dict[str, Any]:
    """更新自选"""
    async with async_session() as session:
        stmt = select(Watchlist).where(Watchlist.id == item_id)
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="自选项不存在")

        if data.notes is not None:
            item.notes = data.notes
        if data.asset_type is not None:
            item.asset_type = data.asset_type

        await session.commit()
        await session.refresh(item)

        return {
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name,
            "asset_type": item.asset_type,
            "notes": item.notes,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }


@router.delete("/watchlist/{item_id}", status_code=204)
async def watchlist_remove(item_id: int):
    """删除自选"""
    async with async_session() as session:
        stmt = select(Watchlist).where(Watchlist.id == item_id)
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="自选项不存在")
        await session.delete(item)
        await session.commit()


@router.delete("/watchlist", response_model=dict)
async def watchlist_batch_remove(ids: list[int]) -> dict[str, int]:
    """批量删除自选"""
    async with async_session() as session:
        stmt = select(Watchlist).where(Watchlist.id.in_(ids))
        result = await session.execute(stmt)
        items = result.scalars().all()
        count = len(items)
        for item in items:
            await session.delete(item)
        await session.commit()
        return {"deleted": count}
