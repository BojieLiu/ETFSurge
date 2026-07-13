# Strategy Check & Apply / 策略检查与调仓

## 1. 概述 / Overview

调用 LLM 分析当前组合，生成策略调整建议（权重调整、替换、维持不变），并支持一键应用建议。

Use LLM to analyze the current portfolio, generate strategy suggestions (weight adjustment, replacement, or hold), and apply them in one click.

---

## 2. 端点定义 / Endpoints

### 2.1 策略检查 / Strategy Check

```
POST /api/v1/portfolio/strategy-check
```

**请求体 / Request Body:**

```json
{
  "total_capital": 1000000.00
}
```

**成功响应 / Success Response — `200 OK`:**

```json
{
  "summary": "当前组合进攻性偏强，建议适度增加防御型ETF配置",
  "suggestions": [
    {
      "name": "降低A500权重",
      "condition": "A500ETF权重26%，超过单只上限20%",
      "action": "adjust_weight",
      "risk_control": "单次调整不超过5%",
      "confidence": "high"
    }
  ],
  "raw_llm": "{...}"
}
```

**字段说明 / Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| summary | string | Natural language summary of the strategy analysis |
| suggestions | array | List of actionable suggestions |
| suggestions[].name | string | Short suggestion title |
| suggestions[].condition | string | Condition that triggered the suggestion |
| suggestions[].action | string | `adjust_weight` \| `replace` \| `no_change` |
| suggestions[].risk_control | string | Risk control note |
| suggestions[].confidence | string | `high` \| `medium` \| `low` |
| raw_llm | string | Raw LLM response (for debugging) |

---

### 2.2 应用策略 / Apply Strategy Suggestions

```
POST /api/v1/portfolio/apply-strategy
```

**请求体 / Request Body:**

```json
{
  "suggestions": [
    {
      "symbol": "159338",
      "action": "adjust_weight",
      "weight": -0.03,
      "reason": "降低A500权重以控制集中度"
    }
  ]
}
```

**字段说明 / Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| suggestions | array | Yes | List of strategy actions |
| suggestions[].symbol | string | Yes | ETF trading code |
| suggestions[].action | string | Yes | `adjust_weight` \| `replace` \| `add` |
| suggestions[].weight | float | No | Weight change value (absolute for `replace`/`add`, delta for `adjust_weight`) |
| suggestions[].reason | string | No | Human-readable reason |

**成功响应 / Success Response — `200 OK`:**

```json
{
  "symbols": [
    {
      "symbol": "159338",
      "name": "国泰中证A500ETF",
      "target_weight": 0.23
    }
  ],
  "applied": [
    {
      "symbol": "159338",
      "action": "adjust_weight",
      "status": "success",
      "message": "已调整 159338 权重"
    }
  ]
}
```

**字段说明 / Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| symbols | array | Updated ETF list after applying suggestions |
| applied | array | Per-suggestion execution results |
| applied[].status | string | `success` \| `error` |
| applied[].message | string | Human-readable execution message |

**错误 / Error Codes:**

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | Empty suggestions list or invalid action type |
| 500 | Internal Server Error | DB commit failure |

---

## 3. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `strategy-check` returns summary + suggestions | ☐ | ☐ | |
| `strategy-check` handles empty portfolio | ☐ | ☐ | Returns "组合为空" message |
| `apply-strategy` accepts suggestions array | ☐ | ☐ | |
| `apply-strategy` returns updated symbols | ☐ | ☐ | |
| Suggestion action `adjust_weight` adjusts weight correctly | ☐ | ☐ | |
| Suggestion action `replace` sets new weight | ☐ | ☐ | |
| Suggestion action `add` activates ETF | ☐ | ☐ | |
| Unknown action returns error status | ☐ | ☐ | |
| Unknown symbol returns error status | ☐ | ☐ | |
| Loading state during strategy check | ☐ | N/A | `checkingStrategy` |
| Loading state during apply | ☐ | N/A | `applyingPlan` |
| Error toast on failure | ☐ | N/A | |
