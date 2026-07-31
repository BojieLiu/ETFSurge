# API 契约: 热门个股 Volume/Sector 补全 (Z25)

> 关联方案: `docs/z_fixes_design_v5.3.md` Z25
> 变更类型: 既有端点响应字段增强（repo 侧二次 enrich）
> 版本: v2.0

## 1. 概述 / Overview

**功能描述**: 修复 `/stock-hot-rank` 返回数据缺 `volume`（成交量）和 `sector`（行业）字段的问题。通过 repo 侧二次 enrich：批量行情补全 volume + 行业映射补全 sector。

**触发场景**: 前端热门个股排行组件、市场研判报告引用热门个股数据。

---

## 2. 端点定义 / Endpoint

### 2.1 A股热门个股排名 / Stock Hot Rank (响应增强)

```
GET /api/v1/market/stock-hot-rank
```

#### 查询参数 / Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| limit | integer | No | 50 | 返回最大条数 |

#### 成功响应 / Success Response — `200 OK`

```json
[
  {
    "rank": 1,
    "symbol": "600519",
    "name": "贵州茅台",
    "price": 1750.50,
    "change_pct": 1.25,
    "change_amount": 21.50,
    "volume": 12345678,
    "turnover": 21500000000,
    "sector": "白酒",
    "hot_reason": "机构加仓+业绩超预期",
    "asset_type": "A"
  }
]
```

#### 字段说明 / Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| rank | integer | Yes | 热度排名 |
| symbol | string | Yes | 标的代码（6位数字） |
| name | string | Yes | 标的名称 |
| price | number | Yes | 最新价 |
| change_pct | number | Yes | 涨跌幅（%） |
| change_amount | number | Yes | 涨跌额 |
| volume | number | **新增** | 成交量（股） |
| turnover | number | **新增** | 成交额（元） |
| sector | string | **新增** | 所属行业（申万一级/二级） |
| hot_reason | string | No | 热度原因（同花顺原始字段） |
| asset_type | string | Yes | `A` |

#### 行为契约 / Behavioral Contract (Z25)

1. **数据源**: 同花顺热度榜（`lv.stock_hot_rank_ths`）返回 `rank/code/name/tag`。
2. **Volume/turnover 补全**: 取前 N 只代码，调用 `fetch_a_stock_batch(symbols)` 批量获取实时行情（含 volume、turnover），按 symbol join 回原列表。
3. **Sector 补全**: 
   - 优先从批量行情返回的 `sector` 字段取值（若数据源提供）
   - 否则调用 `get_stock_industry_map(symbols)` 批量查询行业映射（缓存 1h）
   - 最终兜底为空字符串
4. **容错**: 任一补全步骤失败不阻塞主流程，该字段留空/默认值。
5. **缓存**: 热度榜本身 60s 缓存（既有），enrich 后的完整结果同缓存。

---

## 3. 新增内部服务函数 / Internal Service Functions

### `get_stock_industry_map(symbols: list[str]) -> dict[str, str]`

**位置**: `backend/app/services/market_service.py` 或 `backend/app/fetchers/sector_fetcher.py`

**职责**: 批量查询股票代码 → 行业名称映射。

**数据源**: 
- 优先：akshare `stock_board_industry_name_em`（申万行业）
- 降级：本地静态映射表（若有）

**返回**: `{symbol: sector_name, ...}`，失败返回空字典。

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 响应含 `volume` 字段（number） | ☐ | ☐ | 批量行情补全 |
| 响应含 `turnover` 字段（number） | ☐ | ☐ | 批量行情补全 |
| 响应含 `sector` 字段（string） | ☐ | ☐ | 行业映射补全 |
| 补全失败不阻塞主流程 | N/A | ☐ | 字段留空/默认 |
| verify_e2e 断言字段非空 | ☐ | ☐ | section_market 新增断言 |

---

## 5. 测试 / Tests

- 后端单测: `backend/tests/test_z25_stock_hot_rank.py`（mock levistock + 批量行情 + 行业映射）
- verify_e2e: `section_market` 模块新增 `stock_hot_rank` 字段断言