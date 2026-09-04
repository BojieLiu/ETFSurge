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

> **P2-2 (R4-05) 参数形态约定 / Symbol parameter forms (batch):**
> `symbols` 同时支持两种等价形态，服务端统一解析为逗号分隔全量列表（不取首项）：
> - 逗号分隔：`?symbols=159338,510880` → `["159338", "510880"]`
> - 重复参数：`?symbols=159338&symbols=510880` → `["159338", "510880"]`
> - 混合 + 空白清洗：`?symbols=159338, 510880&symbols=518880` → `["159338", "510880", "518880"]`

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

**Portfolio realtime 特殊字段 (Phase 4):** For off-exchange funds, additional fields indicate whether the price is estimated via tracked index:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| is_estimated | bool | `false` | Whether price is estimated (off-exchange during trading hours) |
| estimate_source | string | `null` | `tracked_index` \| `nav` \| `last_close` — source of the estimate |

**R173 (round52 §7.3 方案A+B) 估值口径：**
- 盘中（trading hours）：`tracked_index` 条目的 `price`/`change_pct` = 其 `tracked_index`（场内 ETF 代码）的**实时批量报价**（ti 已显式并入 A 股批量），与该场内标的逐只一致；ti 为指数代码时仍走指数行情映射（兼容）。
- 盘后：`nav` 条目的 `change_pct` = 净值源的 `daily_change_pct`（T-1 净值涨跌），**不再是硬编码 0**；`daily_change_pct` 缺失/非法时为 `0.0`（诚实兜底）。
- 前端红涨绿跌渲染无需改动（字段语义为估值涨跌，非真实成交涨跌）。

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

**asset_type 按 symbol 推断（round28 R62）**: 当调用方未显式传非 `A` 值（默认 `A`）时，后端按 symbol 形态自动推断市场——`AAPL`/`SPY`（纯字母）→ `US`，`00700`/`02800`（5 位 0 开头）→ `HK`，`600519`/`510300`（6 位数字/交易所前缀）→ `A`。显式传 `US`/`HK` 时尊重调用方。响应含 `asset_type` 字段（实际路由使用的市场代码）与 `data_available` 标记。

**成功响应 / Success Response — `200 OK`:**

```json
{
  "symbol": "159338",
  "asset_type": "A",
  "data_available": true,
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

> 空/不足 K 线（<30 根）时返回 `data_available: false`（F10 R32），前端据此渲染空态。
> 全源失败走 stale 缓存兜底时含 `stale: true` 标记（F0-4）。

---

## 6. Signal / 交易信号

```
GET /api/v1/market/signal/{symbol}?asset_type=A
```

**asset_type 推断规则同 Indicators（round28 R62）**，响应亦含 `asset_type` 字段。

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
  "dates": ["2026-07-13", "2026-07-14"],
  "opens": [0.918, 0.921],
  "highs": [0.928, 0.930],
  "lows": [0.915, 0.918],
  "closes": [0.925, 0.927],
  "volumes": [12345678, 9876543],
  "amount": [11420000.0, 9120000.0],
  "ma5": [0.920, 0.922],
  "ma10": [0.915, 0.918],
  "ma20": [0.910, 0.912],
  "ma60": [0.900, 0.901],
  "bollinger": { "upper": [0.940, 0.942], "middle": [0.910, 0.912], "lower": [0.880, 0.882] },
  "macd": { "dif": [0.01, 0.012], "dea": [0.008, 0.009], "histogram": [0.004, 0.006] },
  "kdj": { "k": [50.1, 51.2], "d": [48.9, 50.0], "j": [52.5, 53.6] },
  "rsi": [42.5, 44.1]
}
```

> **字段口径（F14, round6 §16.2）**：`volumes` 为成交量序列（原"成交额"别名已从成交量列解析中分离，避免金额当成交量）；`amount` 为成交额序列，与 `dates` 等长，数据源无成交额列时全 `null` 填充（前端判空隐藏成交额副图）。所有序列与 `dates` 等长。

| 字段 | 类型 | 说明 |
|---|---|---|
| dates | string[] | 交易日（`YYYY-MM-DD`） |
| opens/highs/lows/closes | number[] | OHLC |
| volumes | number[] | 成交量（列缺失时 0 填充） |
| amount | (number\|null)[] | 成交额（F14 新增；列缺失时 null 填充） |
| ma5/ma10/ma20/ma60 | (number\|null)[] | 均线 |
| bollinger | {upper, middle, lower} | 布林带 |
| macd | {dif, dea, histogram} | MACD |
| kdj | {k, d, j} | KDJ |
| rsi | (number\|null)[] | RSI(14) |

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

## 10. 变更记录 / Changelog (F0-4 / F1-1 / F1-2)

### 10.1 Realtime — 港股符号归一化（F1-1）

`GET /api/v1/market/realtime/{symbol}?asset_type=HK` 支持 `00700.HK` 与 `00700` 两种输入；
响应 `symbol` 字段**与请求保持一致**（含 `.HK` 后缀）。降级链：

```
HK: Sina(rt_hk 前缀) → Tencent(QQ, hk 前缀) → 东方财富(代码归一化匹配)
A:  mootdx → Tencent(QQ) → Sina   ← F1-2 补 tencent，与批量版对齐
```

### 10.2 Indicators / Signal — stale 标记（F0-4）

当外部数据源（mootdx/sina/akshare/netease）全部失败、`get_history` 回落
到过期 K 线缓存时，响应附加：

```json
{
  "rsi": 55.2,
  "_stale": true,
  "_stale_note": "数据源全部不可用，返回过期缓存（可能延迟）"
}
```

前端可据此提示「数据可能延迟」。正常场景不出现 `_stale` 字段。

### 10.3 History — stale 缓存兜底（F0-4）

`GET /api/v1/market/history/{symbol}` 在全部数据源失败时，返回**任意年龄的
过期 K 线缓存**（不再返回空数组），由后端 WARNING 日志标记 `stale`。

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

<!-- 路由登记（P3-5 check_routes 门禁） -->
GET /api/v1/market/fundamentals/{symbol}
GET /api/v1/market/indices/meta
