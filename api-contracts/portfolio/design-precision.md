# API 契约: 设计精度降级契约 (round24 R3)

> 关联方案: `docs/archived/round24-reverification-and-fixes.md` R3（P0「仅供参考」横幅 + 精确数字并存）
> 变更类型: 响应增强（`data_precision` 字段）+ 前端呈现约束
> 版本: v1.0

## 1. 概述 / Overview

**功能描述 / Description**: 因子数据完整性降级（`factor_data_quality.valid_rate < 60%`）时，方案的权重/因子分**不得再以精确值呈现**。后端产出 `data_precision` 结构化精度标识，前端据此把权重降级为粗略档位（5% 步进）、因子分降级为强弱分档，并显示「因子数据缺失 N%」红字。

**触发场景 / Trigger**: `GET /portfolio/designs/{id}`、`POST /portfolio/design-async` 完成后的方案卡片渲染。

**问题背景**: round24 §2.1 实证——design 570 `valid_rate=0.0%` + 「方案仅供参考」横幅，但 UI 仍呈现 5%/15%/21% 精确权重与 -0.99/-0.96 精确因子分，专业投资者无法分辨「哪个数字可信」。**降级诚实了，数字没诚实。**

---

## 2. 端点定义 / Endpoint

```
GET  /api/v1/portfolio/designs/{design_id}
POST /api/v1/portfolio/design-async   （异步任务结果同结构）
```

### 响应增强字段 / Enhanced Response Fields

```json
{
  "strategies": [],
  "plans": [],
  "market_context": {
    "factor_data_quality": { "valid_rate": 0.0, "degraded": true },
    "data_precision": {
      "mode": "coarse",
      "factor_valid_rate": 0.0,
      "factor_missing_pct": 100.0,
      "weight_display": "coarse",
      "weight_step_pct": 5.0,
      "factor_score_display": "bucket",
      "note": "因子数据缺失 100%：权重按 5% 档位粗略呈现、因子分仅显示强弱分档，不代表精确配置"
    }
  },
  "data_precision": { "…同 market_context.data_precision（顶层透传）" }
}
```

### data_precision 字段契约 / Field Contract

| Field | Type | Description |
|-------|------|-------------|
| mode | string | `exact` \| `coarse` —— 精度模式。`coarse` = 因子数据降级，数字不得精确呈现 |
| factor_valid_rate | number | 因子 valid 率 0-1（来源 `factor_data_quality.valid_rate`） |
| factor_missing_pct | number | 缺失百分比 = `(1 - valid_rate) * 100`，保留 1 位小数（前端红字用） |
| weight_display | string | `exact` \| `coarse` —— `coarse` 时权重按 `weight_step_pct` 档位呈现 |
| weight_step_pct | number \| null | 粗略档位步长（百分点），`coarse` 固定 5.0；`exact` 为 `null` |
| factor_score_display | string | `exact` \| `bucket` —— `bucket` 时前端只显示偏强/中性/偏弱 |
| note | string | 人类可读说明（前端红字直接可用） |

### 精度模式判定 / Mode Decision

| mode | 触发条件 | 前端呈现 |
|------|----------|----------|
| `exact` | `factor_data_quality.degraded == false`（valid 率 ≥ 60%） | 权重 `21.0%`、因子分 `+0.42`（现状不变） |
| `coarse` | `factor_data_quality.degraded == true`（valid 率 < 60%，含盘后 0%） | 权重 `≈20%`（5% 档位）、因子分 `偏弱`、卡片红字「因子数据缺失 100%」 |

> **不变式**：`data_precision` **始终存在**（正常态 `mode="exact"`），前端无该键时按 `exact` 处理（不误报降级）。
> **不变式（round27 R47 演化）**：`mode="coarse"` 时后端**直接桶化结构化字段**——
> `etfs[].weight` 按 `weight_step_pct` 档位（如 0.2067 → 0.20）、`etfs[].factor_score` 按强弱分档
> （偏强/中性/偏弱）；`target_amount` 随桶后 `weight` **重算**以保持 `target_amount = capital × weight`
> 一致（不破坏「权重不归一化」）。`mode="exact"` 时 `weight` / `factor_score` 原精确值不变。
> 前端 `weightText` / `factorBucket` 对分档值幂等透传（字符串因子分直接显示，数字档位再呈现）。

---

## 3. 前端呈现契约 / Frontend Rendering Contract

`frontend/src/components/design/DesignResult.vue`：

1. **红字横幅**（`mode === 'coarse'`）：显示 `note`，样式 `precision-banner`（红字 `--color-down` 系），`role="alert"`。
2. **权重列**：`weight_display === 'coarse'` → `≈{round(weight*100 / step) * step}%`（后端 `etfs[].weight` 已为档位值，前端幂等再呈现），`title` 属性保留精确值供核对；否则 `{(weight*100).toFixed(1)}%`。
3. **因子分列**：`factor_score_display === 'bucket'` → `偏强`（≥0.5）/ `偏弱`（≤-0.5）/ `中性`（其余）；round27 R47 后端 `etfs[].factor_score` 在 coarse 态已为分档字符串，`factorBucket` 直接透传（幂等）；exact 态为数字时精确 2 位小数。
4. **四态**：`data_precision` 缺失/为 `null` → 按 `exact` 渲染（不出现空白、不误报降级）。

---

## 4. 示例 / Examples

### 降级态响应示例（盘后 valid_rate=0）

```json
{
  "data_precision": {
    "mode": "coarse", "factor_valid_rate": 0.0, "factor_missing_pct": 100.0,
    "weight_display": "coarse", "weight_step_pct": 5.0,
    "factor_score_display": "bucket",
    "note": "因子数据缺失 100%：权重按 5% 档位粗略呈现、因子分仅显示强弱分档，不代表精确配置"
  }
}
```

### 正常态响应示例

```json
{
  "data_precision": {
    "mode": "exact", "factor_valid_rate": 0.82, "factor_missing_pct": 18.0,
    "weight_display": "exact", "weight_step_pct": null,
    "factor_score_display": "exact",
    "note": "因子数据完整性正常（valid 率 82%），权重与因子分为精确值"
  }
}
```

---

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `data_precision` 始终存在 | ☑ | ☑ | 正常态 `mode=exact` |
| 顶层透传（历史设计可查） | ☑ | ☑ | `GET /designs/{id}` 顶层 + `market_context` 内 |
| `coarse` 时权重非精确 1% | ☑ | N/A | 核心验收：不出现 `21.0%` |
| `coarse` 时因子分为分档 | ☑ | N/A | 不出现 `-0.96` |
| 红字缺失百分比 | ☑ | ☑ | `factor_missing_pct` |
| `target_weight` 原值不被篡改 | N/A | ☑ | 只影响呈现 |
| 缺字段时按 exact（不误报） | ☑ | N/A | 负向断言 |

---

## 6. 测试 / Tests

- 后端单测: `backend/tests/test_round24_data_precision.py`（degraded→coarse / 正常→exact / 输入缺失→exact 不误报 / missing_pct 计算）
- 前端单测: `frontend/src/test/DesignResult.r3precision.spec.js`（coarse 态断言「不出现 21.0%」「出现 ≈20%」「因子分为偏弱」+ exact 态回归）
- verify_e2e: `section_portfolio` 断言 design 详情含 `data_precision.mode ∈ {exact, coarse}`
