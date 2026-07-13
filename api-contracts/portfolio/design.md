# Portfolio Design / AI 组合设计

## 1. 概述 / Overview

基于当前行情、宏观数据、财经资讯，调用 LLM 生成三种风险偏好的 ETF 组合方案，并支持一键应用。

Generate three risk-profile ETF portfolio plans using LLM based on market data, macro conditions, and news. Supports one-click apply.

---

## 2. 端点定义 / Endpoints

### 2.1 生成组合设计 / Generate Portfolio Design

```
POST /api/v1/analysis/portfolio-design
```

**请求体 / Request Body:**

```json
{
  "risk_profile": "balanced",
  "capital": 500000
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| risk_profile | string | No | `balanced` | `balanced` \| `growth` \| `conservative` |
| capital | number | No | 500000 | Total capital in CNY |

**成功响应 / Success Response — `200 OK`:**

```json
{
  "market_environment": "当前市场处于震荡格局，流动性充裕...",
  "portfolios": [
    {
      "portfolio_name": "稳健防守组合",
      "portfolio_type": "防御型",
      "market_analysis": {
        "macro_environment": "...",
        "liquidity_condition": "...",
        "style_preference": "价值+红利",
        "sector_opportunity": "公用事业、消费",
        "risk_assessment": "外部风险可控"
      },
      "allocation_rationale": {
        "asset_class_allocation": "权益60%，现金20%，黄金8%",
        "equity_style_tilt": "红利低波+价值",
        "geographic_allocation": "A股70%，港股20%",
        "sector_allocation": "核心配置消费+红利"
      },
      "etfs": [
        {
          "symbol": "510880",
          "name": "华泰柏瑞红利ETF",
          "asset_class": "权益",
          "target_weight": 0.12,
          "selection_rationale": "高股息+低波动，适合防御配置",
          "weight_rationale": "核心仓位，上限12%",
          "tracked_index": "000015",
          "key_metrics": {
            "scale_billion": 198.5,
            "avg_volume_million": 320,
            "pe_ttm": 8.5,
            "pb": 0.9,
            "ytd_return": 12.3
          }
        }
      ],
      "portfolio_metrics": {
        "expected_return": "5-8%",
        "expected_volatility": "12-15%",
        "max_drawdown_estimate": "10-12%",
        "sharpe_estimate": 0.8,
        "turnover_estimate": "30-50%"
      },
      "risk_factors": ["经济复苏不及预期", "地缘政治风险"],
      "rebalance_rules": "季度再平衡，偏离超过5%触发"
    }
  ],
  "indices": ["...index data..."],
  "commodities": ["...commodity data..."]
}
```

**响应字段说明 / Response Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| market_environment | string | Overall market analysis summary |
| portfolios | array | Array of 3 portfolio plans (进攻型/平衡型/防御型) |
| portfolios[].portfolio_name | string | Name of the portfolio plan |
| portfolios[].portfolio_type | string | `进攻型` \| `平衡型` \| `防御型` |
| portfolios[].market_analysis | object | Multi-dimensional market analysis |
| portfolios[].allocation_rationale | object | Rationale for each allocation decision |
| portfolios[].etfs | array | ETFs in this plan (8–12 per plan) |
| portfolios[].etfs[].target_weight | float | Target weight (0–1) |
| portfolios[].portfolio_metrics | object | Expected return, volatility, drawdown, Sharpe |
| portfolios[].risk_factors | array | Key risk factors |
| portfolios[].rebalance_rules | string | Rebalance trigger rules |

---

### 2.2 应用组合设计 / Apply Portfolio Design

```
POST /api/v1/portfolio/apply-design
```

**请求体 / Request Body:**

```json
{
  "portfolio_type": "on_exchange",
  "symbols": ["510880", "159338"],
  "weights": {
    "510880": 0.12,
    "159338": 0.26
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| portfolio_type | string | No | `on_exchange` (default) \| `off_exchange` |
| symbols | array | Yes | List of ETF symbols to apply |
| weights | object | Yes | Symbol → target_weight map |

**成功响应 / Success Response — `200 OK`:**

```json
{
  "symbols": [
    {
      "symbol": "510880",
      "name": "华泰柏瑞红利ETF",
      "target_weight": 0.12,
      "portfolio_type": "on_exchange"
    }
  ],
  "applied": [
    {
      "symbol": "510880",
      "action": "updated",
      "name": "华泰柏瑞红利ETF",
      "target_weight": 0.12,
      "portfolio_type": "on_exchange"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| symbols | array | Full updated ETF list |
| applied | array | Per-symbol application result |
| applied[].action | string | `updated` (existing ETF modified) \| `added` (new ETF created) |

**错误 / Error Codes:**

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | Empty symbols list |
| 500 | Internal Server Error | DB commit failure |

---

## 3. 契约约束 / Design Constraints (from LLM prompt)

- **8–12 ETFs per plan** (including cash position)
- **Single ETF weight: 5%–15%**
- **Same industry ≤ 2 ETFs**
- **Top 5 weights ≤ 50%**
- **No bond ETFs** (managed separately)
- **Growth:Value ≈ 1:1**, single style ≤ 60%
- **Three risk tiers** (no bond):
  - 进攻型: Equity ≥ 85%, Cash ≤ 10%
  - 平衡型: Equity 65–75%, Cash 10–15%
  - 防御型: Equity 50–60%, Cash 15–20%, Gold ≤ 8%

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `POST /analysis/portfolio-design` returns 200 | ☐ | ☐ | |
| Response contains `portfolios` array with 3 plans | ☐ | ☐ | |
| Each plan has `etfs` array with 8–12 items | ☐ | ☐ | |
| `apply-design` accepts symbols + weights | ☐ | ☐ | |
| Existing ETFs are updated, new ones created | ☐ | ☐ | |
| Loading state during design generation | ☐ | N/A | `designing` |
| Design result displays portfolio cards | ☐ | N/A | |
| Apply button has loading state | ☐ | N/A | `applyingPlan` |
| Error toast on failure | ☐ | N/A | |
