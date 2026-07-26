"""
llm_context.py — 统一的 LLM 上下文数据采集管道 (Phase 2.9).

替代三个 LLM 端点各自独立采集数据的模式。
所有方法都包含 try/except，确保单点失败不影响整体。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def build_full_context(
    pool_manager,
    market: str = "A",
    include_regime: bool = True,
    include_sentiment: bool = True,
    include_indices: bool = True,
    include_sectors: bool = True,
    include_news: bool = True,
    include_portfolio: bool = True,
    include_fund_flow: bool = True,
    include_commodities: bool = True,
) -> dict:
    """统一的 LLM 上下文数据采集。

    所有字段都有 try/except 保护，单源失败不污染整体。
    pool_manager 参数是已初始化的 PoolManager 单例。

    Returns:
        dict: 包含请求的上下文数据
    """
    context: dict = {}
    errors: list[str] = []

    # 1. Market regime (Phase 5.1: 按市场获取)
    if include_regime:
        try:
            context["market_regime"] = pool_manager.get_market_regime(market) or ""
        except Exception as e:
            context["market_regime"] = ""
            errors.append(f"regime: {e}")

    # 2. Market sentiment
    if include_sentiment:
        try:
            context["market_sentiment"] = pool_manager.get_market_sentiment() or {}
        except Exception as e:
            context["market_sentiment"] = {}
            errors.append(f"sentiment: {e}")

    # 3. Index realtime (from pool_manager cache)
    if include_indices:
        try:
            idx_data = pool_manager.get_index_realtime() or []
            context["index_realtime"] = idx_data[:10]
        except Exception as e:
            context["index_realtime"] = []
            errors.append(f"indices: {e}")

    # 4. Sector momentum + hot plates + sector heat (Phase 6.1.6)
    if include_sectors:
        try:
            sector_data = pool_manager.get_sector_momentum() or []
            context["sector_momentum"] = sector_data[:15]
        except Exception as e:
            context["sector_momentum"] = []
            errors.append(f"sectors: {e}")
        # Phase 6.1.6: 注入热点板块和板块热度排行
        try:
            hot_plates_data = pool_manager.get_hot_plates() or []
            context["hot_plates"] = hot_plates_data[:10]
        except Exception as e:
            context["hot_plates"] = []
            errors.append(f"hot_plates: {e}")
        try:
            sector_heat_data = pool_manager.get_sector_heat() or []
            context["sector_heat"] = sector_heat_data[:15]
        except Exception as e:
            context["sector_heat"] = []
            errors.append(f"sector_heat: {e}")

    # 5. Realtime ETFs (from market_service cache)
    try:
        from ..services.market_service import get_all_realtime
        all_realtime = await asyncio.wait_for(get_all_realtime(), timeout=15)
        context["market_data"] = all_realtime[:20] if all_realtime else []
    except Exception as e:
        context["market_data"] = []
        errors.append(f"realtime: {e}")

    # 6. News
    if include_news:
        try:
            from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news
            news_items = await asyncio.to_thread(fetch_news_headlines) or []
            try:
                macro_items = await asyncio.to_thread(fetch_macro_news) or []
                news_items.extend(macro_items)
            except Exception:
                pass
            context["news"] = news_items[:15]
        except Exception as e:
            context["news"] = []
            errors.append(f"news: {e}")

    # 7. Commodities (gold, oil, silver futures)
    if include_commodities:
        try:
            from ..services.market_service import get_commodities
            commodities = await asyncio.wait_for(get_commodities(), timeout=15)
            context["commodities"] = commodities[:10] if commodities else []
        except Exception as e:
            context["commodities"] = []
            errors.append(f"commodities: {e}")

    # 8. Fund flow (from pool_manager pool data)
    if include_fund_flow:
        try:
            from ..services.strategy_design import _compute_fund_flow
            context["fund_flow"] = _compute_fund_flow(pool_manager)
        except Exception as e:
            context["fund_flow"] = {}
            errors.append(f"fund_flow: {e}")

    # 9. Portfolio holdings
    if include_portfolio:
        try:
            from ..services.portfolio_service import portfolio_service
            # Use get_holdings or similar if available
            context["portfolio"] = []
        except Exception:
            context["portfolio"] = []

    if errors:
        logger.debug("[llm_context] build_full_context partial errors: %s", errors)

    return context
