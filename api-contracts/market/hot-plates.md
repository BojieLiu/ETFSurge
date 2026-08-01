# Hot Plates & Sector Heat API / 热点板块与板块热度接口

## 1. 概述 / Overview

**功能描述**: 财联社热点板块、板块热度排行、热门个股排行、市场风向等实时板块数据接口集合。

**触发场景**: 市场研判报告的板块分析段落、前端可视化热点板块排行组件（SectorHeatMap）。

**版本记录**:
- v2.0 (F2-3/F2-6): 新增 `GET /market/sectors/heat` 路由（此前 404）；`hot-plates` 输出统一归一化（`secu_name→name`、`up_reason→reason`、`stock_list→lead_stocks` 数组）；`stock-hot-rank` 输出新增 `concept_tags` 数组；`sectors/heat` 响应结构改为 `{items, total}`。

---

## 2. 端点定义 / Endpoints

### 2.1 热点板块 / Hot Plates

```
GET /api/v1/market/hot-plates
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 15 | 返回最大条数 |

**成功响应 — `200 OK`**（v2.0 归一化字段，前端契约稳定）：

```json
[
  {
    "name": "AI智能体",
    "reason": "大模型催化",
    "stock_count": 6,
    "lead_stocks": [
      {"secu_code": "688825", "secu_name": "海光信息"},
      {"secu_code": "688256", "secu_name": "寒武纪"}
    ]
  }
]
```

> 兼容说明：`lead_stocks` 元素为数据源原始字段（`secu_code`/`secu_name`）；前端取 `s.secu_name || s.name`。
> `stock_list`（字符串化列表）已由后端用 `ast.literal_eval` 安全解析为 `lead_stocks` 数组，非法字符串返回 `[]`。

### 2.2 板块热度排行 / Sector Heat

```
GET /api/v1/market/sectors/heat
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 20 | 返回最大条数 |

**成功响应 — `200 OK`**（v2.0 新增路由，`{items, total}` 结构）：

```json
{
  "items": [
    {
      "rank": 1,
      "name": "AI智能体",
      "heat_index": 13501.4,
      "rank_change": 5,
      "is_new": 0,
      "plate_code": "cls82558"
    }
  ],
  "total": 20
}
```

> 归一化：`plate_name→name`、`cur_heat→heat_index`，保留 `rank_change`/`is_new`/`plate_code`。

### 2.3 热门个股排行 / Stock Hot Rank

```
GET /api/v1/market/stock-hot-rank
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 50 | 返回最大条数 |

**成功响应 — `200 OK`**（v2.0 补 `concept_tags`）：

```json
[
  {
    "symbol": "688825",
    "name": "海光信息",
    "price": 108.5,
    "change_pct": 5.2,
    "change_amount": 5.36,
    "volume": 12345678,
    "turnover": 123456789,
    "sector": "半导体",
    "concept_tags": ["国产替代", "AI芯片", "信创"],
    "rank": 1,
    "asset_type": "A"
  }
]
```

> `concept_tags` 由数据源 `tag` 字符串（`ast.literal_eval`）解析为数组；非法字符串返回 `[]`。
> `sector` 优先取批量行情自带字段，其次行业映射，最后空串。

### 2.4 市场风向 / Market Wind

```
GET /api/v1/market/wind
```

**成功响应 — `200 OK`:**

```json
[
  {
    "plate_name": "科技主线",
    "description": "AI算力、半导体等持续走强"
  }
]
```

---

## 3. 变更记录 / Changelog

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.0 | 2026-08-01 | F2-3: 新增 `GET /market/sectors/heat`（`{items,total}`）；F2-6: hot-plates 归一化 + stock-hot-rank 补 `concept_tags`/`price`/`sector`/`turnover` |

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| /hot-plates route | ✅ | ✅ | GET /api/v1/market/hot-plates（v2.0 归一化） |
| /sectors/heat route | ✅ | ✅ | GET /api/v1/market/sectors/heat（v2.0 新增） |
| /stock-hot-rank route | ✅ | ✅ | GET /api/v1/market/stock-hot-rank（含 concept_tags） |
| /wind route | ☐ | ✅ | GET /api/v1/market/wind |
| SectorHeatMap component | ✅ | N/A | 展示 name/reason/lead_stocks + 个股 price/sector/turnover/chip |
| Cache layer get_hot_plates/get_sector_heat | N/A | ✅ | market_data_hub（limit 传值时实时取数） |
