# Daily P&L / 每日盈亏计算

## 1. 概述 / Overview

根据持仓的目标金额和实时涨跌幅，计算每只 ETF 的当日盈亏和汇总数据。

Calculate daily profit/loss for each ETF and aggregated figures based on target amounts and real-time price changes.

---

## 2. 端点定义 / Endpoint

```
POST /api/v1/portfolio/daily-pnl
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

---

## 3. 响应定义 / Response

### 成功响应 / Success Response — `200 OK`

```json
{
  "items": [
    {
      "symbol": "159338",
      "name": "国泰中证A500ETF",
      "short_name": "国泰A500ETF",
      "asset_type": "A",
      "portfolio_type": "on_exchange",
      "target_amount": 260000.00,
      "current_price": 0.925,
      "change_pct": 0.54,
      "daily_pnl": 1404.00,
      "tracked_index": null,
      "is_estimated": false,
      "estimate_source": null,
      "shares_outstanding": 5200000000,
      "fund_scale": 4810000000,
      "pe_ttm": 12.5,
      "pb": 1.3,
      "main_net_inflow": 12500000,
      "main_net_inflow_pct": 4.7
    }
  ],
  "total_pnl": 3200.50,
  "total_amount": 960000.00,
  "weighted_change_pct": 0.33
}
```

**字段说明 / Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| items | array | Per-ETF P&L details |
| items[].daily_pnl | float \| null | `target_amount * change_pct / 100`; **R175 (round52 §7.3 方案C)**: `null` = 行情暂不可用（不计入汇总，不冒充盈亏 0） |
| items[].is_estimated | bool | Off-exchange fund price estimated via tracked index |
| items[].estimate_source | string \| null | `tracked_index` \| `unavailable` \| `null` — **R175**: 涨跌源缺失时标 `unavailable` |
| items[].shares_outstanding | float \| null | Latest total shares outstanding |
| items[].fund_scale | float \| null | Latest fund AUM in CNY |
| items[].pe_ttm | float \| null | TTM P/E ratio |
| items[].pb | float \| null | P/B ratio |
| items[].main_net_inflow | float \| null | Main force net inflow (CNY) |
| items[].main_net_inflow_pct | float \| null | Main force net inflow % |
| total_pnl | float | Sum of all `daily_pnl` values |
| total_amount | float | Sum of all `target_amount` values |
| weighted_change_pct | float | `sum(target_amount * change_pct) / total_amount` |

### Off-Exchange / 场外基金特殊处理

For off-exchange funds with `tracked_index`, the `change_pct` is taken from the tracked index instead of the fund itself, because off-exchange fund NAVs follow their underlying index.

场外联接基金的涨跌幅使用其跟踪指数的涨跌幅作为预估，因为联接基金净值跟随标的指数。

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
| `POST /daily-pnl` returns 200 | ☐ | ☐ | |
| Per-ETF `daily_pnl` calculated correctly | ☐ | ☐ | `amount * change% / 100` |
| Off-exchange uses tracked index change% | ☐ | ☐ | |
| Empty state (no ETFs) | ☐ | ☐ | Returns empty `items` array |
| Negative P&L displays correctly (red) | ☐ | N/A | |
| Positive P&L displays correctly (green) | ☐ | N/A | |
| Loading skeleton | ☐ | N/A | |
