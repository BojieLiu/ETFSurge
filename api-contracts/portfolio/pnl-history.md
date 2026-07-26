# Portfolio Cumulative P&L History / 投资组合累计盈亏历史

## 1. 概述 / Overview

获取投资组合的累计盈亏、持仓成本、收益率曲线数据。区别于 `daily-pnl` 仅计算当日涨跌，本接口基于 `avg_cost`、`shares_held` 计算真实持仓盈亏。

Calculate true cumulative P&L based on cost basis and shares held, not just daily price change.

---

## 2. 端点定义 / Endpoint

```
GET /api/v1/portfolio/pnl-history
```

### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| portfolio_type | string | No | — | Filter: `on_exchange` \| `off_exchange` |
| period | string | No | `all` | Time range: `1d` \| `1w` \| `1m` \| `3m` \| `6m` \| `1y` \| `all` |
| total_capital | float | No | — | 总投资本金；为空时仅返回有成本数据的持仓盈亏，不为空时额外返回基于目标权重估算的持仓 |

---

## 3. 响应定义 / Response

### 成功响应 / Success Response — `200 OK`

```json
{
  "summary": {
    "total_cost_basis": 850000.00,
    "total_market_value": 920000.00,
    "total_cumulative_pnl": 70000.00,
    "total_cumulative_pnl_pct": 8.24,
    "annualized_return": 12.5,
    "max_drawdown": -5.3,
    "sharpe_ratio": 1.42,
    "has_cost_basis_data": true
  },
  "holdings": [
    {
      "symbol": "159338",
      "name": "国泰中证A500ETF",
      "short_name": "国泰A500ETF",
      "asset_type": "A",
      "portfolio_type": "on_exchange",
      "shares_held": 280000,
      "avg_cost": 0.928,
      "cost_basis": 259840.00,
      "current_price": 0.985,
      "market_value": 275800.00,
      "cumulative_pnl": 15960.00,
      "cumulative_pnl_pct": 6.14,
      "first_buy_date": "2024-01-15",
      "last_trade_date": "2024-06-20"
    }
  ],
  "daily_series": [
    {
      "date": "2024-06-01",
      "total_market_value": 890000.00,
      "total_cumulative_pnl": 40000.00,
      "total_cumulative_pnl_pct": 4.71
    },
    {
      "date": "2024-06-02",
      "total_market_value": 895000.00,
      "total_cumulative_pnl": 45000.00,
      "total_cumulative_pnl_pct": 5.29
    }
  ]
}
```

### 字段说明 / Field Reference

| Field | Type | Description |
|-------|------|-------------|
| summary.total_cost_basis | float | Sum of all holdings' cost_basis |
| summary.total_market_value | float | Sum of shares_held * current_price |
| summary.total_cumulative_pnl | float | total_market_value - total_cost_basis |
| summary.total_cumulative_pnl_pct | float | (total_cumulative_pnl / total_cost_basis) * 100 |
| summary.annualized_return | float \| null | Annualized return based on holding period |
| summary.max_drawdown | float \| null | Maximum peak-to-trough decline % |
| summary.sharpe_ratio | float \| null | Risk-adjusted return (if period >= 30d) |
| summary.has_cost_basis_data | boolean | true=有成本数据（真实盈亏），false=基于目标分配估算 |
| holdings[].shares_held | float | Number of shares currently held |
| holdings[].avg_cost | float | Weighted average cost per share |
| holdings[].cost_basis | float | shares_held * avg_cost |
| holdings[].current_price | float | Latest real-time price |
| holdings[].market_value | float | shares_held * current_price |
| holdings[].cumulative_pnl | float | market_value - cost_basis |
| holdings[].cumulative_pnl_pct | float | (cumulative_pnl / cost_basis) * 100 |
| daily_series[].date | string | ISO date (YYYY-MM-DD) |
| daily_series[].total_market_value | float | Portfolio value on that date |
| daily_series[].total_cumulative_pnl | float | Cumulative P&L on that date |
| daily_series[].total_cumulative_pnl_pct | float | Cumulative P&L % on that date |

---

## 4. 错误码 / Error Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| 400 | Bad Request | Invalid period parameter |
| 404 | Not Found | No portfolio data (no holdings with cost basis) |

---

## 5. 示例 / Examples

### 请求示例 / Request Example

```
GET /api/v1/portfolio/pnl-history?portfolio_type=on_exchange&period=3m
```

---

## 6. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | GET /api/v1/portfolio/pnl-history |
| Query params match | ☐ | ☐ | portfolio_type, period |
| Response fields match | ☐ | ☐ | summary, holdings[], daily_series[] |
| Error codes handled | ☐ | ☐ | 400, 404 |
| Loading state | ☐ | N/A | Skeleton / spinner |
| Empty state | ☐ | N/A | "No holdings with cost basis" |