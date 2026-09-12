# LLM Report Follow-up / 综合研判追问 (llm-report/stream)

> A 端：`POST /api/v1/analysis/llm-report/stream` 扩展追问。复用 `ChatSessionStore`
>（LRU100 / TTL30min / SQLite24h / 历史10轮+8K截断），模式照抄 `llm-chat-session.md`
>（advice 多轮）。差异仅一处：本会话市场快照**会话内冻结**（首轮冻结，追问不重采），
> 而 advice 是 60s 复用后重采。

## 1. 概述 / Overview

**功能描述 / Description**: 首报生成后，用户可就报告内容追问（为什么判震荡/哪几个板块背离/风险点展开）。
请求携带可选 `query` + `session_id`；`done.metadata` 返回本轮生效 `session_id`。

**触发场景 / Trigger**: MarketReport 组件首报完成后追问；“基于最新数据重判”= 丢 session 走首报。

---

## 2. 端点定义 / Endpoint

```
POST /api/v1/analysis/llm-report/stream   （既有端点扩展，SSE 不变）
```

### 请求体 / Request Body

```json
{
  "symbols": null,
  "market": "A",
  "query": "为什么判震荡？",
  "session_id": "sess-abc123"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| symbols | array \| null | 否 | 既有语义不变 |
| market | string | 否 | 默认 `"A"`；追问跨 market 自动开新会话 |
| query | string \| null | 否 | 空/缺失=首报生成；非空=追问 |
| session_id | string \| null | 否 | None=新会话；无效/过期自动开新不报错 |

### SSE 事件流 / Event Stream（契约不变，done 扩展 metadata）

| 事件 | data | 变更 |
|---|---|---|
| progress | `{phase, message}` | 不变 |
| token | `{token}` | 不变 |
| done | `{full_text, metadata, disclaimer}` | **metadata 新增 `session_id`** |
| error | `{code, message}` | 不变 |

---

## 3. 会话语义 / Session Semantics

1. **首报**：`query` 空 → 全量 `build_full_context`，冻结 `ctx(indices/regime/sentiment/domestic_macro/as_of)` + 首报摘要进会话；
2. **追问**：命中 → 读冻结快照 + `render_history` 注入，**不重采**（mock 断言 0 调用）；
3. **prompt 槽**：`## 冻结快照（as_of=..）` + `## 对话历史` + `## 本轮问题` + 硬约束“只引用快照内数值，超出声明不得编数”；
4. **隔离**：`session_type=report`，与 advice/symbol 串话则开新；跨 `market` 自动开新；
5. **落库**：done 时 `user + assistant` 入内存 + SQLite upsert（失败不阻塞）；
6. **护栏**：历史 ≤10 轮、token ≤8K、内存 TTL 30min / SQLite 24h、LRU 100。

## Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | POST path 不变 |
| Request body fields match | ☐ | ☐ | query/session_id 可选 |
| done.metadata.session_id 每轮返回 | ☐ | ☐ | 新=新 id，追问=原 id |
| 无效 id 自动开新不报错 | ☐ | ☐ | 回归保护 |
| 冻结期内追问 0 重采 | N/A | ☐ | 单测 mock 断言 |
| 空历史不注入对话槽 | N/A | ☐ | |
| Loading/streaming/done/error 四态 | ☐ | N/A | progress/token/done/error |
