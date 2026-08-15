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
    },
    {
      "id": 2,
      "symbol": "TSLA",
      "name": "特斯拉",
      "asset_type": "US",
      "added_at": "2024-01-15T10:30:00Z",
      "notes": "",
      "realtime": null,
      "realtime_unavailable": true,
      "realtime_note": "该市场数据源暂不可用（无实时行情）"
    },
    {
      "id": 3,
      "symbol": "AAPL",
      "asset_type": "US",
      "realtime": {
        "price": 189.5,
        "change_pct": -0.42,
        "volume": 54321098,
        "is_estimated": true
      },
      "realtime_unavailable": true,
      "realtime_note": "该市场数据源暂不可用（无实时行情）"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

#### 行为契约 / Behavioral Contract (Z22 脏数据修复，合并自 watchlist-v2.md)

1. **名称解析自愈**: 对每个条目，先按 `symbol` 查询实时行情；若返回 None 且 `symbol` 非合法代码形态（含中文/非代码字符），调用 `resolve_symbol_to_code(symbol, asset_type)` 尝试按名称反查代码。
2. **重查行情**: 解析成功得到真实代码后，用真实代码重新查询实时行情。
3. **自愈回写**: 解析成功且真实代码与原 symbol 不同时，执行 `UPDATE watchlist SET symbol=:resolved, name=COALESCE(NULLIF(name,''), :realname) WHERE id=:id`。遇唯一约束冲突时仅记 warning，不阻塞响应，本次响应仍使用解析后的行情。
4. **name 空串兜底**: 无论写入还是读取，`name = (realtime.get("name") or "").strip() or symbol`。
5. **round24 R20 — 美股/HK 无实时源显式标记**（合约新增字段 `realtime_unavailable` / `realtime_note`）：
   - 当条目 `asset_type in ("US", "HK")` 且实时行情解析为 None（批量失败/超时/无源）时，**不再静默置 `realtime: null`**，而是置 `realtime_unavailable: true` + `realtime_note: "该市场数据源暂不可用（无实时行情）"`，前端据此渲染「暂无实时」徽标（红涨绿跌语义下杜绝被误读为「没波动」）。
   - 同时尝试 T-1 收盘兜底 `_last_close_fallback(symbol, asset_type)`（F39 K 线源）；命中则在 `realtime` 中回填 `{price, change_pct, volume, is_estimated: true}`，并仍保留 `realtime_unavailable: true`（说明这是估值非实时）。
   - A 股（`asset_type` 其他值）无实时源时仅置 `_degraded: true`（兼容既有降级语义），不置 `realtime_unavailable`。
   - 端点整体 5s 超时（P0-4）时直接返回 DB-only 行（无 `realtime`/`realtime_unavailable`/`_degraded` 键）——属超时降级，非字段语义，前端应识别 loading/慢数据态。

**合法代码形态判断**:

```python
import re
CODE_PATTERN = re.compile(r"^[0-9]{6}(\.HK)?$|^[A-Z]{1,5}$|^[A-Z]{1,5}\.[A-Z]{1,2}$")
# 匹配：A股6位数字、港股xxxx.HK、美股字母代码、带后缀代码
```

**内部服务函数 `resolve_symbol_to_code(symbol, asset_type) -> str | None`**（`backend/app/services/market_service.py`）:
1. **ETF 路径** (`asset_type` in `["A", "etf", "ETF"]`): 查 `instruments` 表 `name == symbol` → `name LIKE %symbol%`，返回 `symbol` 列。
2. **个股路径** (`asset_type == "A"`): 调用 `fetch_all_stocks()`（levistock→akshare 双源），按 `stock_name == symbol` 精确匹配 → 包含匹配，按 Z20 排序契约取首条，返回 `stock_code`。
3. **其他市场**: 暂不支持，返回 None。

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
| symbol | string | Yes | 标的代码，**必须符合代码格式（字母数字点横线），拒绝中文** |
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

#### 错误响应 / Error Response (Z22 校验，合并自 watchlist-v2.md)

| Status Code | Condition | Detail |
|-------------|-----------|--------|
| 422 | symbol 校验失败（含中文/空格/特殊字符） | `无法解析该标的，请通过搜索选择` |
| 422 | 实时行情查不到（代码无效） | `无法解析该标的，请通过搜索选择` |
| 409 | 标的已存在 | `该标的已在自选列表中` |

#### 行为契约 / Behavioral Contract (Z22)

1. **Schema 校验**: `WatchlistCreate.symbol` 增加 `pattern=r"^[0-9A-Za-z.\-]+$"`，`min_length=1`，`max_length=20`。
2. **行情存在性校验**: 入库前调用 `market_data_hub.get_asset_realtime(symbol, asset_type)`，返回 None 抛 422。
3. **name 空串兜底**: `name = (realtime.get("name") or "").strip() or symbol`。
4. **asset_type 默认值统一**: `WatchlistBase.asset_type` 默认 `"A"`（与数据库模型一致）。

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
| realtime | object \| null | 实时行情快照（可选，含 price, change_pct, volume；T-1 兜底时含 `is_estimated: true`） |
| realtime_unavailable | boolean \| null | round24 R20：美股/HK 实时源不可用显式标记（true=暂无实时，非静默 null） |
| realtime_note | string \| null | round24 R20：无实时源说明文案 |
| _degraded | boolean \| null | A 股等无实时源时的兼容降级标记 |

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