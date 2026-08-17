# Contract: /api/v1/market/search (Z29 cross-market search)

> 关联方案: `docs/v5_z15_z29_implementation_design.md`（Z29 搜索自动补全不完善）
> 变更类型: 既有端点行为修订（market=null 跨市场合并 + include_stocks 按分支生效 + asset_type 语义对齐）
> 版本: v3.1（2026-08-04，round7 O30：新增 `kind` 参数 + 板块/指数段）

## 1. 概述 / Overview
**功能描述**: 统一搜索。默认（无 `market` 参数）跨市场合并返回 A 股 ETF + 港股 ETF + 美股 ETF
（`include_stocks=true` 时追加 A 股个股）；`market=HK/US` 走 `search_hk_us` 三级搜索
（静态 ETF 基座 + 可选 akshare 全量 spot 个股）；`market=A` 保持个股优先、ETF 降级的既有行为。

## 2. 端点定义 / Endpoint
```
GET /api/v1/market/search?keyword=<kw>[&market=<A|HK|US|global>][&include_stocks=<bool>][&kind=<symbol|sector|index|all>]
```

### 查询参数
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| keyword | string | No | "" | 代码/名称/拼音/首字母模糊匹配 |
| market | string | No | null | `A` / `HK` / `US` / `global`（`global` 与 null 同）；`null` = 跨市场合并 |
| include_stocks | bool | No | false | 结果中是否包含个股（按分支生效，见行为契约 3） |
| kind | string | No | "all" | `symbol`（默认：股票/ETF 段）/ `sector`（板块段）/ `index`（指数段）/ `all`（全部，symbol + sector + index） |

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
8. **`kind` 参数（round7 O30，新增）**：
   - `kind=sector`：仅查询 `sectors` 表（`name ilike %kw%`），返回
     `{symbol: BK码, name, type: "sector"}`，独立于 market/stock 段（不影响现有 symbol 行为）。
   - `kind=index`：仅查询 `indices_meta` 表（`name/pinyin/first_letter ilike %kw%`），返回
     `{symbol: "sh000001", name, type: "index"}`。
   - `kind=symbol`：现有行为（stock/etf/HK/US 段），不含板块/指数。
   - `kind=all`（默认）：现有 stock/etf/HK/US 段 + **尾部追加** sector/index 段
     （每段 top 10，总计上限由各段共享；向后兼容——旧调用方不受影响）。
   - `market` 参数与 `kind` 正交：`kind=sector|index` 时忽略 `market`（板块/指数无市场维度）。
   - **R54（round27）指数 vs ETF 边界**：`indices_meta` 表**只存指数**，`_STATIC_EXTRA_INDICES`
     种子表不得混入 ETF（标普 500 的 SPY、半导体 SOXX、材料 XLB 等 `index_type=price` 伪装的 ETF 行
     已移除），也不得与彭博代码（`^GSPC`/`^DJI`/`^IXIC`）重复（仅保留 SPX/DJI/IXIC）。
     因此 `kind=index` 美股搜索「标普」**只返回 `SPX` 一条**，绝不含 SPY/^GSPC。
     上述 ETF（SOXX/XLB 等）改入 `market_service.HKUS_ETF_MAP`，在 `market=US` 个股/ETF tab
     （`search_hk_us`）以 `type="etf"`、`market="US"` 正确命中，与指数 tab 互不串场。

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

## 6. 排序契约 / Sorting Contract (Z20，合并自 search-sorting.md)

**分档优先级（高 → 低）**:

| 档位 | 规则 | 说明 |
|------|------|------|
| 1 | **精确代码匹配** | `symbol == keyword`（大小写不敏感） |
| 2 | **代码前缀匹配** | `symbol LIKE keyword%`（如 `510` → `510300`, `510050`） |
| 3 | **精确名称匹配** | `name == keyword` |
| 4 | **名称前缀匹配** | `name LIKE keyword%` |
| 5 | **名称包含匹配** | `name LIKE %keyword%` |
| 6 | **拼音/首字母匹配** | `pinyin LIKE keyword%` 或 `first_letter == keyword.upper()` |

**同档内次序**:
- ETF 优先于个股（同市场内）
- 按 `market` 顺序：`A` → `HK` → `US` → `index` → `commodity`
- 同档同市场同类型内：按 `symbol` 字典序升序

**总条数限制**: `LIMIT 30`（跨市场合并模式），单市场模式 `LIMIT 50`。

#### SQL 实现契约 (SQLite)

```sql
SELECT *, 
  CASE
    WHEN symbol = ? THEN 1                    -- 精确代码
    WHEN symbol LIKE ? || '%' THEN 2          -- 代码前缀
    WHEN name = ? THEN 3                      -- 精确名称
    WHEN name LIKE ? || '%' THEN 4            -- 名称前缀
    WHEN name LIKE '%' || ? || '%' THEN 5     -- 名称包含
    ELSE 6                                    -- 拼音/首字母（需额外列）
  END AS sort_rank,
  CASE asset_type WHEN 'etf' THEN 0 ELSE 1 END AS type_rank,
  market_order(market) AS market_rank,        -- A=1, HK=2, US=3, index=4, commodity=5
  symbol
FROM instruments
WHERE ...匹配条件...
ORDER BY sort_rank, type_rank, market_rank, symbol
LIMIT ?
```

> 注：`market_order` 为 SQL 标量函数或 CASE 表达式实现。

#### Python 降级实现契约 (Z20 同契约)

当走降级路径（如 `get_all_stocks()` 返回列表后 Python 过滤）时，**必须复用相同排序逻辑**：

```python
def _sort_search_results(items: list[dict], keyword: str) -> list[dict]:
    """统一排序契约：SQL 与 Python 行为完全一致。"""
    kw = keyword.strip().upper()
    
    def rank(item):
        sym = item.get("symbol", "").upper()
        name = item.get("name", "")
        asset_type = item.get("asset_type", "")
        market = item.get("market", "")
        
        # 档位 1-5
        if sym == kw:
            sort_rank = 1
        elif sym.startswith(kw):
            sort_rank = 2
        elif name == keyword:
            sort_rank = 3
        elif name.startswith(keyword):
            sort_rank = 4
        elif keyword in name:
            sort_rank = 5
        else:
            # 拼音/首字母匹配（简化：检查首字母）
            first_letters = ''.join([c[0] for c in name.split() if c]).upper() if name else ''
            if first_letters.startswith(kw):
                sort_rank = 6
            else:
                sort_rank = 7
        
        type_rank = 0 if asset_type == "etf" else 1
        market_order = {"A": 1, "HK": 2, "US": 3, "index": 4, "commodity": 5}.get(market, 9)
        
        return (sort_rank, type_rank, market_order, sym)
    
    return sorted(items, key=rank)
```

#### 排序适用范围 / Scope

| 端点/功能 | 适用排序契约 |
|-----------|-------------|
| `GET /api/v1/market/search` | ✅ 全模式 |
| `GET /api/v1/market/watchlist` 建议搜索 | ✅ 复用 `_sort_search_results` |
| `market_data_hub.search_etf()` | ✅ 内部复用 |
| `market_data_hub.search_stocks()` | ✅ 内部复用 |

#### 排序契约测试 / Sorting Tests

- 后端单测: `backend/tests/test_z20_search_sort.py`（构造测试数据，验证 SQL 与 Python 排序结果完全一致）
- verify_e2e: `section_search` 模块新增顺序断言用例

#### 排序契约检查表 / Sorting Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 搜索结果按分档排序（代码精确→代码前缀→名称精确→名称前缀→名称包含→拼音） | ☐ | ☐ | 核心契约 |
| 同档内 ETF 优于个股 | ☐ | ☐ | type_rank |
| 同档同类型内按市场序 A→HK→US | ☐ | ☐ | market_rank |
| 最终按 symbol 字典序 | ☐ | ☐ | 确定性 |
| SQL 与 Python 降级排序结果一致 | N/A | ☐ | 单测对比验证 |
| verify_e2e 顺序断言（输入 510/茅台/沪深300） | N/A | ☐ | section_search 新增 |

## Frontend-Backend Checklist
- [x] 后端 `market=null` 跨市场合并（SPY / 盈富基金 可搜到）
- [x] 后端 `market=HK/US` + `include_stocks=true` 返回个股（00700 / AAPL）
- [x] HK/US 条目 `asset_type` = 市场代码（"HK"/"US"），`type` = "etf"/"stock"
- [x] 默认分支排序 A股ETF → A股个股 → HK → US；总计 ≤ 30
- [x] 前端 WatchlistPanel 传 `include_stocks: true` 且 `selectSuggestion` 回填 asset_type
- [x] verify_e2e 覆盖 `search` / `hk-market` / `us-market` 模块（无恒过断言）
