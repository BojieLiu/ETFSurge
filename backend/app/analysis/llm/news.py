"""News summary & impact analysis — split from analysis/llm.py (Batch 2)."""

import json

from app.core.logging import get_logger
from app.analysis.registry import get_agent
from app.analysis.llm.client import llm_complete

logger = get_logger(__name__)

async def generate_news_summary(title: str, content: str) -> str:
    """Z18: 单条新闻生成一句话中文摘要（后台管道用，失败返回空串不抛错）。"""
    prompt = (
        f"请用一句话（不超过40字）概括以下新闻的核心要点，"
        f"直接输出摘要正文，不要任何前缀、引号或标点修饰。\n"
        f"标题：{title}\n内容：{(content or '')[:200]}"
    )
    try:
        text = await llm_complete(prompt, max_retries=0)
        return (text or "").strip().strip('"').strip("'")[:80]
    except Exception:
        return ""
def _news_body_text(news_item: dict) -> str:
    """O5 (round7 §7 P16): news-impact 正文兜底——content → summary → title。

    数据源冷却/快讯类头条 content 为空时，prompt 里「新闻内容：」段为空 →
    LLM 收到空正文 → 返回「新闻内容为空」空洞结论。三级兜底保证正文段非空。
    """
    content = (news_item.get("content") or "").strip()
    if content:
        return content
    summary = (news_item.get("summary") or "").strip()
    if summary:
        return summary
    title = (news_item.get("title") or "").strip()
    if title:
        return f"（快讯）{title}"
    return ""
async def analyze_news_impact(news_item: dict, holdings: list[dict], market_context: dict | None = None) -> dict:
    """分析单条新闻对当前组合内各标的的具体影响。

    Z32: 当组合为空时，改为分析对市场整体的影响。
    R46: market_context（regime/指数/板块，由路由层采集注入）可选——传入时
    在 prompt 中加入当前市场背景，使相关新闻能展开传导分析、无关新闻给出理由。
    R48: 返回前用持仓白名单过滤 LLM 虚构标的并记 WARNING 日志。
    R49: prompt 注入显式代码清单（affected_holdings 只能从清单中选）。
    返回 {"impact_scope": str, "affected_holdings": [...], "summary": str}。
    """
    has_holdings = bool(holdings and any(h.get('symbol') for h in holdings))
    holdings_text = "\n".join(
        f"- {h.get('symbol', '')} {h.get('name', '')} "
        f"({h.get('asset_type', '')}) 目标权重 {h.get('target_weight', '')}"
        for h in holdings
    ) if has_holdings else "（暂未持仓）"
    # R49: 显式代码清单——LLM 只能从清单中选 affected_holdings.symbol
    code_list = ", ".join(
        str(h.get("symbol", "")).strip() for h in holdings if h.get("symbol")
    ) if has_holdings else ""

    # R46: 市场背景段（regime / 指数 / 板块热度），由路由层采集注入
    background = ""
    if market_context:
        parts = []
        # regime 可能是 dict {regime, confidence} 或 str（build_full_context 返回）
        regime_raw = market_context.get("market_regime") or ""
        regime = regime_raw.get("regime", "") if isinstance(regime_raw, dict) else str(regime_raw)
        if regime:
            parts.append(f"当前市场状态：{regime}")
        indices = market_context.get("indices") or []
        if indices:
            idx_txt = "；".join(
                f"{i.get('name', i.get('symbol', ''))} {i.get('price', '')}"
                for i in indices[:6] if isinstance(i, dict)
            )
            if idx_txt:
                parts.append(f"主要指数：{idx_txt}")
        sectors = market_context.get("sectors") or []
        if sectors:
            hot = sorted(
                (s for s in sectors if isinstance(s, dict) and s.get("change_pct") is not None),
                key=lambda s: abs(s.get("change_pct") or 0), reverse=True,
            )[:5]
            if hot:
                parts.append("板块热度："
                             + "；".join(f"{s.get('name', '')} {s.get('change_pct', '')}%" for s in hot))
        if parts:
            background = "当前市场背景：\n" + "\n".join(parts) + "\n\n"

    # O5 (round7 §7 P16): 正文三级兜底——content 空时用 summary/title，
    # 杜绝空正文段进 prompt（LLM 收到空正文会回「新闻内容为空」空洞结论）
    news_body = _news_body_text(news_item) or "（无正文）"
    if has_holdings:
        prompt = f"""新闻标题：{news_item.get('title', '')}
新闻内容：{news_body}

{background}当前组合持仓：
{holdings_text}

当前组合持仓代码：{code_list}
（affected_holdings 中的 symbol 必须严格从上述清单中选择，不得新增任何代码）

请分析这条新闻对组合的影响，重点回答：
(a) 影响范围：必须明确方向（利好/利空/中性）＋板块＋概念，如「方向：利好；板块：A股文化传媒（影视院线、内容制作）；概念：影视、内容IP」；
(b) 组合内哪些标的会受到影响、具体如何受影响。
只返回约定结构的 JSON。

重要约束（必须遵守）：
- 若新闻与组合内标的无直接关联，须明确回答「无直接影响」，禁止强行关联；
- 只列出实际受影响的标的，宁缺毋滥；
- 若组合为空，回答对市场整体的影响。"""
    else:
        prompt = f"""新闻标题：{news_item.get('title', '')}
新闻内容：{news_body}

当前无持仓组合。

请分析这条新闻对市场整体的影响，重点回答：
(a) 影响范围：必须明确方向（利好/利空/中性）＋板块＋概念，如「方向：利好；板块：A股文化传媒（影视院线、内容制作）；概念：影视、内容IP」；
(b) 哪些行业或主题会受到正面/负面影响。
只返回约定结构的 JSON。

重要约束（必须遵守）：
- 若新闻与 A 股市场无直接关联，须明确回答「无直接影响」，禁止强行关联；
- 只列出实际受影响的行业/主题，宁缺毋滥。"""

    try:
        data = await get_agent("news_impact").run_json(prompt)
    except Exception as e:
        logger.warning("[news_impact] LLM analysis failed: %s", e)
        data = {}

    # R48: 持仓白名单过滤——仅保留传入 holdings 代码集内的标的，LLM 虚构标的丢弃
    affected = (data.get("affected_holdings") or []) if isinstance(data, dict) else []
    if has_holdings and affected:
        whitelist = {str(h.get("symbol", "")).strip() for h in holdings if h.get("symbol")}
        filtered = [a for a in affected if str(a.get("symbol", "")).strip() in whitelist]
        dropped = len(affected) - len(filtered)
        if dropped:
            fake_symbols = [a.get("symbol") for a in affected
                            if str(a.get("symbol", "")).strip() not in whitelist]
            logger.warning(
                "[news_impact] LLM 虚构 %d 个持仓标的已过滤（不在持仓白名单）: %s",
                dropped, fake_symbols,
            )
        affected = filtered

    return {
        "impact_scope": data.get("impact_scope", "") if isinstance(data, dict) else "",
        "affected_holdings": affected,
        "summary": data.get("summary", "") if isinstance(data, dict) else "",
    }
