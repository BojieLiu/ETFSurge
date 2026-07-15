# Analysis — LLM Agent Chains / AI 分析 Agent 链路

## 0. 架构说明 / Architecture Note

所有分析端点后端均由**统一的 Agent 运行时**驱动。每条分析链路 = 一条 `AgentConfig`
配置（系统提示词文件 + 模型 + 温度 + 响应格式），由 `analysis/runtime.py` 的
`AgentRuntime` 统一执行（含重试、降级、token 记账）。

Agent 配置集中在 `analysis/registry.py` 的 `AGENTS` 字典中；系统提示词存放在
`analysis/prompts/v1/*.md`（版本化、可热更新，无需改代码即可迭代 prompt）。

> 本次重构**不改变任何对外 HTTP 接口的请求/响应结构**，仅内部组织方式变化。

| Agent Key | 端点 | 系统提示词文件 | 模型 | temperature | response_format |
|-----------|------|--------------|------|-------------|----------------|
| `market_report` | `POST /analysis/llm-report` | general_analyst.md | deepseek-chat | 0.3 | text |
| `advice` | `POST /analysis/llm-advice` | general_analyst.md | deepseek-chat | 0.5 | text |
| `news_analysis` | `POST /analysis/llm-news-analysis` | general_analyst.md | deepseek-chat | 0.3 | text |
| `news_impact` | `POST /analysis/news-impact` | news_impact.md | deepseek-chat | 0.3 | json_object |
| `portfolio_design` | `POST /analysis/portfolio-design` | portfolio_design.md | deepseek-chat | 0.3 | json_object |
| `portfolio_review` | `POST /analysis/portfolio-review` | risk_officer.md | deepseek-chat | 0.1 | json_object |
| `strategy_suggestions` | (internal, called by portfolio service) | general_analyst.md | deepseek-chat | 0.3 | json_object |
| `sector_analysis` | `POST /analysis/sector-analysis` | general_analyst.md | deepseek-chat | 0.3 | text |
| `symbol_analysis` | `POST /analysis/symbol-analysis` | general_analyst.md | deepseek-chat | 0.3 | text |

---

## 1. 端点一览 / Endpoint Overview

| Method | Path | Agent Key | Description |
|--------|------|-----------|-------------|
| POST | `/api/v1/analysis/llm-report` | market_report | 市场研判报告 |
| POST | `/api/v1/analysis/llm-advice` | advice | 投资建议（带上下文） |
| POST | `/api/v1/analysis/llm-news-analysis` | news_analysis | 资讯影响分析 |
| POST | `/api/v1/analysis/news-impact` | news_impact | 单条新闻对组合的影响 |
| POST | `/api/v1/analysis/portfolio-design` | portfolio_design | 三档组合设计 |
| POST | `/api/v1/analysis/portfolio-review` | portfolio_review | 组合检视/再平衡 |
| POST | `/api/v1/analysis/sector-analysis` | sector_analysis | 行业板块分析 |
| POST | `/api/v1/analysis/symbol-analysis` | symbol_analysis | 个股/ETF 分析 |

> `strategy_suggestions` 无独立 HTTP 端点，由 `portfolio_service.calculate_daily_pnl`
> 内部调用，经 `POST /api/v1/portfolio/strategy-check` 暴露。

---

## 2. LLM Report / 市场研判报告

```
POST /api/v1/analysis/llm-report
```

**请求体 / Request Body:**

```json
{ "symbols": ["510050", "510880"] }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbols | array of string | No | 指定标的；缺省则分析主要指数/期货 |

**成功响应 / `200 OK`:**

```json
{
  "report": "## 1. 市场阶段与核心矛盾 ...",
  "market_data": [ { "symbol": "...", "name": "...", "price": 3.91, "change_pct": 1.2 } ],
  "indices": [ { "symbol": "...", "name": "...", "price": 3200, "change_pct": -0.5 } ],
  "commodities": [ { "symbol": "...", "name": "黄金", "price": 550, "change_pct": 0.8 } ],
  "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
}
```

---

## 3. LLM Advice / 投资建议

```
POST /api/v1/analysis/llm-advice?query=<question>
```

**查询参数 / Query:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | Yes | 自然语言问题 |

**请求体:** 任意 JSON 上下文（可选）

**成功响应 / `200 OK`:**

```json
{ "advice": "LLM 生成的投资建议...", "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负" }
```

---

## 4. LLM News Analysis / 资讯分析

```
POST /api/v1/analysis/llm-news-analysis
```

**请求体:** 空（服务端拉取资讯）

**成功响应 / `200 OK`:**

```json
{ "analysis": "新闻影响分析...", "news_count": 12, "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负" }
```

---

## 5. News Impact / 单条新闻影响

```
POST /api/v1/analysis/news-impact
```

**请求体 / Request Body:**

```json
{
  "news": { "title": "...", "content": "..." },
  "portfolio": [ { "symbol": "510300", "name": "沪深300ETF", "asset_type": "A", "target_weight": 0.2 } ]
}
```

**成功响应 / `200 OK`:**

```json
{
  "impact_scope": "A股宽基指数",
  "affected_holdings": [ { "symbol": "510300", "name": "沪深300ETF", "impact_reason": "..." } ],
  "summary": "一句话总结...",
  "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
}
```

---

## 6. Portfolio Design / 组合设计

```
POST /api/v1/analysis/portfolio-design
```

**请求体 / Request Body:**

```json
{ "capital": 500000 }
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| capital | number | No | 500000 | 总资金（元） |

**成功响应 / `200 OK`:**

```json
{
  "design_text": "Markdown 报告...",
  "data_snapshot_time": "2026-07-14 20:28（北京时间）",
  "market_environment": "...",
  "plans": [ { "style": "进攻型", "portfolio_name": "...", "allocations": [...] } ],
  "comparison_table": { "进攻型": {...}, "平衡型": {...}, "防御型": {...} },
  "indices": [...],
  "commodities": [...],
  "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
}
```

详见 `portfolio/design.md`。

---

## 7. Portfolio Review / 组合检视

```
POST /api/v1/analysis/portfolio-review
```

**请求体 / Request Body:**

```json
{
  "portfolio_type": "平衡型",
  "last_rebalance_date": "2026-04-10",
  "current_portfolio_holdings": [ { "ticker": "510300.SH", "name": "...", "weight_pct": 25.0 } ],
  "new_market_snapshot": { "macro": {...}, "style_factor_zscore": {...}, "risk_indicators": {...} },
  "risk_budget": { "max_single_etf_weight_pct": 30.0 },
  "type_thresholds": { "进攻型": {...}, "防御型": {...}, "平衡型": {...} },
  "meta_context": { "days_since_rebalance": 93 }
}
```

**成功响应 / `200 OK`:**

```json
{
  "action": "REBALANCE | HOLD",
  "trigger_rule_id": "TR_DEV_EXCEED",
  "signals": [ { "signal_id": "S1", "source": "...", "direction": "...", "strength": "...", "horizon": "...", "affected_tickers": [...] } ],
  "hold_reason": "仅 HOLD 时",
  "sell": [ { "ticker": "...", "target_weight_pct": 15.0, "reason": "..." } ],
  "buy": [ { "ticker": "...", "target_weight_pct": 10.0, "reason": "..." } ],
  "post_check": { "compliance_table": [...] },
  "thresholds_used": { "进攻型": {...} },
  "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
}
```

---

## 8. Sector Analysis / 行业分析

```
POST /api/v1/analysis/sector-analysis
```

**请求体 / Request Body:**

```json
{ "sector_code": "881001", "sector_type": "industry", "sector_name": "银行" }
```

**成功响应 / `200 OK`:** `{ "analysis": "行业深度分析...", "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负" }`

---

## 9. Symbol Analysis / 个股分析

```
POST /api/v1/analysis/symbol-analysis
```

**请求体 / Request Body:**

```json
{ "symbol": "600519", "name": "贵州茅台", "asset_type": "A" }
```

**成功响应 / `200 OK`:** `{ "analysis": "个股/ETF 深度分析...", "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负" }`

---

## 10. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | 参数校验失败 |
| 502 | Bad Gateway | LLM API 调用失败（含重试耗尽） |
| 500 | Internal Server Error | 未预期异常 |

---

## 11. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 8 个端点路由与契约一致 | ☐ | ☐ | method + path |
| 请求体字段名/类型一致 | ☐ | ☐ | |
| 响应体字段结构一致 | ☐ | ☐ | |
| 所有端点 LLM 超时/失败优雅降级 | ☐ | ☐ | AgentRuntime 重试 + fallback |
| 错误码 400/502/500 处理 | ☐ | N/A | 前端 toast |
| 加载态 | ☐ | N/A | spinner |
| 空态 | ☐ | N/A | no-data |
| 错误态 | ☐ | N/A | error toast |
| 新增 agent 仅需 registry 配置 + prompt 文件 | N/A | ☐ | 架构约束 |
| 所有 AI 响应包含 disclaimer 字段 | ☐ | ☐ | "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负" |
| 前端在 AI 输出下方显示免责声明 | ☐ | N/A | |
