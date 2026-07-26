# News API / 资讯接口

## 1. All endpoints overview / 所有端点一览

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/news/headlines` | Latest financial news headlines |
| GET | `/api/v1/news/macro` | Macroeconomic news |
| GET | `/api/v1/news/global` | Global market news |
| GET | `/api/v1/news/stock/{symbol}` | Stock/ETF-specific news |
| GET | `/api/v1/news/research/{symbol}` | Research reports for a symbol |
| WS | `/api/v1/ws/news` | WebSocket news push (single + batch) |

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
    "time": "2026-07-13 15:30:00",
    "sort_time": 1802410200,
    "url": "https://..."
  }
]
```

**注意 / Note:** The `id` field is a 12-character MD5 hex digest of `time + title`, computed server-side for WebSocket deduplication. News items pushed via WebSocket always include `id`. This `id` is stable across refreshes — the same news item will have the same `id`.

**Field details:**

| Field | Type | Description |
|-------|------|-------------|
| id | string | 12-char MD5 hex digest, stable dedup key |
| title | string | News headline |
| content | string | News body / summary |
| source | string | News source name |
| time | string | Human-readable time in `YYYY-MM-DD HH:MM:SS` format |
| sort_time | int | Unix epoch seconds, **numeric sort key** for reliable client-side ordering |
| url | string | Source link |
| level | int | Importance 1-5 (5=urgent) |
| stars | int | Same as level (legacy alias) |

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

## 7. WebSocket / WebSocket 实时推送

### Connection / 连接

```
ws://host/api/v1/ws/news
```

### Message types / 消息类型

The server pushes two message types on the `news` channel:

#### 7a. Single news item (legacy)

```json
{
  "type": "news",
  "data": {
    "id": "...",
    "title": "...",
    "time": "2026-07-13 15:30:00",
    "sort_time": 1802410200,
    ...
  }
}
```

Used for **individual hot-push** items. On connect, server sends a batch of individual `news` messages as the initial snapshot.

#### 7b. Batch news items (primary)

```json
{
  "type": "news_batch",
  "data": [
    { "id": "...", "title": "...", "time": "...", "sort_time": 1802410200, ... },
    { "id": "...", "title": "...", "time": "...", "sort_time": 1802410100, ... }
  ]
}
```

**Push rule / 推送规则:**
- **First cycle** (server restart): pushes all items as `news_batch`
- **Subsequent cycles**: pushes only new items (by title dedup) as `news_batch`
- The `data` array is **pre-sorted by `sort_time` descending** (newest first) by the server

**Frontend must handle both `news` (single) and `news_batch` (array) types.**

---

## 8. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 500 | Internal Server Error | News source fetch failure |

---

## 9. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| All 5 endpoints return 200 | ☐ | ☐ | |
| `stock/{symbol}` filters by symbol | ☐ | ☐ | |
| Empty array on no news (not 404) | ☐ | ☐ | |
| Loading skeleton | ☐ | N/A | |
| Empty state "暂无资讯" | ☐ | N/A | |
| Clickable news link opens in new tab | ☐ | N/A | |
| `sort_time` field present in all items | ☐ | ☐ | Added in news-timeline-fix |
| `sort_time` is int type (not string) | ☐ | ☐ | Added in news-timeline-fix |
| Items sorted by `sort_time` descending | ☐ | ☐ | Added in news-timeline-fix + verify_e2e |
| WS `news_batch` format handled | ☐ | ☐ | Added in news-timeline-fix |
| Frontend re-sorts after any WS merge | ☐ | N/A | Added in news-timeline-fix |
| Multi-item WS push order preserved | ☐ | N/A | Added in news-timeline-fix |
| No-sort_time fallback to time string | ☐ | N/A | Added in news-timeline-fix |
