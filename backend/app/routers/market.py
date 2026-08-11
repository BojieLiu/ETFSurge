import asyncio

from fastapi import APIRouter, Query
from ..core.logging import get_logger
from ..services.cache_service import sync_memory_cache  # P0-4: watchlist 端级 3s 缓存

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
from sqlalchemy import func, select  # P1-7: func.upper 用于补名 market 大小写不敏感匹配
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
    # P2-2 (R4-05): 统一解析——「重复参数」（?symbols=a&symbols=b）与
    # 「逗号分隔」（?symbols=a,b）两种形态等价；逗号分隔按逗号全量 split，
    # 不取首项（旧行为：list[str] 把 "a,b" 当单个元素 → 只返回 1 条）。
    flat: list[str] = []
    for _s in symbols:
        for _part in str(_s).split(","):
            _part = _part.strip()
            if _part:
                flat.append(_part)
    if not flat:
        return []
    return await market_data_hub.get_realtime(flat, asset_type)

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
    kind: str = Query("all", description="搜索类型: symbol(股票/ETF)/sector(板块)/index(指数)/all(全部)"),
) -> list[dict[str, Any]]:
    """统一搜索。

    - market=A   → 个股优先（instruments 表）→ 空则降级 ETF（F2 既有行为）。
    - market=HK/US → search_hk_us(keyword, include_stocks=include_stocks)
      （include_stocks=false 仅静态 ETF 基座；true 静态基座 + akshare spot 个股）。
    - market=null/global → 跨市场合并：A股ETF →（include_stocks 时 A股个股）→ HK → US，
      各段 top 10、总计 ≤ 30、按 (market, symbol) 去重（Z29）。
    - kind (O30, round7 §7 P30①)：sector → sectors 表（name ilike）；
      index → indices_meta 表（name/pinyin/first_letter ilike）；all（默认）→
      现有 symbol 段 + 尾部追加 sector/index 段（向后兼容，旧调用方不受影响）。
    """
    from ..models.search import Instrument
    from sqlalchemy import select, or_

    mkt = str(market or "").upper() or None
    kind = str(kind or "all").lower()

    # O30: sector/index 专用分支（round10 P2-T: sector 现在带 market 过滤——US/HK 返回空）
    if kind == "sector":
        return await _search_sectors(keyword, market=mkt)
    if kind == "index":
        # round14 P2-AG: 透传 market（港股 tab 只出港股指数，防 A 股占满）
        return await _search_indices(keyword, market=mkt)

    # kind=symbol（或 all）：先走既有 symbol 逻辑
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
        return await search_hk_us(keyword, include_stocks=include_stocks, market="HK")
    if mkt == "US":
        return await search_hk_us(keyword, include_stocks=include_stocks, market="US")

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
    # O30: kind=all（默认）→ 尾部追加 sector/index 段（向后兼容：旧调用方不受影响）
    if kind != "symbol":
        try:
            merged += await _search_sectors(keyword, market=mkt)
        except Exception as e:
            logger.warning("[search] sector segment failed: %s", e)
        try:
            # round14 P2-AG: all 模式尾部段同样透传 market（否则港股指数仍不过滤）
            merged += await _search_indices(keyword, market=mkt)
        except Exception as e:
            logger.warning("[search] index segment failed: %s", e)
        for it in merged:
            key = (it.get("market"), it.get("symbol"))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(it)
    return _sort_search_results(dedup[:30], keyword)

async def _search_sectors(keyword: str, market: str | None = None) -> list[dict[str, Any]]:
    """O30: 板块搜索——sectors 表 name ilike %kw%（type='sector'，BK 码）。

    round10 P2-T: market 参数——US/HK 传入时返回空（美股/港股无板块数据源，
    防美股 tab 展示 A 股板块）；A/None 行为不变。
    """
    if market and market.upper() in ("US", "HK"):
        return []  # 美股/港股暂无板块数据源（round6 F16）
    from ..models.search import Sector
    from sqlalchemy import select

    kw = (keyword or "").strip()
    if not kw:
        return []
    try:
        async with async_session() as session:
            stmt = select(Sector).where(Sector.name.ilike(f"%{kw}%")).limit(10)
            rows = (await session.execute(stmt)).scalars().all()
            return [{
                "symbol": r.code, "name": r.name,
                "type": "sector", "market": "A", "asset_type": "sector",
            } for r in rows]
    except Exception as e:
        logger.warning("[search] sector search failed: %s", e)
        return []

async def _search_indices(keyword: str, market: str | None = None) -> list[dict[str, Any]]:
    """O30: 指数搜索——indices_meta 表 name/pinyin/first_letter ilike（type='index'）。

    round14 P2-AG: 加 market 参数——market='HK' 时按 IndexMeta.market 过滤 + limit
    10→20（放大港股指数命中面）；market='A' 只查 A；None 保持全市场。
    """
    from ..models.search import IndexMeta
    from sqlalchemy import select, or_

    kw = (keyword or "").strip()
    if not kw:
        return []
    try:
        async with async_session() as session:
            stmt = select(IndexMeta).where(
                IndexMeta.is_active == True,  # noqa: E712
                or_(
                    IndexMeta.name.ilike(f"%{kw}%"),
                    IndexMeta.pinyin.ilike(f"%{kw}%"),
                    IndexMeta.first_letter.ilike(f"%{kw}%"),
                ),
            )
            if market and market.upper() == "HK":
                stmt = stmt.where(IndexMeta.market == "HK")
            elif market and market.upper() == "A":
                stmt = stmt.where(IndexMeta.market == "A")
            stmt = stmt.limit(20)  # P2-AG: 10→20（放大港股指数命中面）
            rows = (await session.execute(stmt)).scalars().all()
            return [{
                "symbol": r.symbol, "name": r.name,
                "type": "index", "market": r.market, "asset_type": "index",
            } for r in rows]
    except Exception as e:
        logger.warning("[search] index search failed: %s", e)
        return []

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
        "amount": [],  # F14: 成交额序列
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

@router.get("/fund-flow/{symbol}")
async def fund_flow(symbol: str) -> dict[str, Any]:
    """O28 (round7 §7 P28②): 单标的资金流——包装 market_data_hub.get_fund_flow。

    契约: api-contracts/market/fund-flow.md——成功返回东财资金流字段
    （snake_case 直通）；数据源不可用/异常返回 200 + available:false（不抛 500）。
    """
    try:
        flow = market_data_hub.get_fund_flow(symbol)
    except Exception as e:
        logger.warning("[fund-flow] %s failed: %s", symbol, e)
        flow = None
    if not isinstance(flow, dict) or flow.get("main_net_inflow") is None:
        return {
            "symbol": symbol,
            "main_net_inflow": None,
            "main_net_inflow_pct": None,
            "main_inflow": None,
            "main_outflow": None,
            "available": False,
            "detail": "数据源不可用（get_fund_flow 返回空）",
        }
    return {
        "symbol": symbol,
        "main_net_inflow": flow.get("main_net_inflow"),
        "main_net_inflow_pct": flow.get("main_net_inflow_pct"),
        "main_inflow": flow.get("main_inflow"),
        "main_outflow": flow.get("main_outflow"),
        "update_time": flow.get("update_time"),
        "available": True,
    }

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
# F16 (round6 §16.4): 加 market 参数（A/HK/US）——HK 走港股行业聚合，US 暂不支持。
@router.get("/hot-plates")
async def hot_plates(limit: int = Query(15), market: str = "A") -> list[dict[str, Any]]:
    """热点板块及涨停股(财联社)。market=HK 时返回港股行业热点；US 返回空列表。"""
    return await asyncio.to_thread(market_data_hub.get_hot_plates, limit, market)

# F2-3: 板块热度路由（数据源/hub 方法已存在，此前未暴露 → 前端 404）
# F16: 加 market 参数（HK 走港股行业聚合；US 返回空 items）。
@router.get("/sectors/heat")
async def sectors_heat(limit: int = Query(20), market: str = "A") -> dict[str, Any]:
    """板块热度排行(财联社)。market=HK 时返回港股行业热度；US 暂不支持。"""
    rows = await asyncio.to_thread(market_data_hub.get_sector_heat, limit, market)
    # O19 补充（round9 §6.1 专项）: 财联社热度无涨跌幅字段 → 东财板块行情按名称回填
    # 真实涨跌幅（行业+概念板块 f3）；东财失败时保持 0 兜底（不抛错）。
    # round14 P2-AE: 财联社 plate_list 按 plate_code 精确 join 优先（实测 20/20 命中）——
    # 东财名称回填仅命中 5/20（民爆/光通信等东财无此板块）；sign 失效时自动回退东财。
    changes: dict[str, float] = {}
    cls_changes: dict[str, float] = {}
    if market and market.upper() == "A":
        try:
            from ..fetchers.sector_fetcher import fetch_cls_plate_changes
            cls_changes = await asyncio.to_thread(fetch_cls_plate_changes) or {}
        except Exception as e:
            get_logger("market").warning("[sectors_heat] cls plate changes failed: %s", e)
        try:
            from ..fetchers.sector_fetcher import fetch_em_sector_changes
            changes = await asyncio.to_thread(fetch_em_sector_changes) or {}
        except Exception as e:
            get_logger("market").warning("[sectors_heat] em sector changes backfill failed: %s", e)
    items = []
    for r in rows or []:
        name = r.get("plate_name") or r.get("name", "")
        plate_code = r.get("plate_code", "")
        # plate_code join 优先（财联社同源同码）→ 东财名称回填兜底 → 0
        cls_chg = cls_changes.get(plate_code)
        em_chg = _match_em_change(name, changes)
        em_chg = cls_chg if cls_chg is not None else em_chg
        # P2-4 (R4-11a): 透传 change_pct（前端 SectorHeatMap 读 item.change_pct 显示涨跌幅，
        # 旧白名单丢弃该字段 → 热度行涨跌幅恒不显示）
        # O19 (round8 §7 §5.1D): 财联社板块热度无涨跌幅字段 → null 兜底为 0——
        # 与前端 `!= null` 防御协同（「非 null 可为 0」口径，见 O9 验收②）。
        # 东财回填优先：em_chg 命中用真实涨跌；未命中保持原逻辑（null → 0）。
        items.append({
            "rank": r.get("rank"),
            "name": name,
            "heat_index": r.get("cur_heat", r.get("heat_index", 0)),
            "rank_change": r.get("rank_change"),
            "is_new": r.get("is_new", 0),
            "plate_code": plate_code,
            # P2-3 (round9 §6.1): 板块涨跌幅 ±10% 值域校验（em 回填已过校验；非回填路径也拦）
            "change_pct": em_chg if em_chg is not None
            else (r.get("change_pct") if r.get("change_pct") is not None
                  and abs(float(r.get("change_pct") or 0)) <= 10.0 else 0),
        })
    return {"items": items, "total": len(items)}

def _match_em_change(cls_name: str, em_map: dict[str, float]) -> float | None:
    """东财板块涨跌幅按名称匹配（财联社名 vs 东财名）。

    财联社板块名（PCB/CRO/CMO/光通信）与东财板块名（印制电路板/CRO）不完全一致，
    三级匹配：①精确相等；②包含（一方 ⊇ 另一方，长度 ≥2 防误配）；
    ③「/」分割首段（CRO/CMO → CRO）。未命中返回 None（保持 0 兜底）。
    """
    if not cls_name or not em_map:
        return None
    if cls_name in em_map:
        return em_map[cls_name]
    for em_name, pct in em_map.items():
        if len(em_name) >= 2 and len(cls_name) >= 2 and (em_name in cls_name or cls_name in em_name):
            return pct
    head = cls_name.split("/")[0].strip()
    if len(head) >= 2 and head in em_map:
        return em_map[head]
    return None

# Phase 6: 前端已接入（marketApi.getStockHotRank）
# F16: 加 market 参数（HK 走港股成交额榜；US 返回空列表）。
@router.get("/stock-hot-rank")
async def stock_hot_rank(limit: int = Query(50), market: str = "A") -> list[dict[str, Any]]:
    """A股热门个股排名(同花顺)。market=HK 时返回港股热门个股；US 暂不支持。"""
    return await asyncio.to_thread(market_data_hub.get_stock_hot_rank, limit, market)

# Phase 6: 前端已接入（marketApi.getMarketWind）
@router.get("/wind")
async def wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""
    return await asyncio.to_thread(market_data_hub.get_market_wind)

# ── Watchlist / 自选列表 ──────────────────────────────────────────────

import re
from ..services.market_service import resolve_symbol_to_code

CODE_PATTERN = re.compile(r"^[0-9A-Za-z.\-]+$")

async def _watchlist_enrich_items(items: list) -> list[dict]:
    """P0-4 (round9 §10): watchlist 实时行情 enrich（批量 + per-item 降级 + auto-heal）。

    从 watchlist_list 抽出以便整体加超时——旧实现批量 8s + per-item 3s×N +
    resolve_symbol_to_code 无超时，10 条自选最坏 **29.9s**（§10 实测 29856ms）。
    """
    # Enrich with realtime data — R5: 并行拉取（原串行逐 item，多标的时响应数秒；
    # 单标的 3s 超时截断，慢源不拖累整体——对齐 P2-1/R4-16 模式）
    # R5-2-1: A 股多标的改批量路径（fetch_a_stock_batch，P3-3 原案）——
    # 逐标的 get_asset_realtime 对 5+ 标的仍要 5 次独立慢源调用（4525ms 退化）；
    # 批量一次拉全，慢源只触发一次。
    async def _realtime_one(item):
        try:
            # round14 P2-AF/AH: 超时分级——A/stock 5s（对齐批量 4s + 余量），
            # HK/US 8s（对齐 get_asset_realtime 非 A _timeout=15 内的快速返回级）。
            # 批量路径优先后 per-item 罕见触发，仅作兜底。
            _t = 5 if (item.asset_type or "A") in ("A", "stock") else 8
            return await asyncio.wait_for(
                market_data_hub.get_asset_realtime(item.symbol, item.asset_type),
                timeout=_t,
            )
        except BaseException:
            return None

    # round14 P2-AF/AH: 按 asset_type 分组批量——A/stock → get_realtime_batch("A")，
    # HK → get_realtime_batch("HK")，US → get_realtime_batch("US")。
    # 旧实现只对 asset_type=="A" 走批量：stock（江波龙 301317 搜索结果入库）与 HK
    # 全部落 per-item 3s 截断（get_asset_realtime 内部 _timeout=15）→ 必超时 → 前端
    # 「行情加载中」。去掉 len>=2 门槛（单只也走批量，批量并发远优于 per-item 截断）。
    _a_items = [it for it in items if (it.asset_type or "A") in ("A", "stock")]
    _hk_items = [it for it in items if (it.asset_type or "A") == "HK"]
    _us_items = [it for it in items if (it.asset_type or "A") == "US"]

    from ..services.market_service import get_realtime_batch

    async def _batch_for(group: list, asset_type: str, timeout: float = 4) -> dict[str, dict]:
        try:
            _rows = await asyncio.wait_for(
                get_realtime_batch([it.symbol for it in group], asset_type),
                timeout=timeout,  # P0-4: 5→4s——批量慢源（mootdx 空转后）快速降级
            )
            return {r.get("symbol"): r for r in (_rows or []) if r.get("symbol")}
        except BaseException as _e:
            logger.warning("[watchlist] %s batch realtime failed (fallback per-item): %s", asset_type, _e)
            return {}

    _batch_map: dict[str, dict] = {}
    if _a_items:
        _batch_map.update(await _batch_for(_a_items, "A"))
    if _hk_items:
        _batch_map.update(await _batch_for(_hk_items, "HK"))
    if _us_items:
        _batch_map.update(await _batch_for(_us_items, "US"))

    # P0-4 (round9 §10): 批量失败后 A 股**不再逐个 per-item 重试**——慢源时 10 条 ×
    # 2.5s 串联把整体拖到 8s+（实测 8.4s）；A 股缺失直接 DB-only（realtime=None +
    # _degraded 标记，P0-D），HK/US 少量条目保留 per-item（分级超时兜底）。
    _a_hit = any((it.asset_type or "A") in ("A", "stock") and it.symbol in _batch_map for it in items)
    _skip_a_per_item = bool(_a_items) and not _a_hit
    _realtimes = await asyncio.gather(
        *(
            asyncio.sleep(0, result=None)
            if (_skip_a_per_item and (it.asset_type or "A") in ("A", "stock"))
            else _realtime_one(it)
            if it.symbol not in _batch_map
            else asyncio.sleep(0, result=_batch_map[it.symbol])
            for it in items
        ),
        return_exceptions=True,
    )

    enriched = []
    for item, realtime in zip(items, _realtimes):
        if isinstance(realtime, BaseException):
            realtime = None

        # Z22: Auto-heal dirty data - if symbol is not a valid code, try to resolve by name
        resolved_symbol = item.symbol
        resolved_realtime = realtime
        # P0-4 (round9 §10): resolve 仅对**非法代码**（脏数据）触发——旧逻辑 `realtime is None`
        # 也触发 resolve，批量失败后 10 条 A 股 realtime 全 None → 串行 resolve 死循环
        # （每个 resolve 内部同步阻塞事件循环 → wait_for 整体超时失效 → 实测 9-15s）。
        # 慢源时合法代码直接 DB-only（realtime=None），不再逐条 resolve。
        if not CODE_PATTERN.match(item.symbol):
            # Try to resolve symbol from name（P0-4: 加 2s 超时——旧实现无超时，脏数据可拖满整体）
            try:
                resolved = await asyncio.wait_for(
                    resolve_symbol_to_code(item.symbol, item.asset_type), timeout=2)
            except BaseException:
                resolved = None
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
        else:
            # P0-E (round10 §5.2): 实时 enrich 失败/超时 → 降级到单标的轻量快照
            # （5s TTL quote 缓存）。命中则回填 realtime 并标注 data_source=stale，
            # 列表不再整体变空三列；缓存 miss 才保持 DB-only。
            try:
                from ..services.market_service import quote_key as _quote_key
                from ..services.cache_service import cache_get as _cache_get
                _q = await _cache_get(_quote_key(resolved_symbol, item.asset_type or "A"))
                if _q and _q.get("price") is not None:
                    item_dict["realtime"] = {
                        "price": _q.get("price"),
                        "change_pct": _q.get("change_pct"),
                        "volume": _q.get("volume"),
                        "data_source": "stale",
                    }
            except Exception as _e:
                logger.debug("[watchlist] quote-cache fallback failed for %s: %s", resolved_symbol, _e)
            # round14 P0-D/P2-AF: 降级注入显式标记——realtime 显式置 null + _degraded=true
            #（旧实现直接丢 realtime 键，前端无法区分「加载中」与「已降级」）
            if item_dict.get("realtime") is None:
                item_dict["realtime"] = None
                item_dict["_degraded"] = True
        enriched.append(item_dict)

    return enriched

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

        # P0-4 (round9 §10): watchlist 端级 3s 短缓存——冷缓存首发慢（数据源弱：mootdx
        # 空转/EM 冷却/新浪慢），缓存热后 ≤1s（实测 1.26s）；realtime 数据本身有 quote
        # 5s TTL 缓存，端级缓存避免 resolve/auto-heal 路径绕过 quote 缓存重复走慢源链。
        _wl_key = f"watchlist:{limit}:{offset}"
        _cached = sync_memory_cache.get(_wl_key)
        if _cached is not None:
            return _cached

        # P0-4 (round9 §10): watchlist 实时 enrich 整体超时 5s——批量 4s + per-item
        # 2.5s×N + resolve 2s，慢源短路后再整体截断，DB 侧数据兜底返回。
        try:
            enriched = await asyncio.wait_for(_watchlist_enrich_items(items), timeout=5)
        except asyncio.TimeoutError:
            logger.warning("[watchlist] realtime enrich timed out after 5s — returning DB-only rows (P0-4)")
            enriched = [{
                "id": it.id, "symbol": it.symbol, "name": it.name,
                "asset_type": it.asset_type, "notes": it.notes,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            } for it in items]

        resp = {
            "items": enriched,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        sync_memory_cache.set(_wl_key, resp, 3)
        return resp

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
        # P2-J (round10 §5.2): 前端已传合法 name 时直接跳过实时验证（慢源下
        # 添加不再卡 8-15s）——R29 已允许 name 入库；
        # 否则才做带超时的实时验证（A≤3s、港/指≤8s）降级 DB-only。
        provided_name = (data.name or "").strip()
        has_provided_name = bool(provided_name) and provided_name != data.symbol
        if has_provided_name:
            # 前端已带 name → 跳过实时验证直接入库（慢源下添加秒回）
            realtime = {}
        else:
            # 带超时的实时验证：A≤3s、港/指≤8s，超时降级 DB-only（后续 name 补名逻辑接管）
            try:
                _rt_timeout = 3 if (data.asset_type or "A") == "A" else 8
                realtime = await asyncio.wait_for(
                    market_data_hub.get_asset_realtime(data.symbol, data.asset_type),
                    timeout=_rt_timeout,
                )
            except BaseException:
                realtime = None
        # O9 (round8 §7 P9-新): realtime name 空时从 instruments 本地表补名
        # （F17 启动自动同步）——命中后视为已解析（不再 422），name 用真实名称。
        _instrument_name = ""
        if not realtime:
            try:
                from ..models.search import Instrument
                from sqlalchemy import select as _sel
                # P1-7 (round9 §6.2): instruments 补名查询放宽 market 匹配——旧实现严格等值
                # （Instrument.market == data.asset_type），asset_type='A' 与 instruments 表
                # market 大小写/映射差异（etf→A 等）导致补名失效 → 新增条目 name=代码。
                # 新逻辑：等值命中优先；miss 时大小写不敏感 + etf/ETF → A 映射回退。
                _inst_row = None
                _inst_row = (await session.execute(
                    _sel(Instrument).where(
                        Instrument.symbol == data.symbol,
                        Instrument.market == data.asset_type,
                    )
                )).scalar_one_or_none()
                if not _inst_row:
                    _mkt = (data.asset_type or "").upper()
                    if _mkt == "ETF":
                        _mkt = "A"
                    if _mkt:
                        _inst_row = (await session.execute(
                            _sel(Instrument).where(
                                Instrument.symbol == data.symbol,
                                func.upper(Instrument.market) == _mkt,
                            )
                        )).scalar_one_or_none()
                if _inst_row and _inst_row.name:
                    _instrument_name = _inst_row.name
            except Exception:
                pass
        if not realtime and not has_provided_name and not _instrument_name:
            raise HTTPException(status_code=422, detail="无法解析该标的，请通过搜索选择")

        # Name fallback: 前端传入 name（排除代码占位）→ instruments 补名 → realtime.name → symbol
        name = (provided_name if has_provided_name else "") or _instrument_name or (realtime.get("name", "") if realtime else "") or data.symbol
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
            # R5: 响应携带实时行情——添加后前端立即可显示价格，不等慢速全量 GET
            "realtime": {
                "price": realtime.get("price") if realtime else None,
                "change_pct": realtime.get("change_pct") if realtime else None,
                "volume": realtime.get("volume") if realtime else None,
            },
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