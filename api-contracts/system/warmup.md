# Warmup Status API / 系统预热状态

## 1. 概述 / Overview

**功能描述 / Description**: 返回后端各数据预热任务的完成状态，供前端判断系统是否初始化就绪。

**触发场景 / Trigger**: 前端页面挂载时轮询（每 5 秒一次），直到 `all_done` 为 `true`。

---

## 2. 端点定义 / Endpoint

```
GET /api/v1/system/warmup
```

### 请求头 / Request Headers

无。

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
  "warmup": {
    "market_cache": {
      "done": true,
      "success": true,
      "label": "行情缓存"
    },
    "global_indices": {
      "done": true,
      "success": true,
      "label": "全球指数"
    },
    "etf_cache": {
      "done": false,
      "success": false,
      "label": "ETF 扫描"
    }
  },
  "all_done": false,
  "elapsed_seconds": 12.5
}
```

### 字段说明 / Field Description

| 字段 | 类型 | 说明 |
|------|------|------|
| `warmup` | object | 各预热任务的完成状态 |
| `warmup.*.done` | boolean | 是否已完成（成功或超时均算完成） |
| `warmup.*.success` | boolean | 是否成功完成 |
| `warmup.*.label` | string | 中文描述标签 |
| `all_done` | boolean | 所有预热任务是否都已结束 |
| `elapsed_seconds` | number | 自服务启动以来的秒数 |

### 错误响应 / Error Response

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| 404 | Not Found | 无此端点（尚未注册） |
| 500 | Internal Server Error | 服务端异常 |

**Error body:**

```json
{
  "detail": "<error message>"
}
```

---

## 4. 示例 / Examples

### 请求示例 / Request Example

```
GET /api/v1/system/warmup
```

### 响应示例 / Response Example

```json
{
  "warmup": {
    "market_cache": {"done": true, "success": true, "label": "行情缓存"},
    "global_indices": {"done": true, "success": true, "label": "全球指数"},
    "etf_cache": {"done": false, "success": false, "label": "ETF 扫描"}
  },
  "all_done": false,
  "elapsed_seconds": 12.5
}
```

---

## 5. 前端消费说明

前端 `useWarmupStatus.js` composable 负责轮询此端点：

1. 页面挂载时开始轮询，间隔 5s
2. 每次响应更新 warmup 状态和阶段文字
3. 当 `all_done === true` 时停止轮询并通知消费方
4. 组件卸载时自动清除轮询定时器
5. 最多轮询 120s（24 次），超时后标记为"超时"状态

---

## 6. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | GET `/api/v1/system/warmup` |
| Response body fields match | ☐ | ☐ | `warmup`, `all_done`, `elapsed_seconds` |
| Error codes handled | ☐ | ☐ | 404/500 |
| Warmup state shape matches | ☐ | ☐ | 3 tasks × {done, success, label} |
| Polling interval | ☐ | N/A | 5s, max 120s |
| Loading state | ☐ | N/A | 使用 warmup 状态 + loading 骨架屏 |
| Empty state | ☐ | N/A | 轮询完成但无数据时显示空组合 |
| Error state | ☐ | N/A | 后端不可达时 toast 提示 |
