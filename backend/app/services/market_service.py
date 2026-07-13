import asyncio
from typing import Any
from ..fetchers import akshare_fetcher, yfinance_fetcher
from ..database import async_session
from .cache_service import cache_get, cache_mget, cache_set
from . import source_registry


_SYNC_TIMEOUT = 8


async def _sync(call, *args, timeout: int = _SYNC_TIMEOUT):
    """在默认线程池中执行同步调用，避免阻塞事件循环。"""
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, call, *args), timeout=timeout
    )


async def get_all_realtime() -> list[dict[str, Any]]:
    results = []
    try:
        results.extend(await _sync(akshare_fetcher.fetch_index_realtime))
    except Exception:
        pass
    return results


async def get_indices() -> list[dict[str, Any]]:
    try:
        return await _sync(akshare_fetcher.fetch_index_realtime)
    except Exception:
        return []


async def get_commodities() -> list[dict[str, Any]]:
    try:
        return await _sync(akshare_fetcher.fetch_futures_realtime)
    except Exception:
        return []


# 主流全球指数定义：(symbol, name, region)
_GLOBAL_INDEX_DEFS = [
    ("000001", "上证指数", "A股"),
    ("399001", "深证成指", "A股"),
    ("399006", "创业板指", "A股"),
    ("000300", "沪深300", "A股"),
    ("000688", "科创50", "A股"),
    ("^HSI", "恒生指数", "港股"),
    ("^HSCE", "恒生国企指数", "港股"),
    ("^HSTECH", "恒生科技指数", "港股"),
    ("^N225", "日经225", "日经"),
    ("^KS11", "韩国综合指数", "韩国"),
    ("^GSPC", "标普500", "美股"),
    ("^IXIC", "纳斯达克", "美股"),
    ("^DJI", "道琼斯", "美股"),
]


async def get_global_indices() -> dict[str, list[dict[str, Any]]]:
    """返回分组的主流全球指数行情：A股(akshare) + 港股/日经/韩国/美股(yfinance)。

    指数定义从本地 indices 表读取（替代硬编码 _GLOBAL_INDEX_DEFS）。
    表为空时降级使用 _GLOBAL_INDEX_DEFS。
    """
    # 读取指数定义
    defs = await _global_index_defs()
    regions: dict[str, list[dict[str, Any]]] = {}

    # A 股指数（akshare）
    a_map: dict[str, dict[str, Any]] = {}
    try:
        a_list = await _sync(akshare_fetcher.fetch_index_realtime)
        for it in a_list or []:
            a_map[it.get("symbol")] = it
    except Exception:
        pass
    for sym, name, region in defs:
        if region != "A股":
            continue
        it = a_map.get(sym)
        if it:
            item = dict(it)
            item["name"] = name
            item["region"] = region
            item["asset_type"] = "index"
            regions.setdefault(region, []).append(item)

    # 海外指数（yfinance，失败则降级为占位）
    async def _foreign(sym: str, name: str, region: str):
        d = None
        try:
            d = await _sync(yfinance_fetcher.fetch_us_etf_realtime, sym, timeout=15)
        except Exception:
            d = None
        if d and d.get("price") is not None:
            d = dict(d)
            d["name"] = name
            d["region"] = region
            d["asset_type"] = "index"
            d["available"] = True
            return region, d
        return region, {
            "symbol": sym, "name": name, "region": region,
            "asset_type": "index", "price": None, "change_pct": None,
            "available": False,
        }

    f_defs = [(s, n, r) for s, n, r in defs if r != "A股"]
    outs = await asyncio.gather(*[_foreign(s, n, r) for s, n, r in f_defs], return_exceptions=True)
    for o in outs:
        if isinstance(o, tuple) and len(o) == 2:
            region, d = o
            regions.setdefault(region, []).append(d)

    return regions


async def _global_index_defs() -> list[tuple[str, str, str]]:
    """从 indices 表读取 (symbol, name, region)，表为空降级到硬编码。"""
    from ..models.search import Index
    from sqlalchemy import select

    try:
        async with async_session() as session:
            rows = (await session.execute(
                select(Index).where(Index.is_active == True)  # noqa: E712
            )).scalars().all()
            if rows:
                return [(r.symbol, r.name, r.region) for r in rows]
    except Exception as e:
        print(f"[_global_index_defs] failed, fallback to hardcoded: {e}")
    return [(s, n, r) for s, n, r in _GLOBAL_INDEX_DEFS]


async def get_sectors_local(sector_type: str) -> list[dict[str, Any]]:
    """从本地 sectors 表读取板块列表。表为空时返回 []（触发调用方降级）。"""
    from ..models.search import Sector
    from sqlalchemy import select

    try:
        async with async_session() as session:
            rows = (await session.execute(
                select(Sector).where(Sector.type == sector_type)
            )).scalars().all()
            return [{"sector_code": r.code, "sector_name": r.name} for r in rows]
    except Exception as e:
        print(f"[get_sectors_local] failed ({sector_type}): {e}")
        return []


async def search_etf(keyword: str) -> list[dict[str, Any]]:
    """搜索标的：优先查本地 instruments 表（毫秒级），表为空时降级到 akshare。"""
    from ..models.search import Instrument
    from sqlalchemy import select, or_

    try:
        async with async_session() as session:
            stmt = select(Instrument).where(Instrument.is_active == True)  # noqa: E712
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
                return [
                    {
                        "symbol": r.symbol,
                        "name": r.name,
                        "market": r.market,
                        "asset_type": r.asset_type,
                    }
                    for r in rows
                ]
    except Exception as e:
        print(f"[search_etf] local table failed, fallback to akshare: {e}", flush=True)

    # 降级：akshare 全量缓存（仅首次/表空时）
    full = await cache_get("etf:list")
    if full is None:
        full = await _sync(akshare_fetcher.fetch_etf_list, timeout=30)
        await cache_set("etf:list", full, 3600)
    if not keyword:
        return full[:20]
    kw = keyword.lower()
    return [e for e in full if kw in e["symbol"].lower() or kw in e["name"].lower()][:20]


async def get_indices_meta() -> list[dict[str, Any]]:
    """获取所有指数元数据（用于下拉/分组展示）。"""
    from ..models.search import IndexMeta
    from sqlalchemy import select

    try:
        async with async_session() as session:
            rows = (await session.execute(
                select(IndexMeta).where(IndexMeta.is_active == True)  # noqa: E712
            )).scalars().all()
            return [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "market": r.market,
                    "category": r.category,
                    "index_type": r.index_type,
                    "source": r.source,
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[get_indices_meta] failed: {e}", flush=True)
        return []


async def search_indices(keyword: str) -> list[dict[str, Any]]:
    """搜索指数（毫秒级），支持代码/名称/拼音/首字母模糊匹配。"""
    from ..models.search import IndexMeta
    from sqlalchemy import select, or_

    try:
        async with async_session() as session:
            stmt = select(IndexMeta).where(IndexMeta.is_active == True)  # noqa: E712
            if keyword:
                kw = keyword.lower()
                stmt = stmt.where(
                    or_(
                        IndexMeta.symbol.ilike(f"%{kw}%"),
                        IndexMeta.name.ilike(f"%{kw}%"),
                    )
                )
            stmt = stmt.limit(50)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "market": r.market,
                    "category": r.category,
                    "index_type": r.index_type,
                    "source": r.source,
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[search_indices] failed: {e}", flush=True)
        return []


_QUOTE_TTL = {"A": 5, "HK": 10, "US": 15, "index": 3}


def quote_key(symbol: str, asset_type: str = "A") -> str:
    return f"quote:{asset_type}:{symbol}"


async def get_realtime_batch(symbols: list[str], asset_type: str = "A") -> list[dict[str, Any]]:
    if not symbols:
        return []
    if asset_type == "A":
        keys = [quote_key(s, "A") for s in symbols]
        cached = await cache_mget(keys)
        hits: dict[str, dict] = {}
        misses: list[str] = []
        for sym, val in zip(symbols, cached):
            if val is not None:
                hits[sym] = val
            else:
                misses.append(sym)
        results = list(hits.values())
        if misses:
            fetched = await _sync(akshare_fetcher.fetch_a_stock_batch, misses)
            ttl = _QUOTE_TTL.get("A", 5)
            for item in fetched:
                await cache_set(quote_key(item["symbol"], "A"), item, ttl)
                results.append(item)
        return results
    results = []
    for sym in symbols:
        item = await get_asset_realtime(sym, asset_type)
        if item:
            results.append(item)
    return results


async def get_portfolio_realtime() -> list[dict[str, Any]]:
    from .portfolio_service import list_etfs

    async with async_session() as db:
        on_exchange = await list_etfs(db, "on_exchange")
        off_exchange = await list_etfs(db, "off_exchange")
    all_etfs = on_exchange + off_exchange
    name_map = {etf.symbol: etf.name for etf in all_etfs}
    short_name_map = {etf.symbol: (etf.short_name or etf.name) for etf in all_etfs}

    symbols = list({str(etf.symbol) for etf in all_etfs})
    if not symbols:
        return []

    a_symbols = [s for s in symbols if s.isdigit() and (s.startswith("5") or s.startswith("1") or s.startswith("6"))]
    quotes: list[dict[str, Any]] = []
    if a_symbols:
        quotes.extend(await get_realtime_batch(a_symbols, "A"))

    index_symbols = {"000001", "399001", "399006", "000688", "000300", "000016", "000905", "000852"}
    try:
        index_quotes = await _sync(akshare_fetcher.fetch_index_realtime)
    except Exception:
        index_quotes = []
    for q in index_quotes:
        if q["symbol"] in index_symbols:
            quotes.append(q)
            await cache_set(quote_key(q["symbol"], "index"), q, _QUOTE_TTL.get("index", 3))

    # Enrich quotes with portfolio names (overwrite empty/missing names)
    for q in quotes:
        sym = q["symbol"]
        if not q.get("name") or q["name"] == sym:
            q["name"] = name_map.get(sym, q.get("name", sym))
        if not q.get("short_name"):
            q["short_name"] = short_name_map.get(sym, q.get("name", sym))

    return quotes


async def get_asset_realtime(symbol: str, asset_type: str) -> dict | None:
    try:
        if asset_type == "US":
            return await _route_us(symbol)
        try:
            all_a = await _sync(akshare_fetcher.fetch_a_stock_realtime, symbol)
            for item in all_a:
                if item["symbol"] == symbol:
                    return item
        except Exception:
            pass
        try:
            all_hk = await _sync(akshare_fetcher.fetch_hk_stock_realtime, symbol)
            for item in all_hk:
                if item["symbol"] == symbol:
                    return item
        except Exception:
            pass
        return None
    except Exception:
        return None


async def _route_us(symbol: str) -> dict | None:
    """美股/ETF:Stooq(主,免费稳定) → yfinance(兜底)。各自独立超时,避免单源阻塞。"""
    from ..fetchers import stooq_fetcher

    try:
        rows = await _sync(stooq_fetcher.fetch_us_etf_realtime, symbol, timeout=5)
        if rows:
            return rows[0]
    except Exception:
        pass
    try:
        result = await _sync(yfinance_fetcher.fetch_us_etf_realtime, symbol, timeout=8)
        return result or None
    except Exception:
        return None


_HISTORY_TTL = {"daily": 86400, "weekly": 604800, "monthly": 2592000,
                 "4h": 300, "1h": 300, "30m": 300, "15m": 300}


async def get_history(symbol: str, asset_type: str = "A", period: str = "daily") -> list[dict[str, Any]]:
    key = f"kline:{asset_type}:{symbol}:{period}"
    cached = await cache_get(key)
    if cached is not None:
        return cached
    result = await _sync(akshare_fetcher.fetch_history, symbol, asset_type, period)
    ttl = _HISTORY_TTL.get(period, 300)
    if result:
        await cache_set(key, result, ttl)
    return result


_TUSHARE_TTL = 86400


def _yyyymmdd(days_ago: int = 0) -> str:
    from datetime import datetime, timedelta

    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


async def get_fundamentals(symbol: str) -> dict[str, Any]:
    """Tushare 增强数据(日线 + 主力资金流),长缓存、稀疏调用(免费 token 有积分限制)。"""
    from ..fetchers import tushare_fetcher

    key = f"tushare:fund:{symbol}"
    cached = await cache_get(key)
    if cached is not None:
        return cached
    end = _yyyymmdd(0)
    start = _yyyymmdd(120)
    daily = await _sync(tushare_fetcher.fetch_daily, symbol, start, end)
    moneyflow = await _sync(tushare_fetcher.fetch_moneyflow, symbol, start, end)
    result = {"symbol": symbol, "daily": daily, "moneyflow": moneyflow}
    await cache_set(key, result, _TUSHARE_TTL)
    return result
