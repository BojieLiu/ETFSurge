# Symbol Analysis Follow-up / 标的分析追问 (symbol-analysis/stream)

> B 端：`POST /api/v1/analysis/symbol-analysis/stream` 扩展追问。复用 `ChatSessionStore`，
> 模式照抄 `llm-chat-session.md`。标的快照**会话内冻结并绑定单一 symbol**；
> 首版不支持双标同会话对比，换标自动开新会话。

## 1. 概述 / Overview

**功能描述 / Description**: 标的首报（AI 解读）后追问（顶背离可信吗/和 XX 比/风险展开）。
`question` 非空 + `session_id` 即追问；`done.metadata` 返回生效 `session_id`。

**触发场景 / Trigger**: AnalysisView “AI 解读”首报后追问；切换标的自动开新会话。

---

## 2. 端点定义 / Endpoint

```
POST /api/v1/analysis/symbol-analysis/stream   （既有端点扩展，SSE 不变）
```

### 请求体 / Request Body

```json
{
  "symbol": "510300",
  "name": "",
  "asset_type": "ETF",
  "market": "A",
  "question": "顶背离可信吗？",
  "session_id": "sess-xyz"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| symbol | string | 是 | 代码 |
| name/asset_type/market/question | — | 否 | 既有语义不变；`question` 空=首报 |
| session_id | string \| null | 否 | None=新会话；无效/过期自动开新不报错 |

### SSE 事件流 / Event Stream

| 事件 | data | 变更 |
|---|---|---|
| progress | `{phase, message}` | 不变 |
| token | `{token}` | 不变 |
| done | `{full_text, metadata, disclaimer}` | **metadata 新增 `session_id`** |
| error | `{code, message}` | 不变（含 DATA_UNAVAILABLE 全空降级） |

---

## 3. 会话语义 / Session Semantics

1. **首报**：无 session → 全量采集（realtime/hist30/indicators/PE_PB/sector_line/news10），冻结标的快照（含 symbol + indicators + hist 尾30 + fundamentals + sector_line + as_of）；
2. **追问**：命中 → 读冻结快照 + 历史，**不重拉 K 线/基本面**；
3. **换标**：同 session 传不同 `symbol` → 自动开新会话返回新 id（不混指标）；
4. **prompt 槽**：`## 冻结标的快照` + `## 对话历史` + `## 本轮问题` + 硬约束只引快照数；
5. **隔离**：`session_type=symbol`；落库/护栏与 report 契约同（10轮/8K/30min/24h/100）。

## Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | POST path 不变 |
| Request body fields match | ☐ | ☐ | session_id 可选 |
| done.metadata.session_id 每轮返回 | ☐ | ☐ | |
| 换标自动开新会话 | ☐ | ☐ | 前端切对话区 |
| 冻结期内追问 0 重拉 | N/A | ☐ | 单测 mock 断言 |
| 四态 UI | ☐ | N/A | progress/token/done/error |
