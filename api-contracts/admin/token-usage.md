# Admin — Token Usage Monitoring / Token 用量监控

## 1. 概述 / Overview

**功能描述 / Description**: 监控 DeepSeek/OpenCode Zen 等 LLM 提供商的 API token 消耗、调用次数、失败记录和时间序列趋势。

**触发场景 / Trigger**: TokenMonitor 页面加载时自动获取；用户切换时间粒度时重新获取。

---

## 2. 端点定义 / Endpoints

### 2.1 Token 用量概览 / Token Usage Summary

```
GET /api/v1/admin/token-usage
```

**成功响应 — `200 OK`:**

```json
{
  "total": {
    "calls": 1234,
    "tokens": 567890,
    "prompt_tokens": 400000,
    "completion_tokens": 167890,
    "error_rate": 2.3
  },
  "daily": {
    "calls": 45,
    "tokens": 23456,
    "error_rate": 1.1,
    "date": "2026-07-25"
  },
  "monthly": {
    "calls": 890,
    "tokens": 400000
  },
  "by_function": {
    "market_report": {
      "calls": 230,
      "prompt_tokens": 150000,
      "completion_tokens": 50000,
      "total_tokens": 200000
    },
    "advice": {
      "calls": 180,
      "prompt_tokens": 120000,
      "completion_tokens": 40000,
      "total_tokens": 160000
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| total | object | 累计统计（所有历史数据） |
| total.calls | int | 总调用次数 |
| total.tokens | int | 总 token 消耗 |
| total.prompt_tokens | int | 总 prompt token 数 |
| total.completion_tokens | int | 总 completion token 数 |
| total.error_rate | float | 错误率（百分比，如 2.3） |
| daily | object | 今日统计 |
| monthly | object | 本月统计 |
| by_function | object | 按功能分类的细分统计 |

### 2.2 Token 时间序列 / Token Timeseries

```
GET /api/v1/admin/token-usage/timeseries
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| granularity | string | No | `"day"` | 聚合粒度: `hour` \| `day` \| `month` |
| days | int | No | 30 | 按天时近 N 天 (1-365) |
| months | int | No | 12 | 按月时近 N 月 (1-60) |
| hours | int | No | 48 | 按小时时近 N 小时 (1-720) |

**成功响应 — `200 OK`:**

```json
{
  "granularity": "day",
  "days": 30,
  "series": [
    {
      "date": "07-01",
      "total_tokens": 15000,
      "calls": 30
    },
    {
      "date": "07-02",
      "total_tokens": 22000,
      "calls": 45
    }
  ]
}
```

**按月粒度返回:**

```json
{
  "granularity": "month",
  "series": [
    {
      "date": "2026-01",
      "total_tokens": 150000,
      "calls": 300
    }
  ]
}
```

**按小时粒度返回:**

```json
{
  "granularity": "hour",
  "hours": 48,
  "series": [
    {
      "date": "07-25 09:00",
      "total_tokens": 5000,
      "calls": 8
    }
  ]
}
```

### 2.3 Token 失败记录 / Token Failures

```
GET /api/v1/admin/token-usage/failures
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | int | No | 50 | 返回最近 N 条 (1-200) |

**成功响应 — `200 OK`:**

```json
{
  "failures": [
    {
      "time": "2026-07-25T10:30:00",
      "function": "market_report",
      "error": "Rate limit exceeded",
      "duration_ms": 3200
    }
  ]
}
```

---

## 3. 已知断裂点 / Known Breakage ⚠️

### tokenTimeseries 前端调用与 API 函数签名不一致

**位置**: `frontend/src/api/index.js:87` 和 `frontend/src/components/TokenMonitor.vue`

**问题**: `api/index.js` 定义为 `tokenTimeseries: (granularity = 'day', days = 30)`（位置参数），但 `TokenMonitor.vue` 调用 `adminApi.tokenTimeseries(tsParams)` 传入一个对象 `{granularity, days, months, hours}`。

**实际效果**: `granularity` 形参收到整个对象，`days` 保持默认 30，导致 URL 参数为 `granularity=[object Object]&days=30`。

**修复方案**: 将 `api/index.js` 的 `tokenTimeseries` 改为接收对象参数：
```js
tokenTimeseries: (params = {}) => api.get('/admin/token-usage/timeseries', { params })
```

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `token-usage` 返回 summary 含 total/daily/by_function | ✅ | ✅ | TokenMonitor.vue 消费 summary.total.calls, summary.daily.calls, summary.by_function 等 |
| `token-usage/timeseries` 返回 series 数组 | ✅ | ✅ | TokenMonitor.vue 消费 dates/total_tokens/calls |
| `token-usage/failures` 返回失败列表 | ✅ | ✅ | 消费 failures[].time/function/error |
| **tokenTimeseries 参数传递断裂** | ❌ | ❌ | 见 §3 需修复 |
