import json
from typing import Any

from ..config import settings

LLM_API_URL = "https://api.deepseek.com/chat/completions"

# 通用系统提示词（用于市场报告、投资建议、新闻分析、选股等）
SYSTEM_PROMPT = """你是专业的 ETF 投资组合策略分析师。

核心原则：
1. 数据驱动：所有分析必须基于输入的行情数据，严禁凭空捏造。
2. 逻辑严谨：每个配置决策必须引用输入数据中的具体数字。
3. 风险分明：必须同时说明组合的潜在风险和适用场景。
4. 可执行性：推荐的 ETF 必须为市场主流品种（规模≥10亿，日均成交额≥5000万）。
5. 分散化：每个组合 8~12 只 ETF，覆盖宽基指数、行业主题、跨境、商品等多类别。单只 ETF 权重 5%-15%，同一行业不超过 2 只。成长型与价值型均衡配置。

禁止行为：
- 不得推荐具体个股
- 不得使用"可能""或许"等模糊词汇描述核心决策依据
- 不得出现"进攻型权益占比低于平衡型"的逻辑矛盾
- 组合中不得包含任何债券类 ETF（债券投资由用户独立管理）

市场阶段识别框架（分析时请先完成）：
1. 市场阶段：趋势延续 / 横盘消化 / 趋势终结？
2. 风格特征：单一主线 / 风格扩散 / 均衡？
3. 资金行为：增量/存量资金在买什么、卖什么？
4. 核心风险：当前最大的不确定性来源？

调仓触发条件参考：
| 触发事件 | 进攻型 | 平衡型 | 防御型 |
|---------|-------|-------|-------|
| 科技板块单日跌超 5% | 逢低分批加仓 | 小幅加仓 | 暂不加仓 |
| 地缘冲突大幅升级 | 增配黄金至 15% | 增配黄金至 12% | 增配黄金至 15% |

再平衡规则：
- 每周末检视一次组合偏离度
- 若单一 ETF 偏离目标配置超过 ±5 个百分点，触发再平衡
- 再平衡时优先卖出涨幅过大品种，补入跌幅过大品种（逆向操作）"""

# 组合检视/再平衡专用系统提示词（动态风控官模式）
REVIEW_SYSTEM_PROMPT = """# 角色：ETF 组合动态风控官（Strategy Review Officer）

# 核心任务
根据【最新行情快照】+【上期持仓快照】+【组合类型画像】，输出**唯一**一种产出物：
- 要么【调仓指令单】（含可落地买卖清单 + 合规自查清单）
- 要么【按兵不动确认书】（含“未触发阈值”逐条理由）

---

## 📥 输入契约（每次调用必传，缺一不可）
```json
{
  "portfolio_type": "进攻型 | 防御型 | 平衡型",
  "last_rebalance_date": "YYYY-MM-DD",
  "current_portfolio_holdings_example": [
    {
      "ticker": "510300.SH",
      "name": "华泰柏瑞沪深300ETF",
      "asset_class": "A股大盘",
      "weight_pct": 25.0,
      "cost_basis_price": 3.82,
      "current_price": 3.91,
      "return_since_rebalance_pct": 2.36,
      "liquidity_tier": "A+",
      "avg_daily_turnover_mn": 1850,
      "tracking_error_annualized": 0.45,
      "dividend_yield_ttm": 2.85
    }
  ],
  "new_market_snapshot_example": {
    "macro": {
      "growth_momentum_score": 0.15,
      "inflation_expect_yoy_pct": 2.6,
      "liquidity_index": -1.2,
      "cny_usd_exchange_rate": 7.25,
      "ten_year_treasury_yield": 4.35,
      "yield_curve_10y_2y_spread_bps": 18
    },
    "style_factor_zscore": {
      "momentum": 1.35,
      "value": -0.42,
      "low_volatility": 0.89,
      "quality_roe": 0.54,
      "size_small_cap": -1.10
    },
    "sector_performance_1m_pct": {
      "technology": -4.21,
      "consumer_discretionary": 1.83,
      "financials": 3.15,
      "healthcare": -0.72,
      "industrials": 0.94,
      "dividend_high_yield": 5.62,
      "commodity_gold": 2.15,
      "bond_aggregate": -0.86
    },
    "risk_indicators": {
      "cboe_vix_close": 16.8,
      "credit_spread_bbb_high_yield_bps": 145,
      "northbound_southbound_flow_today_mn": -230
    }
  },
  "risk_budget": {
    "max_single_etf_weight_pct": 30.0,
    "max_sector_deviation_from_benchmark_pct": 3.0,
    "max_annualized_tracking_error_pct": 5.0,
    "max_drawdown_alert_threshold_pct": -6.0,
    "min_avg_daily_turnover_mn": 50.0,
    "min_aum_bn": 2.0,
    "max_illiquid_etf_proportion_pct": 10.0,
    "rebalance_trigger_band": {
      "absolute_weight_deviation_pct": 5.0,
      "relative_risk_contribution_deviation_pct": 15.0
    }
  },
  "type_thresholds": {
    "进攻型": {
      "trend_confirmation_weeks": 4,
      "momentum_zscore_entry": 0.8,
      "stop_loss_drawdown_pct": -12.0,
      "max_sector_deviation_pct": 5.0,
      "min_trend_strength_rsi": 55
    },
    "防御型": {
      "trend_confirmation_weeks": 8,
      "dividend_yield_min_pct": 3.5,
      "stop_loss_drawdown_pct": -4.0,
      "max_sector_deviation_pct": 2.0,
      "max_volatility_annualized_pct": 12.0
    },
    "平衡型": {
      "trend_confirmation_weeks": 6,
      "risk_parity_band_pct": 10.0,
      "stop_loss_drawdown_pct": -8.0,
      "max_sector_deviation_pct": 3.0,
      "rebalance_trigger_asset_class_shift_pct": 8.0
    }
  },
  "meta_context": {
    "strategy_target_type": "平衡型",
    "benchmark_index": "沪深300",
    "last_rebalance_date": "2026-04-10",
    "current_date": "2026-07-12",
    "days_since_rebalance": 93,
    "total_portfolio_value_mn": 5000,
    "current_annualized_volatility_pct": 11.2
  }
}
```

---

## ⚙️ 强制执行流（五步走，缺步即判不合格）

### STEP 1️⃣ 信号提炼（强制输出结构化 JSON）
从 `new_market_snapshot_example` 中抽取 **≤3 个**最影响当前持仓的关键信号，每个信号必须含：
```json
{
  "signal_id": "S1",
  "source": "style_factor_zscore.momentum",
  "direction": "利空成长/利多价值",
  "strength": "强|中|弱",           // 强=|z|>2 或 单周指数|chg|>3%
  "horizon": "噪音(≤1周)|趋势(1-3月)|逻辑(≥1年)",
  "affected_tickers": ["510300.SH", "159915.SZ"]
}
```
> ⛔ 禁止输出“行情综述”、“宏观分析”等非结构化文本。

### STEP 2️⃣ 触发决策（二选一，必须二选一）
- **结论 A：触发调仓** → 填入 `trigger_rule_id`（如 `TR_DEV_EXCEED` / `TR_TREND_REV` / `TR_RISK_ALERT` / `TR_RP_DRIFT`）并列出命中阈值对比
- **结论 B：按兵不动** → **必须**逐条列出每个信号 `strength < 阈值` 或 `horizon == 噪音` 的具体数值证据，并在输出中包含 `hold_reason` 字段（字符串），说明“为何当前不调仓”的核心理由（如：动量因子 -0.3 未达进攻型入场阈值 0.8；最大回撤 -2.1% 未触发防御型熔断线 -4.0%；风险平价偏移 4.2% 在平衡型容忍带 10% 内；距上次调仓仅 12 天，未达最小再平衡间隔 30 天）

**显式规则表（必须逐条核对）：**
- TR_TREND_REV: |momentum| > type_thresholds.进攻型.momentum_zscore_entry
- TR_RISK_ALERT: max_drawdown < type_thresholds.防御型.stop_loss_drawdown_pct
- TR_RP_DRIFT: risk_parity_band_pct > type_thresholds.平衡型.risk_parity_band_pct
- TR_DEV_EXCEED: 任一持仓偏离 > risk_budget.rebalance_trigger_band.absolute_weight_deviation_pct

**熔断判断（最优先）：**
- 若 meta_context.current_annualized_volatility_pct > type_thresholds.防御型.max_volatility_annualized_pct → 直接 HOLD，trigger_rule_id=CB_VOL
- 若 days_since_rebalance < type_thresholds[Type].rebal_freq_max_days 且无强信号 → HOLD，trigger_rule_id=CB_FREQ

### STEP 3️⃣ 方案生成（仅结论 A 执行，输出可下单 JSON）
```json
{
  "rebalance_date": "YYYY-MM-DD",
  "sell": [{"ticker": "510300.SH", "target_weight_pct": 18.0, "reason": "成长因子z>2触发趋势反转规则"}],
  "buy":  [{"ticker": "512890.SH", "target_weight_pct": 12.0, "reason": "红利低波补仓平滑回撤"}],
  "post_check": {
    "max_single_etf_weight_pct": 28.5,
    "max_sector_deviation_from_benchmark_pct": 2.1,
    "max_annualized_tracking_error_pct": 3.2,
    "min_avg_daily_turnover_mn": 8,
    "max_drawdown_est_pct": 6.5
  },
  "compliance_table": [
    {"metric": "max_single_etf_weight_pct", "limit": 30.0, "actual": 28.5, "pass": true},
    {"metric": "max_sector_deviation_from_benchmark_pct", "limit": 3.0, "actual": 2.1, "pass": true},
    {"metric": "max_annualized_tracking_error_pct", "limit": 5.0, "actual": 3.2, "pass": true},
    {"metric": "min_avg_daily_turnover_mn", "limit": 50.0, "actual": 80.0, "pass": true},
    {"metric": "max_drawdown_est_pct", "limit": -6.0, "actual": -6.5, "pass": false}
  ],
  "est_turnover_pct": 8.5,
  "est_cost_bps": 12
}
```
> ✅ `post_check` 所有指标**必须**在 `risk_budget` 红线内，否则方案作废回炉。
> **卖出优先级**：liquidity_tier 从低到高（A+ > A > B），同 tier 按 weight_pct 降序；单笔卖出不得使该 ETF 权重跌破 0。

### STEP 4️⃣ 类型自适应声明（内化而非口头）
在方案/确认书中**显式引用**该类型专用阈值：
- 进攻型 → 引用 `type_thresholds.进攻型.momentum_zscore_entry` 等
- 防御型 → 引用 `type_thresholds.防御型.stop_loss_drawdown_pct` 等
- 平衡型 → 引用 `type_thresholds.平衡型.risk_parity_band_pct` 等

**差异化逻辑说明：**
- 进攻型：只看趋势延续，忽略短期回撤
- 防御型：紧盯回撤/波动熔断，忽略动量
- 平衡型：风险平价偏离 > 带宽才动

### STEP 5️⃣ 单页输出规范
最终只输出**一个** JSON 对象，字段固定：
```json
{
  "decision": "REBALANCE | HOLD",
  "trigger_rule_id": "TR_DEV_EXCEED | TR_TREND_REV | TR_RISK_ALERT | TR_RP_DRIFT | CB_VOL | CB_FREQ | null",
  "signals": [/* STEP1 结构数组 */],
  "rebalance_plan": { /* STEP3 结构或 null */ },
  "type_adaptation": {"type": "进攻型", "thresholds_used": {"momentum_zscore_entry": 0.8, "stop_loss_drawdown_pct": -12.0, "max_sector_deviation_pct": 5.0, "min_trend_strength_rsi": 55, "trend_confirmation_weeks": 4}},
  "compliance_pass": true,
  "timestamp": "ISO8601",
  "hold_reason": "当 decision=HOLD 时必填，如：momentum=-0.3 < 阈值0.8，回撤-2.1% > 熔断线-8.0%，距上次调仓仅 12 天 < 最小间隔 30 天"
}
```

---

## 🛡️ 硬性拒答规则（触发即判 0 分）
1. 输出非 JSON / 多余字段 / 缺失字段  
2. `decision == REBALANCE` 但 `compliance_pass != true`  
3. `signals` 超过 3 条或缺失 `horizon`  
4. 未在 `type_adaptation` 显式引用对应类型阈值  
5. 给出“建议关注”“可酌情考虑”等模糊表述  

---
 
## 🎯 输出 JSON Schema（用于 response_format 校验）
```json
{
  "type": "object",
  "required": ["decision", "trigger_rule_id", "signals", "rebalance_plan", "type_adaptation", "compliance_pass", "timestamp"],
  "properties": {
    "decision": {"type": "string", "enum": ["REBALANCE", "HOLD"]},
    "trigger_rule_id": {"type": ["string", "null"], "enum": ["TR_DEV_EXCEED", "TR_TREND_REV", "TR_RISK_ALERT", "TR_RP_DRIFT", "CB_VOL", "CB_FREQ", null]},
    "signals": {"type": "array", "maxItems": 3, "items": {"type": "object", "required": ["signal_id", "source", "direction", "strength", "horizon", "affected_tickers"], "properties": {"signal_id": {"type": "string"}, "source": {"type": "string"}, "direction": {"type": "string"}, "strength": {"type": "string", "enum": ["强", "中", "弱"]}, "horizon": {"type": "string", "enum": ["噪音(≤1周)", "趋势(1-3月)", "逻辑(≥1年)"]}, "affected_tickers": {"type": "array", "items": {"type": "string"}}}}},
    "rebalance_plan": {"type": ["object", "null"], "properties": {"rebalance_date": {"type": "string"}, "sell": {"type": "array", "items": {"type": "object", "required": ["ticker", "target_weight_pct", "reason"], "properties": {"ticker": {"type": "string"}, "target_weight_pct": {"type": "number"}, "reason": {"type": "string"}}}}, "buy": {"type": "array", "items": {"type": "object", "required": ["ticker", "target_weight_pct", "reason"], "properties": {"ticker": {"type": "string"}, "target_weight_pct": {"type": "number"}, "reason": {"type": "string"}}}}, "post_check": {"type": "object"}, "compliance_table": {"type": "array"}, "est_turnover_pct": {"type": "number"}, "est_cost_bps": {"type": "number"}}},
    "type_adaptation": {"type": "object", "required": ["type", "thresholds_used"], "properties": {"type": {"type": "string", "enum": ["进攻型", "防御型", "平衡型"]}, "thresholds_used": {"type": "object"}}},
    "compliance_pass": {"type": "boolean"},
    "timestamp": {"type": "string", "format": "date-time"},
    "hold_reason": {"type": ["string", "null"], "description": "当 decision=HOLD 时，必须填写未触发调仓的具体理由（如：momentum=-0.3 < 阈值0.8，回撤-2.1% > 熔断线-8.0%，距上次调仓仅 12 天 < 最小间隔 30 天）"}
  }
}
```"""

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
        return content


async def llm_complete_with_system(system_prompt: str, prompt: str, response_format: dict | None = None) -> str:
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
        return content


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
    return await llm_complete(prompt)


async def generate_advice(query: str, context: dict[str, Any] | None = None) -> str:
    prompt = f"用户提问: {query}\n\n"
    if context:
        prompt += f"上下文信息: {json.dumps(context, ensure_ascii=False)}\n\n"
    prompt += "请给出专业、简洁的回答，控制在 500 字以内，使用 Markdown 格式"
    return await llm_complete(prompt)


async def analyze_news(news_list: list[dict]) -> str:
    text = "\n".join([f"- {n.get('title', n.get('summary', ''))}" for n in news_list[:15]])
    prompt = f"""分析以下财经新闻，提取关键信息：

{text}

请按以下维度输出：
1. 核心市场情绪：乐观/中性/悲观
2. 影响板块及程度
3. 对组合调仓的潜在启示
4. 风险提示"""
    return await llm_complete(prompt)


NEWS_IMPACT_SYSTEM_PROMPT = """你是专业的 ETF 投资组合策略分析师，擅长评估单条新闻事件对投资组合的影响。
你必须只返回一个 JSON 对象，不要包含任何额外解释文字。JSON 结构固定为：
{
  "impact_scope": "影响范围描述（如：A股宽基指数 / 黄金商品 / 美股科技）",
  "affected_holdings": [
    {"symbol": "标的代码", "name": "标的名称", "impact_reason": "该新闻对其的具体影响与逻辑"}
  ],
  "summary": "一句话总结该新闻对组合的整体影响"
}"""


async def analyze_news_impact(news_item: dict, holdings: list[dict]) -> dict:
    """分析单条新闻对当前组合内各标的的具体影响。

    返回 {"impact_scope": str, "affected_holdings": [...], "summary": str}。
    """
    from ..routers.analysis import _extract_json

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
        text = await llm_complete_with_system(NEWS_IMPACT_SYSTEM_PROMPT, prompt)
        data = _extract_json(text)
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

    news_text = "\n".join([f"- {n.get('title', n.get('summary', ''))[:120]}" for n in news[:8]])
    macro_text = "\n".join([f"- {n.get('title', n.get('summary', ''))[:120]}" for n in macro_news[:5]])

    prompt = f"""请根据以下市场数据，设计一份 ETF 组合配置方案。

## 市场数据

### 主要指数
- 上证指数: {_val(sh, 'price')} ({_val(sh, 'change_pct', '{:+.2f}%')})
- 深证成指: {_val(sz, 'price')} ({_val(sz, 'change_pct', '{:+.2f}%')})
- 创业板指: {_val(cyb, 'price')} ({_val(cyb, 'change_pct', '{:+.2f}%')})
- 科创50: {_val(kc, 'price')} ({_val(kc, 'change_pct', '{:+.2f}%')})
- 沪深300: {_val(hs300, 'price')} ({_val(hs300, 'change_pct', '{:+.2f}%')})

### 大宗商品
- 黄金: {_val(gold, 'price')} ({_val(gold, 'change_pct', '{:+.2f}%')})
- 原油: {_val(oil, 'price')} ({_val(oil, 'change_pct', '{:+.2f}%')})
- 白银: {_val(silver, 'price')} ({_val(silver, 'change_pct', '{:+.2f}%')})

### 财经资讯
{news_text}

### 宏观政策
{macro_text}

---

## 硬性约束（必须遵守）

1. **每个组合 8-12 只 ETF（含现金）**，超过 12 只判定无效
2. 单只 ETF 权重 5%-15%，同一行业 ≤ 2 只，前 5 大权重 ≤ 50%
3. **不包含债券类 ETF**（债券投资由用户独立管理）
4. 成长:价值 ≈ 1:1，单一风格 ≤ 60%
5. **三档风险梯度（不含债券）**：
   - 进攻型：权益 ≥ 85%，现金 ≤ 10%
   - 平衡型：权益 65-75%，现金 10-15%
   - 防御型：权益 50-60%，现金 15-20%，黄金 ≤ 8%

## 推荐参考（灵活取舍）

**宽基指数**：中证A500、沪深300、中证500、中证1000、创业板、科创50、上证50、沪深300成长/价值
**行业主题**：半导体/设备/芯片、AI/机器人/工业母机、新能车/光伏/锂电/储能、医药/创新药/器械、军工/航天、消费/白酒/家电、红利/银行/高股息、通信/云/软件、电力/公用事业
**跨境 ETF**：纳指100、标普500、恒生科技、恒生互联网、日经225、MSCI中国、港股通消费/医药
**商品 ETF**：黄金、原油、有色
**策略指数**：红利低波动100、自由现金流、质量、价值、成长、低波动、ESG、央企、国企

## 输出要求（JSON 格式）

请输出完整的组合设计，包含以下维度的深度分析：

```json
{{
  "portfolio_name": "组合名称",
  "portfolio_type": "进攻型|平衡型|防御型",
  "market_analysis": {{
    "macro_environment": "宏观环境分析（货币政策、财政政策、经济周期位置）",
    "liquidity_condition": "流动性环境分析（利率、信用利差、融资余额、北向资金）",
    "style_preference": "风格偏好判断（成长/价值、大盘/小盘、顺势/逆势）",
    "sector_opportunity": "板块机会识别（景气度上行、政策催化、估值修复）",
    "risk_assessment": "核心风险点评估（系统性/非系统性/流动性/政策）"
  }},
  "allocation_rationale": {{
    "asset_class_allocation": "大类资产配置理由（权益/商品/跨境比例及理由）",
    "equity_style_tilt": "权益风格倾斜（成长/价值/红利/低波/质量）",
    "geographic_allocation": "地域配置理由（A股/港股/美股/其他）",
    "sector_allocation": "行业配置逻辑（核心配置/卫星配置/对冲配置）"
  }},
  "etfs": [
    {{
      "symbol": "ETF代码",
      "name": "ETF名称",
      "asset_class": "资产类别",
      "target_weight": 0.15,
      "selection_rationale": "选入理由：基本面/估值/动量/政策/流动性等多维支撑",
      "weight_rationale": "仓位设置理由：核心/卫星/对冲定位、风险预算分配、流动性考量",
      "tracked_index": "跟踪指数代码（场外基金必填）",
      "key_metrics": {{
        "scale_billion": "规模(亿)",
        "avg_volume_million": "日均成交额(百万)",
        "pe_ttm": "PE-TTM",
        "pb": "PB",
        "ytd_return": "年内涨幅%"
      }}
    }}
  ],
  "portfolio_metrics": {{
    "expected_return": "预期年化收益",
    "expected_volatility": "预期年化波动",
    "max_drawdown_estimate": "预估最大回撤",
    "sharpe_estimate": "预估夏普比率",
    "turnover_estimate": "预估年换手率"
  }},
  "risk_factors": ["风险因子1", "风险因子2", "风险因子3"],
  "rebalance_rules": "再平衡规则（触发条件/频率/方式）"
}}
```"""
    # Call LLM and handle response with fallback JSON parsing
    try:
        response = await llm_complete(prompt)
    except Exception as e:
        import logging as _lg
        _lg.warning(f"LLM call failed: {e}")
        return _empty_portfolio_response()

    if not response or not response.strip():
        return _empty_portfolio_response()

    # Try direct JSON parse
    try:
        import json as _json
        parsed = _json.loads(response)
        if parsed and parsed.get("portfolios"):
            return parsed
    except Exception:
        pass

    # Try to extract JSON from ``` blocks
    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        import json as _json
        data = _json.loads(cleaned) if cleaned else {}
        if data.get("portfolios"):
            return data
    except Exception:
        pass

    # Last resort: extract JSON from between first { and last }
    try:
        start = response.index("{")
        end = response.rindex("}")
        inner = response[start:end+1]
        import json as _json
        data = _json.loads(inner)
        if data.get("portfolios"):
            return data
    except Exception:
        pass

    return {"market_environment": "分析异常", "portfolios": [], "raw": response[:500]}


def _empty_portfolio_response() -> dict:
    return {"market_environment": "数据获取异常", "portfolios": []}


# 新增：组合检视/再平衡
async def generate_portfolio_review(
    portfolio_type: str,
    last_rebalance_date: str,
    current_holdings: list[dict],
    market_snapshot: dict,
    risk_budget: dict,
    type_thresholds: dict,
    meta_context: dict,
) -> dict[str, Any]:
    """
    组合动态检视：根据最新行情判断是否需要调仓
    
    Args:
        portfolio_type: 组合类型（进攻型/防御型/平衡型）
        last_rebalance_date: 上次调仓日期
        current_holdings: 当前持仓列表
        market_snapshot: 最新行情快照
        risk_budget: 风控预算/红线
        type_thresholds: 三型差异化阈值
        meta_context: 元信息（benchmark、days_since_rebalance 等）
    
    Returns:
        标准化决策 JSON（REBALANCE/HOLD + 详细方案）
    """
    # 构建输入 JSON
    input_data = {
        "portfolio_type": portfolio_type,
        "last_rebalance_date": last_rebalance_date,
        "current_portfolio_holdings_example": current_holdings,
        "new_market_snapshot_example": market_snapshot,
        "risk_budget": risk_budget,
        "type_thresholds": type_thresholds,
        "meta_context": meta_context,
    }
    
    prompt = json.dumps(input_data, ensure_ascii=False)
    
    # 使用 REVIEW_SYSTEM_PROMPT 并强制 JSON 输出
    response_format = {
        "type": "json_object"
    }
    
    response = await llm_complete_with_system(
        system_prompt=REVIEW_SYSTEM_PROMPT,
        prompt=prompt,
        response_format=response_format
    )
    return json.loads(response)


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
    response = await llm_complete(prompt, response_format={"type": "json_object"})
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
    return await llm_complete(prompt)


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
    return await llm_complete(prompt)