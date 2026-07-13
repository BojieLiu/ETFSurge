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
- **结论 B：按兵不动** → 逐条列出每个信号 `strength < 阈值` 或 `horizon == 噪音` 的具体数值证据

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
  "timestamp": "ISO8601"
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
    "timestamp": {"type": "string", "format": "date-time"}
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
        return data["choices"][0]["message"]["content"]


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
        return data["choices"][0]["message"]["content"]


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
    portfolio: dict | None = None,
) -> str:
    prompt = _build_report_prompt(indices, commodities, market_data, indicators, news, macro_news, portfolio)
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


def _build_report_prompt(
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
    macro_news: list[dict],
    portfolio: dict | None = None,
) -> str:
    overview = _build_market_overview(indices, commodities, market_data, news, macro_news)

    prompt = f"""{overview}

请生成一份专业的市场分析报告，包含：
1. 市场整体走势研判
2. 关键风格/板块轮动信号
3. 宏观流动性与政策解读
4. 组合层面的操作建议（如有持仓）
5. 核心风险提示

要求：专业、客观、可执行，控制在 800 字以内。"""
    if portfolio:
        prompt += f"\n\n当前组合：{json.dumps(portfolio, ensure_ascii=False)}"
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

## 任务要求

设计一份 ETF 组合，满足：
1. 覆盖 A股宽基、行业主题、跨境、商品四大类
2. 共 8-12 只 ETF，单只权重 5%-15%
3. 同一行业不超过 2 只
4. 成长与价值均衡
5. 推荐 ETF 必须为主流品种（规模≥10亿，日均成交额≥5000万）
6. **不包含债券类 ETF**

请输出 JSON 格式：
```json
{{
  "portfolio_name": "组合名称",
  "portfolio_type": "进攻型|平衡型|防御型",
  "etfs": [
    {{
      "symbol": "ETF代码",
      "name": "ETF名称",
      "asset_class": "资产类别",
      "target_weight": 0.15,
      "reason": "配置理由（引用具体市场数据）",
      "tracked_index": "跟踪指数代码（场外基金必填）"
    }}
  ],
  "expected_return": "预期年化收益",
  "expected_volatility": "预期年化波动",
  "max_drawdown_estimate": "预估最大回撤",
  "risk_factors": ["风险因子1", "风险因子2"]
}}
```"""
    response = await llm_complete(prompt, response_format={"type": "json_object"})
    return json.loads(response)


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