import asyncio
import json
import time
from fastapi import APIRouter, Query, Depends

from ..core.logging import get_logger

logger = get_logger(__name__)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from ..analysis.llm import (
    generate_market_report, generate_advice, analyze_news, analyze_news_impact,
    generate_sector_analysis, generate_symbol_analysis,
    _build_report_prompt,
)
from ..analysis.registry import get_agent
from ..services.market_service import (
    get_all_realtime, get_history, get_indices, get_commodities,
    get_asset_realtime, get_realtime_batch,
)

from ..analysis.indicators import compute_all_indicators
from ..services.market_data_hub import market_data_hub
from ..services.market_data_hub import market_data_hub
from ..database import get_db
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


FETCH_TIMEOUT = 45


def _sse_stream(agent_generator):
    """Convert AgentRuntime async generator to SSE StreamingResponse."""
    async def event_generator():
        async for item in agent_generator:
            event = item.get("event")
            data = item.get("data")
            if event == "token":
                yield f"event: token\ndata: {json.dumps({'token': data.get('token', '')})}\n\n"
            elif event == "done":
                full_text = data.get('full_text', '')
                # Append disclaimer to the final response
                disclaimer = "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
                full_text_with_disclaimer = f"{full_text}\n\n---\n*{disclaimer}*"
                yield f"event: done\ndata: {json.dumps({'full_text': full_text_with_disclaimer, 'metadata': data.get('usage', {}), 'disclaimer': disclaimer})}\n\n"
            elif event == "error":
                yield f"event: error\ndata: {json.dumps({'code': 'STREAM_ERROR', 'message': data})}\n\n"
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


def _inject_market_context(query: str, ctx: dict) -> dict:
    """根据 query 关键词智能注入市场数据到 context。

    Sector Phase 5: 流式和非流式路由共享的公共函数。
    根据查询关键词识别用户意图，从 market_data_hub 缓存获取对应数据注入 ctx。
    """
    from ..services.market_data_hub import market_data_hub
    q = query.lower()
    injection_lines = []

    # 板块/行业/概念相关查询
    sector_keywords = ["板块", "行业", "概念", "热点", "半导体", "新能源", "消费", "医药", "科技", "金融", "军工"]
    if any(kw in q for kw in sector_keywords):
        sector = market_data_hub.get_sector_momentum() or []
        for item in sector[:5]:
            name = item.get("sector_name") or item.get("name", "?")
            chg = item.get("change_pct", 0)
            if isinstance(chg, (int, float)):
                injection_lines.append(f"· {name}: 涨跌幅 {chg:+.2f}%")
            else:
                injection_lines.append(f"· {name}")

    # 大盘/行情相关查询
    market_keywords = ["大盘", "今天", "最新", "市场", "行情", "指数"]
    if any(kw in q for kw in market_keywords):
        idx_data = market_data_hub.get_index_realtime() or []
        for item in idx_data[:5]:
            name = item.get("name", item.get("symbol", "?"))
            price = item.get("price", "")
            chg = item.get("change_pct", "")
            if isinstance(chg, (int, float)):
                injection_lines.append(f"· {name}: {price} ({chg:+.2f}%)")
            else:
                injection_lines.append(f"· {name}: {price}")

    if injection_lines:
        ctx["market_snapshot"] = "\n".join(injection_lines)
    return ctx


class SectorAnalysisRequest(BaseModel):
    sector_code: str
    sector_type: str = "industry"
    sector_name: str = ""
    market: str = "A"


class SymbolAnalysisRequest(BaseModel):
    symbol: str
    name: str = ""
    asset_type: str = "A"


class NewsImpactRequest(BaseModel):
    news: dict[str, Any]
    portfolio: list[dict[str, Any]] = []


class LLMReportRequest(BaseModel):
    symbols: list[str] | None = None
    market: str = "A"


class LLMAdviceRequest(BaseModel):
    query: str
    market: str = "A"
    context: dict | None = None


# _fetch_all_market 已废弃 — 数据管道统一在编排器中采集
# 参见 strategy_design.py 或 market_data_hub.refresh()


# --- Market Overview 已迁移到数据管道 ---
# 不再使用独立缓存，统一由编排器提供


# TODO: 未接入前端（前端使用 /llm-report/stream 流式版本）
@router.post("/llm-report")
async def llm_report(req: LLMReportRequest):
    """市场综合研判报告 — 优先使用编排器缓存，降级才自采。"""
    # 尝试从编排器取缓存数据
    from ..services.market_data_hub import market_data_hub

    try:
        regime = market_data_hub.get_market_regime()
        sentiment = market_data_hub.get_market_sentiment()
        if regime:
            logger.debug("[llm-report] using orchestrator cache: regime=%s", regime)
    except Exception:
        regime = None
        sentiment = None

    try:
        from ..services.market_service import get_all_realtime, get_indices, get_commodities
        
        results = await asyncio.gather(
            asyncio.wait_for(get_all_realtime(), timeout=15),
            asyncio.wait_for(get_indices(), timeout=15),
            asyncio.wait_for(get_commodities(), timeout=15),
            asyncio.to_thread(market_data_hub.get_news_headlines),
            asyncio.to_thread(market_data_hub.get_news_macro),
            return_exceptions=True,
        )

        def _safe(r, fallback):
            return r if isinstance(r, list) else fallback

        market_data = _safe(results[0], [])
        indices = _safe(results[1], [])
        commodities = _safe(results[2], [])
        news_items = _safe(results[3], [])
        macro_items = _safe(results[4], [])
        all_news = news_items + macro_items
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {e}")

    if req.symbols:
        market_data = [m for m in market_data if m.get("symbol") in req.symbols]
    else:
        from app.core.market_context import resolve_market_context
        market_ctx = resolve_market_context(req.market)
        market_data = [m for m in market_data if m.get("symbol", "") in market_ctx.major_symbols or m.get("asset_type", "") in ("index", "futures")]

    indicators = {}
    for item in market_data[:5]:
        if item.get("asset_type") in ("index", "futures"):
            continue
        try:
            hist = await asyncio.wait_for(get_history(item["symbol"], item["asset_type"]), timeout=30)
            ind = compute_all_indicators(hist)
            if ind:
                indicators[item["symbol"]] = ind
        except Exception:
            continue

    # 注入编排器的市场状态和情绪数据
    enriched_news = all_news
    if regime or sentiment:
        context = []
        if regime:
            context.append(f"市场状态: {regime}")
        if sentiment and isinstance(sentiment, dict):
            s_idx = sentiment.get("sentiment_index", "")
            s_lbl = sentiment.get("sentiment_label", "")
            context.append(f"市场情绪: {s_lbl} ({s_idx}/100)" if s_idx else f"市场情绪: {s_lbl}")
        if context:
            enriched_news = [{"title": "【市场背景】" + " | ".join(context)}] + all_news
    try:
        report = await generate_market_report(indices, commodities, market_data, indicators, enriched_news, [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM analysis failed: {e}")
    return {"report": report, "market_data": market_data[:10], "indices": indices[:10], "commodities": commodities[:6], "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"}


# TODO: 未接入前端（前端使用 /llm-advice/stream 流式版本）
@router.post("/llm-advice")
async def llm_advice(req: LLMAdviceRequest):
    """AI 投资顾问 — 自动注入市场数据管道缓存。"""
    from ..services.market_data_hub import market_data_hub

    query = req.query
    ctx = dict(req.context or {})

    # 根据 query 关键词智能注入管道数据（零额外采集成本）
    try:
        q = query.lower()
        injection_lines = []

        if any(kw in q for kw in ["大盘", "今天", "最新", "走势", "行情"]):
            regime = market_data_hub.get_market_regime()
            sentiment = market_data_hub.get_market_sentiment()
            if regime:
                injection_lines.append(f"· 市场状态: {regime}")
            if sentiment and isinstance(sentiment, dict):
                idx = sentiment.get("sentiment_index", "?")
                lbl = sentiment.get("sentiment_label", "?")
                injection_lines.append(f"· 市场情绪: {lbl} ({idx}/100)")
            # index_realtime from market_data_hub or fallback
            idx_data = market_data_hub.get_index_realtime() or []
            for item in idx_data[:5]:
                injection_lines.append(
                    f"· {item.get('name','?')}: {item.get('price','N/A')} ({item.get('change_pct',0):+.2f}%)"
                )

        if any(kw in q for kw in ["板块", "行业", "半导体", "新能源", "医药", "军工", "消费"]):
            sector = market_data_hub.get_sector_momentum() or []
            for item in sector[:5]:
                injection_lines.append(
                    f"· {item.get('name','?')}: 涨跌幅 {item.get('change_pct',0):+.2f}%"
                )

        if any(kw in q for kw in ["政策", "利好", "利空", "监管", "新闻", "资讯"]):
            news = market_data_hub.get_news() or []
            sentiment = market_data_hub.get_market_sentiment()
            if sentiment and isinstance(sentiment, dict):
                lbl = sentiment.get("sentiment_label", "?")
                injection_lines.append(f"· 市场情绪: {lbl}")
            for n in news[:5]:
                title = n.get("title", "")[:100]
                injection_lines.append(f"· {title}")

        if injection_lines:
            ctx["market_snapshot"] = "\n".join(injection_lines)
    except Exception as e:
        logger.debug("[llm-advice] smart injection skipped: %s", e)

    try:
        advice = await generate_advice(query, ctx)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM advice failed: {e}")
    return {"advice": advice, "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"}


# TODO: 未接入前端
@router.post("/llm-news-analysis")
async def llm_news_analysis():
    news = market_data_hub.get_news_headlines() or []
    try:
        macro = market_data_hub.get_news_macro() or []
        news.extend(macro)
    except Exception:
        pass
    try:
        analysis = await analyze_news(news)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM news analysis failed: {e}")
    return {"analysis": analysis, "news_count": len(news), "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"}


@router.post("/news-impact")
async def news_impact(req: NewsImpactRequest):
    """分析单条新闻对当前组合内各标的的具体影响。"""
    result = await analyze_news_impact(req.news, req.portfolio)
    result["disclaimer"] = "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
    return result


# ── /portfolio-design 已废弃 ──
# 组合设计功能已迁移到 POST /portfolio/design-async（引擎驱动）
# 旧 LLM 路径不再维护


class PortfolioReviewRequest(BaseModel):
    """组合检视请求体"""
    portfolio_type: str  # 进攻型 | 防御型 | 平衡型
    last_rebalance_date: str
    current_portfolio_holdings: list[dict]  # 包含 ticker, weight_pct, cost_basis_price, current_price, return_since_rebalance_pct, liquidity_tier, avg_daily_turnover_mn, tracking_error_annualized, dividend_yield_ttm
    new_market_snapshot: dict  # 包含 macro, style_factor_zscore, sector_performance_1m_pct, risk_indicators
    risk_budget: dict  # 包含 max_single_etf_weight_pct, max_sector_deviation_from_benchmark_pct, max_annualized_tracking_error_pct, max_drawdown_alert_threshold_pct, min_avg_daily_turnover_mn, min_aum_bn, max_illiquid_etf_proportion_pct, rebalance_trigger_band
    type_thresholds: dict  # 进攻型/防御型/平衡型各自的阈值
    meta_context: dict  # strategy_target_type, benchmark_index, last_rebalance_date, current_date, days_since_rebalance, total_portfolio_value_mn, current_annualized_volatility_pct


# TODO: 未接入前端
@router.post("/portfolio-review")
async def portfolio_review(req: PortfolioReviewRequest):
    """
    ETF 组合动态检视/再平衡（Strategy Review Officer 模式）
    
    输入：完整的持仓快照 + 最新行情快照 + 风控预算 + 类型阈值
    输出：REBALANCE（含买卖清单）或 HOLD（含未触发理由），严格 JSON 格式
    """
    # 构造完整输入
    input_data = {
        "portfolio_type": req.portfolio_type,
        "last_rebalance_date": req.last_rebalance_date,
        "current_portfolio_holdings_example": req.current_portfolio_holdings,
        "new_market_snapshot_example": req.new_market_snapshot,
        "risk_budget": req.risk_budget,
        "type_thresholds": req.type_thresholds,
        "meta_context": req.meta_context,
    }
    
    # 使用 registry 中的 portfolio_review agent（risk_officer.md 提示词），强制 JSON 输出
    from ..analysis.registry import get_agent

    try:
        result = await get_agent("portfolio_review").run_json(
            json.dumps(input_data, ensure_ascii=False)
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM portfolio review failed: {e}")

    result["disclaimer"] = "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
    return result


    #     )
    # except Exception as e:
    #     raise HTTPException(status_code=502, detail=f"LLM sector analysis failed: {e}")
    # return {"sector_name": name, "sector_code": sector_code, "report": report, "constituents_count": len(constituents), "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"}



@router.post("/llm-report/stream")
async def llm_report_stream(req: LLMReportRequest):
    """流式市场研判报告 — 使用统一上下文管道 (Phase 2.9)。"""
    from ..services.market_data_hub import market_data_hub
    from ..services.llm_context import build_full_context

    # 使用统一上下文管道采集数据
    ctx = await build_full_context(
        market_data_hub,
        include_regime=True,
        include_sentiment=True,
        include_indices=True,
        include_sectors=True,
        include_news=True,
        include_portfolio=False,
        include_fund_flow=False,
        include_commodities=True,
    )

    regime = ctx.get("market_regime", "")
    sentiment = ctx.get("market_sentiment", {})
    market_data = ctx.get("market_data", [])
    indices = ctx.get("index_realtime", [])
    commodities = ctx.get("commodities", [])
    all_news = ctx.get("news", [])

    # Phase 5.1: 使用 MarketContext 按市场过滤主要标的
    from app.core.market_context import resolve_market_context

    market_ctx = resolve_market_context(req.market)
    if req.symbols:
        market_data = [m for m in market_data if m.get("symbol") in req.symbols]
    else:
        market_data = [m for m in market_data if m.get("symbol", "") in market_ctx.major_symbols or m.get("asset_type", "") in ("index", "futures")]

    indicators = {}
    for item in market_data[:5]:
        if item.get("asset_type") in ("index", "futures"):
            continue
        try:
            hist = await asyncio.wait_for(get_history(item["symbol"], item["asset_type"]), timeout=30)
            ind = compute_all_indicators(hist) if hist else {}
            if ind:
                indicators[item["symbol"]] = ind
        except Exception:
            continue

    # 注入编排器的市场状态和情绪数据
    enriched_news = all_news
    if regime or sentiment:
        context = []
        if regime:
            context.append(f"市场状态: {regime}")
        if sentiment and isinstance(sentiment, dict):
            s_idx = sentiment.get("sentiment_index", "")
            s_lbl = sentiment.get("sentiment_label", "")
            context.append(f"市场情绪: {s_lbl} ({s_idx}/100)" if s_idx else f"市场情绪: {s_lbl}")
        if context:
            enriched_news = [{"title": "【市场背景】" + " | ".join(context)}] + all_news

    try:
        # Phase E(2): True streaming — 使用 agent.run_stream 实时推送 LLM token
        prompt = _build_report_prompt(indices, commodities, market_data, indicators, enriched_news, [])
        agent = get_agent("market_report")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")


@router.post("/llm-advice/stream")
async def llm_advice_stream(req: LLMAdviceRequest):
    """流式投资建议问答 — 使用统一上下文管道 (Phase 2.9)。

    Phase D(1): 新增 market 参数，传递给 build_full_context() 按市场获取数据。
    """
    from ..services.market_data_hub import market_data_hub
    from ..services.llm_context import build_full_context
    from ..analysis.llm import _build_advice_stream_prompt

    # 使用统一上下文管道（按市场获取数据）
    ctx = await build_full_context(
        market_data_hub,
        market=req.market,
        include_regime=True,
        include_sentiment=True,
        include_indices=True,
        include_sectors=True,
        include_news=True,
        include_portfolio=False,
        include_fund_flow=True,
        include_commodities=False,
    )

    # Merge with user-provided context
    user_ctx = dict(req.context or {})
    user_ctx.update(ctx)

    # Build market_data for advice from index_realtime + sector_momentum
    market_data = list(ctx.get("index_realtime", []) or [])
    sector_data = ctx.get("sector_momentum", []) or []
    for s in sector_data[:5]:
        market_data.append({
            "name": s.get("sector_name") or s.get("name", "?"),
            "change_pct": s.get("change_pct"),
            "asset_type": "sector",
        })
    user_ctx["market_data"] = market_data
    user_ctx["market_regime"] = ctx.get("market_regime", "")
    user_ctx["market_sentiment"] = ctx.get("market_sentiment", {})
    user_ctx["sector_momentum"] = sector_data[:10]
    user_ctx["fund_flow"] = ctx.get("fund_flow", {})
    user_ctx["news"] = ctx.get("news", [])

    # Sector Phase 5: 注入市场上下文
    user_ctx = _inject_market_context(req.query, user_ctx)

    try:
        prompt = _build_advice_stream_prompt(req.query, user_ctx)
        from ..analysis.registry import get_agent
        agent = get_agent("advice")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")


# ── /portfolio-design/stream 已废弃 ──
# 组合设计流式端点已移除，使用 POST /portfolio/design-async


@router.post("/sector-analysis/stream")
async def sector_analysis_stream(req: SectorAnalysisRequest):
    """流式板块分析 — Phase 5.1: 非 A 市场返回友好提示。"""
    try:
        sector_code = req.sector_code
        sector_type = req.sector_type
        sector_name = req.sector_name

        # Phase 5.1: 非 A 市场不支持板块分析
        from app.core.market_context import resolve_market_context
        market_ctx = resolve_market_context(req.market)
        if not market_ctx.supports_sector_analysis:
            prompt = f"当前市场为 {market_ctx.title}，该市场暂无板块分析数据。请切换到 A 股市场查看板块分析。"
            disclaimer = "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
            async def empty_generator():
                yield f"event: done\ndata: {json.dumps({'full_text': prompt, 'disclaimer': disclaimer})}\n\n"
            return StreamingResponse(
                empty_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )

        if sector_type == "concept":
            sectors = await asyncio.to_thread(market_data_hub.get_sector_concept, 200)
        else:
            sectors = await asyncio.to_thread(market_data_hub.get_sector_industry, 200)
        sector_data = next((s for s in sectors if s.get("sector_code") == sector_code), None)
        name = sector_name or (sector_data.get("sector_name", "") if sector_data else sector_code)
        
        constituents = await asyncio.to_thread(market_data_hub.get_sector_stocks, sector_code)
        news = market_data_hub.get_news_headlines() or []
        try:
            macro = market_data_hub.get_news_macro() or []
            news.extend(macro)
        except Exception:
            pass
        
        prompt = f"""分析板块 {name} ({sector_code})：
成分股：{json.dumps(constituents[:15], ensure_ascii=False)}
资讯：{json.dumps(news[:10], ensure_ascii=False)}

请输出：板块概况、资金面、技术面、催化因素、风险提示、核心标的推荐"""
        
        agent = get_agent("sector_analysis")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")


@router.post("/symbol-analysis/stream")
async def symbol_analysis_stream(req: SymbolAnalysisRequest):
    """流式标的深度解读"""
    try:
        symbol = req.symbol
        name = req.name
        asset_type = req.asset_type
        
        realtime = await get_asset_realtime(symbol, asset_type) or {}
        hist = []
        try:
            hist = await asyncio.wait_for(get_history(symbol, asset_type, "daily"), timeout=30)
        except Exception:
            pass
        indicators = compute_all_indicators(hist) if hist else {}
        
        news = market_data_hub.get_news_headlines() or []
        try:
            macro = market_data_hub.get_news_macro() or []
            news.extend(macro)
        except Exception:
            pass
        
        display_name = name or (realtime.get("name", "") if realtime else symbol)
        
        prompt = f"""深度分析标的 {display_name} ({symbol})：
实时行情：{json.dumps(realtime, ensure_ascii=False)}
技术指标：{json.dumps(indicators, ensure_ascii=False)}
历史K线(最近30条)：{json.dumps(hist[-30:], ensure_ascii=False) if hist else '无'}
资讯催化：{json.dumps(news[:10], ensure_ascii=False)}

请输出：基本面概览、技术面分析、资讯催化、风险提示、操作建议"""
        
        agent = get_agent("symbol_analysis")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")


@router.post("/news-impact/stream")
async def news_impact_stream(req: NewsImpactRequest):
    """流式单条新闻影响分析"""
    try:
        holdings_text = "\n".join(
            f"- {h.get('symbol', '')} {h.get('name', '')} "
            f"({h.get('asset_type', '')}) 目标权重 {h.get('target_weight', '')}"
            for h in req.portfolio
        ) or "（组合为空）"
        
        prompt = f"""新闻标题：{req.news.get('title', '')}
新闻内容：{req.news.get('content', '')}

当前组合持仓：
{holdings_text}

请分析这条新闻对组合的影响，重点回答：
(a) 影响范围（市场/板块）；
(b) 组合内哪些标的会受到影响、具体如何受影响。
只返回约定结构的 JSON。"""
        
        agent = get_agent("news_impact")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")
