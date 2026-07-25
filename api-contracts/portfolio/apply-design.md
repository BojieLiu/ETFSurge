# Apply Portfolio Design / 应用组合设计方案

## 1. 概述 / Overview

**功能描述 / Description**: 将组合设计（三套方案中选择的一套）应用到当前持仓——更新现有 ETF 权重、添加新 ETF。

**触发场景 / Trigger**: 用户在 DashboardAiTools 中查看设计方案后点击"应用此方案"。

---

## 2. 端点定义 / Endpoint

```
POST /api/v1/portfolio/apply-design
```

### 请求体 / Request Body

```json
{
  "portfolio_type": "on_exchange",
  "symbols": ["510300", "510050", "159915"],
  "weights": {
    "510300": 0.4,
    "510050": 0.3,
    "159915": 0.3
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| portfolio_type | string | No | `"on_exchange"` | `on_exchange` \| `off_exchange` |
| symbols | array of string | Yes | — | 要应用的目标 ETF 代码列表 |
| weights | object | No | `{}` | symbol → 目标权重（小数，如 0.4 = 40%），缺失的 symbol 默认 0.1 |

> **注意**: `design` 入参是 `dict` 类型（非 Pydantic 模型），无自动校验。后端对权重做 `max(0, min(0.5, w))` 限幅。

### 成功响应 / Success Response — `200 OK`

```json
{
  "symbols": [
    {
      "symbol": "510300",
      "name": "沪深300ETF",
      "target_weight": 0.4,
      "portfolio_type": "on_exchange"
    },
    {
      "symbol": "510050",
      "name": "上证50ETF",
      "target_weight": 0.3,
      "portfolio_type": "on_exchange"
    }
  ],
  "applied": [
    {
      "symbol": "510300",
      "name": "沪深300ETF",
      "target_weight": 0.4,
      "portfolio_type": "on_exchange",
      "action": "updated"
    },
    {
      "symbol": "159915",
      "name": "159915 ETF",
      "target_weight": 0.3,
      "portfolio_type": "on_exchange",
      "action": "added"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| symbols | array | 应用后所有活跃持仓列表 |
| symbols[].symbol | string | ETF 代码 |
| symbols[].name | string | ETF 名称（新加的默认 `"{symbol} ETF"`） |
| symbols[].target_weight | float | 目标权重（小数） |
| symbols[].portfolio_type | string | 组合类型 |
| applied | array | 每个符号的执行结果 |
| applied[].action | string | `"updated"`（已有 ETF 调权）\| `"added"`（新创建） |

### 错误响应 / Error Response

| Code | Meaning | When |
|------|---------|------|
| 500 | Internal Server Error | DB commit 失败或未捕获异常 |

---

## 3. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 请求体中 `symbols` + `weights` 正确传递 | ☐ | ✅ | DashboardAiTools.vue:622 传入完整 plan 对象 |
| 新 ETF 自动创建（`action: "added"`） | ☐ | ✅ | 后端自动创建 PortfolioETF 记录 |
| 已有 ETF 权重更新（`action: "updated"`） | ☐ | ✅ | 后端查 symbol 更新 target_weight |
| 权重限幅 0~0.5 | ☐ | ✅ | `max(0, min(0.5, w))` |
| 成功时前端弹出 toast | ✅ | ☐ | |
| 失败时前端弹出错误 toast | ✅ | ☐ | |
