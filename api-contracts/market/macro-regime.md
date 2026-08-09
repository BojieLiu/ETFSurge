# Contract: 市态判定宏观增强 / Macro-Enhanced Market Regime (round13 §3.1 P1)

> **用途**: 慢变量（PMI / M2 / LPR）调节日频市态判定——宏观为辅助非主导。
> 内部接口（无 HTTP 端点变更）：`detect_market_regime(macro=...)` 可选参数 +
> `macro_fetcher.fetch_macro_snapshot()` 聚合快照。`market_data_hub.update_market_regime`
> 在 A 市场刷新路径组装 macro 快照传入。

---

## 1. 概述 / Overview

**功能描述 / Description**: `detect_market_regime` 增加可选参数 `macro: dict | None = None`（默认 None，现有调用零影响）。
宏观方向修正规则：
- PMI < 50 → 风险偏下（防御倾向）
- M2 同比环比下行（货币收紧）→ 风险偏下
- LPR 同比下调（降息周期）→ 风险偏上
- 修正规则：现有输出 + 宏观同向叠加；宏观冲突/数据缺失时**保持现有输出**

**触发场景 / Trigger**: `market_data_hub.update_market_regime("A")` 定时刷新（120s 后台循环）时组装 macro 快照传入。

---

## 2. 内部接口 / Internal Interface

### 2.1 `macro_fetcher.fetch_macro_snapshot() -> dict | None`

```python
fetch_macro_snapshot() -> dict | None
```

**语义**: 聚合 M2 同比 / PMI / LPR 1Y 三指标 + 方向标注；复用 `macro:*` 24h 成功 / 1h 失败缓存模式；全失败降级返回 `None`。

### 2.2 `detect_market_regime(..., macro: dict | None = None) -> str`

**参数**: 追加 `macro`（keyword-only，默认 None）。

**macro 快照字段结构**:

```json
{
  "m2_yoy_now": 6.8,
  "m2_yoy_3m_ago": 7.0,
  "m2_slope": -0.2,
  "m2_direction": -1,
  "pmi_value": 49.5,
  "pmi_direction": -1,
  "lpr_1y_now": 3.0,
  "lpr_1y_12m_ago": 3.45,
  "lpr_direction": 1,
  "macro_direction": -1,
  "as_of": "2026-07",
  "sources": ["M2", "PMI", "LPR"]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `m2_yoy_now` / `m2_yoy_3m_ago` | number | M2 同比 现期 / 3 个月前（环比窗口） |
| `m2_slope` | number | `m2_yoy_now - m2_yoy_3m_ago` |
| `m2_direction` | int | 斜率 < -0.1 → -1；> +0.1 → +1；否则 0 |
| `pmi_value` | number | 最新 PMI 值（荣枯线 50） |
| `pmi_direction` | int | PMI ≥ 50 → +1；< 50 → -1 |
| `lpr_1y_now` / `lpr_1y_12m_ago` | number | LPR 1Y 现期 / 12 个月前 |
| `lpr_direction` | int | 同比下降 → +1（降息周期）；上升 → -1；持平 → 0 |
| `macro_direction` | int | `sign(m2_direction + pmi_direction + lpr_direction)`；-1/0/+1 |
| `as_of` | string | 数据截至（YYYY-MM，时间戳诚实标注） |
| `sources` | string[] | 实际可用指标名 |

### 2.3 修正规则（`detect_market_regime` 内部）

```
macro_dir = macro["macro_direction"]（数据缺失/None → 0，保持现有输出）
regime_level = {panic:-3, bear:-2, correction:-1, defensive_rotate:-1,
                range_bound:0, bull_weakening:+1, bull_strong:+2}[regime]
若 regime_level == 0（中性市态）:
    macro_dir < 0 → "defensive_rotate"（中性 + 防御倾向）
    macro_dir > 0 → "bull_weakening"（中性 + 进攻倾向）
若 sign(regime_level) == macro_dir（同向叠加）:
    强化一级（bull_weakening→bull_strong；defensive_rotate/correction→bear；bear→panic）
若冲突（sign 相反）或 macro_dir == 0: 保持现有输出（宏观不主导快变量）
```

**关键约束**: 宏观冲突时保持现有输出；数据全 None 时行为与 `macro=None` 完全一致。

---

## 3. 降级 / Degradation

| 场景 | 行为 |
|------|------|
| `macro=None` 或空 dict | 现有判定路径，零影响 |
| 三指标全不可用 | snapshot 返回 None → 等同 macro=None |
| PMI/GDP 数据源超时 | 24h 缓存命中旧值；1h 失败缓存后自动恢复 |
| GDP 前视偏差 | 只用已发布值 + 滞后期标注（`as_of` 字段诚实） |

---

## 4. 验收 / Acceptance

- [x] 单测：`macro=None` 行为不变（既有用例全绿）
- [x] 单测：PMI<50 + range_bound → `defensive_rotate`
- [x] 单测：宏观偏下 + bear → 保持 bear（冲突不主导）
- [x] 单测：三指标全 None → 行为与 macro=None 一致
- [x] 单测：LPR 同比下调（+1）+ range_bound → `bull_weakening`
- [x] 真实链路：`fetch_macro_snapshot()` 返回非空（宿主机实测）
- [x] `market_data_hub.update_market_regime("A")` 传 macro 参数（调用点接通）

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| HTTP 端点变更 | N/A | N/A | 纯内部接口，无端点变更 |
| 既有调用零影响 | N/A | ☐ | macro 默认 None |
| 调用点接通 | N/A | ☐ | update_market_regime("A") |
| 真实数据非兜底 | N/A | ☐ | snapshot 非空含真实值 |
