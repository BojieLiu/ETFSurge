# Portfolio Design / 组合设计

> **v3.0 (F3-3)**: `STRATEGY_META.layer_budget` 三档预算和调整为 0.85（防御 45/30/10、平衡 45/30/10、进攻 40/35/10）——`range_bound` 市态方案现金由 22-32% 收紧至 **≤15%**（balanced 方案现金 = 15%）；bear/correction 分支的额外现金保护逻辑不变。

## 1. 概述 / Overview

基于全市场 ETF 扫描 + 三层分类 + 多维度数据（行情/资讯/资金流/情绪），生成三种风险偏好的 ETF 组合方案。

Generate three risk-profile ETF portfolio plans using full-market ETF scanning, 3-layer classification, and multi-dimensional data (market data, news, fund flow, sentiment).

---

## 2. 端点定义 / Endpoints

### 2.1 生成组合设计 / Generate Portfolio Design

```
POST /api/v1/portfolio/design-async（原 /design 已迁移，T11 校准）
```

**请求体 / Request Body:**

```json
{
  "risk_profile": "balanced",
  "capital": 500000,
  "mode": "standard",
  "constraints": {
    "min_names": 8,
    "max_names": 15
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| risk_profile | string | No | `balanced` | `defensive` \| `balanced` \| `aggressive` |
| capital | number | No | 500000 | Total capital in CNY |
| mode | string | No | `standard` | `standard` (含全量数据) \| `fast` (仅候选池默认值) |
| constraints | object | No | - | 可选约束：`min_names`, `max_names`, `min_weight`, `max_weight` |

**成功响应 / Success Response — `200 OK`:**

```json
{
  "strategies": [
    {
      "id": "defensive",
      "label": "防御型",
      "color": "#43A047",
      "portfolio_name": "防御稳健组合",
      "positioning": "低波稳健配置，控制回撤，适合保守风险偏好者",
      "expected_return": 0.08,
      "max_drawdown": -0.12,
      "sharpe_ratio": 1.2,
      "expected_characteristics": "预期年化波动10-12%，最大回撤区间10-12%",
      "layer_budget": {
        "core": 0.55,
        "satellite": 0.25,
        "defense": 0.20
      },
      "etfs": [
        {
          "symbol": "510300",
          "name": "沪深300ETF",
          "layer": "core",
          "weight": 0.18,
          "price": 3.845,
          "change_pct": 0.012,
          "selection_rationale": "沪深300核心指数，稳健配置首选"
        },
        {
          "symbol": "560600",
          "name": "中证A500ETF",
          "layer": "core",
          "weight": 0.15,
          "price": 1.023,
          "change_pct": 0.005,
          "selection_rationale": "A股优质龙头，补足核心层分散度"
        },
        {
          "symbol": "518880",
          "name": "黄金ETF",
          "layer": "defense",
          "weight": 0.10,
          "price": 2.95,
          "change_pct": -0.003,
          "selection_rationale": "黄金防御配置，低相关性资产"
        }
      ]
    }
  ],
  "generated_at": "2026-07-16T15:00:00Z",
  "market_context": {
    "timestamp": "2026-07-16 15:00",
    "indices": [
      {"code": "000001", "name": "上证指数", "price": 3456, "change_pct": 1.2},
      {"code": "399001", "name": "深证成指", "price": 11234, "change_pct": 1.5},
      {"code": "000300", "name": "沪深300", "price": 3845, "change_pct": 1.0}
    ],
    "fund_flow": [
      {"code": "510300", "net_inflow": 120000000, "flow_direction": "inflow"}
    ],
    "valuation_metrics": [
      {"code": "510300", "pe_ttm": 12.5, "pb": 1.8, "valuation_percentile": 0.35}
    ],
    "market_sentiment": {                             ← NEW
      "sentiment_index": 65,
      "sentiment_label": "中性偏乐观",
      "institutional_direction": "净买入",
      "retail_direction": "净卖出",
      "is_divergence": true,
      "north_net_inflow": 12.5
    },
    "benchmark_stocks": [                             ← NEW
      {
        "symbol": "600519",
        "name": "贵州茅台",
        "sector": "消费",
        "change_pct": 0.8,
        "institutional_net_inflow": 0.5,
        "main_net_inflow_pct": 0.12,
        "signal": "机构增配",
        "top_news": ["茅台提价10%"]
      },
      {
        "symbol": "300750",
        "name": "宁德时代",
        "sector": "新能源",
        "change_pct": 2.5,
        "institutional_net_inflow": 3.2,
        "main_net_inflow_pct": 0.28,
        "signal": "机构积极布局",
        "top_news": ["宁德时代Q2财报超预期，营收同比+45%"]
      }
    ]
  }
}
```

### 2.2 基于 LLM 的组合设计（含情绪/指标股数据）

```
```

**请求体同 2.1。**

**成功响应（与 2.1 结构一致，增加 LLM 报告字段）：**

```json
{
  "design_text": "基于实时市场数据生成的组合设计报告...",
  "data_snapshot_time": "2026-07-16 20:28（北京时间）",
  "market_environment": "当前市场情绪偏乐观，机构净买入，散户净卖出...",
  "plans": [...]                                    ← 与 strategies 结构相同
  "comparison_table": {...},
  "market_context": {                               ← NEW: 同上
    "market_sentiment": {...},
    "benchmark_stocks": [...]
  }
}
```

### 2.3 异步任务提交 / Submit Async Design Task

```
POST /api/v1/portfolio/design-async（async 语义内建）
```

**请求体同 2.1。**

**成功响应 — `202 Accepted`:**

```json
{
  "task_id": "uuid-string",
  "status": "pending",
  "created_at": "2026-07-17T15:00:00Z"
}
```

### 2.4 查询任务状态 / Get Task Status

```
GET /api/v1/portfolio/tasks/{task_id}
```

**成功响应 — `200 OK`:**

```json
{
  "task_id": "uuid-string",
  "status": "running",
  "progress": 45,
  "design_id": null,
  "error_message": null,
  "created_at": "2026-07-17T15:00:00Z",
  "completed_at": null
}
```

**status 取值:** `pending` / `running` / `completed` / `failed`

### 2.5 任务列表 / List Tasks

```
GET /api/v1/portfolio/tasks?limit=10&offset=0
```

**成功响应 — `200 OK`:**

```json
[
  {
    "task_id": "uuid-1",
    "status": "completed",
    "progress": 100,
    "design_id": 1,
    "created_at": "...",
    "completed_at": "..."
  },
  {
    "task_id": "uuid-2",
    "status": "running",
    "progress": 60,
    "design_id": null,
    "created_at": "...",
    "completed_at": null
  }
]
```

### 2.6 WebSocket 异步任务通知

```
WS /api/v1/ws/task-notifications
```

**服务端推送消息格式：**

```json
{
  "type": "task_update",
  "task_id": "uuid-string",
  "status": "completed",
  "progress": 100,
  "design_id": 1
}
```

status 变化时推送一次，前端不需要轮询。

### 2.7 WebSocket 异步报告推送

```
WS /api/v1/ws/design-report/{session_id}
```

**服务端推送消息格式：**

```json
{
  "type": "design_report",
  "session_id": "uuid",
  "status": "generating",
  "progress": 75,
  "report": "部分或完整的 Markdown 报告文本"
}
```

### 2.8 前端报告 Tab 行为（无硬编码 fallback）

**原则：** 前端 **不允许** 在 `design_text` 为空时硬编码生成假报告。LLM 报告唯一来源是 WS 推送。

**状态机：**

```
结果页加载 → design_text="" 且 reportError=""
                ↓
报告 Tab 显示：「⏳ AI 报告生成中…」
                ↓
WS 推送 streaming chunks → 逐步显示
                ↓ 完成                     ↓ 失败/超时
        ✅ 完整 Markdown 报告        ❌ 报告生成失败 + 重试按钮
```

| 状态 | 触发条件 | 前端展示 |
|------|---------|---------|
| `waiting` | `design_text=""` 且 `reportError=""` | ⏳ AI 报告生成中... |
| `streaming` | WS 推送 `status: "streaming"` chunks | 逐步渲染 Markdown |
| `complete` | WS 推送 `status: "complete"` + `report_text` | 完整 Markdown 报告 |
| `error` | WS 推送 `status: "error"` | ❌ 错误信息 + 重试按钮 |

**方案卡片 Tab 始终可用**（不依赖 LLM 报告）。

---

### 2.10 设计方案列表 / List Design History

```
GET /api/v1/portfolio/designs?limit=10&offset=0
```

**成功响应 — `200 OK`:**

```json
[
  {
    "id": 1,
    "created_at": "2026-07-23T16:55:23.998973",
    "capital": 500000.0,
    "risk_profile": "balanced",
    "status": "completed",
    "error_message": null
  },
  {
    "id": 2,
    "created_at": "2026-07-23T16:55:23.998973",
    "capital": 500000.0,
    "risk_profile": "balanced",
    "status": "failed",
    "error_message": "无候选标的: 数据管道未能生成候选池，请检查数据源连接或稍后重试"
  }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 方案 ID |
| `created_at` | string | ISO 格式创建时间 |
| `capital` | float | 设计本金 |
| `risk_profile` | string | 风险偏好，默认 "balanced" |
| `status` | string | `completed` 或 `failed` |
| `error_message` | string or null | 失败时的详细错误信息，成功时为 null |

**注意：** 列表接口仅返回元数据字段，`strategies_json` 和 `market_snapshot_json` 等大字段由详情接口 `GET /portfolio/designs/{id}` 返回。

---

### 2.9 设计方案状态 / Design Status

```
GET /api/v1/portfolio/designs/{design_id}（原 /status 端点已移除，T11 校准）
```

**成功响应 — `200 OK`:**

```json
{
  "design_id": 70,
  "alive": true,
  "status": "running",
  "design_text": null,
  "created_at": "2026-07-19T03:29:57",
  "progress": null
}
```

**status 取值:**
| 值 | alive | 条件 |
|------|-------|------|
| `running` | true | created_at < 300s 前 且 design_text 为空 |
| `completed` | false | design_text 非空 |
| `failed` | false | created_at > 300s 前 且 design_text 为空 |
| `not_found` | false | 设计 ID 不存在于数据库 |

---

## 3. 数据流程 / Data Flow

```
全量 ETF 扫描 (fund_etf_spot_em, ~5s)
  → 硬性过滤 (AUM>1亿, 成交额>1000万)
  → 三层自动分类 (核心/卫星/防御)
  → 层内评分排序 (核心&防御: 流动性优先; 卫星: 两轮递进)
  → 市场指标股追踪 (10固定+3~5动态)
  → 市场情绪指数 (涨跌比+资金流+北向+两融)
  → LLM 精选 + 分配权重 (一次调用, ~5s)
  → 算法校验 + 约束修复
  → 异步 LLM 报告推送 (WS)
```

---

## 4. 约束规则 / Constraints

| 规则 | 值 | 执行方 |
|------|-----|--------|
| 三层结构 | 核心+卫星+防御，每层至少 1 只 | 算法校验层 |
| 核心层必备 | 510300(沪深300)+560600(中证A500)，各≥5% | 算法校验层 |
| 权重范围 | 每只 1%~30% | 算法校验层 |
| 标的数量 | 8~15 只 | 算法校验层 |
| 层预算(防御) | 核心55% 卫星25% 防御20% | 算法校验层(建议值) |
| 层预算(平衡) | 核心55% 卫星30% 防御15% | 算法校验层(建议值) |
| 层预算(进攻) | 核心50% 卫星40% 防御10% | 算法校验层(建议值) |
| 代码有效性 | 所有 symbol 必须在全量 ETF 列表中 | 算法校验层 |

---

## 5. Frontend-Backend Checklist

- [ ] Request: `POST /portfolio/design` 调用正常
- [ ] Response: `strategies` 数组包含 `defensive/b
alanced/aggressive`
- [ ] Response: `market_context.market_sentiment` 含情绪指数
- [ ] Response: `market_context.benchmark_stocks` 含指标股列表
- [ ] Response: 每个 ETF 的 `symbol` 是真实代码
- [ ] Response: 权重加总为 100%
- [ ] Response: 核心层含 510300/560600
- [ ] Response: 权重在 1%~30% 区间
- [ ] Response: 标的数量在 8~15 之间
- [ ] WS: `/api/v1/ws/design-report/{session_id}` 可连接
- [ ] WS: 推送的 design_report 包含完整 Markdown
- [ ] `GET /api/v1/portfolio/designs/{id}（原 /status 已移除，T11 校准）` implemented and tested
