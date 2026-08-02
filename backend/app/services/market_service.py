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
    import asyncio
    import time
    try:
        now = time.time()
        if _global_indices_cache and (now - _global_indices_cache_ts) < _GLOBAL_INDICES_TTL:
            return _global_indices_cache

        defs = await _global_index_defs()
        regions: dict[str, list[dict[str, Any]]] = {}

        # F2-5: A 股指数 / EM / HK 三段拉取并行 gather（此前顺序 await 串行拉长预热）
        from ..fetchers import global_markets_fetcher

        async def _fetch_a_indices():
            from ..fetchers.china_market import fetch_index_realtime
            try:
                return await _call(fetch_index_realtime)
            except Exception:
                return []

        async def _fetch_em_all():
            try:
                return await _call(global_markets_fetcher.fetch_all, timeout=10)
            except Exception:
                return {}

        async def _fetch_hk_indices():
            try:
                return await _call(global_markets_fetcher.fetch_hk_indices, timeout=10)
            except Exception:
                return {}

        _a_list, _em_regions, _hk_data = await asyncio.gather(
            _fetch_a_indices(), _fetch_em_all(), _fetch_hk_indices(),
        )

        # A 股指数
        a_map: dict[str, dict[str, Any]] = {}
        for it in _a_list or []:
            a_map[it.get("symbol")] = it
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
        from ..fetchers.china_market import fetch_sina_global_index as sina_index
        from ..fetchers.china_market import fetch_sina_page_global_index as sina_page_index

        # Call EM once for all foreign symbols (batched API)
        _em_map: dict[str, dict] = {}
        if _em_regions:
            for _items in _em_regions.values():
                for _it in _items:
                    _em_map[_it["symbol"]] = _it

        # HK 指数批量接口（补充 EM 不含的 HSTECH 恒生科技指数）
        _hk_map: dict[str, dict] = {}
        if _hk_data:
            _hk_map.update(_hk_data)

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
                results = [
                    {
                        "symbol": r.symbol,
                        "name": r.name,
                        "market": r.market,
                        "asset_type": r.asset_type,
                        "type": "etf",
                    }
                    for r in rows
                ]
                # Z20: 统一排序契约
                return _sort_search_results(results, keyword)
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


# Z29: 静态个股基座（离线可用）。5 位港股代码无后缀；美股代码无后缀。
# 与 HKUS_ETF_MAP 一并作为 `search_hk_us` 的静态基座；高流动性龙头为主。
HKUS_STOCK_MAP: list[dict[str, str]] = [
    # 港股个股
    {"symbol": "00700", "name": "腾讯控股", "market": "HK"},
    {"symbol": "09988", "name": "阿里巴巴-W", "market": "HK"},
    {"symbol": "03690", "name": "美团-W", "market": "HK"},
    {"symbol": "01810", "name": "小米集团-W", "market": "HK"},
    {"symbol": "00005", "name": "汇丰控股", "market": "HK"},
    {"symbol": "00388", "name": "香港交易所", "market": "HK"},
    {"symbol": "00941", "name": "中国移动", "market": "HK"},
    {"symbol": "01299", "name": "友邦保险", "market": "HK"},
    {"symbol": "02318", "name": "中国平安", "market": "HK"},
    {"symbol": "09618", "name": "京东集团-SW", "market": "HK"},
    {"symbol": "01024", "name": "快手-W", "market": "HK"},
    {"symbol": "02020", "name": "安踏体育", "market": "HK"},
    {"symbol": "02382", "name": "舜宇光学科技", "market": "HK"},
    {"symbol": "00939", "name": "建设银行", "market": "HK"},
    {"symbol": "01398", "name": "工商银行", "market": "HK"},
    # 美股个股
    {"symbol": "AAPL", "name": "苹果", "market": "US"},
    {"symbol": "MSFT", "name": "微软", "market": "US"},
    {"symbol": "NVDA", "name": "英伟达", "market": "US"},
    {"symbol": "GOOGL", "name": "谷歌-A", "market": "US"},
    {"symbol": "AMZN", "name": "亚马逊", "market": "US"},
    {"symbol": "TSLA", "name": "特斯拉", "market": "US"},
    {"symbol": "META", "name": "Meta平台", "market": "US"},
    {"symbol": "BRK.B", "name": "伯克希尔哈撒韦-B", "market": "US"},
    {"symbol": "LLY", "name": "礼来", "market": "US"},
    {"symbol": "AVGO", "name": "博通", "market": "US"},
    {"symbol": "JPM", "name": "摩根大通", "market": "US"},
    {"symbol": "V", "name": "Visa", "market": "US"},
    {"symbol": "XOM", "name": "埃克森美孚", "market": "US"},
    {"symbol": "COST", "name": "好市多", "market": "US"},
    {"symbol": "ORCL", "name": "甲骨文", "market": "US"},
    {"symbol": "PG", "name": "宝洁", "market": "US"},
    {"symbol": "HD", "name": "家得宝", "market": "US"},
    {"symbol": "NFLX", "name": "奈飞", "market": "US"},
]


def _norm_symbol(s: str) -> str:
    """归一化去重键：去掉 .HK/.US 后缀（基座 ETF 带后缀、spot 全量列表不带）。"""
    return s.split(".")[0].lower()


def _sort_search_results(items: list[dict], keyword: str) -> list[dict]:
    """Z20: 统一搜索排序契约（SQL 与 Python 降级行为完全一致）。

    分档优先级（高 → 低）:
      1 精确代码（symbol == kw，大小写不敏感）
      2 代码前缀（symbol.startswith(kw)）
      3 精确名称（name == kw）
      4 名称前缀（name.startswith(kw)）
      5 名称包含（kw in name）
      6 拼音/首字母（first_letter 前缀匹配，简化实现）
      7 其他

    同档内次序:
      type_rank: etf=0 < stock=1
      market_rank: A=1 < HK=2 < US=3 < index/commodity=4
      symbol 字典序升序（大小写不敏感）

    确定性: 相同输入 → 相同输出（sorted 稳定）。
    """
    kw = (keyword or "").strip()
    kw_lower = kw.lower()

    def _rank(item: dict):
        sym = str(item.get("symbol", "") or "")
        name = str(item.get("name", "") or "")
        asset_type = str(item.get("asset_type", "") or "").lower()
        market = str(item.get("market", "") or "")

        if sym.lower() == kw_lower:
            tier = 1
        elif kw_lower and sym.lower().startswith(kw_lower):
            tier = 2
        elif name == kw:
            tier = 3
        elif kw and name.startswith(kw):
            tier = 4
        elif kw and kw in name:
            tier = 5
        elif kw:
            first_letters = "".join(c[0] for c in name.split() if c).upper()
            if first_letters.startswith(kw.upper()):
                tier = 6
            else:
                tier = 7
        else:
            tier = 7

        type_rank = 0 if asset_type == "etf" else 1
        market_rank = {
            "A": 1, "HK": 2, "US": 3,
            "index": 4, "commodity": 4, "gold": 4, "oil": 4, "silver": 4,
        }.get(market, 9)
        return (tier, type_rank, market_rank, sym.lower())

    return sorted(items, key=_rank)


async def search_hk_us(keyword: str = "", enrich: bool = True,
                       include_stocks: bool = False) -> list[dict[str, Any]]:
    """三级搜索 HK/US：静态基座 →（include_stocks=True 时）akshare 全量 spot → ETF 实时 enrich。

    include_stocks=False 为默认（仅静态 ETF 基座，向后兼容，不触网——
    既有 F3 单测保持纯静态）；True 时启用 spot 动态补充（调用方显式传入）。

    asset_type 统一为市场代码（"HK"/"US"），type 为证券种类（"etf"/"stock"）——
    与 PortfolioManager.selectHotEtf / watchlist 添加链路的 asset_type 语义对齐。

    enrich 仅作用于 type=="etf" 命中（全部来自静态 ETF 基座，≤24 只）：
    spot 个股命中量大且行内已带实时价 → 不 enrich（防限流）；
    静态基座个股命中因 HK 实时链路前缀 bug 不可靠 → 不 enrich（R5）。
    """
    kw = keyword.lower().strip()
    # ① 静态基座: HKUS_ETF_MAP（恒有）+ HKUS_STOCK_MAP（仅 include_stocks 时，参数语义一致）
    base_pool = HKUS_ETF_MAP + (HKUS_STOCK_MAP if include_stocks else [])
    base = [{
        "symbol": e["symbol"], "name": e["name"], "market": e["market"],
        "asset_type": e["market"],
        "type": "etf" if e["symbol"] in _HKUS_ETF_SYMBOLS else "stock",
    } for e in base_pool
        if not kw or kw in e["symbol"].lower() or kw in e["name"].lower()]

    # ② 动态补充: akshare 全量 spot（尽力而为；与基座按归一化 symbol 去重，基座优先）
    spot: list[dict[str, Any]] = []
    if include_stocks:
        # 函数内局部导入 + 每次调用重新解析模块属性 → 测试 patch 模块属性即生效
        from ..fetchers.china_market import fetch_hk_spot_list, fetch_us_spot_list
        # 并发拉取两个市场的 spot（单个最坏 10s 超时，串行会翻倍阻塞搜索）
        spot_rows = await asyncio.gather(
            _call(fetch_hk_spot_list, timeout=15),
            _call(fetch_us_spot_list, timeout=15),
            return_exceptions=True,
        )
        for mk, rows in zip(("HK", "US"), spot_rows):
            if not rows or not isinstance(rows, list):
                continue
            for r in rows:
                sym = r.get("symbol", "")
                name = r.get("name", "")
                name_en = r.get("name_en") or ""
                if kw and kw not in sym.lower() and kw not in name.lower() and kw not in name_en.lower():
                    continue
                spot.append({
                    "symbol": sym, "name": name_en or name,
                    "market": mk, "asset_type": mk, "type": "stock",
                })

    # 去重（key 归一化处理 .HK/.US 后缀不一致；base 在前 → 基座优先天然成立）
    seen: set[tuple[str, str]] = set()
    merged: list[dict[str, Any]] = []
    for it in base + spot:
        key = (_norm_symbol(it["symbol"]), it["market"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(it)
    results = merged[:30]

    if not enrich:
        return results

    # ③ enrich 仅作用于 type=="etf" 命中
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

    etf_results = [it for it in results if it["type"] == "etf"]
    try:
        enriched = await asyncio.gather(*(_enrich(it) for it in etf_results),
                                        return_exceptions=True)
        # gather 保持顺序，与 etf_results 一一对应；_enrich 返回新 dict，不能用 id() 映射
        enriched_map = {
            (orig["symbol"], orig["market"]): new
            for orig, new in zip(etf_results, enriched) if isinstance(new, dict)
        }
        results = [enriched_map.get((it["symbol"], it["market"]), it)
                   if it["type"] == "etf" else it for it in results]
    except Exception as _exc:
        logger.warning("[search_hk_us] enrichment gather failed: %s", _exc)
    return results


_HKUS_ETF_SYMBOLS = {e["symbol"] for e in HKUS_ETF_MAP}


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


# N07: 同步超时结果短缓存（3s TTL）——避免数据源慢时每次请求都重复等待
_asset_realtime_cache: dict[tuple[str, str], tuple[float, dict | None]] = {}
_ASSET_REALTIME_CACHE_TTL = 3.0


async def get_asset_realtime(symbol: str, asset_type: str) -> dict | None:
    from ..fetchers.china_market import fetch_a_stock_realtime, fetch_hk_stock_realtime

    # N07: 3s 短缓存（并发请求/重复刷新场景避免重复 8s 等待）
    _ckey = (str(symbol).upper(), str(asset_type).upper())
    _cached = _asset_realtime_cache.get(_ckey)
    if _cached and (time.time() - _cached[0]) < _ASSET_REALTIME_CACHE_TTL:
        return _cached[1]

    # N07: _call 超时按 asset_type 分级——A 股 8s，HK/US 放宽到 15s
    # （港股降级链更长，8s 常超时导致间歇 null）
    _timeout = 8 if asset_type == "A" else 15

    result: dict | None = None
    try:
        if asset_type == "US":
            data = await _route_us(symbol)
            # F3-7: 美股实时数据源（TwelveData/Finnhub）可能无 name →
            # 用静态基座映射补全（自选 SPY 显示 "SPDR S&P 500 ETF"）
            if data and not data.get("name"):
                data["name"] = _us_static_name(symbol)
            result = data
        # U1/N03: 按 asset_type 分流——HK 标的不再先跑 A 股路径。
        # 旧逻辑先查 A 股再查 HK：A 股路径对非 A 股代码返回空被计为失败，
        # 污染 sina/tencent 熔断状态（round2 U1 / round3 N03 根因）。
        elif asset_type == "HK":
            all_hk = await _call(fetch_hk_stock_realtime, symbol, timeout=_timeout)
            for item in all_hk or []:
                if item["symbol"] == symbol:
                    result = item
                    break
        else:
            all_a = await _call(fetch_a_stock_realtime, symbol, timeout=_timeout)
            for item in all_a or []:
                if item["symbol"] == symbol:
                    result = item
                    break
            # 非 A/HK/US 类型（或 A 股查无此标的）：保持旧行为尝试 HK 兜底
            if result is None and asset_type != "A":
                all_hk = await _call(fetch_hk_stock_realtime, symbol, timeout=_timeout)
                for item in all_hk or []:
                    if item["symbol"] == symbol:
                        result = item
                        break
    except Exception:
        pass

    _asset_realtime_cache[_ckey] = (time.time(), result)
    return result


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

    def _td():
        return global_markets_fetcher.fetch_realtime_twelvedata(symbol)
    def _fh():
        return global_markets_fetcher.fetch_realtime(symbol)

    return registry.route([
        ("twelvedata", _td),
        ("finnhub", _fh),
    ], route_name="US_ETF", operation="realtime", target=symbol)


def _us_static_name(symbol: str) -> str:
    """F3-7: 从静态基座映射查美股名称（SPY → 'SPDR S&P 500 ETF'）。"""
    sym = (symbol or "").upper()
    if not sym:
        return ""
    for e in HKUS_ETF_MAP + HKUS_STOCK_MAP:
        if e.get("market") == "US" and str(e.get("symbol", "")).upper() == sym:
            return str(e.get("name", ""))
    return ""


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
        from .market_data_hub import market_data_hub
        cached = market_data_hub.get_kline_rows(symbol, max_age=300)
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
    k_data = await _call(get_k_data, symbol, period, timeout=15) or []
    if k_data:
        return k_data

    # F0-4: akshare 熔断 / 数据源全线失败时，从 Hub K 线缓存取任意年龄的过期数据
    # 兜底（stale 标记），避免 history/indicators/signal 全线 insufficient_data。
    try:
        from .market_data_hub import market_data_hub
        stale_rows = market_data_hub.get_kline_rows_any(symbol)
        if stale_rows:
            age = market_data_hub.get_kline_age_seconds(symbol)
            market_data_hub.mark_kline_stale(symbol, True)
            logger.warning(
                "[market_service] get_history all sources empty for %s (%s) — "
                "falling back to stale K-line cache (age=%.0fs, rows=%d)",
                symbol, asset_type, age if age is not None else -1, len(stale_rows),
            )
            return stale_rows
    except Exception as e:
        logger.debug("[market_service] stale cache fallback failed for %s: %s", symbol, e)
    return []


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

async def resolve_symbol_to_code(symbol: str, asset_type: str = "A") -> str | None:
    """按名称反查标的代码（Z22 watchlist 脏数据自愈）。

    当 watchlist 中 symbol 存的是中文名称（历史脏数据）时，据此函数
    反查真实代码。

    路径:
    1. ETF（asset_type in A/etf/ETF）: 查 instruments 表 name 匹配
       （先精确、后包含），返回 symbol 列。
    2. 个股（asset_type == A）: fetch_all_stocks() 全量列表按
       stock_name 精确 → 包含匹配，返回 stock_code。
    3. 其他市场: 暂不支持，返回 None。

    返回解析出的真实代码，失败返回 None。
    """
    from ..models.search import Instrument
    from sqlalchemy import or_

    kw = (symbol or "").strip()
    if not kw:
        return None

    # ── 1. ETF / 指数路径：本地 instruments 表 ─────────────────────
    try:
        async with async_session() as session:
            # 先精确名称匹配
            stmt_exact = (
                select(Instrument.symbol)
                .where(
                    Instrument.is_active == True,  # noqa: E712
                    Instrument.name == kw,
                )
                .limit(5)
            )
            exact_rows = (await session.execute(stmt_exact)).scalars().all()
            if exact_rows:
                return exact_rows[0]
            # 包含匹配：取 symbol 最短（最可能是主代码）
            stmt = (
                select(Instrument.symbol)
                .where(
                    Instrument.is_active == True,  # noqa: E712
                    Instrument.name.like(f"%{kw}%"),
                )
                .limit(20)
            )
            rows = (await session.execute(stmt)).scalars().all()
            if rows:
                rows_sorted = sorted(rows, key=lambda s: len(s))
                return rows_sorted[0]
    except Exception as e:
        logger.warning("[watchlist] resolve_symbol_to_code instruments lookup failed: %s", e)

    # ── 2. 个股路径：全量 A 股列表按名称匹配 ────────────────────────
    try:
        from ..services.market_data_hub import market_data_hub

        full = market_data_hub.get_all_stocks() or []
        for item in full:
            stock_name = item.get("stock_name") or item.get("name") or ""
            if stock_name == kw:
                return item.get("stock_code") or item.get("symbol")
        # 包含匹配：优先 symbol 前缀匹配 6 位
        candidates = [
            item for item in full
            if kw in (item.get("stock_name") or item.get("name") or "")
        ]
        if candidates:
            candidates.sort(key=lambda i: len(i.get("stock_code") or i.get("symbol") or ""))
            return candidates[0].get("stock_code") or candidates[0].get("symbol")
    except Exception as e:
        logger.warning("[watchlist] resolve_symbol_to_code stock lookup failed: %s", e)

    return None


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

        # Enrich with realtime data (N07: 串行 → asyncio.gather 并发)
        async def _enrich_one(item):
            try:
                realtime = await get_asset_realtime(item.symbol, item.asset_type)
            except Exception:
                realtime = None
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

        enriched = await asyncio.gather(*[_enrich_one(i) for i in items])

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
