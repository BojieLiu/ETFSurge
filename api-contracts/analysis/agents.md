# Analysis — LLM Agent Chains / AI 分析 Agent 链路

## 0. 架构说明 / Architecture Note

所有分析端点后端均由**统一的 Agent 运行时**驱动。每条分析链路 = 一条 `AgentConfig`
配置（系统提示词文件 + 模型 + 温度 + 响应格式），由 `analysis/runtime.py` 的
`AgentRuntime` 统一执行（含重试、降级、token 记账）。

Agent 配置集中在 `analysis/registry.py` 的 `AGENTS` 字典中；系统提示词存放在
`analysis/prompts/v1/*.md`（版本化、可热更新，无需改代码即可迭代 prompt）。

> round11（2026-08-09）清理：非 stream 版 `/llm-report`、`/llm-advice`、
> `/llm-news-analysis`、`/portfolio-review`、`/portfolio-design` 已删除，
> 前端只使用 stream 版（SSE）。本表以**实际存在**的路由为准。

## 1. 端点一览 / Endpoint Overview

| Method | Path | Agent Key | Description |
|--------|------|-----------|-------------|
| POST | `/api/v1/analysis/llm-report/stream` | market_report | 市场研判报告（SSE 流式） |
| POST | `/api/v1/analysis/llm-advice/stream` | advice | 投资建议（SSE 流式，带市场上下文注入） |
| POST | `/api/v1/analysis/news-impact` | news_impact | 单条新闻对组合的影响 |
| POST | `/api/v1/analysis/sector-analysis/stream` | sector_analysis | 行业/概念板块分析（SSE 流式） |
| POST | `/api/v1/analysis/symbol-analysis/stream` | symbol_analysis | 个股/ETF/指数分析（SSE 流式） |

> `strategy_suggestions` 无独立 HTTP 端点，由 `portfolio_service.calculate_daily_pnl`
> 内部调用，经 `POST /api/v1/portfolio/strategy-check-async` 暴露。

---

## 2. LLM Report Stream / 市场研判报告（SSE）

```
POST /api/v1/analysis/llm-report/stream
```

**请求体 / Request Body:**

```json
{ "symbols": ["510050", "510880"], "market": "A" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbols | array of string | No | 指定标的；缺省则分析主要指数/期货 |
| market | string | No | A/HK/US/global，用于过滤指数与商品（默认 A） |

**成功响应 / `200 OK`:** `text/event-stream`，事件携带 LLM token 增量；
结束时输出完整报告与 `disclaimer`。

**内容契约（round10 P3-A）**：报告应包含真实指数数据（如「上证指数 …」或
「市场状态: …」），不得退化为「暂无实时指数数据」模板。

---

## 3. LLM Advice Stream / 投资建议（SSE）

```
POST /api/v1/analysis/llm-advice/stream
```

**请求体 / Request Body:**

```json
{ "query": "当前A股市场怎么配置", "market": "A" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| query | string | Yes | 自然语言问题 |
| market | string | No | 市场维度（A/HK/US），决定注入的指数/板块数据 |

**上下文注入（round10 P0-A 修复后）**：router 注入**全部引擎消费槽位**——
`market_data`（结构化指数列表）、`market_regime`、`market_sentiment`、
`hot_plates`、`sector_heat`、`market_snapshot`（字符串槽）。任一槽为空时
引擎才输出显式降级文案（「暂无实时指数数据」仅当注入为空时出现）。

**成功响应 / `200 OK`:** `text/event-stream`，流式返回 `advice` 文本 +
`disclaimer`。

---

## 4. News Impact / 单条新闻影响

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

> **v2.0 (F2-9)**: prompt 含硬约束「若新闻与组合内标的无直接关联，须明确回答『无直接影响』，
> 禁止强行关联；只列出实际受影响的标的，宁缺毋滥」。`affected_holdings` 允许为空数组（无直接关联时）。

---

## 5. Sector Analysis Stream / 行业板块分析（SSE）

```
POST /api/v1/analysis/sector-analysis/stream
```

**请求体 / Request Body:**

```json
{ "sector_code": "881001", "sector_type": "industry", "sector_name": "银行" }
```

**成功响应 / `200 OK`:** `text/event-stream`，最终事件含
`{ "analysis": "行业深度分析...", "disclaimer": "..." }`。

---

## 6. Symbol Analysis Stream / 个股分析（SSE）

```
POST /api/v1/analysis/symbol-analysis/stream
```

**请求体 / Request Body:**

```json
{ "symbol": "600519", "name": "贵州茅台", "asset_type": "A", "market": "A" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | string | Yes | 代码（510300 / 00700 / AAPL / 000300） |
| market | string | Yes | A / HK / US |
| asset_type | string | No | etf / stock / index / HK_etf（round10 P2-O：港股 ETF 识别） |

**成功响应 / `200 OK`:** `text/event-stream`，最终出文
`{ "analysis": "个股/ETF 深度分析...", "disclaimer": "..." }`。

---

## 6.1 SSE 事件协议 / SSE Event Protocol（R49 新增 progress）

所有 `* /stream` 端点返回 `text/event-stream`，`_sse_stream`（routers/analysis.py）
按 `event:` / `data:` 帧推送，前端 `useLLMStream.js` 按事件类型消费。

| event | data 字段 | 说明 |
|-------|-----------|------|
| `progress` | `phase`: `calling_model`；`message`: 进度文案 | R49：首字节（first_byte 34-78s）前必发的可见进度，前端据此渲染进度条（不可静默丢弃）。`phase=calling_model`（正在调用模型） |
| `token` | `token`: 增量文本 | LLM 流式增量；首个 `token` 到达后前端清除 progress 条 |
| `done` | `full_text`, `metadata`, `disclaimer`, `cached?` | 结束帧；`cached=true` 表示命中交易日内结果缓存（秒级返回），否则为 LLM 实时生成 |
| `error` | `code`, `message` | 错误帧（STREAM_ERROR / DATA_UNAVAILABLE / [rate-limited] / [timeout]） |

**缓存（R49 可选优化）**：相同 `(query, data_as_of)` 的二次请求按 prompt 指纹命中
模块级交易日内缓存（TTL 8h），直接回放 `done`（`cached=true`），不调用 LLM。
首字节前的 `progress` 事件契约对所有路径（含缓存命中）保持一致。

**前端四态**：progress（调用中）/ token（流式渲染）/ done（完成+免责声明）/ error（降级文案）。

---

## 7. 错误码 / Error Codes（与 stream 段共用）

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | 参数校验失败 |
| 502 | Bad Gateway | LLM API 调用失败（含重试耗尽） |
| 500 | Internal Server Error | 未预期异常 |

---

## 8. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| stream 端点路由与契约一致 | ☐ | ☐ | method + path |
| SSE 事件格式（event:/data:）一致 | ☐ | ☐ | 前端按事件类型消费 |
| 请求体字段名/类型一致 | ☐ | ☐ | |
| 响应含完整报告 + disclaimer | ☐ | ☐ | stream 尾部事件 |
| LLM 超时/失败优雅降级 | ☐ | ☐ | AgentRuntime 重试 + fallback |
| llm-advice 注入槽与引擎消费槽一致 | ☐ | ☐ | round10 P3-G 契约单测 |
| 错误码 400/502/500 处理 | ☐ | N/A | 前端 toast |
| 加载态 / 空态 / 错误态 | ☐ | N/A | SSE 连接中/无数据/error |
| 首字节前 `progress` 进度条可见（非空白 spinner） | ☐ | ☐ | R49：calling_model 事件 |
| `done.cached=true` 缓存命中路径前端可感知 | ☐ | ☐ | R49：交易日内二次同请求秒级返回 |
| 前端在 AI 输出下方显示免责声明 | ☐ | N/A | |