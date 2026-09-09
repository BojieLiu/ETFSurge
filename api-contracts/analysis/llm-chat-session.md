# LLM 对话多轮会话 / LLM Chat Multi-turn Session (llm-advice/stream)

> R185 批次（round53 §9 拍板：阶段 1+2 一起落地）。
> 会话模型：内存 LRU（100 会话 / TTL 30min）+ SQLite `chat_sessions` 表（24h TTL，
> 启动加载为 L1）；上下文窗口 = 最近 10 轮 + 8K token 截断；本会话市场快照 60s 复用。

## 1. 概述 / Overview

**功能描述 / Description**: `/llm-advice/stream` 支持多轮追问——请求携带可选
`session_id`（None=开新会话），后端把会话历史注入 prompt（`{{ chat_history }}` 槽），
`done` 事件 metadata 返回 `session_id`；前端渲染消息气泡列表并保存 session_id 用于追问。

**触发场景 / Trigger**: AiAdvisor 组件每次提问（首轮无 session_id，追问带）。

---

## 2. 端点定义 / Endpoint

```
POST /api/v1/analysis/llm-advice/stream   （既有端点扩展，SSE 不变）
```

### 请求体 / Request Body

```json
{
  "query": "那换成 510300 呢？",   // string，本轮用户提问
  "market": "A",                  // string，默认 "A"
  "context": null,                // object | null，既有语义不变
  "session_id": "sess-abc123"     // string | null，None=开新会话；追问带上轮返回值
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| query | string | 是 | 本轮用户提问 |
| market | string | 否 | 默认 `"A"`（既有） |
| context | object | 否 | 既有语义不变 |
| session_id | string | 否 | 新增。None=新会话；无效/过期 id 自动开新会话（不报错） |

### SSE 事件流 / Event Stream（契约不变，done 扩展 metadata）

| 事件 | data | 变更 |
|---|---|---|
| progress | `{phase, message}` | 不变 |
| token | `{token}` | 不变 |
| done | `{full_text, metadata, disclaimer}` | **metadata 新增 `session_id`**（本轮实际生效的会话 id） |
| error | `{code, message}` | 不变 |

### done.metadata 示例

```json
{
  "session_id": "sess-9f2c…",
  "prompt_tokens": 0,
  "completion_tokens": 0
}
```

---

## 3. 会话语义 / Session Semantics

1. **新会话**：`session_id` 缺失/为 None/未命中存储 → 生成 `sess-<16hex>`，历史为空；
2. **追问**：命中 → 追加本轮 user 消息，prompt 注入最近 10 轮历史（token ≤8K，超出截最旧轮）；
3. **历史槽**：prompt 中以「## 对话历史」段呈现（`用户: …` / `助手: …` 逐轮），
   当前 query 不重复进历史；
4. **上下文快照复用**：会话内存有 `market_snapshot_ts`，60s 内的追问跳过
   `build_full_context` 重采集（行情/板块快照复用，省 5s+ /轮）；
5. **落库时机**：本轮 done 时把 `user + assistant` 两条消息写入会话（内存 + SQLite upsert）；
6. **护栏**：历史轮数 ≤10、历史 token ≤8K、会话 TTL 30min（内存）/24h（SQLite，
   读取时惰性过期）、LRU 100 会话；
7. **成本/工具白名单**：沿用 v7 现有机制，本契约不新增写操作面。

## 4. 持久化 / Persistence（阶段 2）

SQLite 表 `chat_sessions`（init_db 自动建表）：

| 列 | 类型 | 说明 |
|---|---|---|
| session_id | String(40) PK | 会话 id |
| messages_json | Text | `[{role, content, ts}]` JSON 序列化 |
| created_at / updated_at | DateTime | 时间戳 |

启动时加载未过期（24h 内）会话到内存 LRU；过期行惰性删除。

## Frontend-Backend Checklist

- [ ] 前端 `useLLMStream` start() 透传 body 原样（session_id 在 body 中）
- [ ] 前端 done 处理保存 `metadata.session_id` 到组件 ref
- [ ] 后端 `LLMAdviceRequest.session_id` 可选，None 兼容旧调用方（MarketReport/UnifiedAnalysis 不带 id）
- [ ] done.metadata.session_id 每轮返回（新会话=新 id，追问=原 id）
- [ ] 无效 session_id 自动开新会话不报错（回归保护）
- [ ] prompt 含「## 对话历史」段仅当历史非空
- [ ] 上下文快照 60s 复用（第二次同会话提问不重复 build_full_context）
