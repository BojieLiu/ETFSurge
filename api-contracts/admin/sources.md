# Admin — Source Health Monitoring / 数据源健康监控

## 1. 概述 / Overview

**功能描述 / Description**: 监控所有注册数据源的当前健康状态、熔断器状态、事件时间线趋势和最近的失败事件。

**触发场景 / Trigger**: SourceMonitor 页面加载时自动获取；用户点击刷新时重新获取。

---

## 2. 端点定义 / Endpoints

### 2.1 数据源健康状态 / Source Health

```
GET /api/v1/admin/sources/health
```

**成功响应 — `200 OK`:**

```json
[
  {
    "name": "mootdx",
    "available": true,
    "failures": 0,
    "cooldown_remaining": 0.0,
    "failure_threshold": 3,
    "cooldown_secs": 30
  },
  {
    "name": "sina",
    "available": true,
    "failures": 1,
    "cooldown_remaining": 0.0,
    "failure_threshold": 3,
    "cooldown_secs": 30
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| name | string | 数据源名称 (e.g. 'mootdx', 'sina', 'tencent', 'akshare', 'twelvedata') |
| available | bool | 当前是否可用（不在冷却期） |
| failures | int | 连续失败次数 |
| cooldown_remaining | float | 冷却剩余秒数 |
| failure_threshold | int | 触发熔断的失败阈值 |
| cooldown_secs | int | 熔断后的冷却时长 |

### 2.2 事件时间线 / Event Timeline

```
GET /api/v1/admin/sources/events/timeline
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| hours | float | No | 1 | 回溯小时数 (0.1–168) |

**成功响应 — `200 OK`:**

```json
[
  {
    "bucket": "2026-07-26T10:00:00+00:00",
    "success": 42,
    "failure": 1,
    "total": 43
  },
  {
    "bucket": "2026-07-26T10:01:00+00:00",
    "success": 38,
    "failure": 0,
    "total": 38
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| bucket | string (ISO 8601) | 时间桶的开始时间 |
| success | int | 桶内成功事件数 |
| failure | int | 桶内失败事件数 |
| total | int | 桶内总事件数 |

### 2.3 最近失败事件 / Recent Failures

```
GET /api/v1/admin/sources/events/failures
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | int | No | 10 | 返回最近 N 条 (1–100) |

**成功响应 — `200 OK`:**

```json
[
  {
    "source_name": "twelvedata",
    "route": "US_ETF",
    "operation": "realtime",
    "target": "SPY",
    "success": false,
    "duration_ms": 5032.1,
    "error_message": "Connection timeout",
    "timestamp": 1721978400.0
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| source_name | string | 数据源名称 |
| route | string | 业务路径名 (e.g. 'A_stock_realtime', 'US_ETF', 'probe') |
| operation | string | 操作类型 (e.g. 'realtime', 'history', 'probe') |
| target | string | 标的代码 |
| success | bool | 是否成功 (false for failures) |
| duration_ms | float | 调用耗时(毫秒) |
| error_message | string | 错误信息 |
| timestamp | float | Unix 时间戳 |

### 2.4 熔断器状态 / Circuit Breakers

```
GET /api/v1/admin/sources/circuit-breakers
```

**成功响应 — `200 OK`:**

```json
[
  {
    "name": "mootdx",
    "state": "closed",
    "failures": 0,
    "failure_threshold": 3,
    "cooldown": 30
  },
  {
    "name": "twelvedata",
    "state": "open",
    "failures": 5,
    "failure_threshold": 3,
    "cooldown": 30
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| name | string | 数据源名称 |
| state | string | 熔断状态: 'closed' / 'open' |
| failures | int | 连续失败次数 |
| failure_threshold | int | 触发熔断的阈值 |
| cooldown | int | 冷却时长(秒) |

---

## 3. 已知断裂点 / Known Breakage ⚠️

此为新功能，尚无已知断裂点。

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `sources/health` 返回源状态列表 | ✅ | ✅ | SourceMonitor 消费 name/available/failures |
| `sources/events/timeline?hours=1` 返回时间桶 | ✅ | ✅ | ECharts 折线图渲染 success/failure 双线 |
| `sources/events/failures?limit=10` 返回失败列表 | ✅ | ✅ | SourceMonitor 渲染失败事件表格 |
| `sources/circuit-breakers` 返回熔断状态 | ✅ | ✅ | SourceMonitor 显示熔断状态标识 |
| Loading state | ✅ | N/A | 骨架屏/loading spinner |
| Empty state | ✅ | N/A | "暂无数据" 占位 |
| Error state | ✅ | N/A | 错误 toast / 信息展示 |

<!-- 路由登记（P3-5 check_routes 门禁） -->
GET /api/v1/admin/sources/health
GET /api/v1/admin/sources/events/timeline
GET /api/v1/admin/sources/events/failures
GET /api/v1/admin/sources/circuit-breakers
GET /api/v1/admin/sources/connection-pool
GET /api/v1/admin/factor-health
GET /api/v1/admin/metrics
GET /api/v1/admin/thread-pool
