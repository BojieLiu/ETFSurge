"""行情 Service 层。

编排 china_market / yfinance_fetcher 等数据源，
提供统一的异步行情接口（实时 / 历史 / 搜索 / 全球指数）。
"""

import time
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

# In-memory cache for _call_with_cb (simple dict, not the Redis cache)
_simple_cache: dict[str, tuple[float, Any]] = {}


# ── 同步调用桥接 ───────────────────────────────────────────────


async def _call(fn, *args, timeout: int = 8):
    """包一层 run_sync，统一异常处理为返回 None。

    显式捕获 CancelledError —— 在 Python 3.8+ 中它继承自
    BaseException 而非 Exception，外层 wait_for 超时会触发它，
    漏接会导致异常冒泡到 APScheduler 任务边界。
    """
    try:
        return await run_sync(fn, *args, timeout=timeout)
    except asyncio.CancelledError:
        return None
    except Exception as e:
        fn_name = getattr(fn, '__name__', str(fn))
        logger.warning("[market_service] _call failed for %s: %s", fn_name, e)
        return None


async def _call_with_cb(source_name: str, fn, *args,
                        timeout: int = 8,
                        route: str = "",
                        operation: str = "realtime",
                        target: str = "",
                        cache_key: str | None = None,
                        cache_ttl: int = 0) -> Any:
    """_call with SourceRegistry circuit breaker awareness (S1).

    Checks circuit breaker before calling; records success/failure after.
    Optional in-memory cache with configurable TTL.

    Args:
        source_name: Data source name for circuit breaker tracking.
        fn: Sync function to call via run_sync.
        timeout: Timeout in seconds (default 8).
        route/operation/target: Circuit breaker event metadata.
        cache_key: Optional key for in-memory result caching.
        cache_ttl: Cache TTL in seconds (0 = no caching).

    Returns:
        Function result, cached result, or None (circuit open / failure).
    """
    # Check in-memory cache first
    if cache_key and cache_ttl > 0:
        cached = _simple_cache.get(cache_key)
        if cached is not None:
            ts, value = cached
            if time.time() - ts < cache_ttl:
                return value

    # Check circuit breaker
    source_h = registry._health(source_name)
    now = time.time()
    fn_name = getattr(fn, '__name__', str(fn))
    if not source_h.available(now):
        logger.debug("[market_service] circuit open for %s, skipping %s", source_name, target or fn_name)
        return None

    t0 = time.perf_counter()
    try:
        result = await _call(fn, *args, timeout=timeout)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if result is not None:
            source_h.record_success(route=route, operation=operation,
                                    target=target or fn_name, duration_ms=elapsed_ms)
            # Store in cache
            if cache_key and cache_ttl > 0:
                _simple_cache[cache_key] = (time.time(), result)
            return result
        source_h.record_failure(now, route=route, operation=operation,
                                target=target or fn_name, duration_ms=elapsed_ms,
                                error_message="empty result")
        return None
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        source_h.record_failure(now, route=route, operation=operation,
                                target=target or fn_name, duration_ms=elapsed_ms,
                                error_message=str(exc)[:200])
        logger.warning("[market_service] _call_with_cb failed for %s: %s", fn_name, exc)
        return None


# ── 基础行情接口 ──────────────────────────────────────────────


async def get_all_realtime() -> list[dict[str, Any]]:
    """Get all realtime market data with circuit breaker (S1)."""
    results = []
    try:
        from ..fetchers.china_market import fetch_index_realtime

        data = await _call_with_cb(
            "china_market", fetch_index_realtime,
            route="realtime", operation="probe", target="indices",
            cache_key="realtime_indices", cache_ttl=15,
        )
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
    # A 股
    ("000001", "上证指数", "A股"),
    ("399001", "深证成指", "A股"),
    ("399006", "创业板指", "A股"),
    ("000300", "沪深300", "A股"),
    ("000688", "科创50", "A股"),
    # 港股
    ("^HSI", "恒生指数", "港股"),
    ("^HSCE", "恒生国企指数", "港股"),
    ("^HSTECH", "恒生科技指数", "港股"),
    # 亚太
    ("^N225", "日经225", "日经"),
    ("^KS11", "韩国综合指数", "韩国"),
    # 欧美
    ("^GSPC", "标普500", "美股"),
    ("^IXIC", "纳斯达克", "美股"),
    ("^DJI", "道琼斯", "美股"),
    ("^FTSE", "英国富时100", "欧洲"),
    ("^GDAXI", "德国DAX", "欧洲"),
    ("^FCHI", "法国CAC40", "欧洲"),
    ("^STOXX50E", "欧洲斯托克50", "欧洲"),
]


# ── 全局指数缓存（30s 防重复采集，非交易时段复用上次成功值） ──
_global_indices_cache: dict[str, Any] = {}
_global_indices_cache_ts: float = 0
_GLOBAL_INDICES_TTL = 30

# 非交易时段缓存：保留最后一次有有效数据的响应（24h 有效）
_global_indices_last_ok: dict[str, Any] = {}
_global_indices_last_ok_ts: float = 0
_GLOBAL_INDICES_OK_TTL = 86400  # 24 小时

# ── 持久化缓存（重启后不丢失） ─────────────────────────────────
_CACHE_DB_PATH: str | None = None


def _get_cache_db_path() -> str:
    global _CACHE_DB_PATH
    if _CACHE_DB_PATH is None:
        import os
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
        os.makedirs(data_dir, exist_ok=True)
        _CACHE_DB_PATH = os.path.join(data_dir, "indices_cache.json")
    return _CACHE_DB_PATH


def _load_ok_cache() -> bool:
    """从磁盘加载缓存到内存。启动时调用一次。"""
    global _global_indices_last_ok_ts
    import json, os
    try:
        path = _get_cache_db_path()
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            blob = json.load(f)
        _global_indices_last_ok.clear()
        _global_indices_last_ok.update(blob.get("data", {}))
        _global_indices_last_ok_ts = blob.get("ts", 0)
        return bool(_global_indices_last_ok)
    except Exception:
        return False


def _save_ok_cache() -> None:
    """将内存缓存写入磁盘。"""
    import json
    try:
        blob = {
            "ts": _global_indices_last_ok_ts,
            "data": _global_indices_last_ok,
        }
        with open(_get_cache_db_path(), "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# 启动时加载持久化缓存
_load_ok_cache()


def _to_json_native(value: Any) -> Any:
    """将 numpy 等非 JSON 原生类型递归转换为 Python 原生类型。

    下游数据源（yfinance 等）可能返回 np.float64 / np.int64 /
    np.bool_ 等标量。FastAPI 的 jsonable_encoder 无法序列化 numpy 类型，
    会导致缓存命中路径（直接返回 _global_indices_cache）时 500。
    这里在写入缓存前统一清洗，保证返回结构可安全 JSON 序列化。
    """
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]

    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _to_json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_native(v) for v in value]
    return value


def _enrich_market_status(
    regions: dict[str, list[dict[str, Any]]],
    default_status: str = "closed",
) -> None:
    """为所有指数条目添加 market_status 字段（基于市场日历，而非数据源可达性）。

    原地修改 ``regions`` 中的条目。
    """
    _REGION_TO_MARKET = {
        "A股": "A股", "港股": "港股",
        "日经": "日经", "韩国": "韩国", "日韩": "日经",
        "欧美": "美股", "美股": "美股", "欧洲": "欧股",
    }
    from ..core.market_calendar import get_market_status
    for rgn, items in regions.items():
        mkt = _REGION_TO_MARKET.get(rgn, "A股")
        status = get_market_status(mkt)
        for it in items:
            it["market_status"] = status


async def get_global_indices() -> dict[str, list[dict[str, Any]]]:
    """返回分组的主流全球指数行情。

    A 股 → china_market (mootdx)
    海外 → EM缓存 → Sina → Finnhub (熔断降级为占位)

    带 30s 缓存，非交易时段复用上次成功值。
    """
    # 函数内对模块级缓存变量有赋值，必须声明 global，
    # 否则 Python 会将该变量视为局部变量，导致缓存命中分支
    # (读取 _global_indices_cache_ts) 触发 UnboundLocalError -> 500。
    global _global_indices_cache, _global_indices_cache_ts, _global_indices_last_ok, _global_indices_last_ok_ts
    import time
    try:
        now = time.time()
        if _global_indices_cache and (now - _global_indices_cache_ts) < _GLOBAL_INDICES_TTL:
            return _global_indices_cache

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
                item["available"] = True
                regions.setdefault(region, []).append(item)
            else:
                item = {
                    "symbol": sym,
                    "name": name,
                    "region": region,
                    "asset_type": "index",
                    "price": None,
                    "change_pct": None,
                    "change_amount": None,
                    "available": False,
                }
                regions.setdefault(region, []).append(item)

        # 海外指数：EM（10s）→ HK 指数（10s）→ Sina（4s）→ Finnhub（6s）→ 占位
        from ..fetchers import global_markets_fetcher
        from ..fetchers.china_market import fetch_sina_global_index as sina_index
        from ..fetchers.china_market import fetch_sina_page_global_index as sina_page_index
        from ..fetchers import global_markets_fetcher

        # Call EM once for all foreign symbols (batched API)
        _em_map: dict[str, dict] = {}
        try:
            _em_regions = await _call(global_markets_fetcher.fetch_all, timeout=10)
            if _em_regions:
                for _items in _em_regions.values():
                    for _it in _items:
                        _em_map[_it["symbol"]] = _it
        except Exception:
            pass

        # HK 指数批量接口（补充 EM 不含的 HSTECH 恒生科技指数）
        _hk_map: dict[str, dict] = {}
        try:
            _hk_data = await _call(global_markets_fetcher.fetch_hk_indices, timeout=10)
            if _hk_data:
                _hk_map.update(_hk_data)
        except Exception:
            pass

        async def _foreign(sym: str, name: str, region: str):
            from ..core.async_utils import run_sync

            # 第1优先：东方财富 EM（10s，批量接口，覆盖全球主要指数）
            if sym in _em_map:
                d = dict(_em_map[sym])
                d.setdefault("change_pct", None)
                d.setdefault("change_amount", None)
                return region, d

            # 第1.5优先：AKShare 香港指数（补 EM 不含的恒生科技指数）
            if sym in _hk_map:
                d = dict(_hk_map[sym])
                return region, d

            # 第2优先：新浪 Sina（4s）
            try:
                d = await run_sync(sina_index, sym, timeout=4)
                if d and d.get("price") is not None:
                    d["name"] = name
                    d["region"] = region
                    d["available"] = True
                    return region, d
            except (asyncio.TimeoutError, Exception):
                pass

            # 第2.5优先：新浪财经页面标题抓取（欧洲指数降级，4s）
            try:
                d = await run_sync(sina_page_index, sym, timeout=4)
                if d and d.get("price") is not None:
                    d["name"] = name
                    d["region"] = region
                    d["available"] = True
                    return region, d
            except (asyncio.TimeoutError, Exception):
                pass

            # 第3优先：Finnhub（6s）
            try:
                d = await run_sync(global_markets_fetcher.fetch_realtime, sym, timeout=6)
                if d and d.get("price") is not None and d.get("price") != 0:
                    d["name"] = name
                    d["region"] = region
                    d["available"] = True
                    return region, d
            except (asyncio.TimeoutError, Exception):
                pass

            # 均失败，返回占位
            return region, {
                "symbol": sym, "name": name, "region": region,
                "asset_type": "index", "price": None, "change_pct": None,
                "available": False,
            }

        import asyncio

        f_defs = [(s, n, r) for s, n, r in defs if r != "A股"]
        outs = await asyncio.gather(
            *[_foreign(s, n, r) for s, n, r in f_defs],
            return_exceptions=True,
        )
        for o in outs:
            if isinstance(o, tuple) and len(o) == 2:
                region, d = o
                regions.setdefault(region, []).append(d)

        # 清洗为 JSON 原生类型（避免 numpy 标量在缓存命中路径导致 500）
        regions = _to_json_native(regions)

        # 标记各指数的实际交易状态（基于市场日历，而非数据源可达性）
        _enrich_market_status(regions)

        # 判断本次响应是否包含有效数据
        has_data = any(
            item.get("available") and item.get("price") is not None
            for lst in regions.values()
            for item in lst
        )

        if has_data:
            # 交易时段：更新 OK 缓存（MERGE 模式）
            merged = {}
            for region, items in _global_indices_last_ok.items():
                merged[region] = [dict(item) for item in items]
            new_symbols: set[str] = set()
            for items in regions.values():
                for item in items:
                    sym = item.get("symbol")
                    if sym:
                        new_symbols.add(sym)
            for region in list(merged.keys()):
                merged[region] = [item for item in merged[region] if item.get("symbol") in new_symbols]
                if not merged[region]:
                    del merged[region]
            for region, items in regions.items():
                if region not in merged:
                    merged[region] = []
                new_items = {item.get("symbol"): item for item in items if item.get("available")}
                existing_symbols = {old.get("symbol") for old in merged[region]}
                for i, old in enumerate(merged[region]):
                    sym = old.get("symbol")
                    if sym in new_items:
                        new_item = new_items.pop(sym)
                        merged[region][i] = new_item
                for item in items:
                    sym = item.get("symbol")
                    if sym not in existing_symbols:
                        merged[region].append(dict(item))
            # 移除被 EM 新区域完全取代的旧缓存区域（避免重复）
            _em_regions = set(regions.keys())
            _all_em_syms = {i["symbol"] for lst in regions.values() for i in lst if i.get("symbol")}
            for _old_r in list(merged.keys()):
                if _old_r not in _em_regions:
                    _old_syms = {i["symbol"] for i in merged[_old_r] if i.get("symbol")}
                    if _old_syms and _old_syms.issubset(_all_em_syms):
                        del merged[_old_r]
            _enrich_market_status(merged)
            _global_indices_last_ok = merged
            _global_indices_last_ok_ts = time.time()
            _save_ok_cache()
            _global_indices_cache = merged
            _global_indices_cache_ts = time.time()
            return merged
        else:
            # 非交易时段：所有源返回空，使用 OK 缓存（如果存在且未过期）
            if _global_indices_last_ok and (time.time() - _global_indices_last_ok_ts) < _GLOBAL_INDICES_OK_TTL:
                stale = {}
                for region, items in _global_indices_last_ok.items():
                    stale[region] = []
                    for item in items:
                        entry = dict(item)
                        entry["available"] = False
                        stale[region].append(entry)
                _enrich_market_status(stale)
                _global_indices_cache = stale
                _global_indices_cache_ts = time.time()
                return stale
            _global_indices_cache = regions
            _global_indices_cache_ts = time.time()
            return regions

    except Exception as e:
        logger.error("[get_global_indices] Unexpected error: %s", e, exc_info=True)
        if _global_indices_last_ok:
            return _global_indices_last_ok
        return {}


async def _global_index_defs() -> list[tuple[str, str, str]]:
    """直接返回硬编码列表（不再查 DB — DB 中的旧记录可能导致索引掉失或多余）。"""
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
                        "type": "etf",
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


HKUS_ETF_MAP: list[dict[str, str]] = [
    # 港股 ETF (港股代码带 `.HK` 后缀用于区分)
    {"symbol": "02800.HK", "name": "盈富基金", "market": "HK"},
    {"symbol": "02828.HK", "name": "恒生中国企业", "market": "HK"},
    {"symbol": "03033.HK", "name": "南方恒生科技", "market": "HK"},
    {"symbol": "03067.HK", "name": "安硕恒生科技", "market": "HK"},
    {"symbol": "03188.HK", "name": "华夏沪深300", "market": "HK"},
    {"symbol": "02823.HK", "name": "安硕A50", "market": "HK"},
    {"symbol": "02840.HK", "name": "SPDR金ETF", "market": "HK"},
    {"symbol": "03081.HK", "name": "价值黄金", "market": "HK"},
    {"symbol": "03111.HK", "name": "易方达MSCI中国A50", "market": "HK"},
    {"symbol": "07200.HK", "name": "FL二南方恒指", "market": "HK"},
    {"symbol": "07226.HK", "name": "XL二南方恒科", "market": "HK"},
    # 美股 ETF
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "US"},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "market": "US"},
    {"symbol": "IVV", "name": "iShares Core S&P 500", "market": "US"},
    {"symbol": "VOO", "name": "Vanguard S&P 500", "market": "US"},
    {"symbol": "VTI", "name": "Vanguard Total Stock Market", "market": "US"},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "market": "US"},
    {"symbol": "SLV", "name": "iShares Silver Trust", "market": "US"},
    {"symbol": "FXI", "name": "iShares China Large-Cap", "market": "US"},
    {"symbol": "KWEB", "name": "KraneShares CSI China Internet", "market": "US"},
    {"symbol": "EEM", "name": "iShares MSCI Emerging Markets", "market": "US"},
    {"symbol": "DIA", "name": "SPDR Dow Jones Industrial", "market": "US"},
    {"symbol": "IWM", "name": "iShares Russell 2000", "market": "US"},
]


async def search_hk_us(keyword: str = "", enrich: bool = True) -> list[dict[str, Any]]:
    """Search HK/US ETFs by keyword.

    Uses static map for fast local matching (always works offline), then
    supplements each hit with live quote data via the project's unified realtime
    pipeline (TwelveData/Finnhub for US, HK sources for HK) — F3.
    Live enrichment is best-effort: any failure falls back to the static result
    without raising.

    Returns list of {symbol, name, market, asset_type, type, [price], [change_pct]}.
    """
    import asyncio

    kw = keyword.lower().strip()

    # Base matches from static map
    if kw:
        base = [e for e in HKUS_ETF_MAP
                if kw in e["symbol"].lower() or kw in e["name"].lower()]
    else:
        base = list(HKUS_ETF_MAP)

    results = [{
        "symbol": e["symbol"],
        "name": e["name"],
        "market": e["market"],
        "asset_type": "etf",
        "type": "etf",
    } for e in base]

    if not enrich or not results:
        return results

    # F3: supplement with live quotes (best-effort, fast-fail on timeout)
    async def _enrich(item: dict) -> dict:
        try:
            quote = await asyncio.wait_for(
                get_asset_realtime(item["symbol"], item["market"]),
                timeout=8.0,
            )
            if quote:
                if quote.get("price") is not None:
                    item = {**item, "price": quote["price"]}
                if quote.get("change_pct") is not None:
                    item = {**item, "change_pct": quote["change_pct"]}
        except Exception as _exc:
            logger.debug("[search_hk_us] live enrich failed for %s: %s",
                         item["symbol"], _exc)
        return item

    try:
        enriched = await asyncio.gather(*(_enrich(it) for it in results),
                                        return_exceptions=True)
        # _enrich catches its own errors and returns the original dict, so
        # `enriched` is normally all dicts; keep only dicts as a safety net.
        dicts = [r for r in enriched if isinstance(r, dict)]
        if dicts:
            results = dicts
    except Exception as _exc:
        logger.warning("[search_hk_us] enrichment gather failed: %s", _exc)
    return results


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


_PORTFOLIO_REALTIME_CACHE_KEY = "portfolio:realtime"
_PORTFOLIO_REALTIME_TTL = 15  # 7.6a: 15s app-level cache


async def get_portfolio_realtime() -> list[dict[str, Any]]:
    """获取组合实时行情（带 15s 应用级缓存）。

    场内 ETF → 实时价
    场外 ETF → 盘中估算（tracked_index）/ 盘后净值
    """
    # 7.6a: 15s app-level cache to reduce API response time
    from .cache_service import cache_get, cache_set
    cached = await cache_get(_PORTFOLIO_REALTIME_CACHE_KEY)
    if cached is not None:
        return cached

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

    # 7.6a: 写入 15s 缓存
    await cache_set(_PORTFOLIO_REALTIME_CACHE_KEY, quotes, _PORTFOLIO_REALTIME_TTL)

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
    """美股/ETF: Twelve Data → Finnhub，通过 SourceRegistry 熔断路由。

    v3: 移除 Stooq（CSV API 已关闭返回404 → Cloudflare）、
    AlphaVantage（25次/天额度太低）、yfinance（境内不稳定）。

    优先级设计理由:
    - TwelveData（1st）: 已配 API key，800次/天免费额度，支持全球指数。
      非交易时段有缓存数据，速度快（~0.5s）。
    - Finnhub（2nd）: 已配 API key，60次/分钟免费额度。TwelveData 失败时兜底。
    """
    from ..fetchers import global_markets_fetcher
    from ..fetchers import global_markets_fetcher

    def _td():
        return global_markets_fetcher.fetch_realtime(symbol)
    def _fh():
        return global_markets_fetcher.fetch_realtime(symbol)

    return registry.route([
        ("twelvedata", _td),
        ("finnhub", _fh),
    ], route_name="US_ETF", operation="realtime", target=symbol)


async def get_us_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """批量获取美股/ETF 实时行情，通过 TwelveData 逐个获取。"""
    if not symbols:
        return []
    from ..fetchers import global_markets_fetcher

    def _td_batch():
        out = []
        for sym in symbols:
            d = global_markets_fetcher.fetch_realtime(sym)
            if d:
                out.append(d)
        return out or None

    result = registry.route([
        ("twelvedata", _td_batch),
    ], route_name="US_batch", operation="batch", target=",".join(symbols))
    return result or []


async def get_us_history(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    """美股/ETF 历史 K 线，通过 get_k_data 获取。"""
    if not symbol:
        return []
    from ..fetchers.china_market import get_k_data
    return await _call(get_k_data, symbol, period, timeout=15) or []


async def get_history(
    symbol: str, asset_type: str = "A", period: str = "daily"
) -> list[dict[str, Any]]:
    # S5: 优先查 Hub K 线缓存
    try:
        from .pool_manager import pool_manager as pm
        cached = pm.get_kline_rows(symbol, max_age=300)
        if cached:
            return cached
    except Exception:
        pass

    from ..fetchers.china_market import fetch_history, get_k_data

    result = await _call(fetch_history, symbol, asset_type, period)
    if result:
        return result
    # Fallback: 当 fetch_history 返回空时尝试 get_k_data（akshare 直查）
    logger.warning(
        "[market_service] get_history fetch_history empty for %s (%s), trying get_k_data",
        symbol, asset_type,
    )
    return await _call(get_k_data, symbol, period, timeout=15) or []


async def get_fundamentals(symbol: str) -> dict[str, Any] | None:
    from ..fetchers.global_markets_fetcher import fetch_daily

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
