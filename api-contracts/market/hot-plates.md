# Hot Plates & Sector Heat API / 热点板块与板块热度接口

## 1. 概述 / Overview

**功能描述**: 财联社热点板块、板块热度排行、热门个股排行、市场风向等实时板块数据接口集合。

**触发场景**: 市场研判报告的板块分析段落、前端可视化热点板块排行组件。

---

## 2. 端点定义 / Endpoints

### 2.1 热点板块 / Hot Plates

```
GET /api/v1/market/hot-plates
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 15 | 返回最大条数 |

**成功响应 — `200 OK`:**

```json
[
  {
    "plate_name": "半导体",
    "reason": "政策利好叠加需求复苏",
    "hot_reason": "政策利好叠加需求复苏",
    "lead_stocks": [
      {"name": "中芯国际", "symbol": "688981"},
      {"name": "北方华创", "symbol": "002371"}
    ]
  }
]
```

### 2.2 板块热度排行 / Sector Heat

```
GET /api/v1/market/sectors/heat
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 20 | 返回最大条数 |

**成功响应 — `200 OK`:**

```json
[
  {
    "sector_code": "BK0447",
    "sector_name": "半导体",
    "heat_index": 85.5,
    "change_pct": 2.35
  }
]
```

### 2.3 热门个股排行 / Stock Hot Rank

```
GET /api/v1/market/stock-hot-rank
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 50 | 返回最大条数 |

**成功响应 — `200 OK`:**

```json
[
  {
    "symbol": "600519",
    "name": "贵州茅台",
    "price": 1820.0,
    "change_pct": 1.25
  }
]
```

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

## 3. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| /hot-plates route | ☐ | ☐ | GET /api/v1/market/hot-plates |
| /sectors/heat route | ☐ | ☐ | GET /api/v1/market/sectors/heat |
| /stock-hot-rank route | ☐ | ☐ | GET /api/v1/market/stock-hot-rank |
| /wind route | ☐ | ☐ | GET /api/v1/market/wind |
| SectorHeatMap component | ☐ | N/A | 前端可视化组件 |
| Cache layer get_hot_plates/get_sector_heat | N/A | ☐ | pool_manager.py |
