# Contract Template / 契约模板

Use this template when adding a new API endpoint. Copy to `api-contracts/<module>/<feature>.md` and fill in all sections.

添加新 API 端点时使用此模板。复制到 `api-contracts/<module>/<feature>.md` 并填写所有部分。

---

## 1. 概述 / Overview

**功能描述 / Description**: <!-- one-line summary -->

**触发场景 / Trigger**: <!-- when is this endpoint called? -->

---

## 2. 端点定义 / Endpoint

```
METHOD /api/v1/<module>/<action>
```

### 请求头 / Request Headers

| Header | Type | Required | Description |
|--------|------|----------|-------------|
| Content-Type | string | Yes | `application/json` |

### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| — | — | — | — | — |

### 请求体 / Request Body

```json
{
  "field_name": "<type>  // <description>",
  "field_name_2": "<type>"
}
```

**JSON Schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "field_name": { "type": "<type>", "description": "<desc>" }
  },
  "required": ["field_name"]
}
```

---

## 3. 响应定义 / Response

### 成功响应 / Success Response

**Status Code:** `200 OK`

```json
{
  "field_name": "<type>  // <description>"
}
```

### 错误响应 / Error Response

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| 400 | Bad Request | 参数校验失败 |
| 404 | Not Found | 资源不存在 |
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
POST /api/v1/<module>/<action>
Content-Type: application/json

{
  "field_name": "value"
}
```

### 响应示例 / Response Example

```json
{
  "field_name": "result"
}
```

---

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | Method + path |
| Request body fields match | ☐ | ☐ | Name + type + required |
| Response body fields match | ☐ | ☐ | Name + type + structure |
| Error codes handled | ☐ | ☐ | 400/404/500 |
| Loading state | ☐ | N/A | Skeleton / spinner |
| Empty state | ☐ | N/A | No-data display |
| Error state | ☐ | N/A | Error toast / message |
