import asyncio

from fastapi import APIRouter, Query
from typing import Any

from ..database import async_session
from ..services.market_service import (
    get_all_realtime, get_asset_realtime, get_history, search_etf,
    get_realtime_batch, get_portfolio_realtime, get_fundamentals,
    get_global_indices, get_sectors_local, get_indices_meta, search_indices,
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
async def search(keyword: str = Query("")) -> list[dict[str, Any]]:
    return await search_etf(keyword)


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
        print(f"[search_stocks] local table failed: {e}")

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


@router.get("/indices/meta")
async def indices_meta() -> list[dict[str, Any]]:
    """获取所有指数元数据（用于下拉/分组展示）。"""
    return await get_indices_meta()


@router.get("/indices/search")
async def indices_search(keyword: str = Query("")) -> list[dict[str, Any]]:
    """搜索指数（毫秒级），支持代码/名称模糊匹配。"""
    return await search_indices(keyword)


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


@router.get("/chart/{symbol}")
async def chart(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    hist = await get_history(symbol, asset_type, period)
    return compute_chart_data(hist)


@router.get("/fundamentals/{symbol}")
async def fundamentals(symbol: str) -> dict:
    """Tushare 增强数据(日线 + 主力资金流)。免费 token 积分有限,已长缓存。"""
    return await get_fundamentals(symbol)


@router.get("/sentiment")
async def sentiment() -> dict:
    """市场情绪(财联社/东财):涨跌分布、封板率、连板梯队、赚钱效应。"""
    return await asyncio.to_thread(fetch_market_emotion)


@router.get("/sectors")
async def sectors(limit: int = Query(20)) -> list[dict[str, Any]]:
    """板块热度排行(财联社)。"""
    return await asyncio.to_thread(fetch_sector_heat, limit)


@router.get("/sectors/industry")
async def industry_sectors(limit: int = Query(80)) -> list[dict[str, Any]]:
    """行业板块列表：优先本地 sectors 表，否则降级到东方财富/akshare。"""
    local = await get_sectors_local("industry")
    if local:
        return local[:limit]
    return await asyncio.to_thread(fetch_industry_sectors, limit)


@router.get("/sectors/concept")
async def concept_sectors(limit: int = Query(80)) -> list[dict[str, Any]]:
    """概念板块列表：优先本地 sectors 表，否则降级到东方财富/akshare。"""
    local = await get_sectors_local("concept")
    if local:
        return local[:limit]
    return await asyncio.to_thread(fetch_concept_sectors, limit)


@router.get("/sectors/industry-cls")
async def sector_industry_cls_route(limit: int = Query(80)) -> list[dict[str, Any]]:
    """行业板块实时行情(财联社)。"""
    return await asyncio.to_thread(fetch_sector_industry_cls, limit)


@router.get("/sectors/{sector_code}/stocks")
async def sector_stocks_route(sector_code: str) -> list[dict[str, Any]]:
    """板块成分股(东方财富)。"""
    return await asyncio.to_thread(fetch_sector_stocks, sector_code)


@router.get("/sectors/{plate_code}/popular")
async def sector_popular(plate_code: str) -> list[dict[str, Any]]:
    """板块热门个股(财联社)。"""
    return await asyncio.to_thread(fetch_sector_popular_stocks, plate_code)


@router.get("/hot-plates")
async def hot_plates(limit: int = Query(15)) -> list[dict[str, Any]]:
    """热点板块及涨停股(财联社)。"""
    return await asyncio.to_thread(fetch_hot_plates, limit)


@router.get("/stock-hot-rank")
async def stock_hot_rank(limit: int = Query(50)) -> list[dict[str, Any]]:
    """A股热门个股排名(同花顺)。"""
    return await asyncio.to_thread(fetch_stock_hot_rank, limit)


@router.get("/wind")
async def wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""
    return await asyncio.to_thread(fetch_market_wind)
