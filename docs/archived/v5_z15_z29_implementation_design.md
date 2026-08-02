# v5.2 — Z15 + Z29 可落地方案设计（实施标准版）

> 关联文档: `docs/v5_diagnostic_and_optimization_plan.md`（§十二 P1 Z15、§十七 Z29）
> 版本: v2.1（第 3 轮终审修订）
> 状态: 设计中（未实施）
> 范围: 仅 Z15（verify_e2e 补充）与 Z29（搜索自动补全不完善）两个问题；不含其他 Z 项。

---

## 0. 结论速览（TL;DR）

| 项 | 结论 |
|----|------|
| Z15 现状 | verify_e2e 已有 `section_search`/`section_fundamentals`/`section_factors`/`check_sector_data`，但断言强度不足：HK/US 只查 HTTP 200 不查结果数、异常路径 `check(..., True, ...)` 恒过、`section_fundamentals` 把 500 当 PASS、`section_admin` 被后定义的同名函数覆盖（弱版顶替强版） |
| Z29 现状 | 前端编码已由 axios `{params}` 自动完成（无需改）；后端 `/search` 是真正的断点：`market=HK/US` 只搜 24 只静态 ETF（`HKUS_ETF_MAP`），`00700`/`AAPL` 返回 0 条；无 `market` 参数的默认模式只搜 A 股 ETF，港股/美股完全搜不到；`include_stocks` 参数声明但从未使用 |
| Z15 ↔ Z29 耦合 | Z15 新加的严格断言（HK/US 搜索必须有结果）是 Z29 后端修复的**验收条件**。必须先落地 Z29 后端，再跑 Z15 的 `us-market`/`hk-market` 模块才能全绿。两者应同一批次实施、同一批次回归 |
| 方案总体 | **Z29**: 后端扩展 `search_hk_us` 为「静态基座 + akshare 全量 spot 缓存 + 实时 enrich」三级搜索，默认模式跨市场合并，`include_stocks` 按分支生效，搜索结果 `asset_type` 与组合/自选添加链路对齐；前端 2 处共 2 行改动（均在 WatchlistPanel）+ 2 个测试。**Z15**: 强化断言、消灭恒过检查、修复重复定义、补 sector rotation / factor-health 门禁 |
| 预估工作量 | 后端 ~4h，前端 ~0.5h，测试 ~2h（含 verify_e2e 扩展） |

---

## 1. 现状核实（代码事实，均已逐条验证）

### 1.1 verify_e2e.py 现状（`backend/scripts/verify_e2e.py`, 1550 行）

| 函数 | 行号 | 现状 | 问题 |
|------|------|------|------|
| `section_search()` | 1454 | A 股检查结果数；HK/US **只检查 HTTP 200** | 违反 Z15 目标（HK/US 搜索 0 条也 PASS）；异常路径 `check("A股搜索", True, ...)` **恒过** |
| F15 交叉市场断言（在 `section_market` 内） | 238-252 | `("A","510880"), ("HK","00700"), ("US","AAPL")` 断言 200 + 列表非空 | 断言正确，但**当前必然 FAIL**（`search_hk_us("00700")` 返回 0 条）→ 只有 `--module market` 时才会执行 |
| `section_fundamentals()` | 1479 | 500 也 `check(..., True)`；异常路径恒过 | 形同虚设（Z16 已在 Phase 35 修复，应严格化） |
| `section_factors(host, port)` | 995 | factor-health 200 + `status=="ok"` + 每符号 healthy + factors/active + factors/ic | 功能上已覆盖「section_factor_health」意图，但模块名是 `factors`，无 `factor-health` 别名 |
| `check_sector_data()` | 709 | `/sectors/industry|concept` 200 + 非空 + change_pct/main_inflow | 未覆盖 Z17 的 `/sectors/rotation`（板块轮动） |
| `section_admin()` **重复定义** | 883 / 1498 | 883 为完整版（token-usage/timeseries/thread-pool/metrics）；1498 为弱版（仅 sources/health），**后者在 1544 行覆盖前者** | 完整版 admin 检查被静默跳过 |
| `section_factor_zscore_check()` | 1130 | Z09 σ 门禁 | 保留（非本方案范围） |

### 1.2 后端搜索现状

**路由 `GET /api/v1/market/search`（`backend/app/routers/market.py:61-113`）**：

```
market=A   → Instrument 表(A股个股) → 空则降级 search_etf()
market=HK  → search_hk_us(keyword)
market=US  → search_hk_us(keyword)
market=null（默认）→ search_etf(keyword)   ← 前端默认模式入口（PortfolioManager/WatchlistPanel）走这里；
                                              UnifiedAnalysis 走 market=marketTab 分支
```

**`search_hk_us()`（`backend/app/services/market_service.py:608-668`）**：
- 基座: 静态 `HKUS_ETF_MAP`（579-605 行，仅 12 只港股 ETF + 12 只美股 ETF）
- 匹配: `kw in symbol.lower() or kw in name.lower()`（港股 ETF 名称为中文可匹配，如「盈富基金」；美股 ETF 名称为英文）
- enrich: `get_asset_realtime(symbol, market)` 尽力而为，失败降级为静态结果

**断点根因**：
1. **R1（个股缺失）**: `HKUS_ETF_MAP` 只有 ETF；搜 `00700`（腾讯）、`AAPL`（苹果）→ 0 条。
2. **R2（默认模式不跨市场）**: 无 `market` 参数时只走 `search_etf()`——该函数查询本地 `Instrument` 表且**不过滤 market/asset_type**（`market_service.py:537`），兜底 akshare ETF 列表；港股/美股在任何路径下都搜不到（`SPY`/`盈富基金` 全局搜索框返回 `[]`）。
3. **R3（死参数）**: 路由签名有 `include_stocks: bool = False` 但函数体从未引用（`market.py:65`）；前端 `useMarketSearch` 传 `{include_stocks: true}` 无任何效果。
4. **R4（HK 实时 enrich 断链，次要）**: `_exchange("00700")` 返回 `sz`（应为 `hk`），Sina/Tencent 路径对 5 位港股代码生成错误前缀 `sz00700`；仅东方财富 akshare spot 路径可用（`china_market.py:557-599`）。该问题**不在 Z29 修复范围**，本方案通过「个股一律不 enrich」从根源规避（见 2.2 改动 3 与 R5）。

### 1.3 数据源可用性（已核实）

> **instruments 表实测**：`data/portfolio.db` 中 `instruments` 共 1544 行，全部为 `market='A', asset_type='etf'` —— **无任何个股行**。含义：A 股个股搜索（含 `market=A` 分支与 `include_stocks=true` 的个股段）必须依赖 levistock `get_all_stocks()` 兜底（`/search/stocks` 已走此链路），仅查 instruments 会恒空。

| 数据源 | 函数 | 可用性 | 列结构（已从现有代码确认） |
|--------|------|--------|------|
| 港股全量 spot | akshare `stock_hk_spot_em()`（`china_market.py:566` 已在用） | 已接入项目，`no_proxy()` + `run_in_thread` + 60s 内存缓存 | `代码`(5位如 00700)、`名称`(腾讯控股)、`最新价`、`涨跌幅`、`成交量`、`成交额` |
| 美股全量 spot | akshare `stock_us_spot_em()` | akshare 1.18.81 已安装、函数存在（本机直连被拒，生产经 `no_proxy` 走代理，需实施时联调验证） | `名称`(中文: 苹果)、`代码`(AAPL)、`英文名称`(Apple Inc)、`最新价`、`涨跌幅` |
| 美股/港股实时 enrich | `get_asset_realtime(symbol, market)` | US→TwelveData/Finnhub（已配置 key）；HK→Sina/Tencent/EM 三级 | — |
| 静态兜底 | 现有 `HKUS_ETF_MAP` + 本方案新增 `HKUS_STOCK_MAP` | 离线可用 | — |

### 1.4 前端搜索入口（已核实）

| 入口 | 文件 | 调用 | 传参 |
|------|------|------|------|
| 组合 ETF 选择器 | `PortfolioManager.vue:521` | `marketApi.search(searchQuery.value)` | 无 market、无 include_stocks（默认模式） |
| 自选添加 | `WatchlistPanel.vue:237` | `marketApi.search(kw)` | 无 market、无 include_stocks（默认模式） |
| 标的分析搜索 | `UnifiedAnalysis.vue:191` | `fetch('/api/v1/market/search?keyword=...&market=...')` | market=marketTab，已 encodeURIComponent |
| （未接线）composable | `useMarketSearch.js:35` | `marketApi.search(q, { include_stocks: true })` | **当前未被任何组件引用**（仅被 `useMarketSearch.spec.js` 使用）——修正表述：真实默认模式入口是 PortfolioManager + WatchlistPanel 两处 |

> 注：`useMarketSearch` 是「未来全局搜索框」的预留 composable，本次不接线、不改动；4.2 为其补编码防护测试仅为防回归（若未来接线，中文编码已由 axios 保证）。

**编码结论**: `marketApi.search` 走 axios `{ params }`（`api/index.js:30`），axios 默认对 params 做 `encodeURIComponent`；`UnifiedAnalysis` 手动 `encodeURIComponent`。**前端中文编码已无问题**（v5 文档 Z13 亦已确认「非 bug」），Z29 无需改编码。

---

## 2. Z29 设计方案（后端为主）

### 2.1 目标行为（验收标准）

| 场景 | 当前 | 目标 |
|------|------|------|
| `GET /search?keyword=00700&market=HK&include_stocks=true` | `[]` | 返回腾讯控股等（非空，`market=HK`） |
| `GET /search?keyword=AAPL&market=US&include_stocks=true` | `[]` | 返回苹果等（非空，`market=US`） |
| `GET /search?keyword=SPY`（无 market，全局搜索框） | `[]` | 返回 SPY（US ETF，静态基座命中，无需 include_stocks） |
| `GET /search?keyword=盈富基金`（无 market） | `[]` | 返回 02800.HK（静态基座命中） |
| `GET /search?keyword=贵州茅台&include_stocks=true`（无 market） | `[]`（默认模式搜不到个股） | 返回贵州茅台（A 股个股，经 `_search_a_stocks` 的 instruments→levistock 降级链，见 2.2 改动 4） |
| `GET /search?keyword=腾讯&market=HK&include_stocks=false` | `[]` | 仍返回 `[]`（ETF-only 模式不含个股，参数语义一致） |
| 所有路径异常 | 不抛 500 | 不抛 500（返回 `[]`，记 WARNING） |

### 2.2 后端改动（4 处）

#### 改动 1 — 新增静态基座 `HKUS_STOCK_MAP`（`market_service.py`，紧邻 `HKUS_ETF_MAP`）

新增约 15-20 只主要港股 + 15-20 只主要美股个股静态表，字段与 `HKUS_ETF_MAP` 一致 `{symbol, name, market}`：

```python
HKUS_STOCK_MAP: list[dict[str, str]] = [
    # 港股个股（5 位代码，无后缀）
    {"symbol": "00700", "name": "腾讯控股", "market": "HK"},
    {"symbol": "09988", "name": "阿里巴巴-W", "market": "HK"},
    {"symbol": "03690", "name": "美团-W", "market": "HK"},
    {"symbol": "01810", "name": "小米集团-W", "market": "HK"},
    {"symbol": "00005", "name": "汇丰控股", "market": "HK"},
    # … 实施时补全：港股另加 00388 港交所/00941 中国移动/01299 友邦保险/02318 中国平安/09618 京东集团-SW 等；
    #   美股另加 BRK.B/LLY/AVGO/JPM/V/XOM/COST/ORCL/PG/HD 等（每市场 15-20 只，选高流动性龙头）
    # 美股个股
    {"symbol": "AAPL",  "name": "苹果", "market": "US"},
    {"symbol": "MSFT",  "name": "微软", "market": "US"},
    {"symbol": "NVDA",  "name": "英伟达", "market": "US"},
    {"symbol": "GOOGL", "name": "谷歌-A", "market": "US"},
    {"symbol": "AMZN",  "name": "亚马逊", "market": "US"},
    {"symbol": "TSLA",  "name": "特斯拉", "market": "US"},
    {"symbol": "META",  "name": "Meta平台", "market": "US"},
    # … 实施时补全
]
```

> 理由：静态基座保证离线可用（与项目「静态基座 + 动态补充 + 熔断降级」既定模式一致，且不破坏 `test_F3_*` 三个既有测试的 `search_hk_us("SPY"/"盈富"/"")` 行为）。

#### 改动 2 — 新增全量 spot 缓存拉取函数（`china_market.py` fetcher 层，2 个新函数）

```python
def fetch_hk_spot_list() -> list[dict[str, Any]]:
    """港股全量 spot 列表（akshare stock_hk_spot_em），长 TTL 缓存，供搜索用。

    返回: [{"symbol": "00700", "name": "腾讯控股", "market": "HK"}, ...]
    失败返回 []，绝不抛异常。
    """
    # 实现: 与 _em_hk_realtime 相同的拉取模式（no_proxy() + run_in_thread），
    # 独立于其 60s 实时缓存，使用 sync_memory_cache key "hk_spot_list" + 6h TTL
    # （代码/名称变化极低频，搜索场景不需要秒级新鲜度）
    # 列映射: 代码 → symbol（5 位补零字符串），名称 → name
```

```python
def fetch_us_spot_list() -> list[dict[str, Any]]:
    """美股全量 spot 列表（akshare stock_us_spot_em），长 TTL 缓存，供搜索用。

    返回: [{"symbol": "AAPL", "name": "苹果", "name_en": "Apple Inc", "market": "US"}, ...]
    失败返回 []，绝不抛异常。
    """
    # no_proxy() + run_in_thread(_p, timeout=10, executor="long")
    # sync_memory_cache key "us_spot_list"，TTL 6h
    # 列映射: 代码 → symbol，名称 → name（中文），英文名称 → name_en
    # 注意：akshare 该接口列名以实际返回为准，实施第一步先打印列名确认
    #       （本机直连验证被拒，需在生产代理环境下核对列名与代码是否为 5 位补零）
```

要点：
- 与 `_em_hk_realtime` 的 60s 缓存不同，搜索列表用**6h 长 TTL**（`CACHE_TTL` 新增 `"hk_spot_list": 21600, "us_spot_list": 21600`，`ttl.py`）。
- **同步函数**（fetcher 层均为同步 + `run_in_thread` 包装，符合项目约定）。
- 全部 `try/except`，失败返回 `[]`，绝不让搜索端点崩。
- 若 `stock_us_spot_em` 在实施联调时不可用（境内网络/限流），降级为仅静态基座（2.2 改动 1），功能不缺失，只少长尾覆盖。

#### 改动 3 — 重写 `search_hk_us()`（`market_service.py:608-668`）

保持**签名兼容**（`search_hk_us(keyword="", enrich=True)`，不破坏 3 个 F3 测试），内部改为三级搜索：

```python
def _norm_symbol(s: str) -> str:
    """归一化去重键：去掉 .HK/.US 后缀（基座 ETF 带后缀、spot 全量列表不带）。"""
    return s.split(".")[0].lower()


async def search_hk_us(keyword: str = "", enrich: bool = True,
                       include_stocks: bool = False) -> list[dict[str, Any]]:
    """三级搜索。include_stocks=False 为默认（仅静态 ETF 基座，向后兼容，
    且使既有 F3 单测保持纯静态、不触网——项目单测红线：外部网络必须 mock）；
    True 时启用 akshare spot 动态补充（调用方显式传入）。
    asset_type 统一为市场代码（"HK"/"US"），type 为证券种类（"etf"/"stock"）——
    与 PortfolioManager.selectHotEtf / watchlist 的 asset_type 语义对齐（见 R8/F3）。"""
    kw = keyword.lower().strip()
    # ① 静态基座: HKUS_ETF_MAP + HKUS_STOCK_MAP（离线可用，先算）
    base = [{"symbol": e["symbol"], "name": e["name"], "market": e["market"],
             "asset_type": e["market"], "type": "etf" if e in HKUS_ETF_MAP else "stock"}
            for e in HKUS_ETF_MAP + HKUS_STOCK_MAP
            if not kw or kw in e["symbol"].lower() or kw in e["name"].lower()]
    # ② 动态补充: akshare 全量 spot（尽力而为；与基座按归一化 symbol 去重，基座优先）
    #    include_stocks=False 时跳过（仅返回静态 ETF，参数语义一致）
    spot: list[dict] = []
    if include_stocks:
        for mk, fetcher in (("HK", fetch_hk_spot_list), ("US", fetch_us_spot_list)):
            # 注意: _call 失败返回 None 而非抛异常（market_service.py:32-46），
            # 必须判空；fetcher 是同步函数，经 _call 的 run_sync 线程池执行，
            # 遵守 AGENTS.md「async def ≠ 非阻塞」红线
            rows = await _call(fetcher, timeout=15)
            if not rows:
                continue
            spot += [{"symbol": r["symbol"], "name": r.get("name_en") or r["name"],
                      "market": mk, "asset_type": mk, "type": "stock"}
                     for r in rows
                     if not kw or kw in r["symbol"].lower()
                     or kw in r["name"].lower() or kw in (r.get("name_en") or "").lower()]
    # 去重（key 归一化处理 .HK/.US 后缀不一致；base 在前 → 基座优先天然成立，
    # spot 重复行被 seen 拦截，同时避免把基座 ETF 误标 stock）
    seen, merged = set(), []
    for it in base + spot:
        key = (_norm_symbol(it["symbol"]), it["market"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(it)
    results = merged[:30]
    # ③ enrich 仅作用于 type == "etf" 的命中（全部来自静态 ETF 基座，≤24 只）:
    #    - spot 个股命中量大且行内已带实时价 → 不 enrich（防限流）
    #    - 静态基座个股命中（如 00700）HK 实时链路因 _exchange 前缀 bug 不可靠（R5）→ 不 enrich
    enriched = []
    for it in results:
        if it["type"] == "etf" and enrich:
            q = await get_asset_realtime(it["symbol"], it["market"])   # 既有逻辑，失败降级
            if q and q.get("price") is not None:
                it = {**it, "price": q["price"]}
            if q and q.get("change_pct") is not None:
                it = {**it, "change_pct": q["change_pct"]}
        enriched.append(it)
    return enriched
```

设计要点：
- **`asset_type`/`type` 语义（关键修订）**：`asset_type` 统一为**市场代码**（`"HK"`/`"US"`），`type` 为证券种类（`"etf"`/`"stock"`）。原因：`PortfolioManager.selectSearch`/`WatchlistPanel.selectSuggestion` 用 `asset_type` 回填表单、`addEtf`/`addWatchlist` 据此路由行情，`selectHotEtf` 已用 `'US'`/`'HK'`；若沿用旧的 `asset_type="etf"`，SPY 等会以错误类型入库拿不到行情（R8 已实证）。
- **spot 行误标 ETF 的处置（HK 为必做）**：`stock_hk_spot_em`/`stock_us_spot_em` 可能混入未收录进基座的 ETF → 以 `"stock"` 返回，属长尾可接受；但**基座已收录的 ETF**（如 02800.HK）绝不能被 spot 行重复且误标 `stock` — 通过归一化去重（`_norm_symbol` 去 `.HK` 后缀 + base 优先）强制保证，联调时若确认 spot 含其他 ETF 且需要精确，可把「symbol ∈ 基座 symbol 集」的 spot 行改标 `"etf"`（可选优化）。
- **enrich 范围**：仅对 `type == "etf"` 命中做 `get_asset_realtime` 实时补充（全部来自静态 ETF 基座，≤24 只，F3 测试行为不变）；个股命中（静态基座与 spot 均不 enrich — 前者因 HK 实时链路不可靠 R5，后者因量大防限流）。→ 详见风险 R5/R6。
- **线程池红线**：fetcher 是同步函数，必须经 `_call(fetcher, timeout=15)`（`market_service.py:32` 既有线程池包装）调用，严禁在 async 函数内直调（AGENTS.md「async def ≠ 非阻塞」红线）。
- **单测不触网**：`include_stocks` 默认 `False` → 既有 F3 测试不触发 spot 拉取；新增测试显式 `include_stocks=True` 并 patch 两个 spot fetcher（见 4.1）。

#### 改动 4 — 重写 `/market/search` 路由（`market.py:61-113`）

```python
@router.get("/search")
async def search(
    keyword: str = Query(""),
    market: str | None = Query(None, description="Market filter: A/HK/US/global; null = 跨市场"),
    include_stocks: bool = Query(False, description="结果中是否包含个股"),
) -> list[dict[str, Any]]:
    ...
```

| market 参数 | 行为（新） |
|------------|-----------|
| `"A"` | 现状保留：Instrument 表(A 股个股) → 空则降级 `search_etf`；个股是本分支主结果，`include_stocks` 不改变行为 |
| `"HK"` / `"US"` | `search_hk_us(keyword, include_stocks=include_stocks)`：`include_stocks=true` → 静态 ETF + spot 个股/证券；`false`（路由默认透传）→ 仅静态 ETF 基座（向后兼容） |
| `"global"` | 与 None 同（保留参数兼容） |
| `None`（默认） | **跨市场合并**：`search_etf(keyword)`（A 股 ETF）+ `search_hk_us(keyword, enrich=False, include_stocks=include_stocks)`（HK/US）；`include_stocks=true` 时另追加 A 股个股（`_search_a_stocks(keyword)`）并按「A股ETF → A股个股 → HK → US」拼接。每段截断 top 10，总计 ≤ 30；A 股 ETF 优先（保持组合选择器现有体验） |

要点：
- **`_search_a_stocks(keyword)` 规格（实证修正）**：instruments 表现状**只有 1544 只 A 股 ETF、无个股行**（`data/portfolio.db` 实测），因此该 helper **不能只查 instruments**，须镜像既有 `/search/stocks` 端点（`market.py:117-157`）的降级链：① instruments 表 `market="A" and asset_type="stock"` 模糊查询；② 空 → `market_data_hub.get_all_stocks()`（levistock 全量 A 股，1h 缓存）过滤 symbol/name → top 10。**仅供默认分支 `include_stocks=true` 使用；`market=A` 分支保持现状不动**（Instrument 个股 → 空则 search_etf 兜底），避免行为变更影响 `UnifiedAnalysis`。
- **`include_stocks` 真正生效**：默认（None）分支按它决定是否混入 A 股个股；这是「前端传了但后端不用」死参数的修复。
- **search_etf 结果过滤**：`search_etf` 不设 market/asset_type 过滤（`market_service.py:537`），可能返回 `asset_type != "etf"` 的行且统一标 `type="etf"` → 默认分支拼接前先过滤为 `asset_type == "etf"`，避免与 `_search_a_stocks` 的结果重复（Finding 5）。
- **路由级去重与截断**：四段拼接后按 `(market, symbol)` 去重（跨段可能重复，如 A 股个股同时在 search_etf 兜底与 _search_a_stocks 中），最后统一 `results[:30]`（4 段 × top10 = 40 > 30，必须最终截断）。
- **性能**：默认分支并发执行 `search_etf` + `search_hk_us`（`asyncio.gather`），`search_hk_us` 传 `enrich=False`（spot 列表已含实时价，不再二次查询），单次搜索预算 < 500ms（除首次 spot 拉取）。
- **排序**：默认分支返回顺序 = A 股 ETF → (include_stocks 时 A 股个股) → HK → US，保证组合选择器现有体验不劣化。
- **响应结构**：统一 `{symbol, name, market, asset_type, type, [price], [change_pct]}`，与现有契约一致（asset_type 为市场代码，见 2.4）。
- 所有分支异常照旧捕获 → `[]`，HTTP 200。

### 2.3 前端改动（2 处，共 2 行，均在 `WatchlistPanel.vue`）

| 文件 | 改动 | 理由 |
|------|------|------|
| `WatchlistPanel.vue` `doSearch()`（~237） | `marketApi.search(kw)` → `marketApi.search(kw, { include_stocks: true })` | 自选可加个股（如 AAPL/00700），当前搜不到 |
| `WatchlistPanel.vue` `selectSuggestion()`（~243） | 增加一行：`if (s.market === 'HK' \|\| s.market === 'US') form.value.asset_type = s.market`（否则保持 `'A'`） | **必改（R8/Finding 1）**：结果回填必须带上市场类型，否则 `addWatchlist(symbol, 'A')` 会把 AAPL/00700 按 A 股入库 → `get_asset_realtime` 查错市场 → 名称退化、无行情 |
| `useMarketSearch.js` | 无需改动（已传 `include_stocks: true`；当前未被组件接线，见 1.4） | — |

> 明确不做：`PortfolioManager.vue` 是「组合 ETF 选择器」，保持 ETF 优先体验（默认分支跨市场后，`SPY`/`盈富基金` 已可搜到，无需传 include_stocks 混入 A 股个股）；其 `selectSearch` 已用 `r.asset_type` 回填，配合 2.2 改动 3 的 asset_type 语义（`"HK"`/`"US"`）天然正确。`UnifiedAnalysis.vue` 已传 market + 编码，无需改。

### 2.4 契约更新（强制，AGENTS.md「契约先行」）

`api-contracts/market/search.md` 必须先行更新（本方案交付物之一），新增/修订行为契约：
1. `market=null` 语义从「仅 ETF」改为「跨市场：A 股 ETF + HK/US ETF（+ include_stocks=true 时 A 股个股）」。
2. `include_stocks` 从「声明未用」改为按分支生效：**None/HK/US 分支** `true` → 静态 ETF 基座 + spot 个股/证券，`false` → 仅静态 ETF（向后兼容）；**market=A 分支无效果**（该分支本就以 A 股个股为主结果、ETF 为降级，`UnifiedAnalysis` 依赖此行为，不得因 `false` 跳过个股）。
3. **`asset_type` 语义修订**：`market=HK/US` 返回条目 `asset_type` 统一为市场代码（`"HK"`/`"US"`），`type` 为证券种类（`"etf"`/`"stock"`）——与 `PortfolioManager.selectHotEtf`/watchlist 表单语义对齐（旧契约中 HK/US ETF 返回 `asset_type:"etf"` 会导致添加后行情路由错误，见 R8/Finding 3）。
4. 响应示例补充港股个股（00700/腾讯控股）与美股个股（AAPL/苹果）条目（含 5 位港股代码、无后缀美股代码）。
5. 新增「搜索结果各市场截断 top 10、总计 ≤ 30」「默认分支排序 = A股ETF → A股个股 → HK → US」「默认分支结果按 (market, symbol) 去重」约束说明。

---

## 3. Z15 设计方案（verify_e2e 强化）

### 3.1 改动清单（`backend/scripts/verify_e2e.py`）

| # | 改动 | 说明 |
|---|------|------|
| C1 | **修复 `section_search()` 反模式**（1454-1476） | 删除所有 `check(..., True, ...)` 恒过路径；异常 → `check(..., False, ...)`。三个子断言（510300 / 盈富基金 / SPY，均无 market 参数 → 默认跨市场模式）在 Z29 落地后**必须全部返回非空**，逐条断言结果数 > 0 |
| C2 | **新增 `section_hk_market()`** | `GET /search?keyword=00700&market=HK&include_stocks=true` → 200 + 非空 + `all(r["market"]=="HK")`；`GET /search?keyword=盈富基金&market=HK` → 200 + 非空（静态 ETF 基座命中，无需 include_stocks） |
| C3 | **新增 `section_us_market()`** | `GET /search?keyword=AAPL&market=US&include_stocks=true` → 200 + 非空 + `all(r["market"]=="US")`；`GET /search?keyword=SPY&market=US` → 200 + 非空（静态 ETF 基座命中） |
| C4 | **新增 `section_factor_health(host, port)`** | 薄包装调用 `section_factors(host, port)`（保留现有完整断言），注册 `MODULES["factor-health"]`；`main()` 的 `(host, port)` 特判元组补上 `"factor-health"` |
| C5 | **强化 `section_fundamentals()`**（1479-1495） | 断言 `200` + `data.get("daily")` 为 list（可空）+ `data.get("symbol")` 存在；500/异常 → FAIL（Z16 已修，禁止再把 500 当 PASS）；注释删除「Tushare token 未配置」豁免；**顺带清理现有中文乱码标签**（1486-1493 行的「基本面端点在�?」等坏字符） |
| C6 | **扩展 `check_sector_data()`**（709-726） | 追加 `GET /sectors/rotation?limit=5` → 200 + 非空 + 条目含 `change_pct`（板块轮动门禁，对应 Z17 回归）。**注意**：rotation 数据源为 `lv.sector_industry_cls()`（外部 provider），`change_pct` 字段名需实施时先打印样例确认（与 R2 同款联调步骤），若列名不同则改为断言实际列名，避免门禁因环境字段差异误红 |
| C7 | **修复 `section_admin` 重复定义**（1498-1512） | 删除弱版定义，把「sources/health」检查并入强版 `section_admin()`（883）末尾；`MODULES["admin"]` 唯一指向强版 |
| C8 | **模块注册与 main() 特判** | `MODULES` 新增 `"hk-market"` / `"us-market"` / `"factor-health"`；`SMOKE_MODULES` 不变（`["health","market"]`） |
| C9 | **同步修正 `section_market` 内 F15 断言**（238-252） | F15 的 `("HK","00700")` / `("US","AAPL")` URL 补 `&include_stocks=true`（`include_stocks=false` 时个股应返回空，与 2.1 验收一致）；断言保持 200 + 非空 + `market` 字段正确 |

### 3.2 与 Z29 的依赖编排

```
Phase 1（本批次先行）: Z29 后端 4 处改动 + 契约更新 + 后端单测
Phase 2:              verify_e2e C1-C8（Z15）——此时 hk-market/us-market 才能全绿
Phase 3:              前端 2 行改动 + 前端测试 + npm run build
Phase 4:              全量回归: pytest + verify_e2e 全模块 + 手动走查搜索框
```

> 验收口径（写死到 verify_e2e）：`--module hk-market,us-market,factor-health,fundamentals,sectors` 必须全 PASS；**本方案新增/修改的检查（C1-C9）不得出现「恒过」**（既有其他 section 的恒过路径，如 `section_factor_ic`/`section_encoding`/`section_llm_import` 中的 `check(..., True, ...)`，不在本方案范围，见 §7 明确不做）。

---

## 4. 测试计划（TDD，先写失败单测）

### 4.1 后端单测（新增/修订）

**新文件 `backend/tests/test_z29_search.py`**（或并入 `test_v5_remaining_fixes.py`，实施时按现有文件组织）：

> **patch 目标（Hermeticity 红线，Finding 4）**：`search_hk_us` 内对 spot fetcher 采用函数内局部导入（`from ..fetchers.china_market import fetch_hk_spot_list, fetch_us_spot_list`，每次调用重新解析模块属性），因此所有涉及 spot 的测试 patch **模块属性** `app.fetchers.china_market.fetch_hk_spot_list` / `fetch_us_spot_list` 即可生效；路由级测试 patch `app.routers.market.search_hk_us`（`market.py:11` 顶部导入的绑定）。既有 3 个 F3 测试因 `include_stocks` 默认 `False` 不触网，**无需改动**。

| 用例 | 断言 |
|------|------|
| `test_search_hk_us_stock_symbol_00700` | patch `app.fetchers.china_market.fetch_hk_spot_list` → `search_hk_us("00700", include_stocks=True, enrich=False)` 非空且含 `00700`、`market="HK"`、`asset_type="HK"`、`type="stock"` |
| `test_search_hk_us_us_stock_aapl` | patch `fetch_us_spot_list` → `search_hk_us("AAPL", include_stocks=True, enrich=False)` 含 AAPL、`asset_type="US"` |
| `test_search_hk_us_chinese_name` | patch spot → `search_hk_us("腾讯", include_stocks=True, enrich=False)` 命中 00700（中文名匹配） |
| `test_search_hk_us_english_name_us` | patch spot → `search_hk_us("Apple", include_stocks=True, enrich=False)` 命中 AAPL（`name_en` 匹配） |
| `test_search_hk_us_static_fallback_when_spot_fails` | patch 两个 spot fetcher 抛异常 → 静态基座仍命中 `00700`/`AAPL`（降级不抛） |
| `test_search_hk_us_include_stocks_false_etf_only` | `search_hk_us("00700", include_stocks=False)` → 不含个股（仅静态 ETF）；`include_stocks=True` → 含个股 |
| `test_search_hk_us_dedup_base_first` | 基座与 spot 同时含 SPY → 结果只有一条且来自基座（`symbol=="SPY"`、`type=="etf"`） |
| `test_search_hk_us_dedup_hk_etf_suffix`（Finding 2） | patch spot 返回含 `02800` 行 → `search_hk_us("盈富基金", include_stocks=True)` **恰好一条**，`symbol=="02800.HK"`、`type=="etf"`（归一化去重，spot 同码行被丢弃、不误标 stock） |
| `test_search_hk_us_asset_type_market_code`（Finding 3） | 基座 ETF 命中 `asset_type=="HK"`/`"US"`（非 `"etf"`），`type=="etf"` |
| `test_search_hk_us_spot_not_enriched_batch` | patch `get_asset_realtime` → spot 命中 >10 条时 `get_asset_realtime` 不被调用；仅 `type=="etf"` 命中被 enrich（≤24 只） |
| `test_search_default_cross_market`（路由级） | patch `app.routers.market.search_etf`+`search_hk_us` → 无 market 参数返回合并列表；**当 A 股与 HK/US 均有命中时** A 股排在首位；总数 ≤ 30；`search_etf` 的非 ETF 行被过滤 |
| `test_search_include_stocks_true_adds_a_stocks` | patch instruments 查询返回空 + patch `market_data_hub.get_all_stocks` 返回含 600519 列表 → `include_stocks=true` 默认分支含 A 股个股段（验证 levistock 降级链，不依赖真实 instruments 个股数据） |
| `test_search_route_hk_us_nonempty`（路由级） | patch `app.routers.market.search_hk_us` 非空 → `/search?keyword=00700&market=HK&include_stocks=true` 返回 200 + 列表 |
| 既有 3 个 `test_F3_*` | **必须保持通过**（签名兼容 + include_stocks 默认 False 不触网） |

> 全部 mock 外部网络（akshare/requests），遵循 `conftest.py` 的 `asyncio_mode = auto`。

### 4.2 前端测试（新增 2 个）

| 用例 | 断言 |
|------|------|
| `WatchlistPanel.spec.js`（或既有组件测试文件）新增: `selectSuggestion()` 选中 `{market:'US', symbol:'AAPL'}` 后 `form.asset_type === 'US'`；选中 `{market:'A'}` 保持 `'A'` | 固化 2.3 的市场类型回填（Finding 1），防止未来回退导致 AAPL 按 A 股入库 |
| `useMarketSearch.spec.js` 追加: `doSearch()` 收到中文 keyword 时**原样**传给 `marketApi.search(q, { include_stocks: true })`（不预编码、不手拼 URL） | 固化「编码由 axios params 自动完成」事实：composable 传原始中文 + axios 层编码，双保险防回归手拼 URL（当前 composable 未接线，此测试为未来全局搜索框的防护） |

### 4.3 verify_e2e（即 Z15 本体的验收）

C1-C9 全部落地后，`python scripts/verify_e2e.py --module search,hk-market,us-market,factor-health,fundamentals,sectors,admin` 全 PASS；全模块 `python scripts/verify_e2e.py` 无 FAIL。

---

## 5. 风险与裁定

| # | 风险 | 裁定/缓解 |
|---|------|-----------|
| R1 | `stock_us_spot_em` 境内网络不可用（本机直连已被拒） | 静态基座兜底（改动 1）保证 AAPL/MSFT 等核心标的一定可搜；全量补充失败只少长尾，不阻断功能；实施第一步在代理环境验证列名 |
| R2 | `stock_hk_spot_em` 代码列格式（`700` vs `00700`）不确定 | 实施时打印样例确认；若为 `700` 需 `zfill(5)` 补零，单测以补零后格式断言 |
| R3 | spot 全量列表 ~6000 行，搜索响应体过大 | 每市场截断 top 10；仅返回 symbol/name/market/asset_type/type，不带价格（spot 命中） |
| R4 | 首次 spot 拉取阻塞搜索（6h TTL 前第一次调用 ~1-3s） | 可接受（单次缓存后瞬时）；备选：预热任务在启动时后台拉取（超出本方案范围，实施时不加） |
| R5 | HK 个股实时 enrich 断链（`_exchange` 前缀错误，sz00700） | **本方案裁定个股一律不 enrich**（含静态基座个股命中），从根源规避该 bug；HK 个股搜索只需「可搜到」，不断言带价格；ETF 命中 enrich 走既有链路不受影响 |
| R6 | 个股命中是否 enrich 的裁定 | **不 enrich 任何个股命中**（spot 命中量大防限流；静态基座个股命中因 R5 不可靠）。响应里个股命中无 price 字段，前端下拉只展示名称/代码，不受影响（`selectSearch` 只用 symbol/name/asset_type） |
| R7 | `search_hk_us` 重写破坏既有 3 个 F3 测试 | 签名兼容 + `include_stocks` 默认 `False` 使 F3 测试保持纯静态不触网；`SPY`/`盈富`/`""` 仍在基座中；4.1 明列回归用例 |
| R8 | 搜索结果的 `asset_type` 与组合/自选添加链路不一致 | **本方案核心修订（Finding 3）**：搜索返回 `asset_type` 统一为市场代码 `"HK"`/`"US"`（`type` 保留 `"etf"`/`"stock"`），与 `selectHotEtf` 一致。已知边界：`get_portfolio_realtime` 只对 A 股数字代码报价（`market_service.py:808-812`），HK/US 持仓**入库成功但无实时行情**——属既有产品限制，不在 Z29 范围，verify 走查时明确记录该行为，不断言 HK/US 持仓有价 |
| R9 | `get_asset_realtime` 对 `asset_type="etf"` 的 US 标的不路由到美股源（`market_service.py:906-911` 只对 `"US"` 走 TwelveData/Finnhub） | 由 R8 的 asset_type 修订根治：搜索与添加链路统一用 `"US"`/`"HK"` 市场代码，不再产生 `"etf"` 类型入库 |

---

## 6. 交付物清单（本方案的产出）

| 交付物 | 文件 | 类型 |
|--------|------|------|
| 契约更新 | `api-contracts/market/search.md` | 文档（实施前先行） |
| 后端改动 | `market_service.py`（HKUS_STOCK_MAP + search_hk_us）、`china_market.py`（fetch_hk_spot_list/fetch_us_spot_list）、`market.py`（路由）、`core/ttl.py`（2 个 TTL） | 代码 |
| verify_e2e 强化 | `backend/scripts/verify_e2e.py`（C1-C9） | 代码 |
| 后端测试 | `backend/tests/`（test_z29_search.py 等） | 测试 |
| 前端改动 | `WatchlistPanel.vue`（doSearch 传参 + selectSuggestion 回填，共 2 处 2 行）+ `WatchlistPanel.spec.js` + `useMarketSearch.spec.js` | 代码 |
| 验收 | `python -m pytest`、`python scripts/verify_e2e.py`（全模块）、`npm test`、`npm run build` | 门禁 |

## 7. 明确不做（防范围蔓延）

- ❌ 前端模糊匹配客户端（v5 文档「或添加前端模糊匹配客户端」——后端解决后无必要）
- ❌ `_exchange()` HK 前缀修复（R5，另立 issue）
- ❌ 搜索排序算法重构（Z20，独立问题）
- ❌ 预热阶段预拉 spot 列表（R4 备选，超范围）
- ❌ 改动 `PortfolioManager.vue` 搜索传参（保持 ETF 优先）
- ❌ `get_portfolio_realtime` 增加 HK/US 报价（既有产品限制，R8 记录边界，另立 issue）
- ❌ 清理既有 section（`section_factor_ic`/`section_encoding`/`section_llm_import` 等）中**非本次范围**的恒过检查（C1-C9 之外的恒过不在本方案内）
- ❌ 接线 `useMarketSearch` 到任一组件（预留 composable，本次不动）

---

## 8. 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-31 | 初稿：基于代码逐条核实的现状 + Z29 三级搜索 + Z15 断言强化 |
| v1.1 | 2026-07-31 | 第 1 轮自查修订：① 修正 spot 拉取函数「复用内核」表述（改为独立实现同模式）；② `_call` 线程池包装替换不存在的 `run_sync` 直调，并明确 `_call` 失败返回 `None` 需判空；③ 路由默认分支抽取 `_search_a_stocks` 共享 helper + 明确排序；④ spot 行误标 ETF 处置说明；⑤ 测试断言细化（A 股在前仅当双方非空 / 前端测试改为断言原样传参）；⑥ section_search 三个子断言在 Z29 后必须非空；TL;DR 前端改动量修正为 1 行 |
| v1.2 | 2026-07-31 | 第 2 轮修订（include_stocks 语义裁定）：① `search_hk_us` 新增 `include_stocks` 参数，`false` 时仅静态 ETF 基座（向后兼容、参数语义一致）；② 路由 None/HK/US 分支透传 `include_stocks`，market=A 分支保持个股为主不变（`UnifiedAnalysis` 依赖）；③ 验收表/verify_e2e C2/C3/C9 的个股用例 URL 补 `&include_stocks=true`，新增「include_stocks=false 返回空」反向用例；④ 契约 2 条改为按分支表述 |
| v1.3 | 2026-07-31 | 第 2 轮修订续：① `include_stocks` 默认值定为 `False`（F3 单测不触网、向后兼容，调用方显式传 True）；② enrich 范围裁定为「仅 ETF 命中」：个股（静态基座/spot）一律不 enrich，从根源规避 HK 实时前缀 bug 与 spot 限流风险；③ R5/R6 风险表述与交付物 C1-C9 同步更新 |
| v2.0 | 2026-07-31 | 第 2 轮独立 review（子代理）修订，4 MAJOR + 8 MINOR/NIT 全部处置：**MAJOR** ① WatchlistPanel `selectSuggestion` 必须回填 asset_type（否则 AAPL/00700 按 A 股入库无行情）→ 2.3/4.2 增加改动与测试；② HK ETF 后缀去重（`_norm_symbol` 归一化 + base 优先，`盈富基金` 恰好一条不误标 stock）→ 伪代码重写 + 新增单测；③ 搜索 `asset_type` 统一为市场代码 `"HK"`/`"US"`（对齐 selectHotEtf/watchlist，R8/R9 实证）→ 2.2/2.4/4.1 同步；④ 单测 Hermeticity：明确 patch 目标（模块属性 vs 路由绑定），F3 测试因默认 False 免改。**MINOR**：默认分支 40>30 截断修正 + search_etf 非 ETF 行过滤 + 路由级去重；enrich 块明确实现（type=="etf" 过滤）；验收口径限定 C1-C9；C5 乱码标签清理；C6 rotation 字段联调步骤；§1.4 修正 useMarketSearch 未接线事实；§7 增加 4 项明确不做 |
| v2.1 | 2026-07-31 | 第 3 轮终审修订（终审发现）：① **instruments 表实证只有 1544 只 A 股 ETF、无个股行** → `_search_a_stocks` 规格改为镜像 `/search/stocks` 的 instruments→levistock 降级链，`market=A` 分支保持现状不动；② 验收表「贵州茅台」行当前值修正为 `[]` 并标注降级链依赖；③ 单测补 patch `get_all_stocks` 用例；④ 头部版本号/「3 处入口」表述修正；⑤ 静态基座补全清单从悬空引用改为具体标的 |
