# Portfolio Design Engine v2 — PoolManager + FactorRegistry Integration / 组合设计引擎 v2 整合方案

## 1. 概述 / Overview

Phase A: 将现有的 `pool_manager`（含 `etf_scanner` + `etf_classifier` + `factor_registry`）接入组合设计引擎 `generate_enhanced_design()`。

Integrate PoolManager (with ETFScanner, ETFClassifier, FactorRegistry) into the portfolio design engine.

### 核心变更 / Core Changes

| Before | After |
|--------|-------|
| `CANDIDATE_POOL` 硬编码 20 只 ETF | `pool_manager.refresh()` 全市场扫描 + 5 层池 |
| `FACTOR_CONFIG` 5 个手工定义的因子 | `factor_registry.compute()` 30 个 YAML 驱动因子 |
| `_SECTOR_ETF_MAP` 手工映射行业 | `etf_classifier.batch_classify()` 40+ 规则自动分类 |
| 卫星层按评分取前 N 名，无去重 | 评分排序 + 行业去重贪婪选择 |
| `valuation` 因子用 `-volatility_20d` 代理 | 真实 `pe_ttm` / `pb` 数据 |
| `fund_flow_20d` 因子用情感分数代理 | 真实 `main_net_inflow` 数据 |
| `mode="fast"` / `mode="standard"` 双模式 | 仅保留 `mode="enhanced"` 一条路径 |

---

## 2. 数据流 / Data Flow

```
POST /portfolio/design-async
  │
  ▼
design_worker() → generate_enhanced_design()
  │
  ├─ Step 1: 并行采集
  │   ├── compute_etf_trends(all_symbols)       → trend_data (含日线)
  │   ├── detect_macro_regime()                 → macro_state
  │   ├── fetch_market_sentiment()              → sentiment
  │   ├── fetch_benchmark_stocks()              → benchmark
  │   ├── fetch_news_headlines()                → news
  │   ├── fetch_fund_flow × N (并行)            → fund_flows
  │   └── fetch_current_pe_pb × N (并行)        → valuation_data
  │
  ├─ Step 2: pool_manager.refresh() ← 新增
  │   ├── etf_scanner.full_pipeline()           → 全市场 ETF 列表
  │   ├── etf_classifier.batch_classify()       → 行业 + 概念标注
  │   ├── factor_registry.compute(symbols)       → 30 个因子分数
  │   └── layer assignment + composite score    → 5 层候选池
  │
  ├─ Step 3: 从 pool_manager 取数据
  │   ├── pool["core"] / pool["satellite"] / pool["defense"]
  │   ├── 每项含: industry, concepts, factor_scores, composite_score
  │   └── 卫星层: 按 composite_score 排序 + 按 industry 去重
  │
  ├─ Step 4: 为三种风险偏好生成方案
  │   ├── dynamic_core_allocation()             → 核心层 3-4 只
  │   ├── dynamic_defense_allocation()          → 防御层 1-3 只
  │   ├── 卫星: 行业去重贪婪选择 + 幂律分配    → 3-8 只
  │   └── build_rationale()                     → 三层入选理由
  │
  └─ Step 5: 返回结果
      ├── strategies [{id, label, portfolio_name, positioning, ...}]
      ├── market_context {indices, market_sentiment, ...}
      └── design_metadata {version, factors_used, pool_version, ...}
```

---

## 3. 响应格式（新增/变更字段） / Response Fields (New/Changed)

### ETF 条目新增字段

```json
{
  "symbol": "512480",
  "name": "半导体ETF",
  "layer": "satellite",
  "weight": 0.079,
  "industry": "电子",                    // ← 新增: ETFClassifier 行业
  "concepts": ["半导体", "芯片"],         // ← 新增: 概念标签
  "factor_score": 0.85,                  // composite_score
  "factor_breakdown": {                   // ← 新增: 因子分解
    "momentum_3m": 0.72,
    "fund_flow_20d": 0.65,
    "valuation": 0.81,
    "liquidity": 0.55,
    "volatility_20d": 0.42
  },
  "fund_flow_20d": 650000000,            // ← 改为真实值 (原为代理)
  "pe_ttm": 45.2,                        // ← 新增: 真实估值
  "trend_1m": 0.032,
  "trend_3m": 0.082,
  "ma_bias_20": 0.015,
  "selection_rationale": "半导体ETF — 科技主线高弹性品种。近3月涨8.2%，主力资金净流入6.5亿。行业偏正面。作为进攻型卫星，提供高弹性超额收益。"  // build_rationale() 输出
}
```

---

## 4. 待删除的旧代码 / Code to Remove

| 文件 | 删除内容 |
|---|---|
| `strategy_design.py` | `CANDIDATE_POOL` 字典 |
| | `CORE_FIXED` 列表 |
| | `DEFENSE_FIXED` 列表 |
| | `CORE_REQUIRED` / `CORE_MIN_EACH` |
| | `MIN_NAMES` / `MAX_NAMES` |
| | `generate_design()` 函数 |
| | `allocate_layer_budget()` 函数 |
| | `_enforce_name_count()` 函数 |
| | `_build_default_context()` 函数 |
| | `_extract_factor()` 函数 |
| | `enrich_market_context()` 函数 |
| | `classify_assets()` 函数 |
| | `Asset` / `MarketContext` dataclass |
| | `_SECTOR_ETF_MAP` 字典 |
| `portfolio.py` | `mode` 参数从设计端点移除 |
| | `POST /portfolio/design` 同步端点 |

---

## 5. 前端变更 / Frontend Changes

| 变更 | 说明 |
|---|---|
| 移除 `portfolioApi.design()` 同步调用 | 统一使用 `designAsync()` |
| GET /tasks/{id} 增加 `strategies` 字段 | 无需额外 listDesigns + getDesign |
| ETF 展示增加 industry 标签 | 用户可见行业分布 |
| history 自动刷新 | exitCoreFeature 重置 historyLoaded |

---

## 6. 验证清单 / Verification Checklist

- [ ] 后端: 全部单元测试通过 (111+ passed)
- [ ] 前端: 全部测试通过 (52 passed)
- [ ] E2E: 生成完整 3 套方案，每套 8-15 只 ETF
- [ ] 卫星层: 每个策略的卫星 ETF 行业各不相同
- [ ] 入选理由: 所有 ETF 均有非空 rationale
- [ ] factor_breakdown: 卫星层 ETF 含多因子分解
- [ ] 无 `mode="fast"` 残留调用
- [ ] 无 `CANDIDATE_POOL` / `CORE_FIXED` 引用残留
