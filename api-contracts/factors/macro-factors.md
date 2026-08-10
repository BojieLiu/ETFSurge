# Contract: 宏观环境因子 / Macro Environment Factors (round13 §3.1 P2)

> **用途**: 5 个 MARKET_LEVEL 类宏观环境因子（月频 3 + 季频 1 + 日频环境 1 两融），注册进因子模型，
> 在 `/factors/active` 以 `status="static"` 展示（全市场单一值 → 截面恒等 → 不参与截面 IC），
> 并作为 LLM 上下文宏观段的方向标注（-1/0/+1）。
> 定位：环境/市态维度，慢变量调节快变量，**不参与盘中高频决策**。

---

## 1. 概述 / Overview

**功能描述 / Description**: 注册 5 个宏观环境因子 + 扩展 LLM 上下文宏观段。

| code | 频率 | 输入 | 输出 | 语义 |
|------|------|------|------|------|
| `macro.m2_trend` | 月频 | M2 同比 3 月斜率 | -1/0/+1 | 货币松紧趋势 |
| `macro.pmi_level` | 月频 | 最新 PMI | 1/0 | 荣枯线上方 = 1 |
| `macro.lpr_direction` | 月频 | LPR 1Y 同比（12 月窗口） | -1/0/+1 | 降息周期 = +1 |
| `macro.gdp_trend` | 季频 | GDP 同比增速分位（近 8 期） | -1/0/+1 | 经济环境分级 |
| `macro.margin_leverage_trend` | 日频数据/环境定位 | 沪深融资余额合计 20 日变化率 | -1/0/+1 | 杠杆资金情绪（与 sentiment 互补） |

**触发场景 / Trigger**: 因子模型后台计算（`registry.compute()`）；`build_full_context(include_macro=True)` LLM 上下文。

---

## 2. 内部接口 / Internal Interface

### 2.1 因子注册（两处，缺一不可）

1. `factor_registry.py` `_BUILTIN_COMPUTERS`：5 个 compute 函数注册（code → fn）
2. `routers/factors.py` `MARKET_LEVEL_FACTOR_CODES`：5 个 code 加入（否则 `/factors/active` 不会以 static 标注）

### 2.2 数据注入

compute 函数从 `data["macro_snapshot"]` 读取（`_fetch_market_data` 组装时注入一次，
复用 `fetch_macro_snapshot()` 的 24h 缓存，非每标的重复拉取）。snapshot 字段同
`market/macro-regime.md` §2.2。

### 2.3 `/factors/active` 输出（新增因子条目）

```json
{
  "code": "macro.pmi_level",
  "name": "PMI 荣枯线水平",
  "category": "macro",
  "subcategory": "environment",
  "status": "static",
  "reason": "市场级因子（全市场单一值），不参与截面 IC，仅作市态/组合层输入",
  "ic_value": null,
  "ic_threshold": 0.0,
  "sample_count": 0,
  "last_computed_at": null
}
```

- `category` 前缀 `macro` → `_get_factor_category` 归一为 `"macro"`；`/factors/model`
  `categories` 出现 `macro` 分类 + `CATEGORY_DESCRIPTIONS["macro"]` 描述文案。

### 2.4 LLM 上下文宏观段扩展（`build_full_context`）

`domestic_macro` 追加两字段（PMI/GDP 实测值 + 方向标注，非占位）：

```json
{
  "pmi_gdp": {
    "pmi_value": 49.5,
    "gdp_yoy": 5.2,
    "as_of": "2026-06",
    "note": ""
  },
  "macro_snapshot": {
    "m2_yoy_now": 6.8,
    "m2_direction": -1,
    "pmi_value": 49.5,
    "pmi_direction": -1,
    "lpr_1y_now": 3.0,
    "lpr_direction": 1,
    "macro_direction": -1,
    "as_of": "2026-07"
  }
}
```

---

## 3. 降级 / Degradation

| 场景 | 行为 |
|------|------|
| snapshot 全不可用 | 5 因子输出 0.0；LLM 上下文 `macro_snapshot` 为 null（不编造） |
| GDP 数据滞后（季后 1.5 月发布） | 只用已发布值，`as_of` 标注「数据截至 YYYY-Qn」 |
| akshare 源超时 | 24h 缓存 + 1h 失败缓存 + 熔断（延续既定模式） |
| 两融接口失败（沪深任一） | margin_leverage_trend 输出 0（诚实降级，不编造）；不影响其他 4 因子 |
| 沪深日期不对齐 | 按日期合并，取双方均有的最新交易日（交集） |

## 4. 验收 / Acceptance

- [x] 5 因子出现在 `/factors/active`，`status="static"` + reason 含「市场级因子」
- [x] `/factors/model` 出现 `macro` category + 描述
- [x] `domestic_macro` 含 PMI/GDP 真实值（非占位）
- [x] LLM 上下文宏观段含方向标注（-1/0/+1）
- [x] 全量测试绿（新增单测：compute 逻辑 / 注册 / 路由集合 / margin 20 日斜率）
- [x] 前视偏差：GDP 因子只用已发布值 + 时间戳标注
- [x] margin_leverage_trend 真实链路：沪深融资余额合计 >0（宿主机实测）

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| /factors/active 新增条目 | ☐（自动渲染） | ☐ | category "macro" 自动出现 |
| /factors/model 分类 | ☐（自动渲染） | ☐ | 需 CATEGORY_DESCRIPTIONS |
| LLM 上下文字段 | N/A | ☐ | 内部上下文，无 UI 契约 |
| static 标注 | ☐（已有 status 渲染） | ☐ | MARKET_LEVEL_FACTOR_CODES |
