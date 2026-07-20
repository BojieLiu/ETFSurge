"""行情 Service 层。

编排 china_mater / yfinance_fetcher / stooq_fetcher 等数据源，
提供统一的异步行情接口（实时 / 历史 / 搜索 / 全球指数）。
"""

from typing import Any

import asyncio

from sqlalchemy import select

from ..database import async_session
from ..core.async_utils import run_sync
from ..core.market_calendar import is_trading_time
from ..core.ttl import CACHE_TTL
from ..services.source_registry import registry
from ..models.search import Index
from .cache_service import cache_get, cache_mget, cache_set
from ..core.logging import get_logger

logger = get_logger(__name__)


# ── 同步调用桥接 ───────────────────────────────────────────────


async def _call(fn, *args, timeout: int = 8):
    """包一层 run_sync，统一异常处理为返回 None。

    显式捕获 CancelledError —— 在 Python 3.8+ 中它继承自
    BaseException 而非 Exception，外层 wait_for 超时会触发它，
    漏接会导致异常冒泡到 APScheduler 任务边界。
    """
    try:
        return await run_sync(fn, *args, timeout=timeout)
    except (Exception, asyncio.CancelledError):
        return None


# ── 基础行情接口 ──────────────────────────────────────────────


async def get_all_realtime() -> list[dict[str, Any]]:
    results = []
    try:
        from ..fetchers.china_market import fetch_index_realtime

        data = await _call(fetch_index_realtime)
        if data:
            results.extend(data)
    except Exception:
        pass
    return results


async def get_indices() -> list[dict[str, Any]]:
    from ..fetchers.china_market import fetch_index_realtime

    return await _call(fetch_index_realtime) or []


async def get_commodities() -> list[dict[str, Any]]:
    from ..fetchers.china_market import fetch_futures_realtime

    return await _call(fetch_futures_realtime) or []


# ── 全球指数 ──────────────────────────────────────────────────


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
    """返回分组的主流全球指数行情。

    A 股 → china_market (mootdx)
    海外 → yfinance (熔断降级为占位)
    """
    defs = await _global_index_defs()
    regions: dict[str, list[dict[str, Any]]] = {}

    # A 股指数
    from ..fetchers.china_market import fetch_index_realtime

    a_map: dict[str, dict[str, Any]] = {}
    try:
        a_list = await _call(fetch_index_realtime)
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

    # 海外指数：Sina（优先，中国大陆最快）→ stooq（第二）→ yfinance（兜底）
    from ..fetchers.china_market import fetch_sina_global_index as sina_index
    from ..fetchers.stooq_fetcher import fetch_global_index_realtime as stooq_index
    from ..fetchers.yfinance_fetcher import fetch_index_realtime as yf_index

    async def _foreign(sym: str, name: str, region: str):
        loop = asyncio.get_running_loop()
        import functools

        # 第1优先：新浪（8s 超时，中国大陆最稳定）
        try:
            d = await asyncio.wait_for(
                loop.run_in_executor(None, functools.partial(sina_index, sym)),
                timeout=10,
            )
            if d and d.get("price") is not None:
                d["name"] = name
                d["region"] = region
                return region, d
        except (asyncio.TimeoutError, Exception):
            pass

        # 第2优先：stooq（8s 超时，免费）
        try:
            d = await asyncio.wait_for(
                loop.run_in_executor(None, functools.partial(stooq_index, sym, name, 8)),
                timeout=10,
            )
            if d and d.get("price") is not None:
                d["region"] = region
                return region, d
        except (asyncio.TimeoutError, Exception):
            pass

        # 第3优先：yfinance（15s 超时，兜底）
        try:
            d = await asyncio.wait_for(
                loop.run_in_executor(None, functools.partial(yf_index, sym)),
                timeout=15,
            )
            if d and d.get("price") is not None:
                d = dict(d)
                d["name"] = name
                d["region"] = region
                d["asset_type"] = "index"
                d["available"] = True
                return region, d
        except (asyncio.TimeoutError, Exception):
            pass

        # 三级源均失败，返回占位
        return region, {
            "symbol": sym, "name": name, "region": region,
            "asset_type": "index", "price": None, "change_pct": None,
            "available": False,
        }

    import asyncio

    f_defs = [(s, n, r) for s, n, r in defs if r != "A股"]
    outs = await asyncio.wait_for(
        asyncio.gather(*[_foreign(s, n, r) for s, n, r in f_defs], return_exceptions=True),
        timeout=30,
    )
    for o in outs:
        if isinstance(o, tuple) and len(o) == 2:
            region, d = o
            regions.setdefault(region, []).append(d)

    return regions


async def _global_index_defs() -> list[tuple[str, str, str]]:
    """从 indices 表读取，表为空降级到硬编码。"""
    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(Index).where(Index.is_active == True)  # noqa: E712
                )
            ).scalars().all()
            if rows:
                return [(r.symbol, r.name, r.region) for r in rows]
    except Exception as e:
        logger.warning(f"[_global_index_defs] fallback to hardcoded: {e}")
    return [(s, n, r) for s, n, r in _GLOBAL_INDEX_DEFS]


# ── 板块 / 搜索 ───────────────────────────────────────────────


async def get_sectors_local(sector_type: str) -> list[dict[str, Any]]:
    from ..models.search import Sector
    from sqlalchemy import select

    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(Sector).where(Sector.type == sector_type)
                )
            ).scalars().all()
            return [{"sector_code": r.code, "sector_name": r.name} for r in rows]
    except Exception as e:
        logger.warning(f"[get_sectors_local] failed ({sector_type}): {e}")
        return []


async def search_etf(keyword: str) -> list[dict[str, Any]]:
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
        logger.warning(f"[search_etf] local table failed, fallback: {e}")

    # 降级：akshare 全量缓存
    from ..fetchers.china_market import fetch_etf_list

    full = await cache_get("etf:list")
    if full is None:
        full = await _call(fetch_etf_list, timeout=30)
        await cache_set("etf:list", full or [], CACHE_TTL["etf_list"])
    if not full:
        return []
    if not keyword:
        return full[:20]
    kw = keyword.lower()
    return [e for e in full if kw in e["symbol"].lower() or kw in e["name"].lower()][:20]


async def get_indices_meta() -> list[dict[str, Any]]:
    from ..models.search import IndexMeta
    from sqlalchemy import select

    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(IndexMeta).where(IndexMeta.is_active == True)  # noqa: E712
                )
            ).scalars().all()
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
        logger.warning(f"[get_indices_meta] failed: {e}")
        return []


async def search_indices(keyword: str) -> list[dict[str, Any]]:
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
        logger.warning(f"[search_indices] failed: {e}")
        return []


# ── 实时行情 (含缓存) ─────────────────────────────────────────

_QUOTE_TTL = {
    "A": CACHE_TTL["quote_a"],
    "HK": CACHE_TTL["quote_hk"],
    "US": CACHE_TTL["quote_us"],
    "index": CACHE_TTL["quote_index"],
}


def quote_key(symbol: str, asset_type: str = "A") -> str:
    return f"quote:{asset_type}:{symbol}"


async def get_realtime_batch(
    symbols: list[str], asset_type: str = "A"
) -> list[dict[str, Any]]:
    if not symbols:
        return []
    if asset_type == "A":
        from ..fetchers.china_market import fetch_a_stock_batch

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
            fetched = await _call(fetch_a_stock_batch, misses, timeout=10)
            ttl = _QUOTE_TTL.get("A", 5)
            for item in fetched or []:
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
    """获取组合实时行情。

    场内 ETF → 实时价
    场外 ETF → 盘中估算（tracked_index）/ 盘后净值
    """
    from .portfolio_service import list_etfs

    async with async_session() as db:
        on_exchange = await list_etfs(db, "on_exchange")
        off_exchange = await list_etfs(db, "off_exchange")
    all_etfs = on_exchange + off_exchange
    name_map = {etf.symbol: etf.name for etf in all_etfs}
    short_name_map = {etf.symbol: (etf.short_name or etf.name) for etf in all_etfs}
    tracked_index_map = {etf.symbol: etf.tracked_index for etf in all_etfs}

    symbols = list({str(etf.symbol) for etf in all_etfs})
    if not symbols:
        return []

    a_symbols = [
        s
        for s in symbols
        if s.isdigit() and (s.startswith("5") or s.startswith("1") or s.startswith("6"))
    ]
    quotes: list[dict[str, Any]] = []
    if a_symbols:
        quotes.extend(await get_realtime_batch(a_symbols, "A"))

    # 指数行情（供场外 ETF 估值用）
    from ..fetchers.china_market import fetch_index_realtime

    index_symbols = {
        "000001", "399001", "399006", "000688",
        "000300", "000016", "000905", "000852",
    }
    try:
        index_quotes = await _call(fetch_index_realtime)
    except Exception:
        index_quotes = []
    index_price_map: dict[str, dict] = {}
    for q in index_quotes or []:
        if q["symbol"] in index_symbols:
            index_price_map[q["symbol"]] = q
            quotes.append(q)
            await cache_set(
                quote_key(q["symbol"], "index"), q, _QUOTE_TTL.get("index", 3)
            )

    # 场外 ETF：填充 is_estimated 信息
    now_trading = is_trading_time()
    from ..fetchers.china_market import fetch_fund_nav

    for etf in off_exchange:
        sym = etf.symbol
        ti = etf.tracked_index
        if not ti:
            continue
        # 检查是否已有数据（通过 tracked_index 映射）
        existing = next((q for q in quotes if q.get("symbol") == sym), None)
        if existing:
            existing["portfolio_type"] = "off_exchange"
            existing["is_estimated"] = now_trading
            existing["estimate_source"] = "tracked_index" if now_trading else "nav"
            continue

        if now_trading and ti in index_price_map:
            idx = index_price_map[ti]
            quotes.append({
                "symbol": sym,
                "name": name_map.get(sym, sym),
                "short_name": short_name_map.get(sym, name_map.get(sym, sym)),
                "price": idx.get("price"),
                "change_pct": idx.get("change_pct"),
                "change_amount": idx.get("change_amount", 0),
                "volume": 0,
                "asset_type": "A",
                "portfolio_type": "off_exchange",
                "is_estimated": True,
                "estimate_source": "tracked_index",
            })
        else:
            # 盘后：尝试净值
            nav_data = await _call(fetch_fund_nav, sym, timeout=8)
            nav_price = None
            if nav_data and isinstance(nav_data, tuple) and len(nav_data) >= 1:
                nav_price = float(nav_data[0])
            quotes.append({
                "symbol": sym,
                "name": name_map.get(sym, sym),
                "short_name": short_name_map.get(sym, name_map.get(sym, sym)),
                "price": nav_price or (index_price_map.get(ti, {}).get("price")),
                "change_pct": 0,
                "change_amount": 0,
                "volume": 0,
                "asset_type": "A",
                "portfolio_type": "off_exchange",
                "is_estimated": True,
                "estimate_source": "nav" if nav_data else "last_close",
            })

    # 补全名称
    for q in quotes:
        sym = q["symbol"]
        if not q.get("name") or q["name"] == sym:
            q["name"] = name_map.get(sym, q.get("name", sym))
        if not q.get("short_name"):
            q["short_name"] = short_name_map.get(sym, q.get("name", sym))
        if "is_estimated" not in q:
            q["is_estimated"] = False
            q["estimate_source"] = None

    return quotes


async def get_asset_realtime(symbol: str, asset_type: str) -> dict | None:
    from ..fetchers.china_market import fetch_a_stock_realtime, fetch_hk_stock_realtime

    try:
        if asset_type == "US":
            return await _route_us(symbol)
        try:
            all_a = await _call(fetch_a_stock_realtime, symbol)
            for item in all_a or []:
                if item["symbol"] == symbol:
                    return item
        except Exception:
            pass
        try:
            all_hk = await _call(fetch_hk_stock_realtime, symbol)
            for item in all_hk or []:
                if item["symbol"] == symbol:
                    return item
        except Exception:
            pass
        return None
    except Exception:
        return None


async def _route_us(symbol: str) -> dict | None:
    """美股/ETF: Twelve Data → Finnhub → Alpha Vantage → yfinance，通过 SourceRegistry 熔断路由。

    所有免费源无需代理，自动跳过 key 未设置的源。
    """
    from ..fetchers import twelvedata_fetcher
    from ..fetchers import finnhub_fetcher
    from ..fetchers import alphavantage_fetcher
    from ..fetchers.yfinance_fetcher import fetch_us_etf_realtime

    def _td():
        return twelvedata_fetcher.fetch_realtime(symbol)
    def _fh():
        return finnhub_fetcher.fetch_realtime(symbol)
    def _av():
        return alphavantage_fetcher.fetch_realtime(symbol)
    def _yf():
        return fetch_us_etf_realtime(symbol)

    return registry.route([
        ("twelvedata", _td),
        ("finnhub", _fh),
        ("alphavantage", _av),
        ("yfinance", _yf),
    ])


async def get_history(
    symbol: str, asset_type: str = "A", period: str = "daily"
) -> list[dict[str, Any]]:
    from ..fetchers.china_market import fetch_history

    return await _call(fetch_history, symbol, asset_type, period) or []


async def get_fundamentals(symbol: str) -> dict[str, Any] | None:
    from ..fetchers.tushare_fetcher import fetch_daily

    try:
        data = await _call(fetch_daily, symbol, "20260101", "20261231", timeout=10)
        if data:
            return {"symbol": symbol, "daily": data}
    except Exception:
        pass
    return None


# ── Watchlist / 自选列表 ──────────────────────────────────────────

async def get_watchlist(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    from ..models.search import Watchlist
    from sqlalchemy import select, func

    async with async_session() as session:
        # Get total count
        total_result = await session.execute(select(func.count(Watchlist.id)))
        total = total_result.scalar() or 0

        # Get items
        result = await session.execute(
            select(Watchlist)
            .order_by(Watchlist.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = result.scalars().all()

        # Enrich with realtime data
        enriched = []
        for item in items:
            realtime = await get_asset_realtime(item.symbol, item.asset_type)
            enriched.append({
                "id": item.id,
                "symbol": item.symbol,
                "name": item.name,
                "asset_type": item.asset_type,
                "notes": item.notes,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "realtime": realtime,
            })

        return {
            "items": enriched,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


async def add_watchlist(symbol: str, asset_type: str, notes: str | None = None) -> dict[str, Any]:
    from ..models.search import Watchlist
    from sqlalchemy import select

    async with async_session() as session:
        # Check if already exists
        existing = await session.execute(
            select(Watchlist).where(Watchlist.symbol == symbol)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Symbol {symbol} already in watchlist")

        # Get name from realtime
        realtime = await get_asset_realtime(symbol, asset_type)
        name = realtime.get("name", symbol) if realtime else symbol

        item = Watchlist(
            symbol=symbol,
            name=name,
            asset_type=asset_type,
            notes=notes,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        realtime = await get_asset_realtime(symbol, asset_type)
        return {
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name,
            "asset_type": item.asset_type,
            "notes": item.notes,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "realtime": realtime,
        }


async def update_watchlist(item_id: int, notes: str | None = None, asset_type: str | None = None) -> dict[str, Any] | None:
    from ..models.search import Watchlist
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Watchlist).where(Watchlist.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return None

        if notes is not None:
            item.notes = notes
        if asset_type is not None:
            item.asset_type = asset_type

        await session.commit()
        await session.refresh(item)

        realtime = await get_asset_realtime(item.symbol, item.asset_type)
        return {
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name,
            "asset_type": item.asset_type,
            "notes": item.notes,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "realtime": realtime,
        }


async def remove_watchlist(item_id: int) -> bool:
    from ..models.search import Watchlist
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Watchlist).where(Watchlist.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return False

        await session.delete(item)
        await session.commit()
        return True


async def batch_remove_watchlist(ids: list[int]) -> int:
    from ..models.search import Watchlist
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Watchlist).where(Watchlist.id.in_(ids)))
        items = result.scalars().all()
        count = len(items)
        for item in items:
            await session.delete(item)
        await session.commit()
        return count
