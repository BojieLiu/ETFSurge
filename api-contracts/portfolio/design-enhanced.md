# Portfolio Design (Enhanced v4) / 增强型组合设计 v4

## 1. 概述 / Overview

基于趋势数据 + 多因子评分 + 宏观状态感知 + 资讯情绪映射的全链路增强组合设计引擎。

The enhanced portfolio design engine incorporating trend data, multi-factor scoring, macro regime awareness, and news-sentiment mapping.

### 新增维度 / New Dimensions

| Dimension | Source | Used By |
|-----------|--------|---------|
| 价格趋势 (1m/3m/6m) | `market_trends.compute_etf_trends()` | Rule engine + LLM |
| 多因子评分 (动量/资金流/估值/流动性/波动率) | `strategy_design.score_satellite_assets()` | Rule engine |
| 宏观状态 (经济/货币/利率/风险) | `macro_state.detect_macro_regime()` | Rule engine + LLM |
| 市场状态 (牛市/熊市/震荡/防御轮动) | `market_trends.detect_market_regime()` | Rule engine + LLM |
| 资讯-ETF映射 (新闻情感得分) | `strategy_design.map_news_to_etfs()` | Rule engine |
| 行业轮动信号 (20日申万排名变化) | `market_trends.compute_sector_momentum()` | Rule engine |
| 核心/防御层动态配置 | `strategy_design.dynamic_*_allocation()` | Rule engine |
| 组合风险 (集中度/相关性/回撤) | `strategy_design.compute_portfolio_risk()` | Response output |

---

## 2. 端点定义 / Endpoints

### 2.1 生成增强型组合设计 / Generate Enhanced Portfolio Design

```
POST /api/v1/portfolio/design-enhanced
```

**请求体 / Request Body:**

```json
{
  "risk_profile": "balanced",
  "capital": 500000,
  "mode": "enhanced",
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
| mode | string | No | `enhanced` | `enhanced` (全量趋势+宏观) \| `standard` (旧版全量) \| `fast` |
| constraints | object | No | - | 可选约束：`min_names`, `max_names`, `min_weight`, `max_weight` |

---

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
      "market_regime_note": "当前市场处于防御轮动阶段，加大防御层配置",
      "layer_budget": {
        "core": 0.40,
        "satellite": 0.15,
        "defense": 0.20
      },
      "etfs": [
        {
          "symbol": "510300",
          "name": "沪深300ETF",
          "layer": "core",
          "weight": 0.15,
          "price": 3.845,
          "change_pct": 0.012,
          "trend_1m": -0.032,
          "trend_3m": 0.085,
          "ma_bias_20": -0.015,
          "fund_flow_20d": 125000000,
          "factor_score": 0.72,
          "selection_rationale": "沪深300核心宽基，当前偏低估区间，20日资金净流入1.25亿，近3月收益+8.5%"
        }
      ],
      "risk_metrics": {
        "sector_concentration": 0.35,
        "max_drawdown_est": -0.12,
        "volatility_est": 0.11,
        "correlation_warning": null
      }
    }
  ],
  "generated_at": "2026-07-16T15:00:00Z",
  "market_context": {
    "timestamp": "2026-07-16 15:00",
    "indices": [...],
    "market_sentiment": {
      "sentiment_index": 45,
      "sentiment_label": "中性偏谨慎",
      "advance_ratio": 0.47,
      "north_flow": -0.3,
      "margin_change": -0.1
    },
    "market_regime": "defensive_rotate",
    "macro_regime": {
      "economic_phase": "弱复苏",
      "monetary_stance": "宽松",
      "rate_direction": "down",
      "bond_bull": true,
      "style_preference": "defensive_value"
    },
    "benchmark_stocks": [...]
  },
  "design_metadata": {
    "version": "v4-enhanced",
    "factors_used": ["momentum_3m", "fund_flow_20d", "valuation", "liquidity", "volatility_20d"],
    "trend_data_collected": 42,
    "news_mapped": 15,
    "generation_time_ms": 12500
  }
}
```

---

### 2.2 新增响应字段说明 / New Response Fields

#### `strategies[].etfs[]` 增强字段

| Field | Type | Description |
|-------|------|-------------|
| `trend_1m` | float | 近1月收益率 (decimal, e.g. -0.032 = -3.2%) |
| `trend_3m` | float | 近3月收益率 |
| `ma_bias_20` | float | 相对20日均线乖离率 |
| `fund_flow_20d` | int | 近20日累计资金净流入(元) |
| `factor_score` | float | 多因子综合评分 (0~1) |

#### `strategies[].risk_metrics`

| Field | Type | Description |
|-------|------|-------------|
| `sector_concentration` | float | 行业集中度 (HHI 0~1) |
| `max_drawdown_est` | float | 预估最大回撤 |
| `volatility_est` | float | 预估年化波动率 |
| `correlation_warning` | string | 相关性预警信息 (null=正常) |

#### `market_context.market_regime`

| Value | Description |
|-------|-------------|
| `bull_strong` | 强牛市 |
| `bull_weakening` | 牛市趋弱 |
| `range_bound` | 震荡市 |
| `correction` | 回调期 |
| `bear` | 熊市 |
| `defensive_rotate` | 防御轮动 |
| `panic` | 恐慌 |

#### `market_context.macro_regime`

| Field | Type | Values |
|-------|------|--------|
| `economic_phase` | string | `衰退` / `弱复苏` / `过热` / `滞胀` |
| `monetary_stance` | string | `宽松` / `中性` / `收紧` |
| `rate_direction` | string | `up` / `down` / `flat` |
| `bond_bull` | bool | 是否处于债牛 |
| `style_preference` | string | `growth` / `balanced` / `defensive_value` |

---

## 3. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route `POST /design-enhanced` created | N/A | ☐ | New endpoint |
| `mode=enhanced` triggers trend data collection | N/A | ☐ | |
| Market regime detection implemented | N/A | ☐ | `detect_market_regime()` |
| Macro regime detection implemented | N/A | ☐ | `detect_macro_regime()` |
| Multi-factor satellite scoring | N/A | ☐ | |
| Dynamic core/defense allocation | N/A | ☐ | |
| ETF-level trend data in response | N/A | ☐ | `trend_1m`, `trend_3m`, etc. |
| Risk metrics computed | N/A | ☐ | `risk_metrics` field |
| Selection rationale includes data citations | N/A | ☐ | |
| Fallback to `standard` mode on data failure | N/A | ☐ | Graceful degradation |
| Tests for trend data module | N/A | ☐ | |
| Tests for macro state module | N/A | ☐ | |
| Tests for multi-factor scoring | N/A | ☐ | |
| LSP diagnostics clean | N/A | ☐ | |
