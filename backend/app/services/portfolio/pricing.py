"""Price-map building helpers — split from portfolio_service (Batch 1)."""

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_utils import run_sync
from app.models.portfolio import PortfolioETF
from app.services.market_data_hub import market_data_hub

logger = logging.getLogger(__name__)

_PRICE_MAP_CACHE: dict[tuple, tuple[float, dict]] = {}

_PRICE_MAP_TTL = 15.0

_FUNDAMENTALS_CACHE: dict[tuple, tuple[float, dict]] = {}


async def build_price_map(etfs: list[PortfolioETF | dict]) -> dict[str, tuple[float, float]]:
    """Public wrapper: fetch realtime prices for all holdings concurrently (F8).

    Runs the independent A-share batch, HK, US and index fetches in parallel
    via asyncio.gather + run_sync so a slow source does not block the others.
    """
    try:
        return await _build_price_map_async(etfs)
    except Exception:
        return {}


async def _build_price_map_async(etfs):
    """Concurrently fetch realtime prices for all holdings (F8 + F2-1)."""
    a_symbols, hk_symbols, us_symbols, tracked_a = _split_symbols(etfs)
    _cache_key = (
        tuple(sorted(a_symbols)),
        tuple(sorted(hk_symbols)),
        tuple(sorted(us_symbols)),
        tuple(sorted(tracked_a)),
    )
    _now = time.monotonic()
    _cached = _PRICE_MAP_CACHE.get(_cache_key)
    if _cached and (_now - _cached[0]) < _PRICE_MAP_TTL:
        return _cached[1]
    m: dict[str, tuple[float, float]] = {}

    async def _a_batch():
        if not a_symbols:
            return []
        # P2-1 (R4-16): 单源超时截断 3s——慢源降级为空并 WARN，不拖累整体
        try:
            return await asyncio.wait_for(
                run_sync(market_data_hub.get_a_stock_batch, a_symbols), timeout=3.0)
        except Exception as e:
            logger.warning("[price_map] A股批量行情超时/失败（3s 截断）: %s", e)
            return []

    async def _hk_batch():
        if not hk_symbols:
            return {}

        async def _one(s):
            try:
                items = await run_sync(market_data_hub.get_hk_stock_realtime, s)
                if items:
                    return s, (float(items[0]["price"]), float(items[0]["change_pct"]))
            except Exception:
                pass
            return s, None

        out = {}
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_one(s) for s in hk_symbols], return_exceptions=True),
                timeout=3.0)
        except Exception as e:
            logger.warning("[price_map] 港股行情超时（3s 截断）: %s", e)
            return out
        for r in results:
            if isinstance(r, tuple) and r[1] is not None:
                out[r[0]] = r[1]
        return out

    async def _us_batch():
        if not us_symbols:
            return {}

        async def _one(s):
            try:
                data = await run_sync(market_data_hub.get_us_etf_realtime, s)
                if data:
                    return s, (float(data["price"]), float(data["change_pct"]))
            except Exception:
                pass
            return s, None

        out = {}
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_one(s) for s in us_symbols], return_exceptions=True),
                timeout=3.0)
        except Exception as e:
            logger.warning("[price_map] 美股行情超时（3s 截断）: %s", e)
            return out
        for r in results:
            if isinstance(r, tuple) and r[1] is not None:
                out[r[0]] = r[1]
        return out

    async def _idx_batch():
        try:
            return {it["symbol"]: (it["price"], it["change_pct"]) for it in await asyncio.wait_for(
                run_sync(market_data_hub.get_index_realtime), timeout=3.0)}
        except Exception as e:
            logger.warning("[price_map] 指数行情超时（3s 截断）: %s", e)
            return {}

    # F8: run independent top-level fetches concurrently (offloaded to threads).
    results = await asyncio.gather(_a_batch(), _hk_batch(), _us_batch(), _idx_batch(),
                                    return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            continue
        if isinstance(res, list):  # A-share batch
            for item in res:
                m[item["symbol"]] = (item["price"], item["change_pct"])
        elif isinstance(res, dict):  # HK / US / index
            m.update(res)

    # NAV fallback for off-exchange tracked indices still missing (parallel).
    tracked = list({_get_etf_attr(e, "tracked_index") for e in etfs
                    if _get_etf_attr(e, "tracked_index") and _get_etf_attr(e, "tracked_index") not in m})
    if tracked:
        async def _nav(s):
            try:
                # P2-1: NAV 单源 3s 截断
                nav = await asyncio.wait_for(
                    run_sync(market_data_hub.get_fund_nav, s), timeout=3.0)
                # round9 P0-7: fetch_fund_nav 契约统一为 dict {"nav","daily_change_pct","nav_date"}
                if nav and isinstance(nav, dict) and nav.get("nav"):
                    return s, (float(nav["nav"]), float(nav.get("daily_change_pct") or 0.0))
            except Exception:
                pass
            return s, None

        nav_res = await asyncio.gather(*[_nav(t) for t in tracked])
        for s, val in nav_res:
            if val is not None:
                m[s] = val

    # Map tracked_index prices to fund symbols for off-exchange funds
    for e in etfs:
        sym = _get_etf_attr(e, "symbol")
        ti = _get_etf_attr(e, "tracked_index")
        if ti and ti in m and sym not in m:
            m[sym] = m[ti]

    _PRICE_MAP_CACHE[_cache_key] = (time.monotonic(), m)
    return m


def _get_etf_attr(e, attr, default=None):
    """Read symbol/asset_type/tracked_index from a PortfolioETF or dict."""
    if isinstance(e, dict):
        return e.get(attr, default)
    return getattr(e, attr, default)


def _split_symbols(etfs):
    a_symbols = [_get_etf_attr(e, "symbol") for e in etfs
                 if _get_etf_attr(e, "asset_type") == "A"
                 and _get_etf_attr(e, "symbol", "")[:1] in ("1", "5", "6")]
    hk_symbols = [_get_etf_attr(e, "symbol") for e in etfs if _get_etf_attr(e, "asset_type") == "HK"]
    us_symbols = [_get_etf_attr(e, "symbol") for e in etfs if _get_etf_attr(e, "asset_type") == "US"]
    tracked_a = [_get_etf_attr(e, "tracked_index") for e in etfs
                 if _get_etf_attr(e, "tracked_index") and _get_etf_attr(e, "tracked_index", "")[:1] in ("1", "5", "6")]
    a_symbols = a_symbols + tracked_a
    return a_symbols, hk_symbols, us_symbols, tracked_a


async def _fetch_realtime_price(db: AsyncSession, etf: PortfolioETF) -> float | None:
    """round19 P3-②/③: 实时价取价（adjust 语义 price 缺省时兜底；拿不到 None）。"""
    try:
        from ...services.market_data_hub import market_data_hub
        rt = await market_data_hub.get_asset_realtime(etf.symbol, etf.asset_type)
        p = (rt or {}).get("price") if rt else None
        return float(p) if p else None
    except Exception:
        return None


def _clear_price_map_cache() -> None:
    """清空行情缓存（测试与手动刷新用）。"""
    _PRICE_MAP_CACHE.clear()
    _FUNDAMENTALS_CACHE.clear()
