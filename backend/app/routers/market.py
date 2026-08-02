import asyncio

from fastapi import APIRouter, Query
from ..core.logging import get_logger

logger = get_logger(__name__)
from typing import Any

from ..database import async_session
from ..services.market_service import (
    get_watchlist, add_watchlist, update_watchlist, remove_watchlist, batch_remove_watchlist, search_hk_us,
    _sort_search_results,
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
        # F3-2: 个股搜索优先（instruments 表）→ 空则降级 levistock 个股 → 再降 ETF
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
                    items = [{
                        "symbol": r.symbol, "name": r.name,
                        "market": r.market, "asset_type": r.asset_type,
                        "type": "stock",
                    } for r in rows]
                    return _sort_search_results(items, keyword)
        except Exception as e:
            logger.warning("[search] stock search failed: %s", e)

        # F3-2: instruments 空 → levistock 个股降级（贵州茅台等）
        try:
            stocks = await _search_a_stocks(keyword)
            if stocks:
                return _sort_search_results(stocks, keyword)
        except Exception as e:
            logger.warning("[search] levistock stock fallback failed: %s", e)

        # F2: fallback to ETF mode when the local instruments table is empty
        # (per system-diagnosis plan: "在 search 端点中 fallback 到 ETF 模式").
        try:
            etfs = await market_data_hub.search_etf(keyword)
            return _sort_search_results(etfs, keyword)
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
    # F3-2: 跨市场合并后全局精确匹配优先（symbol==kw 置顶，段序不再压住精确命中）
    return _sort_search_results(dedup[:30], keyword)


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
    # F10 R32: K 线为空/不足（<30 根）时显式标记 data_available=false——
    # 前端 TechnicalAnalysisModal 收到后显示空态，不再展示占位指标
    if not hist or len(hist) < 30:
        resp = {"data_available": False,
                "reason": "K线数据不足（<30 交易日）或数据源缺失",
                "symbol": symbol, "asset_type": asset_type}
        # F0-4: stale 标记不因数据不足丢失（F0 回归：过期缓存仍须标注新鲜度）
        try:
            if market_data_hub.is_kline_stale(symbol):
                resp["_stale"] = True
        except Exception:
            pass
        return resp
    result = compute_all_indicators(hist)
    result["data_available"] = True
    # F0-4: 全源失败走 stale 缓存兜底时，显式标记数据新鲜度
    try:
        if market_data_hub.is_kline_stale(symbol):
            result["_stale"] = True
            result["_stale_note"] = "数据源全部不可用，返回过期缓存（可能延迟）"
    except Exception:
        pass
    return result


@router.get("/signal/{symbol}")
async def signal(
    symbol: str,
    asset_type: str = Query("A"),
    period: str = Query("daily"),
) -> dict:
    hist = await market_data_hub.get_market_history(symbol, asset_type, period)
    # F10 R32: K 线不足时显式拒绝（signal 对空指标的 hold 信号尤其误导）
    if not hist or len(hist) < 30:
        resp = {"data_available": False,
                "reason": "K线数据不足（<30 交易日）或数据源缺失",
                "symbol": symbol, "asset_type": asset_type}
        try:
            if market_data_hub.is_kline_stale(symbol):
                resp["_stale"] = True
        except Exception:
            pass
        return resp
    ind = compute_all_indicators(hist)
    result = generate_signal(ind)
    result["data_available"] = True
    # F0-4: stale 标记透传
    try:
        if market_data_hub.is_kline_stale(symbol):
            result["_stale"] = True
    except Exception:
        pass
    return result


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


# F2-3: 板块热度路由（数据源/hub 方法已存在，此前未暴露 → 前端 404）
@router.get("/sectors/heat")
async def sectors_heat(limit: int = Query(20)) -> dict[str, Any]:
    """板块热度排行(财联社)。

    响应归一化对齐前端契约：plate_name→name、cur_heat→heat_index，
    保留 rank_change / is_new / plate_code。
    """
    rows = await asyncio.to_thread(market_data_hub.get_sector_heat, limit)
    items = []
    for r in rows or []:
        items.append({
            "rank": r.get("rank"),
            "name": r.get("plate_name") or r.get("name", ""),
            "heat_index": r.get("cur_heat", r.get("heat_index", 0)),
            "rank_change": r.get("rank_change"),
            "is_new": r.get("is_new", 0),
            "plate_code": r.get("plate_code", ""),
        })
    return {"items": items, "total": len(items)}


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

import re
from ..services.market_service import resolve_symbol_to_code

CODE_PATTERN = re.compile(r"^[0-9A-Za-z.\-]+$")


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
            
            # Z22: Auto-heal dirty data - if symbol is not a valid code, try to resolve by name
            resolved_symbol = item.symbol
            resolved_realtime = realtime
            if not CODE_PATTERN.match(item.symbol) or realtime is None:
                # Try to resolve symbol from name
                resolved = await resolve_symbol_to_code(item.symbol, item.asset_type)
                if resolved and resolved != item.symbol:
                    resolved_symbol = resolved
                    resolved_realtime = await market_data_hub.get_asset_realtime(resolved, item.asset_type)
                    # Auto-heal DB: update symbol if different
                    # 用独立短会话执行 UPDATE，避免 rollback 影响主循环 session 中已加载对象
                    if resolved_symbol != item.symbol:
                        from sqlalchemy import update as sa_update
                        resolved_name = resolved_realtime.get("name") if resolved_realtime else None
                        try:
                            async with async_session() as heal_session:
                                await heal_session.execute(
                                    sa_update(Watchlist)
                                    .where(Watchlist.id == item.id)
                                    .values(
                                        symbol=resolved_symbol,
                                        name=resolved_name or item.name,
                                    )
                                )
                                await heal_session.commit()
                        except Exception as e:
                            # Unique constraint conflict - log warning, continue with resolved data
                            logger.warning("[watchlist] auto-heal unique conflict for id=%s: %s", item.id, e)
            
            # Name fallback: realtime.name or symbol
            display_name = item.name
            if resolved_realtime and resolved_realtime.get("name"):
                display_name = resolved_realtime["name"]
            if not display_name or not display_name.strip():
                display_name = resolved_symbol
            
            # R30: auto-heal name——合法代码但 name 为脏数据（=symbol/空）且 realtime 有真实名称时回填
            rt_name = (resolved_realtime or {}).get("name") if resolved_realtime else None
            is_dirty_name = (not (item.name or "").strip()
                             or str(item.name).strip() == str(item.symbol).strip())
            if is_dirty_name and rt_name and rt_name != item.name:
                try:
                    from sqlalchemy import update as sa_update
                    async with async_session() as heal_session:
                        await heal_session.execute(
                            sa_update(Watchlist)
                            .where(Watchlist.id == item.id)
                            .values(name=rt_name)
                        )
                        await heal_session.commit()
                except Exception as e:
                    logger.warning("[watchlist] name auto-heal failed for id=%s: %s", item.id, e)
            
            item_dict = {
                "id": item.id,
                "symbol": resolved_symbol,
                "name": display_name,
                "asset_type": item.asset_type,
                "notes": item.notes,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            if resolved_realtime:
                item_dict["realtime"] = {
                    "price": resolved_realtime.get("price"),
                    "change_pct": resolved_realtime.get("change_pct"),
                    "volume": resolved_realtime.get("volume"),
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
    # Z22: Validate symbol format - must be alphanumeric/dot/dash, no Chinese
    if not CODE_PATTERN.match(data.symbol):
        raise HTTPException(status_code=422, detail="无法解析该标的，请通过搜索选择")
    
    async with async_session() as session:
        # Check if already exists
        stmt = select(Watchlist).where(Watchlist.symbol == data.symbol)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="该标的已在自选列表中")

        # Get realtime data to validate code exists and get name
        realtime = await market_data_hub.get_asset_realtime(data.symbol, data.asset_type)
        # R29: 优先用前端传入的 name（搜索已带真实名称）；仅当 name 与 realtime 都拿不到时才 422。
        # 放宽旧逻辑——realtime 为空但前端已带合法 name 时不再拒绝（用传入 name 入库）。
        provided_name = (data.name or "").strip()
        has_provided_name = bool(provided_name) and provided_name != data.symbol
        if not realtime and not has_provided_name:
            raise HTTPException(status_code=422, detail="无法解析该标的，请通过搜索选择")

        # Name fallback: 前端传入 name → realtime.name → symbol
        name = provided_name or (realtime.get("name", "") if realtime else "") or data.symbol
        if not name.strip():
            name = data.symbol

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
