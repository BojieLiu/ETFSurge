# API 契约: 因子分类明细暴露 (Z03)

> 关联方案: `docs/z_fixes_design_v5.3.md` Z03
> 变更类型: 既有端点响应增强（`/factors/active` 新增样本数/新鲜度/权威状态，移除硬编码 ic=0）
> 版本: v2.0
>
> **v3.0 (F3-4/F3-5)**: ① etf_specific 四因子 no_data 的 reason 区分「数据源未接入（缺字段，N 只样本）」与「IC 未累积（样本 <3）」——依据 `factor_registry._data_source_gaps`（`_fetch_market_data` 注入 nav/benchmark_close/shares_change_20d 后记录缺口）；② sentiment 三因子（panic_greed_diff/news_heat/news_direction）经 `_fetch_market_data` 注入 `sentiment_index`/`sentiment_history`/`news_items` 后产出真实值 → 进入 IC batch → 不再恒 no_data；③ `/factors/ic` 响应新增 `zero_ratio` 字段（code → 零值占比，1.0 = 全部样本为 0 → 数据源未接入）。

## 1. 概述 / Overview

**功能描述**: 修复 `/factors/active` 端点缺少样本数、新鲜度、权威状态，且 china_specific 静态因子硬编码 `ic=0` 掩盖未计算的问题。服务端返回权威的 `status` + `reason` + `sample_count`，前端可自动验证因子健康度。

**触发场景**: DashboardAiTools 页面 FactorModelView 组件挂载、verify_e2e 因子健康检查。

---

## 2. 端点定义 / Endpoint

### 2.1 获取已接入因子列表 / Get Active Factors (响应增强)

```
GET /api/v1/factors/active
```

#### 成功响应 / Success Response — `200 OK`

```json
{
  "total": 33,
  "categories": [
    {
      "name": "technical",
      "count": 17,
      "description": "技术指标因子：移动平均、动量、波动率等",
      "avg_ic": 0.0284,
      "valid_count": 12,
      "warn_count": 3,
      "no_data_count": 2,
      "factors": [
        {
          "code": "technical.ma.sma_5",
          "name": "SMA 5",
          "subcategory": "ma",
          "description": "5日均线，短期趋势指标",
          "standardization": "zscore",
          "ic_threshold": 0.02,
          "ic_value": 0.0321,
          "status": "valid",
          "reason": "IC 0.032 > 阈值 0.02，样本数 240",
          "sample_count": 240,
          "last_computed_at": "2026-07-31T15:00:00Z"
        },
        {
          "code": "china_specific.five_year_plan",
          "name": "十四五规划",
          "subcategory": "policy",
          "description": "十四五规划受益标的标识",
          "standardization": "none",
          "ic_threshold": 0.0,
          "ic_value": null,
          "status": "static",
          "reason": "静态政策标识因子，不计算 IC",
          "sample_count": 0,
          "last_computed_at": null
        }
      ]
    }
  ],
  "summary": {
    "valid": 20,
    "warn": 5,
    "no_data": 8,
    "static": 3,
    "avg_ic": 0.0312
  },
  "updated_at": "2026-07-31T15:00:00Z"
}
```

#### 字段增强 / Enhanced Fields (Z03)

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| factors[].status | string | No | **新增** `valid` \| `warn` \| `no_data` \| `static` —— 权威状态 |
| factors[].reason | string | No | **新增** 状态原因说明（含样本数、IC对比阈值、静态因子标识） |
| factors[].sample_count | integer | No | **新增** 有效样本数，静态因子为 0 |
| factors[].last_computed_at | string (ISO8601) | Yes | **新增** 最后计算时间，静态因子为 null |
| factors[].ic_value | float | Yes | 实时 IC 值，**静态因子为 null（而非 0）**，移除硬编码 0 |

#### status 枚举定义 / Status Enum

| status | 含义 | 判定逻辑 |
|--------|------|----------|
| `valid` | 有效 | `ic_value` 不为 null 且 `\|ic_value\| >= ic_threshold` |
| `warn` | 预警 | `ic_value` 不为 null 但 `\|ic_value\| < ic_threshold` |
| `no_data` | 无数据 | `ic_value` 为 null（尚未计算/数据不足） |
| `static` | 静态因子 | china_specific 等纯标识因子，不计算 IC，`ic_threshold=0` |

#### china_specific 因子处理 (Z03 核心修复)

- `five_year_plan`、`strategic_emerging`、`dual_circulation` 三因子：
  - `ic_value = null`（不再硬编码 0）
  - `ic_threshold = 0`
  - `status = "static"`
  - `reason = "静态政策标识因子，不计算 IC"`
  - `sample_count = 0`
  - `last_computed_at = null`
- 这些因子**不计入** `summary.valid/warn/no_data` 统计，单独归类：
  - `summary.static`（全局静态因子数）
  - `category.static_count`（该分类下静态因子数）
  - 恒等式：`valid + warn + no_data + static == total`（全端点）

---

## 3. 行为契约 / Behavioral Contract (Z03)

1. **IC 值来源**: 从 `FactorRegistry._last_ic_batch` 读取（定期批量计算产生）。
2. **样本数来源**: 因子计算时记录有效样本数（非 NaN 样本数），写入注册表元数据。
3. **最后计算时间**: 批量计算完成时更新 `FactorRegistry._last_computed_at`。
4. **静态因子识别**: `factor_definitions.yaml` 中 `ic_threshold: 0` 且 `standardization: "none"` 的因子标记为静态。
5. **响应生成时**: 遍历注册表所有计算函数，按上述逻辑组装字段，**不再有硬编码兜底值**。

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| factors[].status 字段存在且枚举正确 | ☐ | ☐ | valid/warn/no_data/static |
| factors[].reason 字段存在且含样本数/IC对比 | ☐ | ☐ | 可读性强 |
| factors[].sample_count 字段存在 | ☐ | ☐ | 静态因子为 0 |
| factors[].last_computed_at 字段存在 | ☐ | ☐ | 静态因子为 null |
| china_specific 因子 ic_value=null 而非 0 | ☐ | ☐ | 核心修复 |
| china_specific 因子 status="static" | ☐ | ☐ | 不计入 summary 统计 |
| verify_e2e 断言 status/reason/sample_count | N/A | ☐ | section_factors 新增 |

---

## 5. 测试 / Tests

- 后端单测: `backend/tests/test_z03_factors_active.py`（mock registry 验证字段完整、静态因子处理）
- verify_e2e: `section_factors` 模块新增字段断言