# News API / 资讯接口

## 1. All endpoints overview / 所有端点一览

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/news/headlines` | Latest financial news headlines |
| GET | `/api/v1/news/macro` | Macroeconomic news |
| GET | `/api/v1/news/global` | Global market news |
| GET | `/api/v1/news/stock/{symbol}` | Stock/ETF-specific news |
| GET | `/api/v1/news/research/{symbol}` | Research reports for a symbol |

---

## 2. Headlines / 头条资讯

```
GET /api/v1/news/headlines
```

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "id": "a1b2c3d4e5f6",
    "title": "A股三大指数集体收涨",
    "source": "东方财富",
    "time": "2026-07-13 15:30",
    "url": "https://..."
  }
]
```

**注意 / Note:** The `id` field is a 12-character MD5 hex digest of `time + title`, computed server-side for WebSocket deduplication. News items pushed via WebSocket always include `id`. This `id` is stable across refreshes — the same news item will have the same `id`.

---

## 3. Macro News / 宏观资讯

```
GET /api/v1/news/macro
```

**成功响应 / Success Response — `200 OK`:** Same structure as headlines.

---

## 4. Global News / 全球资讯

```
GET /api/v1/news/global
```

**成功响应 / Success Response — `200 OK`:** Same structure as headlines.

---

## 5. Stock/ETF News / 个股/ETF 资讯

```
GET /api/v1/news/stock/{symbol}
```

**路径参数 / Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| symbol | string | ETF or stock trading code |

**成功响应 / Success Response — `200 OK`:** Same structure as headlines, filtered to symbol.

---

## 6. Research Reports / 研究报告

```
GET /api/v1/news/research/{symbol}
```

**路径参数 / Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| symbol | string | ETF or stock trading code |

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "title": "行业深度报告：半导体国产化加速",
    "institution": "中信证券",
    "date": "2026-07-10",
    "rating": "推荐"
  }
]
```

---

## 7. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 500 | Internal Server Error | News source fetch failure |

---

## 8. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| All 5 endpoints return 200 | ☐ | ☐ | |
| `stock/{symbol}` filters by symbol | ☐ | ☐ | |
| Empty array on no news (not 404) | ☐ | ☐ | |
| Loading skeleton | ☐ | N/A | |
| Empty state "暂无资讯" | ☐ | N/A | |
| Clickable news link opens in new tab | ☐ | N/A | |
