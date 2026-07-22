# Source Event Monitoring API / 数据源事件监控接口

## 1. Overview / 概述

**功能描述 / Description**: Real-time monitoring of data source health, event timeline, failures, and circuit-breaker status for all upstream data fetchers (mootdx, sina, tencent, akshare, levistock, twelvedata, finnhub, dongfang).

**触发场景 / Trigger**: Admin dashboard display (aligned with TokenMonitor style), operational alerting.

---

## 2. Endpoints / 端点

### 2.1 Source Health Overview / 源健康概览

```
GET /api/v1/admin/sources/health
```

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "name": "mootdx",
    "available": true,
    "failures": 0,
    "cooldown_remaining": 0.0,
    "last_ok": 1721620000.0
  },
  {
    "name": "sina",
    "available": true,
    "failures": 1,
    "cooldown_remaining": 0.0,
    "last_ok": 1721620000.0
  }
]
```

### 2.2 Event Timeline / 事件时间线

```
GET /api/v1/admin/sources/events/timeline?hours=1
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| hours | int | No | 1 | Look-back window in hours |

**成功响应 / Success Response — `200 OK`:**

```json
[
  {"bucket": "2026-07-22T10:00:00", "success": 12, "failure": 1, "total": 13},
  {"bucket": "2026-07-22T10:01:00", "success": 8, "failure": 0, "total": 8}
]
```

### 2.3 Recent Failures / 最近失败事件

```
GET /api/v1/admin/sources/events/failures?limit=10
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | int | No | 10 | Max records to return (max 100) |

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "id": 1,
    "source_name": "mootdx",
    "route": "A_stock_realtime",
    "operation": "realtime",
    "target": "510050",
    "error_message": "Connection timeout",
    "duration_ms": 6002.5,
    "timestamp": 1721620000.0
  }
]
```

### 2.4 Circuit Breaker Status / 熔断器状态

```
GET /api/v1/admin/sources/circuit-breakers
```

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "name": "mootdx",
    "state": "closed",
    "failure_threshold": 3,
    "cooldown_secs": 60.0,
    "failures_since_last_ok": 0
  }
]
```

---

## 3. Data Model / 数据模型

### source_events 表 (SQLite: `data/source.db`)

```sql
CREATE TABLE IF NOT EXISTS source_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name     TEXT    NOT NULL,
    route           TEXT    NOT NULL DEFAULT '',
    operation       TEXT    NOT NULL DEFAULT 'realtime',
    target          TEXT    NOT NULL DEFAULT '',
    success         INTEGER NOT NULL,
    duration_ms     REAL    NOT NULL DEFAULT 0,
    error_message   TEXT    NOT NULL DEFAULT '',
    timestamp       REAL    NOT NULL
);
```

---

## Frontend-Backend Checklist

- [ ] Write SourceEventStore (monitor/source_events.py)
- [ ] Add on_event callback to SourceHealth (source_registry.py)
- [ ] Add set_event_callback to SourceRegistry
- [ ] Add route_name parameter to route()
- [ ] Wire callback in main.py
- [ ] Admin API endpoints implemented
- [ ] Backend unit tests pass
- [ ] E2E verification passes
