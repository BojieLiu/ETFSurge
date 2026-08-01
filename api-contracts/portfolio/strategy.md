# Strategy Check & Apply / 策略检查与调仓

> **⚠️ 2026-07-26 修正**: 原契约文档化的同步版策略检查（`POST /portfolio/strategy-check`）在 `61ecc2d` 中被重构为异步版本，**实际路由已不存在**（T11 校准：现为 `POST /portfolio/strategy-check-async`）。以下已更新为正确的异步端点和轮询结果获取端点。

## 1. 概述 / Overview

调用 LLM 分析当前组合，生成策略调整建议（权重调整、替换、维持不变），并支持一键应用建议。

Use LLM to analyze the current portfolio, generate strategy suggestions (weight adjustment, replacement, or hold), and apply them in one click.

---

## 2. 端点定义 / Endpoints

### 2.1 启动异步策略检查 / Launch Async Strategy Check

```
POST /api/v1/portfolio/strategy-check-async
```

**请求体 / Request Body:**

```json
{
  "total_capital": 1000000.00,
  "portfolio_type": "on_exchange"
}
```

**成功响应 / Success Response — `202 Accepted`:**

```json
{
  "task_id": 42,
  "status": "pending",
  "created_at": "2026-07-25T10:30:00"
}
```

---

### 2.2 获取策略检查结果 / Get Strategy Check Result

```
GET /api/v1/portfolio/strategy-check-result/{task_id}
```

**成功响应 / Success Response — `200 OK`（已完成）:**

**成功响应 / Success Response — `200 OK`:**

```json
{
  "summary": "当前组合进攻性偏强，建议适度增加防御型ETF配置",
  "suggestions": [
    {
      "action": "decrease",
      "symbol": "159338",
      "name": "中证A500ETF",
      "current_weight": 0.26,
      "suggested_weight": 0.20,
      "reason": "单只权重超过20%，建议回归基准线",
      "confidence": "high"
    }
  ],
  "holdings_analysis": [
    {
      "symbol": "510300",
      "name": "沪深300ETF",
      "factor_summary": "动量因子+0.8σ，估值因子+0.3σ，流动性充足",
      "tech_signal": "MACD金叉，RSI中性偏强(58)",
      "risk_flag": null
    }
  ],
  "risk_warnings": [
    {
      "type": "concentration",
      "severity": "high",
      "description": "行业集中度过高（半导体+AI合计35%）",
      "affected_symbols": ["512480", "561300"]
    }
  ],
  "market_regime": "correction",
  "raw_llm": "{...}"
}
```

**字段说明 / Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| summary | string | Natural language summary of the strategy analysis |
| suggestions | array | List of actionable suggestions |
| suggestions[].action | string | `increase` \| `decrease` \| `hold` \| `add` \| `remove` |
| suggestions[].symbol | string | ETF trading code |
| suggestions[].name | string | ETF display name |
| suggestions[].current_weight | float | Current target weight (decimal, 0.30 = 30%) |
| suggestions[].suggested_weight | float | Suggested target weight (decimal) |
| suggestions[].reason | string | Data-driven justification |
| suggestions[].confidence | string | `high` \| `medium` \| `low` |
| holdings_analysis | array | Per-holding technical & factor breakdown |
| holdings_analysis[].symbol | string | ETF code |
| holdings_analysis[].name | string | ETF name |
| holdings_analysis[].factor_summary | string | Factor score summary |
| holdings_analysis[].tech_signal | string | Technical signal text |
| holdings_analysis[].risk_flag | string/null | Risk indicator if any |
| risk_warnings | array | Portfolio-level risk alerts |
| risk_warnings[].type | string | `concentration` \| `drift` \| `correlation` \| `volatility` \| `liquidity` |
| risk_warnings[].severity | string | `high` \| `medium` \| `low` |
| risk_warnings[].description | string | Detailed warning |
| risk_warnings[].affected_symbols | array | Related ETF codes |
| market_regime | string | Current market regime |
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
| `strategy-check-async` launches task (returns task_id) | ✅ | ✅ | frontend calls `portfolioApi.strategyCheck(data)` |
| `strategy-check-result/{task_id}` returns summary + suggestions | ✅ | ✅ | frontend polls with `getStrategyCheckResult(taskId)` |
| `strategy-checks` history list | ✅ | ✅ | frontend calls `listStrategyChecks(20,0)` |
| `strategy-check-async` handles empty portfolio | ☐ | ☐ | Returns "组合为空" message |
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
