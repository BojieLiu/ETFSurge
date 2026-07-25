# Portfolio Drift Check / 组合偏离度检查

## 1. 概述 / Overview

**功能描述 / Description**: 计算当前持仓的实际权重与目标权重的偏离度（drift），返回每只 ETF 的偏差百分比和需要再平衡的告警。

**触发场景 / Trigger**: PortfolioAnalysis 页面加载组合数据时自动调用；PortfolioManager 中用户点击"偏离检查"。

---

## 2. 端点定义 / Endpoint

```
GET /api/v1/portfolio/drift-check
```

### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| portfolio_type | string | No | — | Filter: `on_exchange` \| `off_exchange` |

### 成功响应 / Success Response — `200 OK`

```json
{
  "items": [
    {
      "symbol": "510300",
      "name": "沪深300ETF",
      "target_weight": 0.30,
      "actual_weight": 0.2845,
      "deviation": -0.0155,
      "deviation_pct": -5.17,
      "market_value": 142250.00,
      "needs_rebalance": false
    },
    {
      "symbol": "159338",
      "name": "国泰中证A500ETF",
      "target_weight": 0.26,
      "actual_weight": 0.3421,
      "deviation": 0.0821,
      "deviation_pct": 31.58,
      "market_value": 171050.00,
      "needs_rebalance": true
    }
  ],
  "alerts": [
    {
      "symbol": "159338",
      "name": "国泰中证A500ETF",
      "message": "权重偏离 31.6% (目标 26.0%, 实际 34.2%)",
      "severity": "warning"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| items | array | 每只 ETF 的偏离计算结果 |
| items[].symbol | string | ETF 代码 |
| items[].name | string | ETF 名称 |
| items[].target_weight | float | 目标权重（小数，如 0.30 = 30%） |
| items[].actual_weight | float | 实际市值权重（小数，4 位小数） |
| items[].deviation | float | actual - target（4 位小数） |
| items[].deviation_pct | float | deviation / target * 100（2 位小数，百分比值） |
| items[].market_value | float | 持仓市值（2 位小数） |
| items[].needs_rebalance | bool | 是否需要再平衡（\|deviation_pct\| > 20%） |
| alerts | array | 偏离超过 20% 的告警列表 |
| alerts[].severity | string | `"warning"`（20-50%） \| `"critical"`（≥50%） |

### 错误 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 200 | — | 空组合返回 `{"items":[], "alerts":[]}`（非错误） |

---

## 3. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| GET /portfolio/drift-check 带 portfolio_type 参数 | ✅ | ✅ | stores/portfolio.js:54 + PortfolioManager.vue:762 调用 |
| items[].needs_rebalance 显示红色标记 | ☐ | ✅ | 前端需消费此字段 |
| alerts 列表展示告警消息 | ☐ | ✅ | |
| 空组合返回空 items + alerts | ☐ | ✅ | |
