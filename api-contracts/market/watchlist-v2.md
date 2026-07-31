# API 契约: Watchlist 脏数据修复 (Z22)

> 关联方案: `docs/z_fixes_design_v5.3.md` Z22
> 变更类型: 既有端点行为修订 + 新增内部服务函数
> 版本: v2.0

## 1. 概述 / Overview

**功能描述**: 修复 watchlist 历史脏数据（symbol 存中文名称）无法填充实时行情的问题。包含写入侧校验拦截新增脏数据、读取侧名称解析自愈回写、name 空串兜底。

**触发场景**: 
- 用户通过搜索选择标的添加自选（正常流程）
- 用户直接输入中文名称提交（历史脏数据源头）
- GET /watchlist 查询历史脏数据条目

---

## 2. 端点定义 / Endpoints

### 2.1 获取自选列表 / List Watchlist (行为修订)

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
      "symbol": "600519",
      "name": "贵州茅台",
      "asset_type": "A",
      "added_at": "2024-01-15T10:30:00Z",
      "notes": "长期跟踪",
      "realtime": {
        "price": 1750.50,
        "change_pct": 1.25,
        "volume": 12345678
      }
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

#### 行为契约 / Behavioral Contract (Z22)

1. **名称解析自愈**: 对每个条目，先按 `symbol` 查询实时行情；若返回 None 且 `symbol` 非合法代码形态（含中文/非代码字符），调用 `resolve_symbol_to_code(symbol, asset_type)` 尝试按名称反查代码。
2. **重查行情**: 解析成功得到真实代码后，用真实代码重新查询实时行情。
3. **自愈回写**: 解析成功且真实代码与原 symbol 不同时，执行 `UPDATE watchlist SET symbol=:resolved, name=COALESCE(NULLIF(name,''), :realname) WHERE id=:id`。遇唯一约束冲突时仅记 warning，不阻塞响应，本次响应仍使用解析后的行情。
4. **name 空串兜底**: 无论写入还是读取，`name = (realtime.get("name") or "").strip() or symbol`。

#### 合法代码形态判断

```python
import re
CODE_PATTERN = re.compile(r"^[0-9]{6}(\.HK)?$|^[A-Z]{1,5}$|^[A-Z]{1,5}\.[A-Z]{1,2}$")
# 匹配：A股6位数字、港股xxxx.HK、美股字母代码、带后缀代码
```

---

### 2.2 添加自选 / Add to Watchlist (行为修订)

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

#### 错误响应 / Error Response

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

### 2.3 新增内部服务函数 / Internal Service Function

#### `resolve_symbol_to_code(symbol: str, asset_type: str) -> str | None`

**位置**: `backend/app/services/market_service.py`

**职责**: 按名称反查标的代码，供 GET /watchlist 自愈使用。

**逻辑**:
1. **ETF 路径** (`asset_type` in `["A", "etf", "ETF"]`): 查 `instruments` 表 `name == symbol` → `name LIKE %symbol%`，返回 `symbol` 列。
2. **个股路径** (`asset_type == "A"`): 调用 `fetch_all_stocks()`（levistock→akshare 双源），按 `stock_name == symbol` 精确匹配 → 包含匹配，按 Z20 排序契约取首条，返回 `stock_code`。
3. **其他市场**: 暂不支持，返回 None。

**返回**: 解析出的真实代码（如 `"600519"`），失败返回 None。

---

## 3. 响应字段说明 / Response Fields

| Field | Type | Description |
|-------|------|-------------|
| items[].id | integer | 数据库主键 |
| items[].symbol | string | 标的代码（自愈后为真实代码） |
| items[].name | string | 标的名称（非空，兜底为 symbol） |
| items[].asset_type | string | 市场类型 |
| items[].added_at | string (ISO8601) | 添加时间 |
| items[].notes | string | 备注 |
| items[].realtime | object | 实时行情快照，含 `price`、`change_pct`、`volume`；解析失败时字段缺失 |
| total | integer | 总条数 |
| limit | integer | 分页大小 |
| offset | integer | 分页偏移 |

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| GET /watchlist 返回 realtime 含 price/change_pct/volume | ☐ | ☐ | 历史脏数据条目亦应填充 |
| POST /watchlist 传中文 symbol 返回 422 | ☐ | ☐ | Schema pattern 校验 |
| POST /watchlist 传无效代码返回 422 | ☐ | ☐ | 行情存在性校验 |
| POST /watchlist name 空串兜底为 symbol | ☐ | ☐ | `(realtime.get("name") or "").strip() or symbol` |
| GET /watchlist 自愈回写 DB symbol 字段 | ☐ | ☐ | 唯一冲突不抛错、仅记 warning |
| asset_type 默认值统一为 "A" | ☐ | ☐ | schema 与模型一致 |
| 前端 placeholder 文案更新 | ☐ | N/A | "搜索代码或名称（将自动匹配为代码）" |

---

## 5. 测试 / Tests

- 后端单测: `backend/tests/test_watchlist_dirty.py`（5 用例）
- verify_e2e: 新增 `section_watchlist` 模块