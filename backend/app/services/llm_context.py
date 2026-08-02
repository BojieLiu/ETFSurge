"""
llm_context.py — 统一的 LLM 上下文数据采集管道 (Phase 2.9).

替代三个 LLM 端点各自独立采集数据的模式。
所有方法都包含 try/except，确保单点失败不影响整体。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def build_full_context(
    market_data_hub,
    market: str = "A",
    include_regime: bool = True,
    include_sentiment: bool = True,
    include_indices: bool = True,
    include_sectors: bool = True,
    include_news: bool = True,
    include_portfolio: bool = True,
    include_fund_flow: bool = True,
    include_commodities: bool = True,
    include_global_liquidity: bool = True,
) -> dict:
    """统一的 LLM 上下文数据采集。

    所有字段都有 try/except 保护，单源失败不污染整体。
    market_data_hub 参数是已初始化的 MarketDataHub 单例。

    Returns:
        dict: 包含请求的上下文数据
    """
    context: dict = {}
    errors: list[str] = []

    # 1. Market regime (Phase 5.1: 按市场获取)
    if include_regime:
        try:
            context["market_regime"] = market_data_hub.get_market_regime(market) or ""
        except Exception as e:
            context["market_regime"] = ""
            errors.append(f"regime: {e}")

    # 2. Market sentiment
    if include_sentiment:
        try:
            context["market_sentiment"] = market_data_hub.get_market_sentiment() or {}
        except Exception as e:
            context["market_sentiment"] = {}
            errors.append(f"sentiment: {e}")

    # 3. Index realtime (from market_data_hub cache)
    # F1-4: 按 market 参数分支 — A 股用本地指数缓存；HK/US 从全球指数
    # 分组（get_global_indices）取对应区域，修复 market=HK/US 仍输出 A 股指数。
    if include_indices:
        try:
            if market.upper() in ("HK", "US", "EU", "欧股"):
                global_idx = await asyncio.wait_for(
                    market_data_hub.get_global_indices(), timeout=15
                ) or {}
                region = {"HK": "港股", "US": "美股", "EU": "欧股", "欧股": "欧股"}.get(market.upper(), "A股")
                idx_data = global_idx.get(region, []) or []
            else:
                idx_data = market_data_hub.get_index_realtime() or []
            context["index_realtime"] = idx_data[:10]
        except Exception as e:
            context["index_realtime"] = []
            errors.append(f"indices: {e}")

    # 4. Sector momentum + hot plates + sector heat (Phase 6.1.6)
    # F1-4: 板块数据仅 A 股市场适用（HK/US 无本地板块采集）
    if include_sectors and market.upper() in ("A", ""):
        try:
            sector_data = market_data_hub.get_sector_momentum() or []
            context["sector_momentum"] = sector_data[:15]
        except Exception as e:
            context["sector_momentum"] = []
            errors.append(f"sectors: {e}")
        # Phase 6.1.6: 注入热点板块和板块热度排行
        try:
            hot_plates_data = market_data_hub.get_hot_plates() or []
            context["hot_plates"] = hot_plates_data[:10]
        except Exception as e:
            context["hot_plates"] = []
            errors.append(f"hot_plates: {e}")
        try:
            sector_heat_data = market_data_hub.get_sector_heat() or []
            context["sector_heat"] = sector_heat_data[:15]
        except Exception as e:
            context["sector_heat"] = []
            errors.append(f"sector_heat: {e}")

    # 5. Realtime market data (from market_service cache)
    # N04/U9: 按 market 过滤——HK/US 报告不再注入全量 A 股指数实时（旧代码
    # get_all_realtime() 只含 A 股指数 → HK/US 报告大谈创业板/上证50）。
    # 注意：直接使用传入的 market_data_hub 参数（旧代码 `from ... import
    # market_data_hub` 遮蔽参数名 → 单测注入的 FakeHub 失效、依赖全局单例）。
    try:
        all_realtime = await asyncio.wait_for(market_data_hub.get_all_realtime(), timeout=15)
        if market.upper() in ("HK", "US", "EU", "欧股"):
            from app.core.market_context import resolve_market_context
            market_ctx = resolve_market_context(market)
            # get_all_realtime 只含 A 股指数；对 HK/US 补充对应区域全球指数
            global_idx = await asyncio.wait_for(
                market_data_hub.get_global_indices(), timeout=15
            ) or {}
            region = {"HK": "港股", "US": "美股", "EU": "欧股", "欧股": "欧股"}.get(market.upper(), "A股")
            region_data = list(global_idx.get(region, []) or [])
            # 再叠加该市场 major_symbols 的实时数据（若有）
            major_symbols = market_ctx.major_symbols or set()
            context["market_data"] = (region_data + [
                r for r in (all_realtime or []) if r.get("symbol") in major_symbols
            ])[:20]
        else:
            context["market_data"] = all_realtime[:20] if all_realtime else []
    except Exception as e:
        context["market_data"] = []
        errors.append(f"realtime: {e}")

    # 6. News
    if include_news:
        try:
            from ..services.market_data_hub import market_data_hub
            news_items = await asyncio.to_thread(market_data_hub.get_news_headlines) or []
            try:
                macro_items = await asyncio.to_thread(market_data_hub.get_news_macro) or []
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
            commodities = await asyncio.wait_for(market_data_hub.get_commodities(), timeout=15)
            context["commodities"] = commodities[:10] if commodities else []
        except Exception as e:
            context["commodities"] = []
            errors.append(f"commodities: {e}")

    # 8. Fund flow (from market_data_hub pool data)
    if include_fund_flow:
        try:
            from ..services.strategy_design import _compute_fund_flow
            context["fund_flow"] = await _compute_fund_flow(market_data_hub)
        except Exception as e:
            context["fund_flow"] = {}
            errors.append(f"fund_flow: {e}")

    # 9. Portfolio holdings
    if include_portfolio:
        try:
            from ..services.portfolio_service import portfolio_service  # type: ignore[attr-defined]
            # Use get_holdings or similar if available
            context["portfolio"] = []
        except Exception:
            context["portfolio"] = []

    # 10. 海外流动性（P1-5 / R4-23）——FRED 美债10Y/VIX/联邦基金利率。
    # 任一指标失败静默（该键不注入）；全部失败时不注入该段，不影响主报告。
    if include_global_liquidity:
        gl: dict[str, float] = {}
        try:
            from ..fetchers.global_markets_fetcher import (
                fetch_fed_rate,
                fetch_us_10y,
                fetch_vix,
            )
            _us10, _vix, _fed = await asyncio.wait_for(
                asyncio.gather(
                    fetch_us_10y(), fetch_vix(), fetch_fed_rate(),
                    return_exceptions=True,
                ),
                timeout=15,
            )
            for _k, _v in (("us_10y", _us10), ("vix", _vix), ("fed_rate", _fed)):
                if isinstance(_v, float):
                    gl[_k] = round(_v, 2)
        except Exception as e:
            errors.append(f"global_liquidity: {e}")
        if gl:
            context["global_liquidity"] = gl

    if errors:
        logger.debug("[llm_context] build_full_context partial errors: %s", errors)

    return context
