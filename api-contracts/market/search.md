# Contract: /api/v1/market/search (Z29 cross-market search)

> 关联方案: `docs/v5_z15_z29_implementation_design.md`（Z29 搜索自动补全不完善）
> 变更类型: 既有端点行为修订（market=null 跨市场合并 + include_stocks 按分支生效 + asset_type 语义对齐）
> 版本: v3.0（2026-07-31，Z29 实施修订）

## 1. 概述 / Overview
**功能描述**: 统一搜索。默认（无 `market` 参数）跨市场合并返回 A 股 ETF + 港股 ETF + 美股 ETF
（`include_stocks=true` 时追加 A 股个股）；`market=HK/US` 走 `search_hk_us` 三级搜索
（静态 ETF 基座 + 可选 akshare 全量 spot 个股）；`market=A` 保持个股优先、ETF 降级的既有行为。

## 2. 端点定义 / Endpoint
```
GET /api/v1/market/search?keyword=<kw>[&market=<A|HK|US|global>][&include_stocks=<bool>]
```

### 查询参数
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| keyword | string | No | "" | 代码/名称/拼音/首字母模糊匹配 |
| market | string | No | null | `A` / `HK` / `US` / `global`（`global` 与 null 同）；`null` = 跨市场合并 |
| include_stocks | bool | No | false | 结果中是否包含个股（按分支生效，见行为契约 3） |

### 响应体（统一结构）
```json
[
  { "symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock" },
  { "symbol": "510300", "name": "沪深300ETF", "market": "A", "asset_type": "etf", "type": "etf" },
  { "symbol": "00700",  "name": "腾讯控股", "market": "HK", "asset_type": "HK", "type": "stock" },
  { "symbol": "02800.HK", "name": "盈富基金", "market": "HK", "asset_type": "HK", "type": "etf" },
  { "symbol": "AAPL",  "name": "苹果", "market": "US", "asset_type": "US", "type": "stock" },
  { "symbol": "SPY",   "name": "SPDR S&P 500 ETF", "market": "US", "asset_type": "US", "type": "etf" }
]
```

## 3. 行为契约 / Behavioral Contract (Z29)
1. **`market=A`**：现状保留 — 优先查询 `Instrument` 表（`market="A"`, `asset_type="stock"`）；
   表无匹配行时降级 `search_etf(keyword)`（F2）。个股是本分支主结果，`include_stocks` 不改变其行为。
2. **`market=HK` / `market=US`**：委托 `search_hk_us(keyword, include_stocks=include_stocks)`：
   - `include_stocks=false`（默认）：仅静态 ETF 基座（`HKUS_ETF_MAP`），向后兼容，不触网。
   - `include_stocks=true`：静态基座（`HKUS_ETF_MAP` + `HKUS_STOCK_MAP`）+ akshare 全量 spot
     动态补充（`stock_hk_spot_em` / `stock_us_spot_em`，6h 长 TTL 缓存，尽力而为，失败降级为静态基座）。
   - 静态基座与 spot 按归一化 symbol（去 `.HK`/`.US` 后缀）去重，**基座优先**，绝不把基座 ETF 误标 stock。
3. **`include_stocks` 按分支生效**（修复死参数）：`None`（跨市场）/`HK`/`US` 分支 `true` →
   含个股；`false` → 仅 ETF。`market=A` 分支无效果（该分支本就以个股为主结果）。
4. **`asset_type` 语义（关键修订）**：`market=HK/US` 返回条目 `asset_type` 统一为**市场代码**
   （`"HK"`/`"US"`），`type` 为证券种类（`"etf"`/`"stock"`）— 与组合选择器 `selectHotEtf` /
   自选添加链路的 `asset_type` 语义对齐，避免 HK/US 标的按 A 股入库导致无行情。
5. **`market=null`（默认）/ `global`**：跨市场合并 = `search_etf(keyword)`（A 股 ETF，过滤
   `asset_type=="etf"` 行）+ `search_hk_us(keyword, enrich=False, include_stocks=include_stocks)`（HK/US）；
   `include_stocks=true` 时另追加 A 股个股（`_search_a_stocks`：instruments 表 → levistock 降级链）。
   返回顺序：**A 股 ETF →（include_stocks 时 A 股个股）→ HK → US**；各段 top 10，总计 ≤ 30；
   跨段按 `(market, symbol)` 去重；`search_etf` 的非 ETF 行被过滤。
6. **enrich（实时价格补充）范围**：仅 `type=="etf"` 命中做 `get_asset_realtime` 补充（≤24 只基座 ETF）；
   个股命中一律不 enrich（HK 实时链路前缀 bug + spot 量大防限流），响应中个股无 `price`/`change_pct`。
7. 任一路径异常均被捕获并记录 WARNING，最终返回 `[]`（HTTP 200，不抛 500）。

## 4. 错误与降级 / Error & Fallback
| 情况 | 行为 |
|------|------|
| HK/US spot 拉取失败/超时 | 降级静态基座（`HKUS_ETF_MAP` + `HKUS_STOCK_MAP`），不抛错 |
| A 股 instruments 表无个股行 | `_search_a_stocks` 降级 `market_data_hub.get_all_stocks()`（levistock）过滤 |
| 任意异常 | 捕获，返回 `[]`，HTTP 200 |

## 5. 测试 / Tests
- 后端单测：`backend/tests/test_z29_search.py`（13+ 用例，全部 mock 外部网络）。
- `verify_e2e.py`：`search` / `hk-market` / `us-market` 模块（C1-C3、C9），断言 200 + 非空 + market 字段。
- 反例（修复前）: `GET /search?keyword=00700&market=HK&include_stocks=true` 返回 0 条；
  `GET /search?keyword=SPY`（无 market）返回 `[]`。

## Frontend-Backend Checklist
- [x] 后端 `market=null` 跨市场合并（SPY / 盈富基金 可搜到）
- [x] 后端 `market=HK/US` + `include_stocks=true` 返回个股（00700 / AAPL）
- [x] HK/US 条目 `asset_type` = 市场代码（"HK"/"US"），`type` = "etf"/"stock"
- [x] 默认分支排序 A股ETF → A股个股 → HK → US；总计 ≤ 30
- [x] 前端 WatchlistPanel 传 `include_stocks: true` 且 `selectSuggestion` 回填 asset_type
- [x] verify_e2e 覆盖 `search` / `hk-market` / `us-market` 模块（无恒过断言）
