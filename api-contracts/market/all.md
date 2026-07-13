# Market API / 行情接口

## 1. All endpoints overview / 所有端点一览

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/market/realtime` | All market real-time data |
| GET | `/api/v1/market/realtime/portfolio` | Real-time data for portfolio ETFs only |
| GET | `/api/v1/market/realtime/batch` | Batch query by symbol list |
| GET | `/api/v1/market/realtime/{symbol}` | Single symbol real-time quote |
| GET | `/api/v1/market/history/{symbol}` | Historical price data |
| GET | `/api/v1/market/search` | Search symbols by keyword |
| GET | `/api/v1/market/indicators/{symbol}` | Technical indicators |
| GET | `/api/v1/market/signal/{symbol}` | Trading signal |
| GET | `/api/v1/market/chart/{symbol}` | Chart-ready data |
| GET | `/api/v1/market/indices/global` | Global market indices |

---

## 2. Real-time / 实时行情

```
GET /api/v1/market/realtime
GET /api/v1/market/realtime/portfolio
GET /api/v1/market/realtime/batch?symbols=159338,510880&asset_type=A
GET /api/v1/market/realtime/{symbol}?asset_type=A
```

**查询参数 / Query Parameters:**

| Parameter | Type | Required | Default | Endpoints |
|-----------|------|----------|---------|-----------|
| symbols | string | Yes (batch) | — | batch |
| asset_type | string | No | `A` | batch, single |

**成功响应 / Success Response — `200 OK`:**

```json
{
  "symbol": "159338",
  "name": "国泰中证A500ETF",
  "price": 0.925,
  "change_pct": 0.54,
  "change_amount": 0.005,
  "high": 0.928,
  "low": 0.921,
  "volume": 12345678,
  "amount": 11420000,
  "time": "2026-07-13 14:30:00"
}
```

Batch returns array, single returns object, realtime/portfolio returns array of portfolio ETFs.

---

## 3. History / 历史行情

```
GET /api/v1/market/history/{symbol}?asset_type=A&period=daily
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| asset_type | string | No | `A` | `A` \| `HK` \| `US` |
| period | string | No | `daily` | `daily` \| `weekly` \| `monthly` |

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "date": "2026-07-13",
    "open": 0.920,
    "close": 0.925,
    "high": 0.928,
    "low": 0.918,
    "volume": 12345678
  }
]
```

---

## 4. Search / 搜索

```
GET /api/v1/market/search?keyword=红利
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| keyword | string | Yes | Search keyword (symbol or name) |

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "symbol": "510880",
    "name": "华泰柏瑞红利ETF",
    "asset_type": "A"
  }
]
```

---

## 5. Indicators / 技术指标

```
GET /api/v1/market/indicators/{symbol}?asset_type=A
```

**成功响应 / Success Response — `200 OK`:**

```json
{
  "symbol": "159338",
  "ma5": 0.918,
  "ma10": 0.912,
  "ma20": 0.905,
  "ma60": 0.890,
  "macd": { "dif": 0.005, "dea": 0.003, "macd": 0.002 },
  "rsi": 55.2,
  "bollinger": { "upper": 0.940, "mid": 0.910, "lower": 0.880 },
  "volume_ma5": 8000000,
  "volume_ma10": 7500000
}
```

---

## 6. Signal / 交易信号

```
GET /api/v1/market/signal/{symbol}?asset_type=A
```

**成功响应 / Success Response — `200 OK`:**

```json
{
  "symbol": "159338",
  "overall": "buy",
  "trend": "up",
  "momentum": "positive",
  "volume": "normal",
  "score": 72,
  "signals": {
    "ma_cross": "buy",
    "macd": "buy",
    "rsi": "neutral",
    "bollinger": "hold"
  }
}
```

---

## 7. Chart / 图表数据

```
GET /api/v1/market/chart/{symbol}?asset_type=A&period=daily
```

**成功响应 / Success Response — `200 OK`:**

```json
{
  "symbol": "159338",
  "period": "daily",
  "bars": [
    { "date": "2026-07-13", "open": 0.920, "close": 0.925, "high": 0.928, "low": 0.918, "volume": 12345678 }
  ],
  "ma_lines": [
    { "name": "MA5", "values": [0.918, 0.915, ...] }
  ]
}
```

---

## 8. Global Indices / 全球指数

```
GET /api/v1/market/indices/global
```

**成功响应 / Success Response — `200 OK`:**

```json
{
  "美股": [
    { "symbol": "^DJI", "name": "道琼斯", "price": 39800, "change_pct": 0.32 }
  ],
  "港股": [
    { "symbol": "^HSI", "name": "恒生指数", "price": 18200, "change_pct": -0.45 },
    { "symbol": "^HSCE", "name": "恒生国企指数", "price": 6500, "change_pct": -0.30 },
    { "symbol": "^HSTECH", "name": "恒生科技指数", "price": 3800, "change_pct": 0.15 }
  ],
  "A股": [
    { "symbol": "000001", "name": "上证指数", "price": 3100, "change_pct": 0.50 }
  ]
}
```

**注意 / Note:** External data sources (akshare, yfinance) may time out in restricted environments. Backend has per-call 15s timeout but this endpoint may return slowly or empty.

---

## 9. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | Missing required params |
| 404 | Not Found | Symbol not found |
| 504 | Gateway Timeout | External data source timeout |
| 500 | Internal Server Error | Fetch failure |

---

## 10. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| All 10+ endpoints return 200 | ☐ | ☐ | |
| Real-time endpoints handle missing symbol gracefully | ☐ | ☐ | |
| History returns empty array (not error) if no data | ☐ | ☐ | |
| Search returns empty array for no match | ☐ | ☐ | |
| Global indices grouped by market region | ☐ | ☐ | |
| All numeric fields handle 0/null | ☐ | ☐ | Display "—" |
| Loading skeleton | ☐ | N/A | |
| Error state on timeout (504) | ☐ | ☐ | |
| Global indices horizontal scrolling | ☐ | N/A | flex-wrap per region |
