# Contract: TickFlow 实时行情尾环 / TickFlow Realtime Tail Ring (round13 §3.2)

> **用途**: 免费层 TickFlow key 模式实时快照（`quotes.get`，≤5 只/次）接入三条降级链**尾环**
> （非主环——平时 A 股 tencent/sina、美股 TwelveData/Finnhub 主用，失效才切，规避速率限制）：
> - P1 美股：`market_service._route_us` 链尾（TwelveData → Finnhub → TickFlow）
> - P2 港股：`china_market.fetch_hk_stock_realtime` 链尾（sina → tencent → EM → TickFlow）
> - P3 A 股单只：`china_market.fetch_a_stock_realtime` 链尾（mootdx → tencent → sina → TickFlow）
> - 批量（>5 只）**拒绝**（诚实降级：免费层 5 只/次上限，不做分批伪装）

---

## 1. 概述 / Overview

**功能描述 / Description**: 新增通用包装 `_tickflow_quotes(symbols) -> list[dict]`，
把 TickFlow 实时快照映射为项目统一行情 dict；接入 A/HK/US 三条单只实时链尾环。

**触发场景 / Trigger**: 主链数据源熔断/失效时降级；技术分析页单只标的实时行情。

---

## 2. 内部接口 / Internal Interface

### 2.1 `china_market._tickflow_quotes(symbols: list[str]) -> list[dict]`

| 行为 | 说明 |
|------|------|
| 无 key（`.env` `TICKFLOW_API_KEY` 为空） | 短路返回 `[]`（route 继续下一源） |
| `len(symbols) > 5` | 返回 `[]`（免费层上限，诚实降级不拆分） |
| symbol 映射 | A 股 `510300`→`510300.SH/SZ`（5/6→SH，其余→SZ）；港股 `00700`→`00700.HK`；美股 `AAPL`→`AAPL.US` |
| 执行 | `run_in_thread` + 8s 超时 + 异常隔离返回 `[]` |

**输出行结构**（与现有实时行情链对齐）：

```json
{
  "symbol": "510300",
  "name": "沪深300ETF",
  "price": 4.751,
  "previous_close": 4.72,
  "open": 4.73,
  "high": 4.76,
  "low": 4.71,
  "volume": 123456,
  "amount": 1234567.8,
  "change_pct": 0.66,
  "change_amount": 0.031,
  "turnover_rate": 0.5,
  "asset_type": "A"
}
```

| 字段 | 来源 | 说明 |
|------|------|------|
| `symbol` | 请求原始代码 | 返回与请求一致（含前缀剥除规则同 `_strip_a_prefix`） |
| `price` | `last_price` | 最新价 |
| `previous_close` | `prev_close` | 昨收 |
| `change_pct` | `ext.change_pct`（缺失时 `(price-prev_close)/prev_close*100` 兜底） | 涨跌幅 % |
| `change_amount` | `ext.change_amount`（缺失时 `price-prev_close` 兜底） | 涨跌额 |
| `turnover_rate` | `ext.turnover_rate` | 换手率（可选） |
| `name` | `ext.name` | 名称（可选） |

### 2.2 降级链扩展

```
fetch_a_stock_realtime:  mootdx → tencent → sina → tickflow(尾环)
fetch_hk_stock_realtime:  sina → tencent → dongfang(EM) → tickflow(尾环)
_route_us:                twelvedata → finnhub → tickflow(尾环)
```

- tickflow 环输出经 `_filtered` 语义（price>0 才视为命中）——`_tickflow_quotes` 返回
  空/全 0 → route 继续下一源（对尾环即结束，返回 None → 调用方降级）。
- 源名注册：`tickflow`（SourceRegistry 熔断路由自动管理健康状态）。

---

## 3. 降级 / Degradation

| 场景 | 行为 |
|------|------|
| 无 key | 短路返回 []，零额外调用 |
| >5 只批量 | 返回 []（批量场景不走 tickflow，P3 仅单只场景） |
| 429/超时 | route 记录失败 + 熔断退避（既有机制） |
| 非交易时段 | 返回盘后快照（TickFlow 商业 API 无 EM 反爬，非交易时段可用） |

## 4. 验收 / Acceptance

- [x] 单测：字段映射（mock TickFlow，`last_price→price`、`ext.change_pct→change_pct`）
- [x] 单测：无 key 短路返回 []
- [x] 单测：>5 只拒绝返回 []
- [x] 单测：A/HK/US symbol 映射
- [x] 单测：三条链路由含 `tickflow` 尾环（mock registry.route 捕获 providers）
- [x] 真实链路：三市场各取 1 只非空（宿主机实测，AAPL.US / 00700.HK / 510300.SH）
- [x] 全量测试绿

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| HTTP 端点变更 | N/A | N/A | 纯降级链扩展 |
| 既有主链行为不变 | N/A | ☐ | tickflow 仅尾环 |
| 真实数据非兜底 | N/A | ☐ | 三市场实测非空 |
| 批量诚实降级 | N/A | ☐ | >5 拒绝不拆分 |
