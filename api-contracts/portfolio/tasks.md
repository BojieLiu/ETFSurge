# Task & Async Operation API Contract / 任务与异步操作

## 1. 概述 / Overview

**功能描述**: 异步任务的生命周期管理。耗时操作（组合设计、策略检查）通过异步任务启动，客户端轮询任务状态获取结果。

**触发场景**: 
- 前端点击"生成组合方案" → `POST /api/v1/portfolio/design-async`
- 前端点击"策略检查" → `POST /api/v1/portfolio/strategy-check-async`
- 前端查看任务面板 → `GET /api/v1/portfolio/tasks`

---

## 2. 端点定义 / Endpoints

### 2.1 异步组合设计 / Async Portfolio Design

```
POST /api/v1/portfolio/design-async
```

**请求体 / Request Body:**

```json
{
  "portfolio_type": "on_exchange",
  "total_capital": 500000,
  "risk_profile": "balanced"
}
```

**字段说明:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| portfolio_type | string | No | "on_exchange" | `on_exchange` \| `off_exchange` |
| total_capital | number | No | 500000 | 总资本（CNY） |
| risk_profile | string | No | "balanced" | `balanced` \| `defensive` \| `aggressive` |

**成功响应 `200 OK`:**

```json
{
  "task_id": 39,
  "status": "pending"
}
```

---

### 2.2 异步策略检查 / Async Strategy Check

```
POST /api/v1/portfolio/strategy-check-async
```

**请求体 / Request Body:**

```json
{
  "portfolio_type": "on_exchange",
  "total_capital": 500000
}
```

**字段说明:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| portfolio_type | string | No | None | `on_exchange` \| `off_exchange` \| None(全部) |
| total_capital | number | No | 500000 | 总资本 |

**成功响应 `200 OK`:**

```json
{
  "task_id": 40,
  "status": "pending"
}
```

---

### 2.3 任务列表 / List Tasks

```
GET /api/v1/portfolio/tasks
```

**查询参数 / Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | integer | No | 20 | 每页条数 |
| offset | integer | No | 0 | 偏移量（用于分页） |

**成功响应 `200 OK`:**

```json
[
  {
    "task_id": 39,
    "type": "design",
    "status": "completed",
    "progress": 100,
    "stage": "设计方案生成完成",
    "params": {
      "capital": 500000,
      "portfolio_type": "on_exchange"
    },
    "result": { "...": "设计结果，与 GET /designs/{id} 一致" },
    "error_message": null,
    "created_at": "2026-07-25T16:00:00Z",
    "completed_at": "2026-07-25T16:04:32Z",
    "record_id": 222
  }
]
```

**字段说明:**

| Field | Type | Description |
|-------|------|-------------|
| task_id | integer | **任务唯一标识**（前端读取此字段，不是 `id`） |
| type | string | `design` \| `check` \| `report` |
| status | string | `pending` \| `running` \| `completed` \| `failed` \| `cancelled` |
| progress | integer | 0-100 进度百分比 |
| stage | string | 当前阶段描述（如 "数据采集与因子计算"） |
| params | object | 任务创建时传入的参数 |
| result | object | 任务结果（仅 completed 时有；与对应实体一致） |
| error_message | string | 错误信息（仅 failed 时有） |
| created_at | string | ISO 8601 创建时间 |
| completed_at | string | ISO 8601 完成时间 |
| record_id | integer | 关联的 DB 记录 ID（design: design ID; check: check ID） |

---

### 2.4 任务详情 / Get Task

```
GET /api/v1/portfolio/tasks/{task_id}
```

**成功响应 `200 OK`:**

```json
{
  "task_id": 39,
  "type": "design",
  "status": "running",
  "progress": 50,
  "stage": "因子评分计算中",
  "params": { "capital": 500000, "portfolio_type": "on_exchange" },
  "result": null,
  "error_message": null,
  "created_at": "2026-07-25T16:00:00Z",
  "completed_at": null,
  "record_id": null
}
```

**失败响应 `404 Not Found`:**

```json
{
  "detail": "Task not found"
}
```

---

### 2.5 设计方案列表 / List Designs

```
GET /api/v1/portfolio/designs
```

**查询参数 / Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | integer | No | 10 | 最大返回数 |

**成功响应 `200 OK`:**

```json
[
  {
    "id": 222,
    "created_at": "2026-07-25T16:35:15.681614",
    "capital": 500000.0,
    "risk_profile": "balanced",
    "status": "completed",
    "error_message": null
  }
]
```

**字段说明:**

| Field | Type | Description |
|-------|------|-------------|
| id | integer | 设计记录 ID |
| created_at | string | ISO 8601 创建时间 |
| capital | float | 总资本 |
| risk_profile | string | `balanced` \| `defensive` \| `aggressive` |
| status | string | `pending` \| `running` \| `completed` \| `failed` |
| error_message | string/null | 错误信息 |

---

### 2.6 设计详情 / Get Design Detail

```
GET /api/v1/portfolio/designs/{id}
```

**成功响应 `200 OK`:**

```json
{
  "id": 222,
  "status": "completed",
  "strategies": [
    {
      "profile_name": "保守防御型",
      "risk_profile": "defensive",
      "positioning": "低波稳健，高比例固收打底",
      "etfs": [
        {
          "symbol": "511520",
          "name": "30年国债ETF",
          "weight": 0.30,
          "selection_rationale": "久期匹配+避险需求",
          "factor_score": 0.85
        }
      ]
    }
  ],
  "market_context": {
    "regime": "range_bound",
    "sentiment": "neutral",
    "index_closes": { "sz50": 2500.0 }
  },
  "created_at": "2026-07-25T16:35:15.681614",
  "capital": 500000.0,
  "risk_profile": "balanced"
}
```

**策略字段说明:**

| Field | Type | Description |
|-------|------|-------------|
| profile_name | string | 方案名称（如"保守防御型"） |
| risk_profile | string | `defensive` \| `balanced` \| `aggressive` |
| positioning | string | 策略定位文字描述 |
| etfs[].symbol | string | ETF 代码 |
| etfs[].name | string | ETF 名称 |
| etfs[].weight | float | 目标权重（小数，0.30 = 30%） |
| etfs[].selection_rationale | string | 入选理由 |
| etfs[].factor_score | float | 综合因子评分（0-1） |

---

### 2.7 策略检查列表 / List Strategy Checks

```
GET /api/v1/portfolio/strategy-checks
```

**查询参数 / Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | integer | No | 10 | 最大返回数 |

**成功响应 `200 OK`:**

```json
[
  {
    "id": 97,
    "created_at": "2026-07-25T16:34:19.537075",
    "capital": 500000.0,
    "summary": "组合持仓分析摘要",
    "market_regime": "range_bound",
    "suggestions": [],
    "holdings_analysis": [],
    "risk_warnings": [],
    "type": "check"
  }
]
```

---

### 2.8 策略检查详情 / Get Strategy Check Detail

```
GET /api/v1/portfolio/strategy-checks/{id}
```

**成功响应 `200 OK`:**

```json
{
  "id": 97,
  "summary": "组合分析摘要",
  "market_regime": "range_bound",
  "suggestions": [
    {
      "action": "decrease",
      "symbol": "159338",
      "name": "中证A500ETF",
      "current_weight": 0.26,
      "suggested_weight": 0.20,
      "reason": "权重超 20% 建议回归均值",
      "confidence": "high"
    }
  ],
  "holdings_analysis": [
    {
      "symbol": "510300",
      "name": "沪深300ETF",
      "factor_summary": "趋势动量+0.8，估值动量+0.3，流动性充足",
      "tech_signal": "MACD金叉，RSI中性偏强(58)",
      "risk_flag": null
    }
  ],
  "risk_warnings": [
    {
      "type": "concentration",
      "severity": "high",
      "description": "行业集中度偏高",
      "affected_symbols": ["512480", "561300"]
    }
  ]
}
```

---

## 3. 关键约束 / Key Constraints

1. **字段命名一致性**: 任务列表接口使用 `task_id`（**不是 `id`**），设计方案和检查记录使用 `id`
2. **权重小数制**: 所有 `weight` 字段为小数（0.30 = 30%），不归一化
3. **ISO 8601**: 所有时间字段为 UTC ISO 8601 格式
4. **portfolio_type**: 不传 = 全部持仓；"on_exchange" = 场内；"off_exchange" = 场外

---

## Frontend-Backend Checklist

- [ ] 后端 `GET /api/v1/portfolio/tasks` 返回 `task_id` 字段（非 `id`）
- [ ] 前端读取 `rt.task_id` 作为任务唯一标识
- [ ] 前端显示任务时：pending(等待中) / running(运行中) / completed(已完成) / failed(失败)
- [ ] 前端显示进度百分比 `progress` 字段
- [ ] 前端显示阶段描述 `stage` 字段
- [ ] 设计列表 `GET /designs` 返回清单字段（id, status, created_at, risk_profile）
- [ ] 设计详情 `GET /designs/{id}` 包含 `strategies` 列表
- [ ] 每个策略含 `profile_name`, `risk_profile`, `positioning`, `etfs[]`
- [ ] 每个 ETF 含 `symbol`, `name`, `weight`(小数), `selection_rationale`
- [ ] 策略检查列表 `GET /strategy-checks` 含 summary/regime
- [ ] 策略检查详情 `GET /strategy-checks/{id}` 含 `suggestions[]` / `holdings_analysis[]` / `risk_warnings[]`
- [ ] 异步启动端点 POST 返回 `task_id`
