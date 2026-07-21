import json
import time
import sys
from typing import Any, AsyncGenerator

from ..config import settings
from ..monitor.token_usage import token_store, UsageRecord
from ..core.logging import get_logger
from .registry import get_agent
from .provider import get_configured_providers, has_any_api_key, ProviderConfig

logger = get_logger(__name__)

# Keep the official DeepSeek URL for reference; the actual URL is now
# per-provider and obtained from get_configured_providers().
LLM_API_URL = "https://api.deepseek.com/chat/completions"

# Prompt loading mechanism
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent / "prompts" / "v1"

def load_prompt(name: str) -> str:
    """Load a prompt from the prompts/v1/ directory."""
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")

# System prompts are loaded from markdown files (prompts/v1/*.md)
SYSTEM_PROMPT = load_prompt("general_analyst.md")

# System prompts are loaded per-agent via AgentRuntime (registry.py).

async def _check_key():
    if not has_any_api_key():
        raise ValueError(
            "No LLM API keys configured. Set OPENCODE_ZEN_API_KEY "
            "and/or DEEPSEEK_API_KEY in backend/.env"
        )


async def llm_complete(prompt: str, response_format: dict | None = None) -> str:
    import httpx
    await _check_key()

    _caller = sys._getframe(1).f_code.co_name
    providers = get_configured_providers()
    last_exc: Exception | None = None

    for provider in providers:
        body = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        if response_format:
            body["response_format"] = response_format

        _start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=provider.timeout, trust_env=False
            ) as client:
                resp = await client.post(
                    provider.api_url,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                message = data["choices"][0]["message"]
                content = message.get("content", "")
                if not content:
                    content = message.get("reasoning_content", "")

                usage = data.get("usage", {})
                _duration = (time.monotonic() - _start) * 1000
                await token_store.record(UsageRecord(
                    function_name=_caller,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    model=provider.model,
                    timestamp=time.time(),
                    success=True,
                    duration_ms=round(_duration, 1),
                    provider=provider.id,
                ))
                return content
        except Exception as _exc:
            _duration = (time.monotonic() - _start) * 1000
            await token_store.record(UsageRecord(
                function_name=_caller,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=provider.model,
                timestamp=time.time(),
                success=False,
                duration_ms=round(_duration, 1),
                error_message=str(_exc),
                provider=provider.id,
            ))
            last_exc = _exc
            logger.warning(
                "[LLM] Provider %s failed after %.1fs: %s",
                provider.id, _duration / 1000, _exc,
            )
            continue

    if last_exc is None:
        raise RuntimeError("No LLM providers available")
    raise last_exc


async def llm_complete_stream(
    system_prompt: str,
    prompt: str,
    response_format: dict | None = None,
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> AsyncGenerator[dict, None]:
    """
    Streaming LLM completion with provider failover.
    
    Tries providers in priority order. If the primary provider fails
    BEFORE any token is yielded, falls back to the next provider.
    Once a token has been yielded, commits to that provider.
    
    Yields:
        {"type": "token", "token": "..."} - incremental token
        {"type": "done", "full_text": "...", "usage": {...}} - completion with full text
        {"type": "error", "error": "..."} - error occurred
    """
    import httpx
    await _check_key()

    providers = get_configured_providers()
    last_exc: Exception | None = None

    for provider in providers:
        body = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or 8192,
            "stream": True,
        }
        if response_format:
            body["response_format"] = response_format

        _start = time.monotonic()
        _caller = sys._getframe(1).f_code.co_name

        full_text = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        try:
            async with httpx.AsyncClient(
                timeout=provider.timeout, trust_env=False
            ) as client:
                async with client.stream(
                    "POST",
                    provider.api_url,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                ) as resp:
                    resp.raise_for_status()

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                if chunk.get("choices"):
                                    delta = chunk["choices"][0].get("delta", {})
                                    token = delta.get("content") or delta.get("reasoning_content") or ""
                                    if token:
                                        full_text += token
                                        yield {"type": "token", "token": token}

                                if chunk.get("usage"):
                                    usage = chunk["usage"]
                                    prompt_tokens = usage.get("prompt_tokens", 0)
                                    completion_tokens = usage.get("completion_tokens", 0)
                                    total_tokens = usage.get("total_tokens", 0)
                            except json.JSONDecodeError:
                                continue

        except Exception as _exc:
            _duration = (time.monotonic() - _start) * 1000
            await token_store.record(UsageRecord(
                function_name=_caller,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=provider.model,
                timestamp=time.time(),
                success=False,
                duration_ms=round(_duration, 1),
                error_message=str(_exc),
                provider=provider.id,
            ))
            last_exc = _exc
            logger.warning(
                "[LLM] Stream provider %s failed after %.1fs: %s",
                provider.id, _duration / 1000, _exc,
            )
            # If we yielded any tokens, we're committed - propagate error
            if full_text:
                yield {"type": "error", "error": str(_exc)}
                return
            # Otherwise try next provider
            continue

        # Success: record and yield done
        _duration = (time.monotonic() - _start) * 1000
        await token_store.record(UsageRecord(
            function_name=_caller,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=provider.model,
            timestamp=time.time(),
            success=True,
            duration_ms=round(_duration, 1),
            provider=provider.id,
        ))

        yield {
            "type": "done",
            "full_text": full_text,
            "usage": {
                "model": provider.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": round(_duration, 1),
            }
        }
        return

    # All providers exhausted
    if last_exc is None:
        last_exc = RuntimeError("No LLM providers available")
    yield {"type": "error", "error": str(last_exc)}


async def llm_complete_with_system(system_prompt: str, prompt: str, response_format: dict | None = None, force_json: bool = False) -> str:
    """Call LLM with a custom system prompt, with provider failover."""
    import httpx
    await _check_key()

    _caller = sys._getframe(1).f_code.co_name
    providers = get_configured_providers()
    last_exc: Exception | None = None

    for provider in providers:
        body = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        if response_format:
            body["response_format"] = response_format
        elif force_json:
            body["response_format"] = {"type": "json_object"}

        _start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=provider.timeout, trust_env=False
            ) as client:
                resp = await client.post(
                    provider.api_url,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                message = data["choices"][0]["message"]
                content = message.get("content", "")
                if not content:
                    content = message.get("reasoning_content", "")

                usage = data.get("usage", {})
                _duration = (time.monotonic() - _start) * 1000
                await token_store.record(UsageRecord(
                    function_name=_caller,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    model=provider.model,
                    timestamp=time.time(),
                    success=True,
                    duration_ms=round(_duration, 1),
                    provider=provider.id,
                ))
                return content
        except Exception as _exc:
            _duration = (time.monotonic() - _start) * 1000
            await token_store.record(UsageRecord(
                function_name=_caller,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=provider.model,
                timestamp=time.time(),
                success=False,
                duration_ms=round(_duration, 1),
                error_message=str(_exc),
                provider=provider.id,
            ))
            last_exc = _exc
            logger.warning(
                "[LLM] Provider %s failed after %.1fs: %s",
                provider.id, _duration / 1000, _exc,
            )
            continue

    if last_exc is None:
        raise RuntimeError("No LLM providers available")
    raise last_exc


def _format_indices(indices: list[dict]) -> str:
    if not indices:
        return ""
    lines = [f"- {idx.get('name','')}({idx.get('symbol','')}): {idx.get('price','N/A')}, 涨跌幅{idx.get('change_pct','N/A')}%" for idx in indices[:15]]
    return "\n".join(lines)


def _format_commodities(commodities: list[dict]) -> str:
    if not commodities:
        return ""
    key_names = {"黄金", "白银", "原油", "铜", "铝", "天然气"}
    items = [c for c in commodities if c.get("name", "") in key_names]
    if not items:
        items = commodities[:6]
    lines = [f"- {c.get('name','')}: {c.get('price','N/A')}, 涨跌幅{c.get('change_pct','N/A')}%" for c in items]
    return "\n".join(lines)


# NOTE: _build_portfolio_design_prompt is defined below
# with extended signature supporting trend_data, macro_state, etc.

def _build_market_overview(
    indices: list[dict],
    commodities: list[dict],
    major_stocks: list[dict],
    news: list[dict],
    macro_news: list[dict],
) -> str:
    prompt = """## 全市场概览

### A股市场
"""
    a_stock_names = {"上证指数", "深证成指", "创业板指", "科创50", "沪深300", "上证50", "中证500", "中证1000"}
    for idx in indices:
        if idx.get("name") in a_stock_names:
            prompt += f"- {idx.get('name')}({idx.get('symbol','')}): {idx.get('price','N/A')}, 涨跌幅{idx.get('change_pct','N/A')}%\n"
    if not any(idx.get("name") in a_stock_names for idx in indices):
        prompt += _format_indices(indices) or "（暂无数据）\n"

    prompt += "\n### 美股市场\n"
    us_stock_names = {"标普500", "纳斯达克", "道琼斯"}
    for s in major_stocks + indices:
        if s.get("name") in us_stock_names:
            prompt += f"- {s.get('name')}({s.get('symbol','')}): {s.get('price','N/A')}, 涨跌幅{s.get('change_pct','N/A')}%\n"
    if not any(s.get("name") in us_stock_names for s in major_stocks + indices):
        prompt += "（暂无数据）\n"

    prompt += "\n### 大宗商品\n"
    prompt += _format_commodities(commodities) or "（暂无数据）"

    if major_stocks:
        prompt += "\n\n### 主要标的行情\n"
        for item in major_stocks[:15]:
            prompt += f"- {item.get('name', '')}({item.get('symbol', '')}): ¥{item.get('price', 'N/A')}, 涨跌幅{item.get('change_pct', 'N/A')}%\n"

    if news:
        prompt += "\n\n### 财经资讯\n"
        for n in news[:8]:
            title = n.get("title", n.get("summary", ""))
            prompt += f"- {title[:120]}\n"

    if macro_news:
        prompt += "\n\n### 宏观政策\n"
        for n in macro_news[:5]:
            title = n.get("title", n.get("summary", ""))
            prompt += f"- {title[:120]}\n"

    return prompt


async def generate_market_report(
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
    macro_news: list[dict],
) -> str:
    prompt = _build_report_prompt(indices, commodities, market_data, indicators, news, macro_news)
    return await get_agent("market_report").run(prompt)


async def generate_advice(
    query: str,
    context: dict[str, Any] | None = None,
) -> str:
    """AI 投资顾问 — 结合市场数据、新闻、持仓生成结构化回答。

    从 context 中获取 market_data / news / portfolio / market_snapshot 等信息，
    注入市态判定与情绪数据，按 4 个维度的分析框架输出 Markdown 格式报告。
    """
    # ---- 从 context 获取可用数据 ----
    market_data = (context or {}).get("market_data", [])
    news = (context or {}).get("news", [])
    portfolio = (context or {}).get("portfolio", [])
    market_snapshot = (context or {}).get("market_snapshot", "")
    regime = (context or {}).get("market_regime", "")
    sentiment = (context or {}).get("market_sentiment", {})

    # ---- 1. 大盘概况（含市态/情绪） ----
    idx_lines = []
    if market_data:
        for item in market_data[:10]:
            name = item.get("name", item.get("symbol", "?"))
            price = item.get("price", "N/A")
            chg = item.get("change_pct", "")
            vol = item.get("volume", "")
            amount = item.get("amount", "")
            if chg != "":
                vol_str = f"成交量 {vol}" if vol else ""
                amt_str = f"成交额 {amount}" if amount else ""
                idx_lines.append(
                    f"- **{name}**: {price} 涨跌幅 {chg}%  {vol_str}  {amt_str}"
                )

    idx_summary = "\n".join(idx_lines) if idx_lines else "暂无实时指数数据。"

    # 市态与情绪概览
    regime_line = f"市场状态: {regime}" if regime else "市场状态: 未知"
    sentiment_line = ""
    if sentiment and isinstance(sentiment, dict):
        s_idx = sentiment.get("sentiment_index", "")
        s_lbl = sentiment.get("sentiment_label", "")
        if s_idx and s_lbl:
            sentiment_line = f"市场情绪: {s_lbl} ({s_idx}/100)"
        elif s_lbl:
            sentiment_line = f"市场情绪: {s_lbl}"

    # ---- 2. 热点板块 ----
    sector_lines = []
    for item in market_data[:15]:
        if item.get("asset_type") in ("sector", "concept", "industry", "plate"):
            name = item.get("name", item.get("sector_name", "?"))
            chg = item.get("change_pct", "")
            flow = item.get("main_inflow", item.get("fund_flow", ""))
            sector_lines.append(
                f"- **{name}**: 涨跌幅 {chg}%  资金流向 {flow}"
            )
    sector_summary = "\n".join(sector_lines) if sector_lines else "暂无板块热力数据。"

    # ---- 3. 资金面 / 消息面 ----
    fund_lines = []
    fund_lines.append(f"- 市场快照:\n{market_snapshot}" if market_snapshot else "- 市场快照:暂无")
    news_lines = []
    if news:
        for n in news[:10]:
            title = n.get("title", n.get("content", ""))[:120]
            source = n.get("source", n.get("来源", ""))
            prefix = f"[{source}] " if source else ""
            news_lines.append(f"- {prefix}{title}")
    news_summary = "\n".join(news_lines) if news_lines else "暂无重大新闻。"

    # ---- 4. 持仓/组合概况 ----
    portfolio_lines = []
    if portfolio:
        for p in portfolio[:10]:
            sym = p.get("symbol", p.get("code", "?"))
            name = p.get("name", "")
            weight = p.get("target_weight", p.get("weight", ""))
            if isinstance(weight, (int, float)):
                weight_str = f"{weight*100:.1f}%" if weight < 1 else f"{weight}%"
            else:
                weight_str = str(weight)
            portfolio_lines.append(f"- {name}({sym}): 目标权重 {weight_str}")
    portfolio_summary = "\n".join(portfolio_lines) if portfolio_lines else "用户未提供持仓信息。"

    prompt = f"""你是一位专业的中国金融市场投资顾问。基于以下数据，回答用户的问题。

---
## 用户提问
{query}

---
## 一、大盘概况
{idx_summary}

{regime_line}
{sentiment_line}

---
## 二、热点板块
{sector_summary}

---
## 三、资金流向 / 消息面
{news_summary}

---
## 四、持仓组合概况
{portfolio_summary}
---

请按以下 4 个维度给出结构化 Markdown 格式报告：

### 1. 大盘概况
- 主要指数涨跌幅、**成交量变化**、涨跌家数比
- **给出具体数值而不是模糊描述**，例如"上证指数收于 3200.5，涨幅 0.8%"

### 2. 热点板块
- 领涨板块 / 概念及涨幅/跌幅
- 资金流入流出情况

### 3. 资金流向 / 消息面
- 主力资金动向、北向资金动态
- 重大政策或新闻催化

### 4. 后市展望与建议
- 短期趋势判断、关键支撑/压力位
- 给出 2~4 条具体配置建议

注意：
- 使用 **加粗** 强调关键数据
- 用 `-` 符号列表组织内容
- 保持回答精炼，控制在 600 字以内
- 必须引用上述提供的具体数据，不要凭空編造数据
"""

    from ..analysis.registry import get_agent
    return await get_agent("advice").run(prompt)

async def analyze_news(news_list: list[dict]) -> str:
    text = "\n".join([f"- {n.get('title', n.get('summary', ''))}" for n in news_list[:15]])
    prompt = f"""分析以下财经新闻，提取关键信息：

{text}

请按以下维度输出：
    1. 核心市场情绪：乐观/中性/悲观
2. 影响板块及程度
3. 对组合调仓的潜在启示
4. 风险提示"""
    return await get_agent("news_analysis").run(prompt)


NEWS_IMPACT_SYSTEM_PROMPT = load_prompt("news_impact.md")


async def analyze_news_impact(news_item: dict, holdings: list[dict]) -> dict:
    """分析单条新闻对当前组合内各标的的具体影响。

    返回 {"impact_scope": str, "affected_holdings": [...], "summary": str}。
    """
    holdings_text = "\n".join(
        f"- {h.get('symbol', '')} {h.get('name', '')} "
        f"({h.get('asset_type', '')}) 目标权重 {h.get('target_weight', '')}"
        for h in holdings
    ) or "（组合为空）"

    prompt = f"""新闻标题：{news_item.get('title', '')}
新闻内容：{news_item.get('content', '')}

当前组合持仓：
{holdings_text}

请分析这条新闻对组合的影响，重点回答：
(a) 影响范围（市场/板块）；
(b) 组合内哪些标的会受到影响、具体如何受影响。
只返回约定结构的 JSON。"""

    try:
        data = await get_agent("news_impact").run_json(prompt)
    except Exception as e:
        logger.warning("[news_impact] LLM analysis failed: %s", e)
        data = {}

    return {
        "impact_scope": data.get("impact_scope", "") if isinstance(data, dict) else "",
        "affected_holdings": (data.get("affected_holdings") or []) if isinstance(data, dict) else [],
        "summary": data.get("summary", "") if isinstance(data, dict) else "",
    }


def _build_report_prompt(
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
    macro_news: list[dict],
) -> str:
    overview = _build_market_overview(indices, commodities, market_data, news, macro_news)

    prompt = f"""{overview}

请生成一份纯粹的市场环境研判报告。
重要约束：本报告只做市场研判，严禁给出任何具体组合（进攻型 / 平衡型 / 防御型）的仓位配置、买卖清单或调仓指令——组合层面的操作请使用「检视策略」功能。

报告须使用 Markdown，包含以下 4 个一级章节（以 `##` 作为章节标题），章节之间用 `---` 分隔：

## 1. 市场阶段与核心矛盾
- 市场阶段：趋势延续 / 横盘消化 / 趋势终结（须给出明确判断与依据）
- 风格特征：单一主线 / 风格扩散 / 均衡
- 资金行为：增量与存量资金在买什么、卖什么
- 核心矛盾：当前最大的不确定性来源

## 2. 宏观流动性与政策解读
- 国内流动性：货币与利率信号
- 海外流动性与地缘：美债、美元、油价、地缘冲突的传导
- 政策信号：有无稳增长或行业政策出台

## 3. 板块与风格轮动信号
- 强势板块 / 弱势板块及幅度
- 风格切换迹象（价值 / 成长、大 / 小盘）

## 4. 核心风险提示
- 按风险等级列出 2~4 条关键风险，并给出可观测的触发条件

格式要求：
- 关键结论与数字用 `**加粗**` 标注，数字必须引用上方输入数据
- 要点用 `-` 列表，语言专业、客观、可执行
- 全程控制在 900 字以内"""
    return prompt



def _empty_portfolio_response() -> dict:
    return {"market_environment": "数据获取异常", "portfolios": []}


# 新增：组合检视/再平衡
async def generate_strategy_suggestions(
    market_data: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
    macro_news: list[dict],
) -> dict[str, Any]:
    overview = _build_market_overview(
        [d for d in market_data if d.get("asset_type") == "index"],
        [d for d in market_data if d.get("asset_type") == "commodity"],
        [d for d in market_data if d.get("asset_type") == "stock"],
        news,
        macro_news,
    )

    prompt = f"""{overview}

请基于当前市场环境，给出 3 条具体的策略建议，每条包含：
1. 策略名称
2. 适用市场环境
3. 核心操作（买什么/卖什么/配置比例）
4. 止损/止盈规则
5. 置信度（高/中/低）

输出 JSON 格式：
```json
{{
  "strategies": [
    {{"name": "", "condition": "", "action": "", "risk_control": "", "confidence": ""}},
    {{"name": "", "condition": "", "action": "", "risk_control": "", "confidence": ""}},
    {{"name": "", "condition": "", "action": "", "risk_control": "", "confidence": ""}}
  ]
}}
```"""
    response = await get_agent("strategy_suggestions").run(prompt)
    return json.loads(response)


async def generate_strategy_check_report(
    market_data: list[dict],
    factor_breakdowns: dict[str, dict],
    regime: str,
) -> dict:
    """基于持仓数据 + 因子分 + regime 生成结构化策略检查报告。"""
    # 格式化持仓数据
    holdings_lines = []
    for item in market_data:
        sym = item.get("symbol", "")
        if sym == "CASH":
            continue
        fb = factor_breakdowns.get(sym, {})
        fs = fb.get("factor_scores", {})
        sig = fb.get("technical_signal", {})
        drift = fb.get("weight_drift", {})

        factor_text = "；".join(
            f"{k}: {v:.2f}" for k, v in sorted(fs.items(), key=lambda x: -abs(x[1]))[:5]
        ) if fs else "无因子数据"
        signal_text = sig.get("signal", "hold")
        drift_text = f"偏离 {drift.get('drift_pct', 0):.1f}%" if drift else "—"

        holdings_lines.append(
            f"- {item.get('name', sym)}({sym}): "
            f"权重 {item.get('target_weight', 0)*100:.0f}%, "
            f"{drift_text}；"
            f"技术信号 {signal_text}；"
            f"因子评分: {factor_text}"
        )

    holdings_text = "\n".join(holdings_lines)

    prompt = f"""
## 市场状态
当前 regime: {regime}

## 持仓分析
{holdings_text}

请按 strategy_check.md 要求的 JSON 格式输出分析报告。
"""
    from ..analysis.registry import get_agent
    try:
        return await get_agent("strategy_check").run_json(prompt)
    except Exception as e:
        logger.warning("[strategy_check] LLM analysis failed: %s", e)
        return {
            "summary": "LLM 分析暂不可用，请稍后重试",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }


async def generate_sector_analysis(
    sector_code: str,
    sector_name: str,
    sector_stocks: list[dict],
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    factor_scores: list[dict] | None = None,
) -> str:
    idx_map = {idx.get("name", ""): idx for idx in indices}
    comm_map = {c.get("name", ""): c for c in commodities}

    prompt = f"""## {sector_name}({sector_code}) 行业深度分析

### 成分股行情
"""
    for s in sector_stocks[:20]:
        prompt += f"- {s.get('name', '')}({s.get('symbol', '')}): ¥{s.get('price', 'N/A')}, 涨跌幅{s.get('change_pct', 'N/A')}%\n"

    prompt += f"""
### 宏观背景
- 上证指数: {idx_map.get('上证指数', {}).get('price', 'N/A')} ({idx_map.get('上证指数', {}).get('change_pct', 'N/A')}%)
- 沪深300: {idx_map.get('沪深300', {}).get('price', 'N/A')} ({idx_map.get('沪深300', {}).get('change_pct', 'N/A')}%)
- 黄金: {comm_map.get('黄金', {}).get('price', 'N/A')} ({comm_map.get('黄金', {}).get('change_pct', 'N/A')}%)
"""

    # 注入因子/动量数据（如果有）
    if factor_scores:
        prompt += "\n### 因子评分 / 动量数据\n"
        for fs in factor_scores[:15]:
            name = fs.get("name", fs.get("symbol", "?"))
            scores = fs.get("factor_scores", fs.get("scores", {}))
            if scores and isinstance(scores, dict):
                score_items = "；".join(
                    f"{k}: {v:.2f}" for k, v in sorted(scores.items(), key=lambda x: -abs(x[1]))[:5]
                )
                prompt += f"- {name}: {score_items}\n"
            else:
                chg = fs.get("change_pct", "")
                if chg != "":
                    prompt += f"- {name}: 涨跌幅 {chg}%\n"

    prompt += f"""
**重要说明：**
- 如果分析的概念包含跨市场标的（如同时在 A 股和港股上市的创新药），请明确指出当前分析的市场
- **必须包含近 1-5 日的近期行情分析**，包括近期涨跌幅、成交量变化、板块内个股表现

请从以下时间维度和分析维度进行全面分析：

### 时间维度
1. **短期（近 1-5 日）**：近期涨跌幅、成交量变化、板块内个股表现
2. **中期（近 1 个月）**：趋势方向、主力资金动向
3. **长期（近 3 个月以上）**：行业景气度、估值水平、政策持续性

### 分析维度
1. 行业基本面与景气度
2. 技术面形态与关键位
3. 资金流向与机构动向
4. 核心标的推荐（3-5只）
5. 风险提示
6. 操作建议（买入/持有/减仓区间）

  控制在 600 字以内。"""
    return await get_agent("sector_analysis").run(prompt)


async def generate_symbol_analysis(
    symbol: str,
    name: str,
    asset_type: str,
    realtime: dict,
    history: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
) -> str:
    hist_text = "\n".join([
        f"- {h.get('date', '')}: 收盘 {h.get('close', 'N/A')}, 涨跌幅 {h.get('change_pct', 'N/A')}%"
        for h in history[-10:]
    ])

    ind_text = "\n".join([f"- {k}: {v}" for k, v in indicators.items() if v is not None])

    news_text = "\n".join([f"- {n.get('title', n.get('summary', ''))[:100]}" for n in news[:5]])

    prompt = f"""## {name}({symbol}) 个股/ETF 深度分析

### 实时行情
- 当前价格: {realtime.get('price', 'N/A')}
- 涨跌幅: {realtime.get('change_pct', 'N/A')}%
- 成交额: {realtime.get('turnover', 'N/A')} 万
- 换手率: {realtime.get('turnover_rate', 'N/A')}%

### 近期走势
{hist_text}

### 技术指标
{ind_text}

### 相关资讯
{news_text}

请输出：
1. 技术面研判（趋势/支撑/阻力/量能）
2. 基本面/消息面催化剂
3. 买卖信号（明确给出：买入/持有/卖出）
4. 目标价位区间
5. 止损位
6. 风险提示

  控制在 500 字以内。"""

    return await get_agent("symbol_analysis").run(prompt)

# ── 设计报告 LLM 生成 ────────────────────────────────────


async def generate_design_report(
    strategies: list[dict],
    market_sentiment: dict | None = None,
    benchmark_stocks: list[dict] | None = None,
    market_context: dict | None = None,
    plan_tables: str = "",
) -> str:
    """基于系统算法生成的组合方案，调用 LLM 撰写市场分析报告。

    Args:
        strategies: 三个方案数据（来自战略设计管道）
        market_sentiment: 市场情绪数据（可选，兼容旧调用）
        benchmark_stocks: 核心指标股数据（可选，兼容旧调用）
        market_context: 完整市场上下文（P1 增强：含 index_realtime / market_regime /
            macro_regime / sector_momentum 等），优先于上面两个单独字段

    Returns:
        Markdown 格式的分析报告
    """
    ctx = market_context or {}
    # 兼容旧调用：若未传 market_context，则回退到单独字段
    if not ctx:
        ctx = {
            "market_sentiment": market_sentiment or {},
            "benchmark_stocks": benchmark_stocks or [],
        }
    prompt = _build_design_report_prompt(
        strategies,
        ctx.get("market_sentiment", market_sentiment or {}),
        ctx.get("benchmark_stocks", benchmark_stocks or []),
        market_context=ctx, plan_tables=plan_tables,
    )
    try:
        # 使用"symbol_analysis" agent 的通用上下文，但传入设计报告 prompt
        result = await get_agent("symbol_analysis").run(
            prompt,
            system_override=load_prompt("design_report.md"),
        )
        return result or "报告生成失败"
    except Exception as e:
        logger.warning("[generate_design_report] LLM call failed: %s", e)
        return ""


def _build_factor_breakdown_table(strategies: list[dict]) -> str:
    """Build a markdown table of factor breakdowns from strategies' allocations.

    Returns:
        A markdown table string (may be empty if no factor data found).
    """
    seen: set[str] = set()
    all_factor_keys: set[str] = set()
    rows: list[tuple[str, str, str, list[str]]] = []

    # First pass: collect all unique factor keys across all allocations
    for s in strategies:
        for a in (s.get("allocations") or s.get("etfs") or []):
            sym = a.get("symbol", "")
            if sym and sym not in seen and sym != "CASH":
                seen.add(sym)
                fb = a.get("factor_breakdown") or a.get("factor_scores") or {}
                for k in fb:
                    all_factor_keys.add(k)

    if not all_factor_keys:
        return ""

    factor_keys = sorted(all_factor_keys)
    seen.clear()

    # Second pass: collect row data
    for s in strategies:
        for a in (s.get("allocations") or s.get("etfs") or []):
            sym = a.get("symbol", "")
            if sym and sym not in seen and sym != "CASH":
                seen.add(sym)
                name = (a.get("name", "") or "")[:20]
                fs_raw = a.get("factor_score")
                fs = f"{fs_raw:.3f}" if isinstance(fs_raw, (int, float)) else "—"
                fb = a.get("factor_breakdown") or a.get("factor_scores") or {}
                cells = []
                for k in factor_keys:
                    v = fb.get(k)
                    cells.append(f"{v:.3f}" if isinstance(v, (int, float)) else "—")
                rows.append((sym, name, fs, cells))

    # Build header
    header = ["Symbol", "Name", "Factor Score"] + list(factor_keys)
    sep = ["---"] * len(header)
    lines = [
        "## ETF Factor Breakdown",
        "",
        "Below are the detailed factor scores for each selected ETF, indicating WHY each was selected:",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for sym, name, fs, cells in rows:
        row = [sym, name, fs] + cells
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("For each ETF, the dominant factors are the ones with highest absolute scores.")
    lines.append("Use these factor details when writing the rationale for each ETF selection.")
    lines.append("")
    return "\n".join(lines)



def _build_design_report_prompt(
    strategies: list[dict],
    market_sentiment: dict,
    benchmark_stocks: list[dict],
    market_context: dict | None = None,
    plan_tables: str = "",
) -> str:
    """构建设计报告 prompt。

    P1 增强：新增「市场行情快照」（实时指数点位/涨跌幅）与「行业板块动量」两节，
    使 LLM 报告能引用实际市场数据而非仅情绪指数。
    """
    market_context = market_context or {}
    _regime = market_context.get("market_regime") or market_sentiment.get("market_regime")
    _macro = market_context.get("macro_regime") or {}
    index_realtime = market_context.get("index_realtime") or []
    sector_momentum = market_context.get("sector_momentum") or []

    # 数据日期标签：非交易日的行情来自上一交易日
    from ..core.market_calendar import is_trading_time as _is_trading
    from datetime import timedelta as _td
    _now = __import__('datetime', fromlist=['datetime']).datetime.now()
    if _is_trading(_now):
        data_date_label = "今日"
    else:
        _d = _now - _td(days=1)
        _d -= _td(days=(_d.weekday() - 4)) if _d.weekday() >= 5 else _td(days=0)  # 跳到周五
        data_date_label = f"{_d.month}月{_d.day}日"

    def _fmt_pct(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            # P3.5: 如果已是原始百分比（abs > 1），不再 ×100
            # 指数数据 (change_pct=-5.4) 和 benchmark 数据 (change_pct=-0.054) 单位不一致
            if abs(v) > 1:
                return f"{v:.1f}%"
            return f"{v * 100:.1f}%"
        return str(v)

    # ── P5-a: 注入预生成的方案表格（引擎直接渲染，确保与方案卡片一致） ──
    _factor_table = _build_factor_breakdown_table(strategies)

    if plan_tables:
        lines = [
            "## 注意：报告撰写范围说明",
            "",
            f"以下为引擎算法直接生成的方案详解表格，与前端「方案卡片」的数据来源完全一致。",
            "你**不需要**在报告正文中重新描述各方案的 ETF 标的、权重和入选理由。",
            "你的任务是：",
            "1. 基于「市场行情快照」「行业板块动量」「市场情绪」等输入数据，撰写「市场环境分析」；",
            "2. 说明三层设计框架（核心/卫星/防御）；",
            "3. 横向对比三种方案的特点和适用场景；",
            "4. 给出配置建议和风险提示。",
            "",
            "引擎预生成的方案表格如下（将自动嵌入报告第三部分）：",
            "",
            plan_tables,
            "",
            "---",
            "",
        ]
        if _factor_table:
            lines.append(_factor_table)
            lines.append("")
        lines.append("## 输入数据")
        lines.append("")
        lines.append("### 市场情绪")
    else:
        lines = []
        if _factor_table:
            lines.append(_factor_table)
            lines.append("")
        lines.append("## 输入数据")
        lines.append("")
    lines.append("### 市场情绪")
    lines.append(f"- 情绪指数: {market_sentiment.get('sentiment_index', 'N/A')}")
    lines.append(f"- 情绪标签: {market_sentiment.get('sentiment_label', 'N/A')}")
    lines.append("")

    # ── P1 新增：市场行情快照（实时指数） ──
    if index_realtime:
        lines.append("### 市场行情快照（实时指数）")
        for idx in index_realtime:
            chg = idx.get("change_pct")
            chg_txt = _fmt_pct(chg) if chg is not None else "—"
            lines.append(
                f"- {idx.get('name', idx.get('symbol', ''))}（{idx.get('symbol', '')}）: "
                f"点位 {idx.get('price', '—')}，今日 {chg_txt}"
            )
        lines.append("")

    # ── 市场状态 / 宏观（补充上下文） ──
    if _regime:
        lines.append("### 市场状态")
        lines.append(f"- 市场状态(regime): {_regime}")
        if _macro:
            eco = _macro.get("economic_phase")
            mon = _macro.get("monetary_stance")
            if eco:
                lines.append(f"- 宏观: {eco}" + (f"·{mon}" if mon else ""))
        lines.append("")

    if benchmark_stocks:
        lines.append("### 核心指标股")
        for s in benchmark_stocks[:5]:
            lines.append(f"- {s.get('name', '')}({s.get('symbol', '')}): "
                         f"涨跌{_fmt_pct(s.get('change_pct', 0))}, "
                         f"信号: {s.get('signal', '')}")
        lines.append("")

    # ── P1 新增：行业板块动量 ──
    if sector_momentum:
        lines.append("### 行业板块动量（申万一级，按当日强弱排名）")
        for item in sector_momentum[:10]:
            name = item.get("sector_name") or item.get("sector") or ""
            rank = item.get("rank") or item.get("rank_current")
            total = item.get("total") or ""
            chg = item.get("change_pct")
            chg_txt = _fmt_pct(chg) if chg is not None else ""
            rank_txt = f"第{rank}/{total}名" if rank is not None else ""
            lines.append(f"- {name}: {rank_txt} 当日{chg_txt}".rstrip())
        lines.append("")

    # ── 因子评分（5.0+ 新增） ──
    if strategies:
        lines.append("### 各标的因子评分")
        lines.append("（多因子模型综合评分，0~1）")
        for s in strategies:
            label = s.get("label", "")
            lines.append(f"- {label}:")
            for e in (s.get("allocations") or s.get("etfs") or [])[:5]:
                code = e.get("symbol", "")
                name = e.get("name", "")[:10]
                fs = e.get("factor_score", None)
                if fs is not None:
                    lines.append(f"  - {name}({code}) 评分: {fs:.2f}")
                    # 取 top-3 factor_scores 子项（如有 breakdown）
                    fs_detail = e.get("factor_scores", {})
                    if isinstance(fs_detail, dict) and fs_detail:
                        top_3 = sorted(fs_detail.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
                        for f_code, f_val in top_3:
                            lines.append(f"    {f_code}: {f_val:.2f}")
        lines.append("")

    lines.append("### 组合方案")
    if not plan_tables:
        for s in strategies:
            style = s.get("style", s.get("style_label", ""))
            lines.append(f"- {style}: {s.get('portfolio_name', '')}")
            lines.append(f"  定位: {s.get('positioning', '')}")
            lines.append(f"  预期年化: {_fmt_pct(s.get('expected_return'))}, "
                         f"最大回撤: {_fmt_pct(s.get('max_drawdown'))}, "
                         f"夏普: {s.get('sharpe_ratio', 'N/A')}")
            for a in s.get("allocations", []):
                weight = a.get("target_weight", 0) * 100
                lines.append(f"  - {a.get('name', '')}({a.get('symbol', '')}) "
                             f"[{a.get('layer', '')}] {weight:.1f}% - {a.get('selection_rationale', '')}")
            lines.append("")

    return "\n".join(lines)