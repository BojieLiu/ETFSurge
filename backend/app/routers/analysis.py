import asyncio
import json
from fastapi import APIRouter, Query, Depends

from ..core.logging import get_logger

logger = get_logger(__name__)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from ..analysis.llm import (
    generate_market_report, generate_advice, analyze_news, analyze_news_impact,
    generate_portfolio_design, generate_sector_analysis, generate_symbol_analysis,
)
from ..analysis.registry import get_agent
from ..services.market_service import (
    get_all_realtime, get_history, get_indices, get_commodities,
    get_asset_realtime, get_realtime_batch,
)
from ..services.portfolio_service import list_etfs, build_price_map
from ..analysis.indicators import compute_all_indicators
from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news
from ..fetchers.sector_fetcher import (
    fetch_industry_sectors, fetch_concept_sectors, fetch_sector_stocks,
)
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
                yield f"event: done\ndata: {json.dumps({'full_text': data.get('full_text', ''), 'metadata': data.get('usage', {})})}\n\n"
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


class SectorAnalysisRequest(BaseModel):
    sector_code: str
    sector_type: str = "industry"
    sector_name: str = ""


class SymbolAnalysisRequest(BaseModel):
    symbol: str
    name: str = ""
    asset_type: str = "A"


class NewsImpactRequest(BaseModel):
    news: dict[str, Any]
    portfolio: list[dict[str, Any]] = []


class LLMReportRequest(BaseModel):
    symbols: list[str] | None = None


async def _fetch_all_market():
    from ..fetchers.yfinance_fetcher import fetch_us_etf_realtime
    results = await asyncio.gather(
        asyncio.wait_for(get_all_realtime(), timeout=20),
        asyncio.wait_for(get_indices(), timeout=20),
        asyncio.wait_for(get_commodities(), timeout=20),
        return_exceptions=True,
    )
    def _safe(r, fallback):
        return r if isinstance(r, list) else fallback
    market_data = _safe(results[0], [])
    indices = _safe(results[1], [])
    commodities = _safe(results[2], [])

    # Concurrently fetch US indices and commodities via yfinance
    us_symbols = {"^GSPC": "标普500", "^IXIC": "纳斯达克", "^DJI": "道琼斯",
                  "GC=F": "黄金", "CL=F": "原油", "SI=F": "白银"}
    loop = asyncio.get_running_loop()
    us_tasks = {}
    for sym, name in us_symbols.items():
        us_tasks[sym] = (name, loop.run_in_executor(None, fetch_us_etf_realtime, sym))

    for sym, (name, task) in us_tasks.items():
        try:
            d = await asyncio.wait_for(task, timeout=10)
            if d and d.get("price"):
                d["name"] = name
                if sym in ("GC=F", "CL=F", "SI=F"):
                    commodities.append(d)
                else:
                    market_data.append(d)
        except Exception:
            pass

    return market_data, indices, commodities


def _collect_news():
    news = fetch_news_headlines() or []
    try:
        macro = fetch_macro_news() or []
        news.extend(macro)
    except Exception:
        pass
    return news


@router.post("/llm-report")
async def llm_report(req: LLMReportRequest):
    try:
        market_data, indices, commodities = await _fetch_all_market()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {e}")

    if req.symbols:
        market_data = [m for m in market_data if m.get("symbol") in req.symbols]
    else:
        major_symbols = {"000001", "399001", "399006", "000688", "000300", "510050", "510300", "510500", "159915"}
        market_data = [m for m in market_data if m.get("symbol", "") in major_symbols or m.get("asset_type", "") in ("index", "futures")]

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

    news = _collect_news()
    try:
        report = await generate_market_report(indices, commodities, market_data, indicators, news, [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM analysis failed: {e}")
    return {"report": report, "market_data": market_data[:10], "indices": indices[:10], "commodities": commodities[:6]}


@router.post("/llm-advice")
async def llm_advice(query: str = Query(...), context: dict | None = None):
    try:
        advice = await generate_advice(query, context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM advice failed: {e}")
    return {"advice": advice}


@router.post("/llm-news-analysis")
async def llm_news_analysis():
    news = _collect_news()
    try:
        analysis = await analyze_news(news)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM news analysis failed: {e}")
    return {"analysis": analysis, "news_count": len(news)}


@router.post("/news-impact")
async def news_impact(req: NewsImpactRequest):
    """分析单条新闻对当前组合内各标的的具体影响。"""
    result = await analyze_news_impact(req.news, req.portfolio)
    return result


class PortfolioDesignRequest(BaseModel):
    """组合设计请求体"""
    capital: float = 500000


@router.post("/portfolio-design")
async def portfolio_design(req: PortfolioDesignRequest | None = None, db: AsyncSession = Depends(get_db)):
    market_data, indices, commodities = await _fetch_all_market()
    news = _collect_news()
    capital = req.capital if req else 500000

    # Also fetch portfolio ETF prices
    try:
        etfs = await list_etfs(db)
        if etfs:
            pm = await build_price_map(etfs)
            for e in etfs:
                price, change_pct = pm.get(e.symbol, (0, 0))
                market_data.append({
                    "symbol": e.symbol, "name": e.name,
                    "price": price, "change_pct": change_pct,
                    "asset_type": e.asset_type, "portfolio_type": e.portfolio_type,
                })
    except Exception as exc:
        logger.warning(f"[portfolio-design] ETF price fetch error: {exc}")

    major_symbols = {"000001", "399001", "399006", "000688", "000300", "000016", "000905",
                     "510050", "510300", "510500", "159915", "588000", "513100", "518880", "511880"}
    filtered = [m for m in market_data if m.get("symbol", "") in major_symbols or m.get("asset_type", "") in ("index", "futures")]
    if len(filtered) < 20 and market_data:
        filtered = market_data[:50]

    try:
        result = await generate_portfolio_design(indices, commodities, filtered, news, [], capital=capital)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM portfolio design failed: {e}")
    result["indices"] = indices[:8]
    result["commodities"] = commodities[:6]
    return result


class PortfolioReviewRequest(BaseModel):
    """组合检视请求体"""
    portfolio_type: str  # 进攻型 | 防御型 | 平衡型
    last_rebalance_date: str
    current_portfolio_holdings: list[dict]  # 包含 ticker, weight_pct, cost_basis_price, current_price, return_since_rebalance_pct, liquidity_tier, avg_daily_turnover_mn, tracking_error_annualized, dividend_yield_ttm
    new_market_snapshot: dict  # 包含 macro, style_factor_zscore, sector_performance_1m_pct, risk_indicators
    risk_budget: dict  # 包含 max_single_etf_weight_pct, max_sector_deviation_from_benchmark_pct, max_annualized_tracking_error_pct, max_drawdown_alert_threshold_pct, min_avg_daily_turnover_mn, min_aum_bn, max_illiquid_etf_proportion_pct, rebalance_trigger_band
    type_thresholds: dict  # 进攻型/防御型/平衡型各自的阈值
    meta_context: dict  # strategy_target_type, benchmark_index, last_rebalance_date, current_date, days_since_rebalance, total_portfolio_value_mn, current_annualized_volatility_pct


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

    return result


@router.post("/sector-analysis")
async def sector_analysis(req: SectorAnalysisRequest):
    """行业/概念板块 AI 分析: 行情 + 资金面 + 催化因素。"""
    sector_code = req.sector_code
    sector_type = req.sector_type
    sector_name = req.sector_name
    # 1. 取板块列表, 找到该板块数据
    if sector_type == "concept":
        sectors = await asyncio.to_thread(fetch_concept_sectors, 200)
    else:
        sectors = await asyncio.to_thread(fetch_industry_sectors, 200)
    sector_data = next((s for s in sectors if s.get("sector_code") == sector_code), None)
    if not sector_data and sector_name:
        sector_data = next((s for s in sectors if s.get("sector_name") == sector_name), None)
    name = sector_name or (sector_data.get("sector_name", "") if sector_data else sector_code)

    # 2. 成分股
    constituents = await asyncio.to_thread(fetch_sector_stocks, sector_code)

    # 3. 资讯
    news = fetch_news_headlines() or []
    try:
        macro = fetch_macro_news() or []
        news.extend(macro)
    except Exception:
        pass

    try:
        report = await generate_sector_analysis(
            sector_code=sector_code,
            sector_name=name,
            sector_stocks=constituents,
            indices=[],
            commodities=[],
            market_data=news,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM sector analysis failed: {e}")
    return {"sector_name": name, "sector_code": sector_code, "report": report, "constituents_count": len(constituents)}


@router.post("/symbol-analysis")
async def symbol_analysis(req: SymbolAnalysisRequest):
    """个股/ETF AI 分析: 行情 + 技术指标 + 资讯催化。"""
    symbol = req.symbol
    name = req.name
    asset_type = req.asset_type
    # 1. 实时行情
    realtime = await get_asset_realtime(symbol, asset_type) or {}

    # 2. 历史 + 技术指标
    hist = []
    try:
        hist = await asyncio.wait_for(get_history(symbol, asset_type, "daily"), timeout=30)
    except Exception:
        pass
    indicators = compute_all_indicators(hist) if hist else {}

    # 3. 资讯
    news = fetch_news_headlines() or []
    try:
        macro = fetch_macro_news() or []
        news.extend(macro)
    except Exception:
        pass

    display_name = name or (realtime.get("name", "") if realtime else symbol)
    try:
        report = await generate_symbol_analysis(
            symbol=symbol,
            name=display_name,
            asset_type=asset_type,
            realtime=realtime or {},
            history=hist,
            indicators=indicators,
            news=news,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM symbol analysis failed: {e}")
    return {"symbol": symbol, "name": display_name, "report": report}


# ── SSE Streaming Endpoints ──────────────────────────────────────────────


@router.post("/llm-report/stream")
async def llm_report_stream(req: LLMReportRequest):
    """流式市场研判报告"""
    try:
        # Fetch market data (same as non-streaming)
        market_data, indices, commodities = await _fetch_all_market()
        news = _collect_news()
        
        # Get indicators for portfolio ETFs
        indicators = {}
        try:
            etfs = await list_etfs(None)
            for e in etfs:
                hist = await asyncio.wait_for(get_history(e.symbol, e.asset_type), timeout=30)
                ind = compute_all_indicators(hist) if hist else {}
                if ind:
                    indicators[e.symbol] = ind
        except Exception:
            pass
        
        # Build prompt
        prompt = _build_report_prompt(indices, commodities, market_data, indicators, news, [])
        
        # Stream from agent
        agent = get_agent("market_report")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")


@router.post("/llm-advice/stream")
async def llm_advice_stream(query: str = Query(...), context: dict | None = None):
    """流式投资建议问答"""
    try:
        prompt = f"用户提问: {query}\n\n"
        if context:
            prompt += f"上下文信息: {json.dumps(context, ensure_ascii=False)}\n\n"
        prompt += "请给出专业、简洁的回答，控制在 500 字以内，使用 Markdown 格式"
        
        agent = get_agent("advice")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")


@router.post("/portfolio-design/stream")
async def portfolio_design_stream(req: PortfolioDesignRequest | None = None, db: AsyncSession = Depends(get_db)):
    """流式组合设计"""
    try:
        market_data, indices, commodities = await _fetch_all_market()
        news = _collect_news()
        capital = req.capital if req else 500000
        
        # Also fetch portfolio ETF prices
        try:
            etfs = await list_etfs(db)
            if etfs:
                pm = await build_price_map(etfs)
                for e in etfs:
                    price, change_pct = pm.get(e.symbol, (0, 0))
                    market_data.append({
                        "symbol": e.symbol, "name": e.name,
                        "price": price, "change_pct": change_pct,
                        "asset_type": e.asset_type, "portfolio_type": e.portfolio_type,
                    })
        except Exception as exc:
            logger.warning(f"[portfolio-design] ETF price fetch error: {exc}")
        
        major_symbols = {"000001", "399001", "399006", "000688", "000300", "000016", "000905",
                         "510050", "510300", "510500", "588000", "159915", "512880", "515790"}
        major_data = [d for d in market_data if d.get("symbol") in major_symbols]
        
        prompt = f"""基于以下实时数据，为投资金额 {capital:,.0f} 元设计三种风险偏好的 ETF 组合方案：
进攻型（≥90% 权益，科技/成长为主）、平衡型（65-85% 权益，混合）、防御型（50-75% 权益，高股息/低波为主）。

## A股主要指数
{_format_indices(indices)}

## 全球指数
{_format_major_etfs(major_data)}

## 大宗商品
{_format_commodities(commodities)}

## 重要资讯
{_format_news(news)}

请按以下结构输出 JSON：
{{
  "design_text": "完整 Markdown 报告",
  "data_snapshot_time": "北京时间",
  "market_environment": "宏观环境描述",
  "portfolios": [
    {{"style": "进攻型", "portfolio_name": "...", "positioning": "...", "expected_return": 0.15, "max_drawdown": 0.25, "sharpe_ratio": 0.8, "expected_characteristics": "...", "weight_logic": [...], "market_analysis": {{}}, "allocation_rationale": {{}}, "etfs": [...]}}
  ]
}}"""
        
        agent = get_agent("portfolio_design")
        return _sse_stream(agent.run_stream(prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")


@router.post("/sector-analysis/stream")
async def sector_analysis_stream(req: SectorAnalysisRequest):
    """流式板块分析"""
    try:
        sector_code = req.sector_code
        sector_type = req.sector_type
        sector_name = req.sector_name
        
        if sector_type == "concept":
            sectors = await asyncio.to_thread(fetch_concept_sectors, 200)
        else:
            sectors = await asyncio.to_thread(fetch_industry_sectors, 200)
        sector_data = next((s for s in sectors if s.get("sector_code") == sector_code), None)
        name = sector_name or (sector_data.get("sector_name", "") if sector_data else sector_code)
        
        constituents = await asyncio.to_thread(fetch_sector_stocks, sector_code)
        news = fetch_news_headlines() or []
        try:
            macro = fetch_macro_news() or []
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
        
        news = fetch_news_headlines() or []
        try:
            macro = fetch_macro_news() or []
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
