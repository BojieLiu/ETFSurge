# Portfolio Allocation Calculation / 投资组合配置计算

## 1. 概述 / Overview

根据当前持仓的 `target_weight` 和总资金，计算每只 ETF 的目标金额、预估份额，并获取实时价格和涨跌幅。

Calculate target amounts, estimated shares, and real-time prices for each ETF based on target weights and total capital.

---

## 2. 端点定义 / Endpoint

```
POST /api/v1/portfolio/calculate
```

### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| portfolio_type | string | No | — | Filter: `on_exchange` \| `off_exchange` |

### 请求体 / Request Body

```json
{
  "total_capital": 1000000.00
}
```

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "total_capital": { "type": "number", "description": "Total investable capital in CNY", "minimum": 0 }
  },
  "required": ["total_capital"]
}
```

---

## 3. 响应定义 / Response

### 成功响应 / Success Response — `200 OK`

```json
{
  "total_capital": 1000000.00,
  "allocations": [
    {
      "symbol": "159338",
      "name": "国泰中证A500ETF",
      "short_name": "国泰A500ETF",
      "asset_type": "A",
      "portfolio_type": "on_exchange",
      "target_weight": 0.26,
      "target_amount": 260000.00,
      "current_price": 0.925,
      "change_pct": 0.54,
      "shares": 281081.08,
      "tracked_index": null
    }
  ],
  "cash_weight": 0.04,
  "cash_amount": 40000.00
}
```

**字段说明 / Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| total_capital | float | Input total capital |
| allocations | array | Per-ETF allocation details |
| allocations[].target_amount | float | `total_capital * target_weight / weight_sum` |
| allocations[].current_price | float | Real-time price (0 if unavailable) |
| allocations[].change_pct | float | Real-time change % (0 if unavailable) |
| allocations[].shares | float | `target_amount / current_price` |
| cash_weight | float | Remaining weight after summing all ETF weights |
| cash_amount | float | `total_capital * cash_weight` |

---

## 4. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | Missing `total_capital` |
| 500 | Internal Server Error | Price fetch failure |

---

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `POST /calculate` returns 200 | ☐ | ☐ | |
| `allocations` array handles empty (no ETFs) | ☐ | ☐ | |
| `current_price` = 0 handled gracefully | ☐ | ☐ | Shows "—" or "N/A" |
| `portfolio_type` filter works | ☐ | ☐ | |
| Total weights normalized | ☐ | ☐ | Each alloc = capital * weight / sum(weights) |
| Loading skeleton | ☐ | N/A | |
| Error state on 5xx | ☐ | N/A | |
