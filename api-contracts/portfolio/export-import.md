# Portfolio Export / Import / 投资组合导出导入

## 1. 概述 / Overview

导出组合持仓为 CSV（含成本基数、份额、买入日期），或从 CSV 批量导入/覆盖组合。

Export portfolio holdings to CSV (including cost basis, shares, buy dates) or bulk import/overwrite from CSV.

---

## 2. 端点定义 / Endpoints

### 2.1 导出 / Export

```
GET /api/v1/portfolio/export
```

#### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| portfolio_type | string | No | — | Filter: `on_exchange` \| `off_exchange` |
| format | string | No | `csv` | Output format: `csv` \| `json` |

#### 成功响应 / Success Response — `200 OK`

**CSV 格式** (Content-Type: `text/csv`):

```csv
symbol,name,short_name,asset_type,portfolio_type,target_weight,tracked_index,avg_cost,shares_held,cost_basis,first_buy_date,last_trade_date
159338,国泰中证A500ETF,国泰A500ETF,A,on_exchange,0.26,,0.928,280000,259840.00,2024-01-15,2024-06-20
510050,华夏上证50ETF,上证50ETF,A,on_exchange,0.10,,2.45,10000,24500.00,2024-03-01,2024-06-18
```

**JSON 格式** (Content-Type: `application/json`):

```json
{
  "exported_at": "2024-06-25T10:30:00Z",
  "portfolio_type": "on_exchange",
  "holdings": [
    {
      "symbol": "159338",
      "name": "国泰中证A500ETF",
      "short_name": "国泰A500ETF",
      "asset_type": "A",
      "portfolio_type": "on_exchange",
      "target_weight": 0.26,
      "tracked_index": null,
      "avg_cost": 0.928,
      "shares_held": 280000,
      "cost_basis": 259840.00,
      "first_buy_date": "2024-01-15",
      "last_trade_date": "2024-06-20"
    }
  ]
}
```

---

### 2.2 导入 / Import

```
POST /api/v1/portfolio/import
```

#### 请求头 / Request Headers

| Header | Type | Required | Description |
|--------|------|----------|-------------|
| Content-Type | string | Yes | `multipart/form-data` |

#### 请求体 / Request Body (multipart/form-data)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| file | file | Yes | CSV file with headers matching export format |
| portfolio_type | string | No | Target portfolio: `on_exchange` \| `off_exchange` (default: `on_exchange`) |
| mode | string | No | `merge` \| `replace` (default: `merge`) |
| skip_invalid | boolean | No | Skip rows with validation errors (default: true) |

**CSV 必需列 / Required CSV Columns:**

```
symbol,name,asset_type,portfolio_type
```

**可选列 / Optional Columns:**

```
short_name,target_weight,tracked_index,avg_cost,shares_held,first_buy_date,last_trade_date
```

#### 成功响应 / Success Response — `200 OK`

```json
{
  "imported": 12,
  "skipped": 1,
  "errors": [
    {
      "row": 5,
      "symbol": "INVALID",
      "error": "Symbol not found in market data"
    }
  ],
  "holdings": [
    {
      "id": 14,
      "symbol": "510050",
      "name": "华夏上证50ETF",
      "short_name": "上证50ETF",
      "asset_type": "A",
      "target_weight": 0.10,
      "portfolio_type": "on_exchange",
      "tracked_index": null,
      "avg_cost": 2.45,
      "shares_held": 10000,
      "first_buy_date": "2024-03-01",
      "last_trade_date": "2024-06-18",
      "is_active": true
    }
  ]
}
```

#### 字段说明 / Field Reference

| Field | Type | Description |
|-------|------|-------------|
| imported | int | Number of successfully imported/updated rows |
| skipped | int | Number of rows skipped due to errors (when skip_invalid=true) |
| errors[] | array | Validation errors for skipped rows |
| errors[].row | int | 1-based row number in CSV |
| errors[].symbol | string | Symbol from that row |
| errors[].error | string | Error message |
| holdings[] | array | Created/updated holding objects (same schema as GET /etfs) |

---

## 3. 错误码 / Error Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| 400 | Bad Request | Invalid CSV format, missing required columns, file too large (>5MB) |
| 415 | Unsupported Media Type | Content-Type not multipart/form-data |
| 422 | Unprocessable Entity | Validation errors with details in response body |

---

## 4. 示例 / Examples

### 导出请求 / Export Request

```
GET /api/v1/portfolio/export?portfolio_type=on_exchange&format=csv
```

### 导入请求 / Import Request (curl)

```bash
curl -X POST http://localhost:8000/api/v1/portfolio/import \
  -F "file=@portfolio_backup.csv" \
  -F "portfolio_type=on_exchange" \
  -F "mode=replace" \
  -F "skip_invalid=true"
```

---

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Export route matches | ☐ | ☐ | GET /api/v1/portfolio/export |
| Export query params | ☐ | ☐ | portfolio_type, format |
| Export CSV headers correct | ☐ | ☐ | All cost basis fields included |
| Import route matches | ☐ | ☐ | POST /api/v1/portfolio/import |
| Import multipart handling | ☐ | ☐ | file, portfolio_type, mode, skip_invalid |
| Import validation errors | ☐ | ☐ | Row-level errors returned |
| Loading state | ☐ | N/A | Spinner during file parse |
| Success toast | ☐ | N/A | "Imported X holdings" |