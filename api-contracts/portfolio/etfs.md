# Portfolio ETF CRUD / 投资组合 ETF 增删改查

## 1. 概述 / Overview

管理投资组合中的 ETF 持仓（增、删、改、查）。

Manage ETF holdings in the portfolio (Create, Read, Update, Delete).

---

## 2. 端点定义 / Endpoints

### 2.1 列表查询 / List ETFs

```
GET /api/v1/portfolio/etfs
```

**查询参数 / Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| portfolio_type | string | No | — | Filter: `on_exchange` \| `off_exchange` |

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "id": 1,
    "symbol": "159338",
    "name": "国泰中证A500ETF",
    "short_name": "国泰A500ETF",
    "asset_type": "A",
    "target_weight": 0.26,
    "portfolio_type": "on_exchange",
    "tracked_index": null,
    "is_active": true
  }
]
```

**字段说明 / Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| id | int | Auto-generated primary key |
| symbol | string | ETF trading code |
| name | string | Full Chinese name |
| short_name | string | Short display name |
| asset_type | string | `A` \| `HK` \| `US` \| `other` |
| target_weight | float | Target allocation weight (0–1) |
| portfolio_type | string | `on_exchange` (场内) \| `off_exchange` (场外) |
| tracked_index | string \| null | Underlying index symbol for off-exchange funds |
| is_active | boolean | Soft-delete flag |
| avg_cost | float \| null | Average cost basis per share (CNY) |
| shares_held | float \| null | Number of shares currently held |
| cost_basis | float \| null | Total cost basis = avg_cost * shares_held (CNY) |
| first_buy_date | string \| null | ISO date of first purchase (YYYY-MM-DD) |
| last_trade_date | string \| null | ISO date of last trade (YYYY-MM-DD) |

---

### 2.2 新增 / Create ETF

```
POST /api/v1/portfolio/etfs
```

**请求体 / Request Body:**

```json
{
  "symbol": "510050",
  "name": "华夏上证50ETF",
  "short_name": "上证50ETF",
  "asset_type": "A",
  "target_weight": 0.10,
  "portfolio_type": "on_exchange",
  "tracked_index": null,
  "avg_cost": 2.45,
  "shares_held": 10000,
  "first_buy_date": "2024-01-15"
}
```

**成功响应 / Success Response — `201 Created`:**

```json
{
  "id": 14,
  "symbol": "510050",
  "name": "华夏上证50ETF",
  "short_name": "上证50ETF",
  "asset_type": "A",
  "target_weight": 0.10,
  "portfolio_type": "on_exchange",
  "tracked_index": null,
  "is_active": true
}
```

---

### 2.3 更新 / Update ETF

```
PUT /api/v1/portfolio/etfs/{symbol}
```

**路径参数 / Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| symbol | string | ETF trading code to update |

**请求体 / Request Body** (all fields optional):

```json
{
  "name": "新名称",
  "target_weight": 0.15,
  "is_active": true,
  "portfolio_type": "on_exchange",
  "short_name": "简称",
  "tracked_index": null,
  "avg_cost": 2.45,
  "shares_held": 12000,
  "first_buy_date": "2024-01-15",
  "last_trade_date": "2024-06-20"
}
```

**成功响应 / Success Response — `200 OK`:** Returns the updated ETF object (same schema as create).

**错误 / Error — `404 Not Found`:**

```json
{ "detail": "ETF not found" }
```

---

### 2.4 删除 / Delete ETF

```
DELETE /api/v1/portfolio/etfs/{symbol}
```

**路径参数 / Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| symbol | string | ETF trading code to soft-delete |

**成功响应 / Success Response — `204 No Content`:** No body.

**错误 / Error — `404 Not Found`:**

```json
{ "detail": "ETF not found" }
```

---

## 3. Schema Definitions / 公共数据结构

### PortfolioETFCreate

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | string | Yes | Trading code |
| name | string | Yes | Full name |
| short_name | string | No | Short name |
| asset_type | string | Yes | `A` \| `HK` \| `US` \| `other` |
| target_weight | float | Yes | 0–1 |
| portfolio_type | string | Yes | `on_exchange` \| `off_exchange` |
| tracked_index | string | No | Index symbol for off-exchange |

### PortfolioETFUpdate

All fields optional. Same names as above.

### PortfolioETFResponse

Same as the list response object above.

---

## 4. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | Missing required fields or invalid `target_weight` (not 0–1) |
| 404 | Not Found | ETF symbol does not exist (update/delete) |
| 409 | Conflict | Duplicate symbol (create) |
| 500 | Internal Server Error | Unexpected server error |

---

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `GET /etfs` returns array | ☐ | ☐ | |
| `GET /etfs?portfolio_type=on_exchange` filters | ☐ | ☐ | |
| `POST /etfs` returns 201 | ☐ | ☐ | |
| `PUT /etfs/{symbol}` returns updated object | ☐ | ☐ | |
| `DELETE /etfs/{symbol}` returns 204 | ☐ | ☐ | |
| 400 on invalid weight (not 0–1) | ☐ | ☐ | |
| 404 on nonexistent symbol | ☐ | ☐ | |
| Loading skeleton in list view | ☐ | N/A | |
| Empty state when no ETFs | ☐ | N/A | |
| Error toast on 4xx/5xx | ☐ | N/A | |
