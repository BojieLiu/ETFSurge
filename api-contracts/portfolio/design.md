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
  "design_text": "基于2026-07-14提供的行情快照与资讯设计...\n\n一、锐意进取组合（进攻型）\n定位：捕捉科技主线高弹性机会，承受较大回撤\n\n序号\t标的\t代码\t权重\t入选原因\n1\t科创50ETF\t588000\t15%\t输入数据显示科创50当日涨幅+3.2%，近一周资金净流入45.6亿\n...\n\n权重设置逻辑：\n- 科技三层穿透（合计45%）：宽基β（科创50）+设备龙头（半导体设备）+高弹性芯片（科创芯片）\n- 防御缓冲垫（合计22%）：红利+黄金+银行，对冲成长板块波动\n\n预期特征：预期年化波动20-25%，最大回撤区间22-28%\n\n...（平衡型、防御型同结构）\n\n[最后一章] 三组合核心差异速览\n对比维度\t进攻型\t平衡型\t防御型\n标的数量\t10只\t12只\t14只\n权益仓位\t92%\t85%\t65%\n科技/弹性占比\t65%+\t45%\t20%\n高股息/防御占比\t5%\t25%\t50%+\n现金/流动性\t8%\t12%\t20%\n预期年化波动\t25%+\t15-18%\t10-12%\n核心品种\t科创50、半导体、AI\t沪深300、红利、黄金\t红利低波、银行、黄金\n一句话总结：当前市场风格偏成长，进攻型适合高风险承受者博取超额，防御型适合低波稳健配置",
  "data_snapshot_time": "2026-07-14 20:28（北京时间）",
  "market_environment": "当前市场处于震荡格局，流动性充裕...",
  "portfolios": [
    {
      "style": "进攻型",
      "style_label": "进攻型",
      "portfolio_name": "锐意进取组合",
      "positioning": "捕捉科技主线高弹性机会，承受较大回撤",
      "expected_return": 0.15,
      "max_drawdown": 0.25,
      "sharpe_ratio": 0.8,
      "expected_characteristics": "预期年化波动20-25%，最大回撤区间22-28%",
      "weight_logic": [
        {
          "group": "科技三层穿透",
          "total_weight_pct": 45,
          "rationale": "宽基β（科创50）+设备龙头（半导体设备）+高弹性芯片（科创芯片）"
        },
        {
          "group": "防御缓冲垫",
          "total_weight_pct": 22,
          "rationale": "红利+黄金+银行，对冲成长板块波动"
        }
      ],
      "market_analysis": {
        "macro_environment": "...",
        "liquidity_condition": "...",
        "style_preference": "成长+科技",
        "sector_opportunity": "半导体、AI、新能源",
        "risk_assessment": "外部风险可控"
      },
      "allocation_rationale": {
        "asset_class_allocation": "权益92%，现金5%，商品3%",
        "equity_style_tilt": "成长+动量",
        "geographic_allocation": "A股80%，港股15%，美股5%",
        "sector_allocation": "核心配置半导体+AI+新能源"
      },
      "etfs": [
        {
          "symbol": "588000",
          "name": "科创50ETF",
          "asset_class": "equity",
          "target_weight": 0.15,
          "selection_rationale": "输入数据显示科创50当日涨幅+3.2%，近一周资金净流入45.6亿",
          "weight_rationale": "进攻核心仓位，上限15%",
          "tracked_index": "000688",
          "key_metrics": {
            "scale_billion": 250,
            "avg_volume_million": 1500,
            "pe_ttm": 45.0,
            "pb": 4.2,
            "ytd_return": -5.3
          }
        }
      ],
      "portfolio_metrics": {
        "expected_return": "12-18%",
        "expected_volatility": "20-25%",
        "max_drawdown_estimate": "22-28%",
        "sharpe_estimate": 0.8,
        "turnover_estimate": "60-100%"
      },
      "risk_factors": ["经济复苏不及预期", "地缘政治风险", "科技板块估值回调"],
      "rebalance_rules": "月度检视，偏离超过5%触发再平衡"
    }
  ],
  "comparison_table": {
    "进攻型": {
      "标的数量": "10只",
      "权益仓位": "92%",
      "科技/弹性占比": "65%+",
      "高股息/防御占比": "5%",
      "现金/流动性": "8%",
      "预期年化波动": "25%+",
      "核心品种": "科创50、半导体、AI"
    },
    "平衡型": {
      "标的数量": "12只",
      "权益仓位": "85%",
      "科技/弹性占比": "45%",
      "高股息/防御占比": "25%",
      "现金/流动性": "12%",
      "预期年化波动": "15-18%",
      "核心品种": "沪深300、红利、黄金"
    },
    "防御型": {
      "标的数量": "14只",
      "权益仓位": "65%",
      "科技/弹性占比": "20%",
      "高股息/防御占比": "50%+",
      "现金/流动性": "20%",
      "预期年化波动": "10-12%",
      "核心品种": "红利低波、银行、黄金"
    }
  },
  "indices": ["...index data..."],
  "commodities": ["...commodity data..."]
}
```

**响应字段说明 / Response Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| design_text | string | 完整的 Markdown 格式设计报告（含定位、ETF表格、权重逻辑、预期特征、三组合对比表） |
| data_snapshot_time | string | 数据快照时间，如 `2026-07-14 20:28（北京时间）` |
| market_environment | string | Overall market analysis summary |
| portfolios | array | Array of 3 portfolio plans (进攻型/平衡型/防御型) |
| portfolios[].style | string | `进攻型` \| `平衡型` \| `防御型`（与 portfolio_type 同义） |
| portfolios[].style_label | string | Display label for the style |
| portfolios[].portfolio_name | string | Name of the portfolio plan |
| portfolios[].positioning | string | 一句话定位描述 |
| portfolios[].expected_return | number | Expected annual return (decimal, e.g., 0.15 = 15%) |
| portfolios[].max_drawdown | number | Expected max drawdown (decimal) |
| portfolios[].sharpe_ratio | number | Expected Sharpe ratio |
| portfolios[].expected_characteristics | string | 预期特征：波动率区间、回撤区间等定性+定量描述 |
| portfolios[].weight_logic | array | 权重设置逻辑分组，每项含 group、total_weight_pct、rationale |
| portfolios[].market_analysis | object | Multi-dimensional market analysis |
| portfolios[].allocation_rationale | object | Rationale for each allocation decision |
| portfolios[].etfs | array | ETFs in this plan (8–12 per plan) |
| portfolios[].etfs[].target_weight | float | Target weight (0–1) |
| portfolios[].portfolio_metrics | object | Expected return, volatility, drawdown, Sharpe |
| portfolios[].risk_factors | array | Key risk factors |
| portfolios[].rebalance_rules | string | Rebalance trigger rules |
| comparison_table | object | 三组合核心差异速览表，键为风格，值为维度→取值的对象 |

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
