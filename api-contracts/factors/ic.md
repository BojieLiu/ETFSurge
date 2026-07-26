# Contract: Factor IC Tracking API

> 文件: `api-contracts/factors/ic.md`
>
> IC 追踪器 API — 提供因子有效性（Information Coefficient）数据，
> 用于评估每个核心因子对未来收益的预测能力。

---

## 1. 概述 / Overview

**功能描述 / Description**:
返回当前所有核心因子的 Spearman Rank IC 值列表。

**触发场景 / Trigger**:
- 组合设计后查看因子有效性
- AI 报告生成时引用因子 EV 数据
- 调试/监控时验证因子 pipeline 是否正常

---

## 2. 端点定义 / Endpoint

```
GET /api/v1/factors/ic
```

### 查询参数 / Query Parameters

无

### 请求体 / Request Body

无

---

## 3. 响应定义 / Response

### 正常响应 / Success (200)

```json
{
  "factors": [
    {
      "code": "style.size.ln_mcap",
      "name": "对数总市值",
      "category": "style",
      "ic_value": 0.035,
      "sample_count": 156
    }
  ],
  "total": 33,
  "updated_at": "2026-07-26T10:30:00"
}
```

**JSON Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "factors": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "code": { "type": "string", "description": "Factor unique code (e.g. technical.rsi.rsi_14)" },
          "name": { "type": "string", "description": "Human-readable factor name (Chinese or English)" },
          "category": { "type": "string", "description": "Factor category prefix (style/technical/etf/sentiment/china)" },
          "ic_value": { "type": "number", "description": "Spearman rank IC value (-1 to 1)" },
          "sample_count": { "type": "integer", "description": "Number of symbols used for IC computation" }
        },
        "required": ["code", "ic_value", "sample_count"]
      }
    },
    "total": { "type": "integer", "description": "Total number of factors with computed IC" },
    "updated_at": { "type": "string", "description": "ISO 8601 timestamp of the IC computation" }
  },
  "required": ["factors", "total", "updated_at"]
}
```

### 错误响应 / Error (500)

```json
{
  "detail": "IC data not available"
}
```

---

## 4. API 行为 / Behavior

- **数据来源**: `FactorRegistry._last_ic_batch` — 每次 `compute()` 调用时自动更新
- **刷新时机**: 每次因子计算（全市场扫描）后更新
- **空值处理**: 因子有效数据不足 3 个标的时，IC 返回 0.0
- **精度**: IC 值保留 4 位小数

---

## 5. Frontend-Backend Checklist

| # | Item | Status |
|---|------|--------|
| 1 | `GET /api/v1/factors/ic` returns 200 with factors array | ❌ |
| 2 | Each factor has `code`, `ic_value`, `sample_count` | ❌ |
| 3 | `total` field matches array length | ❌ |
| 4 | `updated_at` is valid ISO 8601 | ❌ |
| 5 | Backend unit tests for API exist | ❌ |
| 6 | verify_e2e.py includes IC endpoint check | ❌ |
