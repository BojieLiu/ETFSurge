# Design Report WebSocket / 设计报告异步推送

## 1. 概述 / Overview

生成组合方案后，前端通过 WebSocket 连接接收 LLM 润色后的完整报告。方案数据由算法生成，报告由 LLM 异步撰写推送。

---

## 2. 端点 / Endpoint

```
WS /api/v1/ws/design-report/{session_id}
```

`sleep(10)` 参数说明：`session_id` 是 UUID 字符串，由前端在发起设计请求时生成并附加到请求参数中。

---

## 3. 推送消息格式 / Push Message Format

### 3.1 进度更新 (status=generating)

```json
{
  "type": "design_report",
  "session_id": "uuid-string",
  "status": "generating",
  "progress": 30,
  "stage": "数据采集中 | 方案生成中 | 报告撰写中"
}
```

### 3.2 报告片段 (status=streaming)

```json
{
  "type": "design_report",
  "session_id": "uuid-string",
  "status": "streaming",
  "chunk": "基于当前市场数据显示..."
}
```

前端将接收到的 `chunk` 按顺序拼接为完整报告文本。

### 3.3 报告完成 (status=complete)

```json
{
  "type": "design_report",
  "session_id": "uuid-string",
  "status": "complete",
  "report_text": "完整的 Markdown 报告文本..."
}
```

### 3.4 错误 (status=error)

```json
{
  "type": "design_report",
  "session_id": "uuid-string",
  "status": "error",
  "message": "报告生成失败，请重试"
}
```

---

## 4. 数据流 / Data Flow

```
前端 POST /portfolio/design?session_id=xxx   ← 携带 session_id
  → 后端保存方案到数据库
  → 后端立即返回 {strategies, id, ...}
  → 前端显示方案卡片，同时连接 WS /design-report/{session_id}

后端后台任务:
  → 读取 strategies + market_context
  → 调用 LLM (generate_design_report)
  → 通过 WS 推送进度 (30%, 60%, 90%)
  → 通过 WS 推送报告片段 (chunk)
  → 通过 WS 推送完成 (complete)

前端收到 complete:
  → 替换或追加 designResult.design_text
  → marked 渲染为 HTML
  → 用户在"完整报告"tab 看到内容
```

---

## 5. 约束 / Constraints

| 规则 | 说明 |
|------|------|
| WS 连接必须在方案生成后建立 | 方案生成后才有 strategies 数据供 LLM 撰写 |
| 报告是非阻塞的 | 卡片展示不受 WS 连接/推送影响 |
| 超时 | LLM 调用 30s 超时，超时后推送 error |
| 重连 | 前端 WS 断连后自动重连，session_id 保证连续性 |
| 幂等 | 同一个 session_id 重复连接不会触发多次 LLM 调用 |

---

## 6. Frontend-Backend Checklist

- [ ] 后端: `/api/v1/ws/design-report/{session_id}` 可连接
- [ ] 后端: 连接后推送 `type: design_report, status: generating` 进度
- [ ] 后端: 推送 `status: streaming` 包含 `chunk` 字段
- [ ] 后端: 推送 `status: complete` 包含 `report_text` 字段
- [ ] 后端: 超时或出错推送 `status: error` 消息
- [ ] 前端: WS 连接在方案生成后建立
- [ ] 前端: 逐段拼接 `chunk` 为完整报告
- [ ] 前端: 收到 `complete` 后更新 `designResult.design_text`
- [ ] 前端: `designReportHtml` computed 基于新内容重新渲染
- [ ] 前端: 断连后自动重连
