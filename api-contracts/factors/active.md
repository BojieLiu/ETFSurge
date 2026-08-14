# API 契约: GET /factors/active — 已接入因子与 IC 状态

> 实现状态: ⬜ 待实现

## 1. 概述 / Overview

**功能描述 / Description**: 返回所有已注册计算函数的因子（已接入因子）列表，按 category 分组，附带实时 IC 值、有效性状态、以及各分类的汇总统计。供 DashboardAiTools 页面的 FactorModelView 组件展示。

**触发场景 / Trigger**: FactorModelView 组件挂载时自动调用。

---

## 2. 端点定义 / Endpoint

```
GET /api/v1/factors/active
```

### 请求头 / Request Headers

| Header | Type | Required | Description |
|--------|------|----------|-------------|
| — | — | — | — |

### 查询参数 / Query Parameters

无。

### 请求体 / Request Body

无。

---

## 3. 响应定义 / Response

### 成功响应 / Success Response

**Status Code:** `200 OK`

```json
{
  "total": 33,
  "categories": [
    {
      "name": "technical",
      "count": 17,
      "description": "技术指标因子：...",
      "avg_ic": 0.0284,
      "valid_count": 12,
      "warn_count": 3,
      "no_data_count": 2,
      "factors": [
        {
          "code": "technical.ma.sma_5",
          "name": "Sma 5",
          "subcategory": "ma",
          "description": "5日均线，短期趋势指标",
          "standardization": "zscore",
          "ic_threshold": 0.02,
          "ic_value": 0.0321
        }
      ]
    }
  ],
  "summary": {
    "valid": 20,
    "warn": 5,
    "no_data": 8,
    "avg_ic": 0.0312
  },
  "updated_at": "2025-01-17T12:00:00+00:00"
}
```

### 字段说明 / Field Descriptions

#### 顶层 / Top-level

| Field | Type | Description |
|-------|------|-------------|
| total | integer | 已接入因子总数（`registry._computers` 的长度） |
| categories | array | 按 category 分组的因子列表 |
| summary | object | 全局汇总统计 |
| updated_at | string (ISO 8601) | 响应生成时间 |

#### categories[].factors[] / 单个因子条目

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| code | string | no | 因子唯一编码，点分式如 `technical.rsi.rsi_14` |
| name | string | no | 因子显示名称，从 definition 或编码推导 |
| subcategory | string | yes | 子分类，如 `ma`、`rsi`、`size` |
| description | string | yes | 因子简介，来自 factor_definitions.yaml |
| standardization | string | no | 标准化方法：`zscore` / `rank` / `minmax` / `none` |
| ic_threshold | float | no | IC 阈值，低于此值视为无效 |
| ic_value | float | yes | 实时 IC 值（当前批次），NULL 表示尚未计算（无数据） |
| ic_mean | float or null | yes | IC 序列均值（带符号，日频 `factor_ic_records` 序列），无序列时为 null。**F25②** |
| ic_std | float or null | yes | IC 序列标准差（样本标准差），无序列时为 null。**F25②** |
| ir | float or null | yes | IR = ic_mean / ic_std（信息比率），无序列时为 null。**F25②** |
| t_stat | float or null | yes | t 值 = ic_mean × √T / SE(Newey-West lag=1)，无序列时为 null。**F25②** |
| sample_count | integer | no | IC 累计**交易日数**（`count(distinct trade_date)`，日频 1 行/因子）。旧实现为刷新次数（240×虚高），F25① 修正 |

#### summary / 汇总

| Field | Type | Description |
|-------|------|-------------|
| valid | integer | 统计显著因子数（交易日 ≥250 且 t≥2 且 \|IR\|≥0.5）。F25② 替换旧「\|IC\|≥阈值」判据 |
| warn | integer | 有样本但统计不显著（交易日 ≥250 但 t<2 或 \|IR\|<0.5）的因子数 |
| no_data | integer | IC 值缺失或交易日 <250（积累中，含可观察档）的因子数 |
| static | integer | 静态/市场级因子数（不参与 IC 统计） |
| avg_ic | float or null | 所有有效 IC 值的绝对值均值，无数据时为 null |
| min_samples | integer | 有效门槛交易日数（`MIN_TRADING_DAYS=250`）。**F32**：前端读此键而非硬编码 30 |
| observable_days | integer | 可观察下限交易日数（`MIN_OBSERVABLE_DAYS=60`）。**F25②** |
| significant | integer | 与 `valid` 同值（统计显著数，兼容前端 IC 卡「统计显著因子 N」标签）。**F25②④** |
| observable | integer | 交易日 ≥60 但 <250（可观察、未达有效门槛）的因子数。**F25②④** |

> **状态语义（F25②，2026-08-14 决策）**：
> - `no_data`：交易日 <60 →「积累中」；60 ≤ 交易日 <250 →「积累中（可观察）」
> - `warn`：交易日 ≥250 但 t<2 或 \|IR\|<0.5 →「有样本但统计不显著」
> - `valid`：交易日 ≥250 且 t≥2 且 \|IR\|≥0.5 →「统计显著」
> - 旧 `MIN_IC_SAMPLES=30`（刷新次数冒充样本）判据已废弃。

### 顶层新增字段（P2-1，合并自 ic.md） / Top-level Fields

> **合并说明（P2-1, 2026-08-09）**: 原独立 IC 端点 `/factors/ic` 已删除，IC 追踪数据并入本端点。
> IC 排序表数据直接读 `categories[].factors[]`（每项含 `code/name/category/ic_value/sample_count/status`），
> 无需独立 IC 端点。原 ic.md 的零值占比字段保留在顶层：| Field | Type | Description |
|-------|------|-------------|
| zero_ratio | object | code → 零值占比（1.0 = 全部样本为 0 → 数据源未接入；区分「数据缺失」与「IC 无效」，F3-4 步骤D） |

### 错误响应 / Error Response

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| 500 | Internal Server Error | 服务端异常（如 registry 未初始化） |

---

## 4. 示例 / Examples

### 请求示例 / Request Example

```
GET /api/v1/factors/active
```

### 响应示例 / Response Example

```json
{
  "total": 3,
  "categories": [
    {
      "name": "technical",
      "count": 2,
      "description": "技术指标因子：基于价格和成交量的技术分析指标",
      "avg_ic": 0.0388,
      "valid_count": 1,
      "warn_count": 0,
      "no_data_count": 1,
      "factors": [
        {
          "code": "technical.rsi.rsi_14",
          "name": "Rsi 14",
          "subcategory": "rsi",
          "description": "14日相对强弱指数",
          "standardization": "zscore",
          "ic_threshold": 0.02,
          "ic_value": 0.0452
        },
        {
          "code": "technical.macd.macd",
          "name": "Macd",
          "subcategory": "macd",
          "description": "MACD 值",
          "standardization": "zscore",
          "ic_threshold": 0.02,
          "ic_value": null
        }
      ]
    }
  ],
  "summary": {
    "valid": 1,
    "warn": 0,
    "no_data": 1,
    "avg_ic": 0.0452
  },
  "updated_at": "2025-01-17T12:00:00+00:00"
}
```

---

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route `GET /api/v1/factors/active` | ✅ | ✅ | Method + path |
| Response `total` (integer) | ✅ | ✅ | `len(registry._computers)` |
| Response `categories[]` | ✅ | ✅ | 按 category 名排序 |
| `categories[].name` | ✅ | ✅ | 与 CATEGORY_DESCRIPTIONS key 对应 |
| `categories[].count` | ✅ | ✅ | 该分类因子数 |
| `categories[].description` | ✅ | ✅ | 中文描述，缺省空串 |
| `categories[].avg_ic` | ✅ | ✅ | 该分类 IC 均值，可为 null |
| `categories[].valid_count` | ✅ | ✅ | 有效因子计数 |
| `categories[].warn_count` | ✅ | ✅ | 低于阈值计数 |
| `categories[].no_data_count` | ✅ | ✅ | 无数据计数 |
| `factors[].code` | ✅ | ✅ | 编码 |
| `factors[].name` | ✅ | ✅ | 显示名 |
| `factors[].subcategory` | ✅ | ✅ | 子分类 |
| `factors[].description` | ✅ | ✅ | 简介 |
| `factors[].standardization` | ✅ | ✅ | 标准化方法 |
| `factors[].ic_threshold` | ✅ | ✅ | IC 阈值 |
| `factors[].ic_value` | ✅ | ✅ | null = 无数据 |
| `summary.valid` | ✅ | ✅ | 全局有效数 |
| `summary.warn` | ✅ | ✅ | 全局警告数 |
| `summary.no_data` | ✅ | ✅ | 全局无数据数 |
| `summary.avg_ic` | ✅ | ✅ | 全局平均 |IC| |
| Loading state | ✅ | N/A | Spinner |
| Error state | ✅ | N/A | Error message + retry |
| Empty state | ✅ | N/A | 分类内无因子时显示"暂无已接入因子" |

<!-- 路由登记（P3-5 check_routes 门禁） -->
GET /api/v1/factors/active
GET /api/v1/factors/model
