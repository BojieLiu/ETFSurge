"""
Market Router — 按市场路由数据请求 (Phase 5.1).

提供 5 个 async 路由函数，根据 market 参数将数据请求分发到正确的数据源。

用法:
    from app.services.market_router import get_market_indices, get_market_realtime
    indices = await get_market_indices("HK")
"""

from __future__ import annotations

import asyncio
import logging

from app.core.async_utils import run_sync

logger = logging.getLogger(__name__)


async def _call(fn, *args, timeout: int = 8):
    """包装 run_sync 统一超时。"""
    return await run_sync(fn, *args, timeout=timeout)


# ── 指数路由 ────────────────────────────────────────────────


async def get_market_indices(market: str) -> list[dict]:
    """按市场返回相关指数行情。"""
    from app.services.market_service import get_indices as get_a_indices
    from app.services.market_service import get_global_indices

    if market == "A":
        data = await get_a_indices()
        return data or []

    # HK/US/global → 从全球指数中过滤
    try:
        global_data = await get_global_indices() or {}
    except Exception:
        logger.warning("[market_router] get_global_indices failed")
        return []

    region_map = {"HK": "港股", "US": "美股", "global": None}
    target_region = region_map.get(market)

    if target_region is None:
        # global: 展平所有区域
        flattened = []
        for region_list in global_data.values():
            if isinstance(region_list, list):
                flattened.extend(region_list)
        return flattened

    return global_data.get(target_region, [])


# ── 实时行情路由 ──────────────────────────────────────────


async def get_market_realtime(market: str, symbols: list[str] | None = None) -> list[dict]:
    """按市场路由实时行情。

    Args:
        market: "A" | "HK" | "US" | "global"
        symbols: 可选的标的列表过滤

    Returns:
        list[dict]: 实时行情数据
    """
    if market == "A":
        from app.services.market_service import get_all_realtime
        data = await get_all_realtime()
        if symbols:
            sym_set = set(symbols)
            return [d for d in data if d.get("symbol") in sym_set]
        return data or []

    elif market == "HK":
        if not symbols:
            return []
        from app.fetchers.china_market import fetch_hk_stock_realtime
        results = []
        for sym in symbols:
            try:
                items = await _call(fetch_hk_stock_realtime, sym, timeout=8)
                if items:
                    results.extend(items)
            except Exception:
                logger.warning("[market_router] HK realtime failed for %s", sym)
        return results

    elif market == "US":
        if not symbols:
            return []
        from app.fetchers import global_markets_fetcher
        # Stooq API closed (Cloudflare 404); fall through to TwelveData
        batch = None
        if batch:
            return batch
        # 降级: TwelveData 逐个
        results = []
        for sym in symbols:
            d = await _call(global_markets_fetcher.fetch_realtime, sym, timeout=8)
            if d:
                d["asset_type"] = "US"
                results.append(d)
        return results

    elif market == "global":
        from app.services.market_service import get_all_realtime
        a_data = await get_all_realtime() or []
        indices_data = await get_market_indices("global")
        return a_data + indices_data

    return []


# ── 历史K线路由 ───────────────────────────────────────────


async def get_market_history(market: str, symbol: str, period: str = "daily") -> list[dict]:
    """按市场路由历史K线。"""
    if market == "A":
        from app.services.market_service import get_history
        return await get_history(symbol, "A", period) or []

    elif market == "HK":
        # fetch_hk_history removed (doesn't exist in china_market.py)
        return []

    elif market == "US":
        from app.fetchers import global_markets_fetcher
        # Fall through to TwelveData
        fallback_data = None
        if fallback_data:
            return fallback_data
        td_data = await _call(global_markets_fetcher.fetch_history, symbol, 60, timeout=10)
        if td_data:
            return td_data
        fh_data = await _call(global_markets_fetcher.fetch_candles, symbol, "D", timeout=10)
        return fh_data or []

    elif market == "global":
        return await get_market_history("A", symbol, period)  # 默认回退

    return []


# ── 新闻路由 ──────────────────────────────────────────────


async def get_market_news(market: str, max_count: int = 10) -> list[dict]:
    """按市场选择新闻源。

    注：当前仅 A 股有专有新闻源（财联社/宏观）。HK/US 通过国际通用新闻补充。
    """
    from app.services.market_data_hub import market_data_hub

    all_news: list = []
    try:
        headlines = await _call(market_data_hub.get_news_headlines, timeout=8) or []
        all_news.extend(headlines)
    except Exception:
        logger.warning("[market_router] get_news_headlines failed")

    try:
        macro = await _call(market_data_hub.get_news_macro, timeout=8) or []
        all_news.extend(macro)
    except Exception:
        logger.warning("[market_router] get_news_macro failed")

    try:
        global_news = await _call(market_data_hub.get_news_global, timeout=8) or []
        all_news.extend(global_news)
    except Exception:
        logger.warning("[market_router] get_news_global failed")

    return all_news[:max_count]


# ── 板块路由 ──────────────────────────────────────────────


async def get_market_sectors(market: str, sector_type: str = "industry") -> list[dict]:
    """按市场选择板块数据源。

    当前仅 A 股有成熟板块数据（申万/东财）。HK/US 返回空列表。
    """
    if market != "A":
        return []

    from app.fetchers.sector_fetcher import fetch_industry_sectors, fetch_concept_sectors

    try:
        if sector_type == "concept":
            return await _call(fetch_concept_sectors, 200, timeout=10) or []
        return await _call(fetch_industry_sectors, 200, timeout=10) or []
    except Exception:
        logger.warning("[market_router] sector fetch failed for %s", market)
        return []

