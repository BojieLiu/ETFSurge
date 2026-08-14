import asyncio
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
    generate_market_report, generate_advice, analyze_news_impact,
    generate_sector_analysis, generate_symbol_analysis,
    _build_report_prompt,
)
from ..analysis.registry import get_agent
from ..services.market_data_hub import market_data_hub
from ..services.llm_context import build_full_context
from ..services.market_service import get_history

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

def _sse_error(message: str):
    """R21: 结构化 SSE error 事件——前端 useLLMStream 抛错走 catch 显示。"""
    return StreamingResponse(
        iter([f"event: error\ndata: {json.dumps({'code': 'DATA_UNAVAILABLE', 'message': message})}\n\n"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

def _build_advice_market_snapshot(query: str, hub) -> str:
    """R5-1-3: 投顾市场快照统一构建——无条件注入基础数据（指数/市态/情绪），
    关键词命中额外注入板块动量/新闻摘要。数据全部来自缓存，零采集成本。

    旧逻辑按关键词表（["大盘","今天","最新","走势","行情"]）命中才注入，
    "当前A股市场怎么配置"（含 A股/配置，不含旧词）不命中 → 全降级模板。
    修复：无条件注入，任何问题都带实时市场数据。
    """
    q = (query or "").lower()
    lines: list[str] = []

    # 无条件基础注入：市态 + 情绪 + 指数（数据来自缓存）
    try:
        regime = hub.get_market_regime()
        if regime:
            lines.append(f"· 市场状态: {regime}")
        sentiment = hub.get_market_sentiment()
        if sentiment and isinstance(sentiment, dict):
            lbl = sentiment.get("sentiment_label", "?")
            idx = sentiment.get("sentiment_index", "?")
            lines.append(f"· 市场情绪: {lbl} ({idx}/100)")
        idx_data = hub.get_index_realtime() or []
        if not idx_data:
            # R6-F6 (round6 §十 R6-07'): 东财限流时 get_index_realtime 空 →
            # 从 market_service 的全球指数缓存兜底——快照构建是同步函数，
            # 不能 await async get_global_indices。
            # O3 (round8 §7 P2-新): stale 分支会把 _global_indices_cache 各 region
            # 重建为空 list 写回（与 /indices/global 的 last_ok 管道不同步）→
            # 改为 24h 兜底 _global_indices_last_ok 优先（含磁盘持久化，可靠），
            # 30s 缓存次之；两套缓存路径由此同步。
            try:
                from ..services import market_service as _ms
                _cache = getattr(_ms, "_global_indices_cache", None) or {}
                _ok = getattr(_ms, "_global_indices_last_ok", None) or {}
                # cache 有数据优先；cache 被 stale 分支清空（region=[]）时回退
                # 24h 兜底 last_ok（与 /indices/global 同一管道，含磁盘持久化）。
                idx_data = list(_cache.get("A股") or []) or list(_ok.get("A股") or [])
            except Exception:
                idx_data = []
        for item in idx_data[:5]:
            name = item.get("name", item.get("symbol", "?"))
            price = item.get("price", "N/A")
            chg = item.get("change_pct", 0)
            if isinstance(chg, (int, float)):
                lines.append(f"· {name}: {price} ({chg:+.2f}%)")
            else:
                lines.append(f"· {name}: {price}")
    except Exception:
        pass

    # 关键词命中额外注入：板块/行业
    sector_keywords = ["板块", "行业", "概念", "热点", "半导体", "新能源", "消费", "医药", "科技", "金融", "军工"]
    if any(kw in q for kw in sector_keywords):
        try:
            sector = hub.get_sector_momentum() or []
            # O3 (round8 §7 P2-新): 板块动量缓存空时回退行业板块实时数据，
            # 投顾快照不再出现「板块热力全缺失」。
            if not sector and hasattr(hub, "get_sector_industry"):
                try:
                    sector = hub.get_sector_industry() or []
                except Exception:
                    sector = []
            for item in sector[:5]:
                name = item.get("sector_name") or item.get("name", "?")
                chg = item.get("change_pct", 0)
                if isinstance(chg, (int, float)):
                    lines.append(f"· {name}: 涨跌幅 {chg:+.2f}%")
                else:
                    lines.append(f"· {name}")
        except Exception:
            pass

    # 关键词命中额外注入：新闻摘要
    news_keywords = ["政策", "利好", "利空", "监管", "新闻", "资讯"]
    if any(kw in q for kw in news_keywords):
        try:
            news = hub.get_news_headlines() or []
            for n in news[:5]:
                lines.append(f"· {(n.get('title', '') or '')[:100]}")
        except Exception:
            pass

    return "\n".join(lines)

def _inject_market_context(query: str, ctx: dict) -> dict:
    """根据 query 关键词智能注入市场数据到 context。

    Sector Phase 5: 流式和非流式路由共享的公共函数。
    R5-1-3: 无条件注入 market_snapshot（指数/市态/情绪/板块/新闻，数据来自缓存），
    旧关键词表覆盖不全（"A股/配置"缺失）导致"当前A股市场怎么配置"不命中。
    """
    from ..services.market_data_hub import market_data_hub
    snapshot = _build_advice_market_snapshot(query, market_data_hub)
    if snapshot:
        ctx["market_snapshot"] = snapshot
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
    # P2-9 B1 (round16 3.9): 补 market 字段显式声明——前端 UnifiedAnalysis 传 market
    # 旧实现无该字段 → Pydantic 忽略 extra 静默丢弃（HK/US 上下文丢失靠 asset_type 兜底）。
    market: str = "A"
    # F10 R35: 预设问题模板（技术面/操作建议等）——可选中个股后针对性分析
    question: str = ""

class NewsImpactRequest(BaseModel):
    news: dict[str, Any]
    portfolio: list[dict[str, Any]] = []

class LLMReportRequest(BaseModel):
    symbols: list[str] | None = None
    market: str = "A"

def _filter_indices_for_market(market_ctx, indices: list[dict]) -> list[dict]:
    """P0-2 (R4-13 / N04 补全): 指数按市场过滤——HK/US 报告不再混入 A 股指数。

    与 market_data 的 N04 修复（market_ctx.index_symbols 白名单）对齐；
    symbol 做 ^ 前缀归一化（数据侧 "HSI" 与配置侧 "^HSI" 等价）。
    A/GLOBAL 市场保持全量（A 报告引用日经/美股属正常关联信息）。
    """
    if market_ctx.market not in ("HK", "US"):
        return indices
    idx_syms = {str(s).lstrip("^") for s in market_ctx.index_symbols}
    if not idx_syms:
        return []
    filtered = [i for i in (indices or [])
                if str(i.get("symbol", "")).lstrip("^") in idx_syms]
    if filtered != indices:
        logger.info(
            "[llm-report] indices filtered for market=%s: %d → %d (A股指数已排除)",
            market_ctx.market, len(indices or []), len(filtered),
        )
    return filtered

def _filter_commodities_for_market(market_ctx, commodities: list[dict]) -> list[dict]:
    """P0-2: 商品行情按市场过滤——HK/US 报告不注入 A 股期货市场数据。

    commodities 为国内期货实时行情（沪金/沪银/原油等，A 股市场数据源），
    对 HK/US 研判无直接关联，避免污染；A/GLOBAL 保留。
    """
    if market_ctx.market in ("HK", "US"):
        return []
    return commodities or []

class LLMAdviceRequest(BaseModel):
    query: str
    market: str = "A"
    context: dict | None = None

@router.post("/news-impact")
async def news_impact(req: NewsImpactRequest):
    """分析单条新闻对当前组合内各标的的具体影响。

    R46: 路由层采集市场上下文（regime/指数/板块）注入 analyze_news_impact；
    采集失败给空 dict（不阻断分析）。
    """
    market_context = {}
    try:
        market_context = await asyncio.wait_for(
            build_full_context(
                market_data_hub,
                include_sentiment=False,
                include_news=False,
                include_fund_flow=False,
                include_commodities=False,
            ),
            timeout=8,
        )
    except Exception:
        logger.warning("[news-impact] market context 采集失败，使用空上下文", exc_info=True)
    result = await analyze_news_impact(req.news, req.portfolio, market_context=market_context)
    result["disclaimer"] = "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
    return result

# ── /portfolio-design 已废弃 ──
# 组合设计功能已迁移到 POST /portfolio/design-async（引擎驱动）
# 旧 LLM 路径不再维护

# round23 §6.2: PortfolioReviewRequest 零调用已删除（旧 LLM 组合检视遗留）

@router.post("/llm-report/stream")
async def llm_report_stream(req: LLMReportRequest):
    """流式市场研判报告 — 使用统一上下文管道 (Phase 2.9)。"""
    from ..services.market_data_hub import market_data_hub
    from ..services.llm_context import build_full_context

    # 使用统一上下文管道采集数据
    ctx = await build_full_context(
        market_data_hub,
        market=req.market,  # Z31: 按 marketTab 采集对应市场数据
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
        # N04/U9: 只保留本市场 major_symbols + 本市场指数（旧 `asset_type in
        # ("index","futures")` 无差别放行 A 股指数 → HK/US 报告混入 A 股数据）
        market_data = [
            m for m in market_data
            if m.get("symbol", "") in market_ctx.major_symbols
            or (
                m.get("asset_type", "") in ("index", "futures")
                and m.get("symbol", "") in market_ctx.index_symbols
            )
        ]

    # P0-2 (R4-13 / N04 补全): indices/commodities 同样按市场过滤（对齐 llm_report）
    indices = _filter_indices_for_market(market_ctx, indices)
    commodities = _filter_commodities_for_market(market_ctx, commodities)

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
        # P1-5 (R4-23): 采集海外流动性（FRED）注入 prompt；失败静默不注入
        _gl = None
        try:
            from ..analysis.llm import _fetch_global_liquidity
            _gl = await _fetch_global_liquidity()
        except Exception:
            _gl = None
        prompt = _build_report_prompt(indices, commodities, market_data, indicators,
                                      enriched_news, [], global_liquidity=_gl)
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
    # P3-G (round10 §10 P3-G): portfolio 槽显式注入——prompt 消费该槽；用户
    # 请求显式携带 portfolio 时透传，未带则为空列表（不凭空捏造持仓）。
    user_ctx["portfolio"] = (req.context or {}).get("portfolio", []) or []

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

def _normalize_sector_code(
    code: str,
    industry: list[dict],
    concept: list[dict],
    name: str = "",
) -> str:
    """板块代码归一化（F2-7 步骤F；§9.8.3）。

    热板块/热度的 cls 前缀代码（如 cls82558）与东财 BK/行业板块是两套编码，
    在 sector 分析前归一化：
      1. 名称优先 —— 前端传 sector_name（热板块行有 plate_name）时按名称精确命中；
      2. 数字段精确匹配 —— cls 数字段 == BK 代码数字段（去掉 BK 前缀）；
      3. 已是 BK 代码原样返回；
      4. 归一化失败返回原值（调用方按未命中返回结构化错误）。
    """
    if not code:
        return code
    tables = list(industry or []) + list(concept or [])
    if name:
        # R41: 名称匹配升级为"包含/前缀 + 大小写不敏感"——前端传板块中文名
        # 可能带"板块"后缀或部分匹配（如"半导体"vs"半导体及元件"）
        name_l = name.strip().lower()
        hit = None
        for s in tables:
            sn = (s.get("sector_name") or "")
            sn_l = sn.strip().lower()
            if sn_l == name_l:
                hit = s
                break
        if hit is None:
            hit = next(
                (s for s in tables
                 if name_l and (name_l in (s.get("sector_name") or "").lower()
                                or (s.get("sector_name") or "").lower() in name_l)),
                None,
            )
        if hit:
            return str(hit.get("sector_code") or code)
    if str(code).lower().startswith("cls"):
        import re as _re
        digits = _re.sub(r"\D", "", code)
        if digits:
            hit = next(
                (s for s in tables if str(s.get("sector_code", "")).replace("BK", "") == digits),
                None,
            )
            if hit:
                return str(hit.get("sector_code") or code)
    return code

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
            sectors = await asyncio.to_thread(market_data_hub.get_sector_concept, 500)
        else:
            sectors = await asyncio.to_thread(market_data_hub.get_sector_industry, 500)
        # R5: 概念映射兜底——前端 sector 模式固定传 sector_type='industry'，
        # 概念名（芯片/光模块/CPO 等）在行业表找不到 → 404。
        # 取对侧表一起参与名称归一化（缓存命中，开销小），命中后按合并表定位 sector_data。
        if sector_type == "concept":
            other = await asyncio.to_thread(market_data_hub.get_sector_industry, 500)
        else:
            other = await asyncio.to_thread(market_data_hub.get_sector_concept, 500)
        combined = [
            # F19 (round6 §16.7): 过滤 placeholder 行（sector_code=''，有名无码）——
            # 它们不参与名称归一化匹配，避免命中后返回空代码 → 404「板块映射失败」
            s for s in (list(sectors or []) + list(other or []))
            if s.get("sector_code")
        ]
        # F2-7 步骤F: 热板块 cls 前缀代码归一化（名称优先 → 数字段匹配）
        normalized = _normalize_sector_code(
            sector_code,
            combined,
            [],
            name=sector_name,
        )
        sector_data = next(
            (s for s in combined if s.get("sector_code") == normalized), None
        )
        if sector_data:
            sector_code = sector_data.get("sector_code", sector_code)
        elif normalized != sector_code:
            # 归一化后未命中 → 用原值兜底再查一次
            sector_data = next(
                (s for s in sectors if s.get("sector_code") == sector_code), None
            )
        if not sector_data:
            # F2-7 步骤F + F19 (round6 §16.7): 映射失败返回结构化错误——
            # 区分「代码不存在」与「数据源缺失」（placeholder 仅 → 数据源暂无数据）
            raise HTTPException(
                status_code=404,
                detail=(
                    f"板块「{req.sector_code}」数据源暂无数据"
                    f"（板块表未收录或数据源缺失），请稍后重试或换用其他板块"
                ),
            )
        name = sector_name or (sector_data.get("sector_name", "") if sector_data else sector_code)
        
        constituents = await asyncio.to_thread(market_data_hub.get_sector_stocks, sector_code)
        news = market_data_hub.get_news_headlines() or []
        try:
            macro = market_data_hub.get_news_macro() or []
            news.extend(macro)
        except Exception:
            pass
        
        # R5: 注入板块实时行情快照（get_sector_industry 已含成交额/主力净流入/换手率/涨跌家数
        # ——旧实现只喂 name/成分股/资讯，LLM 无行情数据 → 报告出现
        # 「未提供板块K线、成交额、主力资金流向、北向持仓」的诚实降级说明）。
        # 北向持仓接口（hsgt）当前数据源不可用，不注入；K线需东财接口（限流时降级），
        # 快照已含板块指数点位与涨跌幅，足以支撑资金面/技术面定量分析。
        sector_snapshot = {
            "板块指数点位": sector_data.get("price"),
            "今日涨跌幅%": sector_data.get("change_pct"),
            "今日成交额": sector_data.get("amount"),
            "换手率%": sector_data.get("turnover_rate"),
            "主力资金净流入": sector_data.get("main_inflow"),
            "上涨/下跌家数": [sector_data.get("up_count"), sector_data.get("down_count")],
            "领涨股": f"{sector_data.get('lead_stock_name')}({sector_data.get('lead_stock_code')}) +{sector_data.get('lead_stock_chg')}%"
            if sector_data.get("lead_stock_name") else None,
            "领跌股": f"{sector_data.get('top_drop_name')}({sector_data.get('top_drop_code')})"
            if sector_data.get("top_drop_name") else None,
        }

        # O26 (round8 §7 §5.1H): 点位口径显式标注——板块分析的点位是「板块指数
        # （BKxxxx，东财板块行情）」自身点位，非成分股均价/沪深大盘；技术面注明
        # 均线周期与数据区间，避免专业读者误读点位主体。
        _sector_idx_label = f"板块指数（{sector_code}，东财板块行情）"
        prompt = f"""分析板块 {name} ({sector_code})：
板块实时行情：{json.dumps(sector_snapshot, ensure_ascii=False)}
成分股：{json.dumps(constituents[:15], ensure_ascii=False)}
资讯：{json.dumps(news[:10], ensure_ascii=False)}
{_sector_idx_label}点位为 {sector_data.get('price')} 点（本报告所有点位均为该板块指数点位，非成分股均价，亦非沪深大盘指数）。

请输出：
1. 板块概况
2. 资金面（基于板块主力净流入、成交额等数据定量分析）
3. 技术面（基于{_sector_idx_label}点位；均线周期为最近 30 个交易日日线，支撑/压力位基于该区间推算）
4. 催化因素
5. 风险提示
6. 核心标的推荐"""
        
        agent = get_agent("sector_analysis")
        return _sse_stream(agent.run_stream(prompt))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")

@router.post("/symbol-analysis/stream")
async def symbol_analysis_stream(req: SymbolAnalysisRequest):
    """流式标的深度解读"""
    try:
        symbol = req.symbol
        name = req.name
        asset_type = req.asset_type
        # P1-3 (R4-09): asset_type 枚举归一化——'stock' 等非标准值会导致
        # get_history 静默返回 0 条（技术指标全空、报告诚实降级）。
        # 归一化到 A/ETF 等标准市场代码后再取数。
        _asset_norm = {"stock": "A", "sh": "A", "sz": "A", "fund": "ETF", "etf": "ETF"}
        asset_type = _asset_norm.get(str(asset_type or "").lower(), asset_type or "A")
        
        realtime = await market_data_hub.get_asset_realtime(symbol, asset_type) or {}
        # R20: 中文名→代码兜底解析（前端漏解析时后端解析）——仅明显非代码输入才触发，
        # 避免个股路径拉全量 akshare 列表的延迟
        if not realtime and any(ch >= '\u4e00' and ch <= '\u9fff' for ch in symbol):
            try:
                from ..services.market_service import resolve_symbol_to_code
                resolved = await resolve_symbol_to_code(symbol, asset_type)
                if resolved:
                    symbol = resolved
                    realtime = await market_data_hub.get_asset_realtime(symbol, asset_type) or {}
            except Exception:
                pass
        hist = []
        try:
            hist = await asyncio.wait_for(get_history(symbol, asset_type, "daily"), timeout=30)
        except Exception:
            pass
        # P1-3: get_history 失败时按 'A' 重试（非标准 asset_type 曾导致 0 条）
        if not hist and str(asset_type).upper() != "A":
            try:
                hist = await asyncio.wait_for(get_history(symbol, "A", "daily"), timeout=30)
            except Exception:
                pass
        indicators = compute_all_indicators(hist) if hist else {}
        
        # P1-3 (R4-09): 基本面估值数据注入——PE/PB（akshare 日线估值列），
        # 缺失时明确标注数据源不可用（不再静默缺失，LLM 不再误报
        # 「输入数据未包含 PE、PB、ROE 等财务指标」）
        fundamentals_text = "（数据源不可用，无法获取 PE/PB 等估值指标）"
        try:
            from ..fetchers.fundamentals_fetcher import fetch_current_pe_pb
            # round14 P2-AN: 透传 market——美股标的（asset_type=US）走东财美股 PE 分支
            _fund_market = asset_type if isinstance(asset_type, str) else "A"
            fund_data = await asyncio.to_thread(fetch_current_pe_pb, symbol, _fund_market)
            if fund_data and (fund_data.get("pe_ttm") is not None or fund_data.get("pb") is not None):
                fundamentals_text = json.dumps(fund_data, ensure_ascii=False)
        except Exception as _fe:
            logger.debug("[symbol-analysis] fundamentals fetch failed (non-fatal): %s", _fe)
        
        news = []
        # R5: 个股新闻（东财 stock_news_em）替代全市场头条——头条含大量其他股票新闻，
        # LLM 会引用无关标的导致「分析的是另一只股票」（用户反馈：002131 利欧股份被带偏）。
        try:
            from ..fetchers.news_fetcher import fetch_stock_news
            news = await asyncio.to_thread(fetch_stock_news, symbol) or []
        except Exception:
            pass
        if not isinstance(news, list):
            news = []
        if not news:
            news = market_data_hub.get_news_headlines() or []
        try:
            macro = market_data_hub.get_news_macro() or []
            news.extend(macro)
        except Exception:
            pass
        
        display_name = name or (realtime.get("name", "") if realtime else symbol)

        # R5: 注入个股所属板块实时快照（对齐 sector 模式 88f4b75 修复）——行业映射 +
        # 行业板块成交额/主力净流入/换手率/涨跌家数，让报告资金面/技术面有定量依据，
        # 消除「未提供主力资金流向」类诚实降级说明（数据源实际可获取）。
        sector_line = ""
        try:
            from ..fetchers.sector_fetcher import get_stock_industry_map
            industry_map = await asyncio.to_thread(get_stock_industry_map, [symbol]) or {}
            industry = (industry_map.get(symbol) or "").strip()
            if industry:
                sectors = await asyncio.to_thread(market_data_hub.get_sector_industry, 500) or []
                matched = next((s for s in sectors if s.get("sector_name") == industry), None)
                if matched:
                    snap = {k: matched.get(k) for k in
                            ("sector_name", "price", "change_pct", "amount", "main_inflow",
                             "turnover_rate", "up_count", "down_count")}
                    sector_line = f"所属板块：{industry}；板块实时快照：{json.dumps(snap, ensure_ascii=False)}"
        except Exception as _se:
            logger.debug("[symbol-analysis] sector snapshot fetch failed (non-fatal): %s", _se)

        # F7 R21: 数据全空时不调 LLM——避免 LLM 用常识生成"伪分析"
        # （用户明确要求：必要数据喂 LLM，非必要不报告缺失）
        if not realtime and not hist:
            return _sse_error("数据源暂不可用，请稍后重试")

        # F10 R35: 预设问题模板——用户关注点拼入 prompt 做针对性分析
        focus_line = f"\n用户关注：{req.question}" if (req.question or "").strip() else ""
        prompt = f"""深度分析标的 {display_name} ({symbol})：
实时行情：{json.dumps(realtime, ensure_ascii=False)}
技术指标：{json.dumps(indicators, ensure_ascii=False)}
历史K线(最近30条)：{json.dumps(hist[-30:], ensure_ascii=False) if hist else '无'}
基本面(PE/PB估值)：{fundamentals_text}
{sector_line}
资讯催化：{json.dumps(news[:10], ensure_ascii=False)}{focus_line}

请输出：
1. 基本面概览
2. 技术面分析
3. 资讯催化
4. 风险提示
5. 操作建议"""
        
        agent = get_agent("symbol_analysis")
        # O24 (round8 §7 §5.1K ④) 修复: 只透传 llm_complete_stream 支持的参数——
        # max_retries=1 快速失败（429 退避上限由 llm.py 的 Retry-After 机制处理），
        # 删除旧实现透传的 llm_complete_stream 不存在之参数（该参数名不在其签名内
        # → TypeError → 全部 symbol-analysis/stream 请求 STREAM_ERROR 全挂）。
        return _sse_stream(agent.run_stream(
            prompt,
            max_retries=1,
        ))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM streaming failed: {e}")

