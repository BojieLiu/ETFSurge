# Industry Sectors API (Enhanced) / 行业板块增强接口

## 1. 概述 / Overview

**功能描述**: 行业板块列表查询，返回含实时行情字段（涨跌幅、主力净流入等）的增强数据，替代原仅返回 code+name 的接口。

**触发场景**: 用户在板块分析、组合设计、市场研判报告中查看行业板块排行。

---

## 2. 端点定义 / Endpoint

```
GET /api/v1/market/sectors/industry
```

### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | int | No | 80 | 返回最大条数 |

### 响应 / Response

**Status Code:** `200 OK`

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

**字段说明:**

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

### 降级响应 / Fallback Response

当实时数据源不可用时，返回本地 sectors 表的基础数据（仅 code+name）：

```json
[
  {
    "sector_code": "BK0447",
    "sector_name": "半导体"
  }
]
```

---

## 3. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches contract | ☐ | ☐ | GET /api/v1/market/sectors/industry |
| Response fields match | ☐ | ☐ | sector_code, sector_name, change_pct, main_inflow |
| 涨跌幅颜色显示 | ☐ | N/A | useSectorAnalysis.js 按 change_pct >=0 显示 text-up/text-down |
| Empty state | ☐ | N/A | 空列表显示"暂无板块数据" |
