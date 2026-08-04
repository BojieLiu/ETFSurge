# Contract: /api/v1/market/fund-flow/{symbol} (round7 O28)

> 关联方案: `docs/round7-rediagnosis.md` §7 O28（热点股票技术分析弹窗增强——资金流区块）
> 变更类型: 新增端点
> 版本: v1.0（2026-08-04）

## 1. 概述 / Overview
**功能描述**: 单标的资金流查询——包装 `market_data_hub.get_fund_flow(symbol)`
（东财 `fetch_fund_flow`，主力净流入/流出）。供前端热点股票技术分析弹窗
`TechnicalAnalysisModal.vue` 的资金流区块展示（主力净流入/流出）。

## 2. 端点定义 / Endpoint
```
GET /api/v1/market/fund-flow/{symbol}
```

### 路径参数
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbol | string | Yes | 标的代码（如 `600519` / `510300`） |

### 响应体（成功）
```json
{
  "symbol": "600519",
  "main_net_inflow": 123456789.0,
  "main_net_inflow_pct": 3.21,
  "main_inflow": 500000000.0,
  "main_outflow": 376543211.0,
  "update_time": "2026-08-04 15:00:00"
}
```

### 响应体（数据源不可用）
```json
{
  "symbol": "600519",
  "main_net_inflow": null,
  "available": false,
  "detail": "数据源不可用（get_fund_flow 返回空）"
}
```

## 3. 行为契约 / Behavioral Contract
1. `GET /market/fund-flow/{symbol}` 调用 `market_data_hub.get_fund_flow(symbol)`（同步，
   内部 fetcher 已有超时/降级保护）；返回结构为东财资金流字段的直通（snake_case 化）。
2. `get_fund_flow` 返回 `None` 或异常时 → HTTP 200 + `main_net_inflow: null` +
   `available: false`（不抛 500）。
3. 主字段 `main_net_inflow`（主力净流入，元）为资金流区块核心数据；
   `main_net_inflow_pct`（占成交额比例）可选；其余字段尽力而为。
4. 前端 `marketApi.fundFlow(symbol)` 封装此端点（`/market/fund-flow/${symbol}`）。

## 4. 错误与降级 / Error & Fallback
| 情况 | 行为 |
|------|------|
| 数据源失败/冷却 | HTTP 200 + `main_net_inflow: null` + `available: false` |
| 任意异常 | 捕获，返回 HTTP 200 降级结构（不抛 500） |

## 5. 测试 / Tests
- 后端单测：`backend/tests/test_fund_flow_endpoint.py`（mock `market_data_hub.get_fund_flow`：
  ① 正常返回字段直通；② 返回 None → `available: false`；③ 异常 → 200 降级）。
- `verify_e2e.py`：`market` 模块可加 fund-flow 探针（数据源可用时非空）。

## Frontend-Backend Checklist
- [ ] 后端 `GET /market/fund-flow/{symbol}` 返回东财资金流字段（snake_case）
- [ ] 数据源不可用时 200 + `available: false`，不抛 500
- [ ] 前端 `marketApi.fundFlow(symbol)` 封装
- [ ] `TechnicalAnalysisModal.vue` 资金流区块渲染（主力净流入/流出）
