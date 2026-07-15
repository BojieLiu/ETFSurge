import json
import time
import sys
from typing import Any

from ..config import settings
from ..monitor.token_usage import token_store, UsageRecord
from ..core.logging import get_logger
from .registry import get_agent

logger = get_logger(__name__)

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
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY not configured in .env")


async def llm_complete(prompt: str, response_format: dict | None = None) -> str:
    import httpx
    await _check_key()
    body = {
        "model": settings.llm_model,
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
    _caller = sys._getframe(1).f_code.co_name  # caller function name
    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            resp = await client.post(
                LLM_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            message = data["choices"][0]["message"]
            content = message.get("content", "")
            # Some models (e.g., DeepSeek) put reasoning in reasoning_content and leave content empty
            if not content:
                content = message.get("reasoning_content", "")

            usage = data.get("usage", {})
            _duration = (time.monotonic() - _start) * 1000
            await token_store.record(UsageRecord(
                function_name=_caller,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                model=settings.llm_model,
                timestamp=time.time(),
                success=True,
                duration_ms=round(_duration, 1),
            ))
            return content
    except Exception as _exc:
        _duration = (time.monotonic() - _start) * 1000
        await token_store.record(UsageRecord(
            function_name=_caller,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            model=settings.llm_model,
            timestamp=time.time(),
            success=False,
            duration_ms=round(_duration, 1),
            error_message=str(_exc),
        ))
        raise


async def llm_complete_with_system(system_prompt: str, prompt: str, response_format: dict | None = None, force_json: bool = False) -> str:
    """使用自定义系统提示词调用 LLM"""
    import httpx
    await _check_key()
    body = {
        "model": settings.llm_model,
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
    _caller = sys._getframe(1).f_code.co_name
    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            resp = await client.post(
                LLM_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
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
                model=settings.llm_model,
                timestamp=time.time(),
                success=True,
                duration_ms=round(_duration, 1),
            ))
            return content
    except Exception as _exc:
        _duration = (time.monotonic() - _start) * 1000
        await token_store.record(UsageRecord(
            function_name=_caller,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            model=settings.llm_model,
            timestamp=time.time(),
            success=False,
            duration_ms=round(_duration, 1),
            error_message=str(_exc),
        ))
        raise


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


async def generate_advice(query: str, context: dict[str, Any] | None = None) -> str:
    prompt = f"用户提问: {query}\n\n"
    if context:
        prompt += f"上下文信息: {json.dumps(context, ensure_ascii=False)}\n\n"
    prompt += "请给出专业、简洁的回答，控制在 500 字以内，使用 Markdown 格式"
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
    except Exception:
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


async def generate_portfolio_design(
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    news: list[dict],
    macro_news: list[dict],
    capital: float = 500000,
) -> dict[str, Any]:
    def _val(d, key, fmt="{}"):
        v = d.get(key, "")
        return fmt.format(v) if v != "" and v is not None else "数据缺失"

    idx_map = {idx.get("name", ""): idx for idx in indices}
    sh = idx_map.get("上证指数", {})
    sz = idx_map.get("深证成指", {})
    cyb = idx_map.get("创业板指", {})
    kc = idx_map.get("科创50", {})
    hs300 = idx_map.get("沪深300", {})

    comm_map = {c.get("name", ""): c for c in commodities}
    gold = comm_map.get("黄金", {})
    oil = comm_map.get("原油", {})
    silver = comm_map.get("白银", {})

    # 数据快照时间（当前请求时间）
    from datetime import datetime
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M（北京时间）")

    # 市场成交额估算
    turnover = ""
    for m in market_data:
        if m.get("name") in ("上证指数", "深证成指", "创业板指", "科创50"):
            if m.get("turnover"):
                turnover = f"{m['turnover']:.0f}"
                break

    # 资讯文本
    news_text = "\n".join([f"- {n.get('title', n.get('summary', ''))[:120]}" for n in news[:8]])
    macro_text = "\n".join([f"- {n.get('title', n.get('summary', ''))[:120]}" for n in macro_news[:5]])

    # 新的用户提示词：按输入模板结构化
    prompt = f"""# 【市场数据输入】

数据快照时间：{snapshot_time}


## 1. 大盘概览
- 上证指数：{_val(sh, 'price')}点（{_val(sh, 'change_pct', '{:+.2f}%')}） 
- 深证成指：{_val(sz, 'price')}点（{_val(sz, 'change_pct', '{:+.2f}%')}） 
- 创业板指：{_val(cyb, 'price')}点（{_val(cyb, 'change_pct', '{:+.2f}%')}） 
- 科创50：{_val(kc, 'price')}点（{_val(kc, 'change_pct', '{:+.2f}%')}） 
- 沪深300：{_val(hs300, 'price')}点（{_val(hs300, 'change_pct', '{:+.2f}%')}） 
- 市场成交额：{turnover or '未获取'}亿元

## 2. 行业/板块表现
（当前输入未提供该维度数据）

## 3. ETF资金流向数据
（当前输入未提供该维度数据）

## 4. 关键资讯/催化剂
{news_text}

{macro_text}

## 5. 重点ETF估值数据
（当前输入未提供该维度数据）

## 6. 流动性/避险指标
- 黄金价格：{_val(gold, 'price')}美元/盎司（{_val(gold, 'change_pct', '{:+.2f}%')}） 
- 原油价格：{_val(oil, 'price')}美元/桶（{_val(oil, 'change_pct', '{:+.2f}%')}） 
- 白银价格：{_val(silver, 'price')}美元/盎司（{_val(silver, 'change_pct', '{:+.2f}%')}） 

---
请基于以上输入的实时数据，设计进攻、平衡、防御三档ETF组合方案。
"""
    try:
        result = await get_agent("portfolio_design").run_json(prompt)
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return _fallback_portfolio_plans(capital, f"LLM 调用失败: {e}")

    if not result or not result.get("plans"):
        return _fallback_portfolio_plans(capital, "LLM 返回格式异常")

    result.setdefault("design_text", "（LLM 未生成完整报告文本）")
    result.setdefault("comparison_table", {})
    result["data_snapshot_time"] = snapshot_time
    return result


def _fallback_portfolio_plans(capital: float = 500000, reason: str = "LLM 暂不可用") -> dict[str, Any]:
    """LLM 不可用时生成简版组合方案（三条风格各一组默认标的）。"""
    base_etfs = [
        {"symbol": "510300", "name": "沪深300ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "核心宽基，覆盖A股大盘", "weight_rationale": "作为底仓配置",
         "tracked_index": "000300", "key_metrics": {"scale_billion": 1200, "avg_volume_million": 2500, "pe_ttm": 12.5, "pb": 1.3, "ytd_return": 8.5}},
        {"symbol": "510500", "name": "中证500ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "中盘成长代表", "weight_rationale": "补充中盘暴露",
         "tracked_index": "000905", "key_metrics": {"scale_billion": 600, "avg_volume_million": 1800, "pe_ttm": 18.0, "pb": 1.8, "ytd_return": 6.2}},
        {"symbol": "159915", "name": "创业板ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "成长风格核心标的", "weight_rationale": "增强组合弹性",
         "tracked_index": "399006", "key_metrics": {"scale_billion": 400, "avg_volume_million": 2200, "pe_ttm": 32.0, "pb": 3.5, "ytd_return": -2.1}},
        {"symbol": "588000", "name": "科创50ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "科技创新方向", "weight_rationale": "布局硬科技赛道",
         "tracked_index": "000688", "key_metrics": {"scale_billion": 250, "avg_volume_million": 1500, "pe_ttm": 45.0, "pb": 4.2, "ytd_return": -5.3}},
        {"symbol": "513100", "name": "纳指ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "美股科技龙头", "weight_rationale": "跨境分散配置",
         "tracked_index": "NDX", "key_metrics": {"scale_billion": 180, "avg_volume_million": 800, "pe_ttm": 28.0, "pb": 6.5, "ytd_return": 15.2}},
        {"symbol": "518880", "name": "黄金ETF", "asset_class": "commodity", "target_weight": 0.0,
         "selection_rationale": "避险资产", "weight_rationale": "对冲尾部风险",
         "tracked_index": "AU9999", "key_metrics": {"scale_billion": 300, "avg_volume_million": 1200, "pe_ttm": 0, "pb": 0, "ytd_return": 12.8}},
        {"symbol": "512880", "name": "证券ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "券商板块弹性标的", "weight_rationale": "博弈市场情绪修复",
         "tracked_index": "399975", "key_metrics": {"scale_billion": 350, "avg_volume_million": 2000, "pe_ttm": 20.0, "pb": 1.5, "ytd_return": 3.5}},
        {"symbol": "159865", "name": "养殖ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "农业周期板块", "weight_rationale": "分散行业集中度",
         "tracked_index": "399812", "key_metrics": {"scale_billion": 60, "avg_volume_million": 300, "pe_ttm": 25.0, "pb": 2.1, "ytd_return": -1.8}},
        {"symbol": "513050", "name": "中概互联ETF", "asset_class": "equity", "target_weight": 0.0,
         "selection_rationale": "中概互联网龙头", "weight_rationale": "布局港股科技核心资产",
         "tracked_index": "H30533", "key_metrics": {"scale_billion": 400, "avg_volume_million": 1800, "pe_ttm": 22.0, "pb": 3.8, "ytd_return": 10.2}},
    ]

    def _make_plan(style: str, label: str, etf_weights: list[float], expected_return: float, max_dd: float, sharpe: float) -> dict:
        etfs = []
        for i, etf in enumerate(base_etfs):
            w = etf_weights[i] if i < len(etf_weights) else 0.05
            e = dict(etf)
            e["target_weight"] = w
            etfs.append(e)
        return {
            "style": style, "style_label": label,
            "portfolio_name": f"{label}组合",
            "expected_return": expected_return,
            "max_drawdown": max_dd,
            "sharpe_ratio": sharpe,
            "allocations": etfs,
            "market_analysis": {
                "macro_environment": "当前宏观环境复杂多变，建议均衡配置",
                "liquidity_condition": "市场流动性充裕",
                "style_preference": "大盘价值为主，小盘成长为辅",
                "sector_opportunity": "关注科技、消费、黄金板块机会",
                "risk_assessment": "关注海外加息尾部风险"
            },
            "allocation_rationale": {
                "asset_class_allocation": f"总仓位 {capital:,.0f} 元，按风险梯度分配权益与商品比例",
                "equity_style_tilt": "均衡配置成长与价值风格",
                "geographic_allocation": "A股为主，跨境分散",
                "sector_allocation": "宽基打底，行业卫星配置"
            },
            "risk_factors": ["市场系统性风险", "风格轮动风险"],
            "rebalance_rules": "季度再平衡，偏离超5%触发调仓",
        }

    return {
        "market_environment": f"{reason}，以下为参考组合方案",
        "plans": [
            _make_plan("进攻型", "进攻型",
                       [0.14, 0.12, 0.14, 0.12, 0.10, 0.05, 0.12, 0.10],
                       0.12, 0.25, 0.75),
            _make_plan("平衡型", "平衡型",
                       [0.12, 0.10, 0.12, 0.08, 0.08, 0.05, 0.08, 0.08],
                       0.08, 0.18, 0.85),
            _make_plan("防御型", "防御型",
                       [0.10, 0.08, 0.08, 0.06, 0.06, 0.08, 0.06, 0.05],
                       0.05, 0.12, 0.90),
        ]
    }


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


async def generate_sector_analysis(
    sector_code: str,
    sector_name: str,
    sector_stocks: list[dict],
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
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

请从以下维度分析：
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