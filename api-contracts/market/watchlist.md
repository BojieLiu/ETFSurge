# Market Watchlist / 自选列表

## 1. 概述 / Overview

**功能描述 / Description**: 管理用户的自选/关注标的列表，支持增删改查，并在行情页面快速查看自选标的的实时行情。

Manage user's watchlist of symbols for quick access to real-time quotes.

**触发场景 / Trigger**: 用户想要关注某些标的但暂不买入，需要一个自选列表进行跟踪。

---

## 2. 端点定义 / Endpoints

### 2.1 获取自选列表 / List Watchlist

```
GET /api/v1/market/watchlist
```

#### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | integer | No | 100 | 返回最大条数 |
| offset | integer | No | 0 | 分页偏移量 |

#### 成功响应 / Success Response — `200 OK`

```json
{
  "items": [
    {
      "id": 1,
      "symbol": "510050",
      "name": "华夏上证50ETF",
      "asset_type": "A",
      "added_at": "2024-01-15T10:30:00Z",
      "notes": "长期跟踪",
      "realtime": {
        "price": 2.56,
        "change_pct": 1.25,
        "volume": 123456789
      }
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

---

### 2.2 添加自选 / Add to Watchlist

```
POST /api/v1/market/watchlist
```

#### 请求体 / Request Body

```json
{
  "symbol": "510050",
  "asset_type": "A",
  "notes": "长期跟踪"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | string | Yes | 标的代码 |
| asset_type | string | No | `A` \| `HK` \| `US` \| `index` \| `commodity` (默认 `A`) |
| notes | string | No | 备注信息 |

#### 成功响应 / Success Response — `201 Created`

```json
{
  "id": 1,
  "symbol": "510050",
  "name": "华夏上证50ETF",
  "asset_type": "A",
  "added_at": "2024-01-15T10:30:00Z",
  "notes": "长期跟踪"
}
```

---

### 2.3 更新自选 / Update Watchlist Item

```
PUT /api/v1/market/watchlist/{id}
```

#### 路径参数 / Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| id | integer | 自选列表项 ID |

#### 请求体 / Request Body (all fields optional)

```json
{
  "notes": "更新备注",
  "asset_type": "A"
}
```

#### 成功响应 / Success Response — `200 OK`

Returns updated watchlist item (same schema as list item).

---

### 2.4 删除自选 / Remove from Watchlist

```
DELETE /api/v1/market/watchlist/{id}
```

#### 路径参数 / Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| id | integer | 自选列表项 ID |

#### 成功响应 / Success Response — `204 No Content`

---

### 2.5 批量删除 / Batch Remove

```
DELETE /api/v1/market/watchlist
```

#### 请求体 / Request Body

```json
{
  "ids": [1, 2, 3]
}
```

#### 成功响应 / Success Response — `200 OK`

```json
{
  "deleted": 3
}
```

---

## 3. 数据模型 / Data Models

### WatchlistItem (响应)

| Field | Type | Description |
|-------|------|-------------|
| id | integer | 自增主键 |
| symbol | string | 标的代码 |
| name | string | 标的名称（从行情服务获取） |
| asset_type | string | `A` \| `HK` \| `US` \| `index` \| `commodity` |
| added_at | string (ISO datetime) | 添加时间 |
| notes | string \| null | 用户备注 |
| realtime | object \| null | 实时行情快照（可选，含 price, change_pct, volume） |

### WatchlistCreate (请求)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | string | Yes | 标的代码 |
| asset_type | string | No | 默认 `A` |
| notes | string | No | 备注 |

### WatchlistUpdate (请求)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| notes | string | No | 备注 |
| asset_type | string | No | 资产类型 |

---

## 4. 错误码 / Error Codes

| Status Code | Meaning | When |
|-------------|---------|------|
| 400 | Bad Request | 参数校验失败、symbol 格式错误 |
| 404 | Not Found | Watchlist 项不存在 |
| 409 | Conflict | 重复添加同一 symbol |
| 500 | Internal Server Error | 服务端异常 |

---

## 5. 示例 / Examples

### 添加自选 / Add to Watchlist

```
POST /api/v1/market/watchlist
Content-Type: application/json

{
  "symbol": "159915",
  "asset_type": "A",
  "notes": "创业板ETF，长期定投"
}
```

### 获取自选列表 / Get Watchlist

```
GET /api/v1/market/watchlist?limit=50
```

---

## 6. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | Method + path |
| Request body fields match | ☐ | ☐ | Name + type + required |
| Response body fields match | ☐ | ☐ | Name + type + structure |
| Error codes handled | ☐ | ☐ | 400/404/409/500 |
| Loading state | ☐ | N/A | Skeleton / spinner |
| Empty state | ☐ | N/A | "暂无自选，点击添加" |
| Error state | ☐ | N/A | Error toast / message |