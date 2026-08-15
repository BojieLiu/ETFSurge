# Market Sectors API / 市场板块接口

## 1. 概述 / Overview

**功能描述 / Description**: 行业板块和概念板块列表查询、板块成分股、热门板块等。板块数据来自本地 sectors 表（优先）或 akshare/东方财富（降级）。

**触发场景 / Trigger**: 用户在 AiAdvisor 板块分析下拉框中选择行业/概念板块。

---

## 2. 端点定义 / Endpoints

### 2.1 行业板块列表 / Industry Sectors

```
GET /api/v1/market/sectors/industry
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 80 | 返回最大条数 |
| market | string | No | — | 市场筛选（目前后端未实际消费此参数，仅前端透传） |

**成功响应 / Success Response — `200 OK`:**

```json
[
  {
    "sector_code": "BK0447",
    "sector_name": "半导体"
  },
  {
    "sector_code": "BK0456",
    "sector_name": "新能源"
  }
]
```

> **注意**: 降级路径（`fetch_industry_sectors` from akshare）可能返回 `plate_code`/`plate_name` 而非 `sector_code`/`sector_name`。前端 `useSectorAnalysis.js` 使用 `s.sector_code || s.plate_code` 兼容两种格式。

**增强响应（实时数据源可用时，合并自 sectors-industry.md）— `200 OK`:**

```json
[
  {
    "sector_code": "BK0447",
    "sector_name": "半导体",
    "change_pct": 2.35,
    "price": 2850.5,
    "main_inflow": 12.3,
    "up_count": 85,
    "down_count": 12,
    "volume": 1250000000,
    "amount": 8500000000
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| sector_code | string | 板块代码 (BK开头) |
| sector_name | string | 板块名称 |
| change_pct | float | 涨跌幅（%） |
| price | float | 板块指数点位 |
| main_inflow | float | 主力净流入（亿元） |
| up_count | int | 上涨家数 |
| down_count | int | 下跌家数 |
| volume | float | 成交量 |
| amount | float | 成交额 |

**降级响应**: 实时数据源不可用时，返回本地 sectors 表的基础数据（仅 code+name，见上）。

### 2.2 概念板块列表 / Concept Sectors

```
GET /api/v1/market/sectors/concept
```

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| limit | int | No | 80 | 返回最大条数 |
| market | string | No | — | 市场筛选 |

**成功响应 — `200 OK`:**

```json
[
  {
    "plate_code": "BK1645",
    "plate_name": "AI大模型"
  }
]
```

> **注意**: 本地表只返回 `sector_code`/`sector_name`（映射自 `Sector.code`/`Sector.name`）；降级路径返回 `plate_code`/`plate_name`。字段名不一致是已有断裂点，前端已做兼容。

**增强响应（实时数据源可用时，合并自 sectors-concept.md）— `200 OK`:**

```json
[
  {
    "sector_code": "BK1645",
    "sector_name": "AI大模型",
    "change_pct": 3.12,
    "price": 1850.5,
    "main_inflow": 25.6,
    "up_count": 45,
    "down_count": 8,
    "volume": 800000000,
    "amount": 5200000000
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| sector_code | string | 板块代码 |
| sector_name | string | 板块名称 |
| change_pct | float | 涨跌幅（%） |
| price | float | 板块指数点位 |
| main_inflow | float | 主力净流入（亿元） |
| up_count | int | 上涨家数 |
| down_count | int | 下跌家数 |
| volume | float | 成交量 |
| amount | float | 成交额 |

**降级响应**: 实时数据源不可用时，仅返回 `sector_code`/`sector_name`（见上）。

### 2.4 板块成分股 / Sector Stocks（round23 §6.1 已删路由，保留文档占位说明）

> **round23 §6.1（2026-08-14）**: `GET /sectors/industry-cls`、`GET /sectors/{sector_code}/stocks`、
> `GET /sectors/{plate_code}/popular` 三路由为死端点（0 生产调用方），已删除。
> 底层能力由保留端点提供：`GET /sectors/rotation`（板块轮动）、`GET /sectors/industry`、`GET /sectors/concept`。
> **round24 R18**: `GET /sectors`（统一 wrapper）亦为死端点（0 生产调用方，前端仅用 industry/concept/rotation/heat 子路径），
> 已删除，能力由 industry/concept 子路由覆盖。
> 底层 service 函数 `get_sector_stocks`/`get_sector_popular_stocks` 仍被 strategy_design/analysis 调用。

---

## 3. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `sectors/industry` 返回 `sector_code`/`sector_name` | ✅ | ✅ | useSectorAnalysis.js 消费 `sector_code` \| `plate_code` |
| `sectors/concept` 返回列表 | ✅ | ✅ | 同上 |
| 降级路径字段名不一致风险 | ⚠️ | ⚠️ | 本地表返回 `sector_code`，akshare 返回 `plate_code`；前端已兼容 |
| `market` 查询参数 | ✅ (URL拼入) | ❌ | 后端未实际消费 `market` 参数，仅前端拼接 URL |
| 空列表时前端切换到手动输入模式 | ✅ | ☐ | |

<!-- 路由登记（P3-5 check_routes 门禁） -->
GET /api/v1/market/sectors/rotation
