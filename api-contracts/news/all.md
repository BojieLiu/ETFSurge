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
| level | int | Importance 1-5 (5=urgent, 4=positive, 3=negative, 2=reminder, 1=other) |
| stars | int | Combined score = level + freshness bonus (within 1h +2, 2h +1), capped at 5 |

### Level classification rules / 等级分类规则

**Level 5 (紧急/重大)** — breaking events, natural disasters, geopolitical crises
- Keywords (Chinese): `重大`, `紧急`, `突发`, `特急`, `崩盘`, `熔断`, `停牌`, `退市`, `破产`, `违约`, `制裁`, `战争`, `军事行动`, `恐怖袭击`, `台风`, `地震`, `疫情`, `暂停交易`, `紧急停牌`
- Keywords (English): `airstrike`, `crash`, `collapse`, `killed`, `fatal`
- Source: 财联社 "important" category items get +1 level boost

**Level 4 (利好/重要正面)** — positive policy, growth, upgrades
- Keywords (Chinese): `利好`, `上调`, `降准`, `降息`, `超预期`, `大涨`, `涨停`, `创新高`, `突破`, `新高`, `大幅增长`, `大幅上升`, `飙升`, `暴涨`, `证监会`, `央行`, `国务院`, `发改委`, `财政部`, `商务部`, `获批`, `核准`, `签署`, `投产`, `量产`, `落地`, `净买入`, `回购`, `增持`, `加仓`, `走强`, `牛市`, `看涨`, `降费`, `减税`, `补贴`, `扶持`, `放宽`, `经济复苏`, `扩张`, `加速`, `回暖`, `降息预期`, `量化宽松`, `协议`, `合作`
- Keywords (English): `positive`, `surge`, `partnership`, `breakthrough`, `soar`

**Level 3 (利空/重要负面)** — negative policy, decline, risk
- Keywords (Chinese): `利空`, `下调`, `暴跌`, `大跌`, `跌停`, `创新低`, `跌破`, `新低`, `减持`, `净卖出`, `流出`, `出逃`, `下滑`, `萎缩`, `放缓`, `减速`, `暂停`, `终止`, `取消`, `撤回`, `中止`, `违规`, `处罚`, `调查`, `立案`, `警示`, `通报批评`, `亏损`, `下降`, `熊市`, `低迷`, `疲软`, `做空`, `抛售`, `空头`, `撤离`, `加息`, `缩表`, `收紧`, `暴雷`, `爆雷`, `踩雷`
- Keywords (English): `negative`, `sanctions`, `layoffs`, `downgrade`

**Level 2 (提醒/关注)** — announcements, data releases, company notices
- Keywords (Chinese): `提醒`, `关注`, `注意`, `风险`, `公告`, `发布`, `通知`, `公布`, `披露`, `预告`, `展望`, `提示`, `预警`, `政策`, `规则`, `办法`, `意见`, `方案`, `措施`, `调整`, `变化`, `影响`, `改革`, `交易所`, `银保监会`, `金管局`, `数据`, `CPI`, `PMI`, `GDP`, `社融`, `信贷`, `指数`, `板块`, `行业`, `赛道`, `反弹`, `拉升`, `回落`, `港股`, `美股`, `外围市场`, `欧股`, `日股`, `审议`, `通过`, `批复`, `逆回购`, `MLF`, `LPR`, `SLF`, `再贷款`, `北向资金`, `主力资金`, `融资`, `融券`, `IPO`, `上市`, `新股`, `定增`, `配股`, `可转债`, `发债`, `分红`, `派息`, `送转`, `评级`, `展望`, `目标价`, `异动`, `跳水`, `冲高`, `密集调研`, `机构调研`, `大宗交易`, `复牌`, `要约收购`, `股权转让`, `重组`, `业绩`, `营收`, `净利润`, `财报`, `国务院`, `发改委`, `财政部`, `商务部`, `欧美`, `美联储`, `欧央行`, `鲍威尔`, `采购`, `重磅`
- Keywords (English): `watch`, `approves`, `launches`, `announces`, `data`, `FDA`

**Level 1 (其他)** — default level for unmatched items

**Stars formula:** `stars = min(level + freshness, 5)` where `freshness = 2` (within 1h), `1` (within 2h), `0` (older)

**财联社 editorial boost:** Items from 财联社's "important" category receive a +1 level boost (capped at 5), reflecting editorial curation.

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
