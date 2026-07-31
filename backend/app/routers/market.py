import asyncio

from fastapi import APIRouter, Query
from ..core.logging import get_logger

logger = get_logger(__name__)
from typing import Any

from ..database import async_session
from ..services.market_service import (
    get_watchlist, add_watchlist, update_watchlist, remove_watchlist, batch_remove_watchlist, search_hk_us,
)
from ..analysis.indicators import compute_all_indicators, compute_chart_data
from ..analysis.signal import generate_signal
from ..services.market_data_hub import market_data_hub
from ..models.search import Watchlist
from ..models.schemas import WatchlistCreate, WatchlistUpdate, WatchlistResponse
from sqlalchemy import select
from fastapi import HTTPException

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/realtime")
async def realtime_all() -> list[dict[str, Any]]:
    return await market_data_hub.get_all_realtime()


@router.get("/realtime/portfolio")
async def realtime_portfolio() -> list[dict[str, Any]]:
    return await market_data_hub.get_portfolio_realtime()


@router.get("/realtime/batch")
async def realtime_batch(
    symbols: list[str] = Query(...),
    asset_type: str = Query("A"),
) -> list[dict[str, Any]]:
    return await market_data_hub.get_realtime(symbols, asset_type)


@router.get("/realtime/{symbol}")
async def realtime_asset(symbol: str, asset_type: str = Query("A")) -> dict | None:
    return await market_data_hub.get_asset_realtime(symbol, asset_type)


@router.get("/indices/global")
async def global_indices() -> dict[str, Any]:
    return {"indices": await market_data_hub.get_global_indices()}


@router.get("/history/{symbol}")
async def history(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> list[dict[str, Any]]:
    return await market_data_hub.get_market_history(symbol, asset_type, period)


@router.get("/search")
async def search(
    keyword: str = Query(""),
    market: str | None = Query(None, description="Market filter: A/HK/US/global; null = 跨市场"),
    include_stocks: bool = Query(False, description="结果中是否包含个股"),
) -> list[dict[str, Any]]:
    """统一搜索。

    - market=A   → 个股优先（instruments 表）→ 空则降级 ETF（F2 既有行为）。
    - market=HK/US → search_hk_us(keyword, include_stocks=include_stocks)
      （include_stocks=false 仅静态 ETF 基座；true 静态基座 + akshare spot 个股）。
    - market=null/global → 跨市场合并：A股ETF →（include_stocks 时 A股个股）→ HK → US，
      各段 top 10、总计 ≤ 30、按 (market, symbol) 去重（Z29）。
    """
    from ..models.search import Instrument
    from sqlalchemy import select, or_

    mkt = market.upper() if market else None

    if mkt == "A":
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
                    return [{
                        "symbol": r.symbol, "name": r.name,
                        "market": r.market, "asset_type": r.asset_type,
                        "type": "stock",
                    } for r in rows]
        except Exception as e:
            logger.warning("[search] stock search failed: %s", e)

        # F2: fallback to ETF mode when the local instruments table is empty
        # (per system-diagnosis plan: "在 search 端点中 fallback 到 ETF 模式").
        try:
            return await market_data_hub.search_etf(keyword)
        except Exception as e:
            logger.warning("[search] A-share ETF-mode fallback failed: %s", e)
        return []

    if mkt == "HK":
        return await search_hk_us(keyword, include_stocks=include_stocks)
    if mkt == "US":
        return await search_hk_us(keyword, include_stocks=include_stocks)

    # 默认 / global：跨市场合并（A股ETF → A股个股(include_stocks) → HK → US）
    try:
        a_etf, hk_us = await asyncio.gather(
            market_data_hub.search_etf(keyword),
            search_hk_us(keyword, enrich=False, include_stocks=include_stocks),
        )
    except Exception as e:
        logger.warning("[search] cross-market merge failed: %s", e)
        a_etf, hk_us = [], []

    merged: list[dict[str, Any]] = []
    # A 股 ETF 段：过滤非 ETF 行，避免与 _search_a_stocks 的个股结果重复
    a_etf = [r for r in (a_etf or []) if r.get("asset_type") == "etf"]
    merged += a_etf[:10]
    if include_stocks:
        merged += await _search_a_stocks(keyword)
    hk_us = hk_us or []
    merged += [r for r in hk_us if r.get("market") == "HK"][:10]
    merged += [r for r in hk_us if r.get("market") == "US"][:10]

    # 按 (market, symbol) 去重（跨段可能重复）
    seen: set[tuple[str, str]] = set()
    dedup: list[dict[str, Any]] = []
    for it in merged:
        key = (it.get("market"), it.get("symbol"))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(it)
    return dedup[:30]


async def _search_a_stocks(keyword: str) -> list[dict[str, Any]]:
    """A 股个股搜索：instruments 表（market=A, asset_type=stock）→ 空则 levistock 降级。

    仅供默认分支 include_stocks=true 使用；market=A 分支保持既有行为不动。
    """
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
            stmt = stmt.limit(10)
            rows = (await session.execute(stmt)).scalars().all()
            if rows:
                return [{
                    "symbol": r.symbol, "name": r.name,
                    "market": r.market, "asset_type": r.asset_type,
                    "type": "stock",
                } for r in rows]
    except Exception as e:
        logger.warning("[search] _search_a_stocks local table failed: %s", e)

    # 降级：levistock 全量（与 /search/stocks 同链）
    try:
        full = await asyncio.to_thread(market_data_hub.get_all_stocks)
        normalised = [
            {"symbol": s.get("stock_code") or s.get("symbol", ""),
             "name": s.get("stock_name") or s.get("name", "")}
            for s in (full or [])
        ]
        if not keyword:
            return [{
                "symbol": s["symbol"], "name": s["name"],
                "market": "A", "asset_type": "stock", "type": "stock",
            } for s in normalised][:10]
        kw = keyword.lower()
        return [{
            "symbol": s["symbol"], "name": s["name"],
            "market": "A", "asset_type": "stock", "type": "stock",
        } for s in normalised
            if kw in s["symbol"].lower() or kw in s["name"].lower()][:10]
    except Exception as e:
        logger.warning("[search] _search_a_stocks levistock fallback failed: %s", e)
        return []


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
    full = await asyncio.to_thread(market_data_hub.get_all_stocks)
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
    return await market_data_hub.get_indices_meta()




@router.get("/indicators/{symbol}")
async def indicators(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    hist = await market_data_hub.get_market_history(symbol, asset_type, period)
    return compute_all_indicators(hist)


@router.get("/signal/{symbol}")
async def signal(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    hist = await market_data_hub.get_market_history(symbol, asset_type, period)
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
    hist = await market_data_hub.get_market_history(symbol, asset_type, period)
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
    """返回 K 线图数据（含 MA/MACD/布林带指标序列）。"""
    try:
        hist = await market_data_hub.get_market_history(symbol, asset_type, period)
        if not hist:
            logger.warning("[chart] Empty history for %s/%s/%s", symbol, asset_type, period)
            return _empty_chart_response()
        return compute_chart_data(hist)
    except KeyError as e:
        logger.error("[chart] Missing column %s in history data for %s", e, symbol)
        return _empty_chart_response()
    except Exception as e:
        logger.exception("[chart] compute_chart_data failed for %s: %s", symbol, e)
        return _empty_chart_response()


def _empty_chart_response() -> dict:
    """Return an empty but valid chart data structure."""
    return {
        "dates": [], "opens": [], "highs": [], "lows": [], "closes": [], "volumes": [],
        "ma5": [], "ma10": [], "ma20": [], "ma60": [],
        "bollinger": {"upper": [], "middle": [], "lower": []},
        "macd": {"dif": [], "dea": [], "histogram": []},
    }


# TODO: 未接入前端
@router.get("/fundamentals/{symbol}")
async def fundamentals(symbol: str) -> dict:
    """Tushare 增强数据(日线 + 主力资金流)。免费 token 积分有限,已长缓存。"""
    result = await market_data_hub.get_market_fundamentals(symbol)
    if result is None:
        # Z16: 数据源不可用时返回结构化空响应而非 None (避免 response_model 校验 500)
        return {"symbol": symbol, "daily": [], "error": "fundamentals data unavailable"}
    return result


# TODO: 未接入前端
@router.get("/sentiment")
async def sentiment() -> dict:
    """市场情绪(财联社/东财):涨跌分布、封板率、连板梯队、赚钱效应。"""
    return await asyncio.to_thread(market_data_hub.get_market_emotion)




@router.get("/sectors/industry")
async def industry_sectors(limit: int = Query(500)) -> list[dict[str, Any]]:
    """行业板块列表（含实时行情）：优先 sector_fetcher 实时数据，本地 sectors 表作降级。"""
    realtime = await asyncio.to_thread(market_data_hub.get_sector_industry, limit)
    if realtime:
        return realtime[:limit]
    local = await market_data_hub.get_sectors_local("industry")
    if local:
        return local[:limit]
    return []


@router.get("/sectors/concept")
async def concept_sectors(limit: int = Query(500)) -> list[dict[str, Any]]:
    """概念板块列表（含实时行情）：优先 sector_fetcher 实时数据，本地 sectors 表作降级。"""
    realtime = await asyncio.to_thread(market_data_hub.get_sector_concept, limit)
    if realtime:
        return realtime[:limit]
    local = await market_data_hub.get_sectors_local("concept")
    if local:
        return local[:limit]
    return []


# TODO: 未接入前端
@router.get("/sectors/industry-cls")
async def sector_industry_cls_route(limit: int = Query(80)) -> list[dict[str, Any]]:
    """行业板块实时行情(财联社)。"""
    return await asyncio.to_thread(market_data_hub.get_sector_industry_cls, limit)


# TODO: 未接入前端
@router.get("/sectors/{sector_code}/stocks")
async def sector_stocks_route(sector_code: str) -> list[dict[str, Any]]:
    """板块成分股(东方财富)。"""
    return await asyncio.to_thread(market_data_hub.get_sector_stocks, sector_code)


# TODO: 未接入前端
@router.get("/sectors/{plate_code}/popular")
async def sector_popular(plate_code: str) -> list[dict[str, Any]]:
    """板块热门个股(财联社)。"""
    return await asyncio.to_thread(market_data_hub.get_sector_popular_stocks, plate_code)


# Z17: Add sector rotation endpoint
@router.get("/sectors/rotation")
async def sector_rotation(limit: int = Query(20)) -> list[dict[str, Any]]:
    """板块轮动数据 — 行业板块实时行情(财联社)，含涨跌幅、主力资金、涨跌家数。"""
    return await asyncio.to_thread(market_data_hub.get_sector_industry_cls, limit)


@router.get("/sectors")
async def unified_sectors(
    type: str = Query("industry", description="Sector type: industry or concept"),
    limit: int = Query(200, description="Max results"),
    market: str = Query("A", description="Market filter"),
) -> list[dict[str, Any]]:
    """Unified sector endpoint. Delegates to industry or concept routes.

    Z17: type 参数改为非必需（默认 industry），避免前端未传参时 422。
    """
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
    return await asyncio.to_thread(market_data_hub.get_hot_plates, limit)


# Phase 6: 前端已接入（marketApi.getStockHotRank）
@router.get("/stock-hot-rank")
async def stock_hot_rank(limit: int = Query(50)) -> list[dict[str, Any]]:
    """A股热门个股排名(同花顺)。"""
    return await asyncio.to_thread(market_data_hub.get_stock_hot_rank, limit)


# Phase 6: 前端已接入（marketApi.getMarketWind）
@router.get("/wind")
async def wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""
    return await asyncio.to_thread(market_data_hub.get_market_wind)


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
            realtime = await market_data_hub.get_asset_realtime(item.symbol, item.asset_type)
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
        realtime = await market_data_hub.get_asset_realtime(data.symbol, data.asset_type)
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
