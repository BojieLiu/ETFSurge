# 板块/概念数据优化方案

> 多资产实时行情分析与 ETF 组合管理系统 · 行情研判数据增强
> 版本: v3.0 | 更新日期: 2026-07-26 | 状态: **部分实施**
> ✅ Phase 1-2 已实施（数据采集 + 缓存写入 + 定时刷新）
> ❌ Phase 3-6 待实施（API 实时行情 / LLM 注入 / 综合研判 / 前端可视化）

---

## 1. 问题总览

当前系统中板块（行业）和概念板块的数据从采集、缓存、API 到 LLM Prompt 存在 **4 层断裂**，导致行情研判报告中的板块/概念数据严重缺失，LLM 无法引用真实的板块热点和资金流向信息。

| 层级 | 问题 | 严重程度 | 影响范围 |
|------|------|----------|----------|
| **L1 数据采集** | `compute_sector_momentum()` 只采集申万一级行业，遗漏概念板块 | P0 | LLM 报告缺失概念板块分析 |
| **L2 缓存写入** | `pool_manager._sector_momentum_cache` 无写入入口，永远为空 | P0 | LLM 报告 sector_momentum 段落恒为空白 |
| **L3 API 响应** | `/sectors/industry` 和 `/sectors/concept` 只返回 code+name，丢实时行情 | P1 | 前端搜索框无涨跌幅颜色，UX 不佳 |
| **L4 LLM Prompt** | `generate_advice()`（llm.py:477-487）用 `asset_type` 筛选但 `market_data` 不含板块条目 | P0 | "暂无板块热力数据" 恒成立 |
| **L5 前端展示** | `fetch_hot_plates()` / `fetch_sector_heat()` 等 6 个路由标记 `TODO: 未接入前端` | P2 | 无热点板块排行可视化 |
| **L6 定时刷新** | APScheduler 只刷新行情和新闻，无板块数据刷新任务 | P1 | 板块数据可能过时 |

---

## 2. 技术背景

### 2.1 数据源现状

| 数据源 | 接口函数 | 返回内容 | 速度 |
|--------|----------|----------|------|
| levistock | `lv.sector_em("industry")` | 行业板块实时行情（涨跌幅、资金流、涨跌家数） | ~0.5s |
| levistock | `lv.sector_em("concept")` | 概念板块实时行情 | ~0.5s |
| akshare | `ak.stock_board_industry_spot_em()` | 东方财富行业板块行情（含主力净流入） | ~1s |
| akshare | `ak.stock_board_concept_spot_em()` | 东方财富概念板块行情 | ~1s |
| levistock | `lv.get_sector_hot_plates()` | 财联社热点板块 + 涨停股 | ~0.3s |
| levistock | `lv.get_sector_heat()` | 板块热度排行 | ~0.3s |
| levistock | `lv.sector_industry_cls()` | 行业板块实时行情(财联社)含首板股 | ~0.3s |

### 2.2 数据流路线（当前）

```
APScheduler (15s)
  └─ refresh_market_cache() ──→ get_portfolio_realtime() ──→ WS广播
APScheduler (30s)
  └─ refresh_news_cache()   ──→ WS广播
                    ┌ 没有板块任务块 ─┐
pool_manager.get_sector_momentum()
  └─ cache miss ──→ return []  ←── 从未被写入
```

### 2.3 数据流路线（目标）

```
APScheduler (15s)
  ├─ refresh_market_cache()
  ├─ refresh_sector_cache()      ←── 新增
  │    ├─ compute_sector_momentum()      → 行业+概念动量
  │    ├─ fetch_hot_plates()             → 热点板块
  │    └─ fetch_sector_heat()            → 板块热度排行
  └─ pool_manager.update_sector_cache() → 写入内存

LLM Report
  └─ _build_design_report_prompt()
       ├─ sector_momentum (行业+概念，各前15)
       ├─ hot_plates       (财联社热点板块)
       └─ sector_heat      (板块热度排行)
```

---

## 3. 实施方案（6 个阶段，按依赖顺序）

### Phase 1 — 数据采集增强 ✅ 已实施

**实施证据**: `backend/app/services/market_trends.py` 中 `compute_sector_momentum()` 已同时采集行业和概念板块动量。`backend/app/fetchers/sector_fetcher.py` 提供了 `fetch_industry_sectors()` / `fetch_concept_sectors()` 双源降级（levistock → akshare），akshare 回退包含完整实时行情字段。

**目标**: `compute_sector_momentum()` 同时采集行业和概念板块动量

**涉及文件**: `backend/app/services/market_trends.py`

**改动要点**:
1. 将现有 `compute_sector_momentum()` 重命名为 `_compute_industry_momentum()`
2. 新增 `_compute_concept_momentum()`，使用 `ak.stock_board_concept_name_em()` + 涨幅排名
3. 新 `compute_sector_momentum(top_n=15)` 合并行业和概念结果，以 `type` 字段区分

```python
async def compute_sector_momentum(top_n: int = 15) -> list[dict[str, Any]]:
    """计算行业+概念板块动量。
    
    返回:
      [{sector, sector_code, type: "industry"|"concept", 
        rank_current, change_pct, main_inflow, up_count, down_count}]
    """
    ind = await _compute_industry_momentum(top_n)
    con = await _compute_concept_momentum(top_n)
    return ind + con
```

4. 每个条目增加 `sector_code`、`type`（"industry"/"concept"）、`main_inflow` 字段，供 LLM 区分引用

### Phase 2 — 缓存写入与定时刷新 ✅ 已实施

**实施证据**: `backend/app/services/pool_manager.py` 中 `update_sector_cache()` 方法已实现（调用 `compute_sector_momentum()` + `fetch_hot_plates()` + `fetch_sector_heat()` 写入内存缓存）。`backend/app/tasks/sector_refresh.py` 作为 60s APScheduler 任务定时调用。`main.py` 中已注册该刷新循环。

**目标**: pool_manager 的 sector_momentum_cache 有真实数据，APScheduler 定期刷新

**涉及文件**:
- `backend/app/services/pool_manager.py`
- `backend/app/tasks/market_refresh.py`（或新建 `sector_refresh.py`）
- `backend/app/main.py`

#### 2a. PoolManager 新增方法

在 `PoolManager` 类中新增：

```python
async def update_sector_cache(self) -> None:
    """刷新行业+概念板块动量缓存。"""
    import time
    from .market_trends import compute_sector_momentum
    try:
        data = await compute_sector_momentum(top_n=30)
        if data:
            self._sector_momentum_cache = data
            self._sector_momentum_cache_ts = time.time()
            logger.info("[pool] sector cache updated: %d rows", len(data))
    except Exception as e:
        logger.exception("[pool] update_sector_cache failed: %s", e)
```

#### 2b. 新增 APScheduler 任务

新建 `backend/app/tasks/sector_refresh.py`:

```python
async def refresh_sector_cache() -> None:
    """定时刷新板块动量缓存。"""
    from ..services.pool_manager import pool_manager
    await pool_manager.update_sector_cache()
```

#### 2c. main.py 注册定时任务

```python
from .tasks.sector_refresh import refresh_sector_cache

# 在 lifespan 中新增
scheduler.add_job(
    lambda: asyncio.create_task(refresh_sector_cache()),
    "interval", seconds=60, id="refresh_sector_cache",
    max_instances=1, coalesce=True,
)
```

刷新周期建议：**60s**（非交易日可停用，但保持简单直接定时运行）。

#### 2d. 缓存刷新也触发热点板块数据

`update_sector_cache()` 同时刷新三组数据：

```python
async def update_sector_cache(self) -> None:
    import time
    from .market_trends import compute_sector_momentum
    from ..fetchers.sector_fetcher import fetch_hot_plates, fetch_sector_heat
    try:
        # 1. 行业+概念动量
        momentum = await compute_sector_momentum(top_n=30)
        if momentum:
            self._sector_momentum_cache = momentum
            self._sector_momentum_cache_ts = time.time()
        
        # 2. 热点板块
        hot = await asyncio.to_thread(fetch_hot_plates, 15)
        self._hot_plates_cache = hot
        self._hot_plates_cache_ts = time.time()
        
        # 3. 板块热度排行
        heat = await asyncio.to_thread(fetch_sector_heat, 20)
        self._sector_heat_cache = heat
        self._sector_heat_cache_ts = time.time()
        
        logger.info("[pool] sector cache updated: mom=%d hot=%d heat=%d",
                     len(momentum or []), len(hot or []), len(heat or []))
    except Exception as e:
        logger.exception("[pool] update_sector_cache failed: %s", e)
```

### Phase 3 — API 增强：返回实时行情数据 ❌ 待实施

**现状**: `market_service.py` 中 `get_sectors_local()` 仍只返回 `sector_code` + `sector_name`（来自本地 Sector 表），不含实时行情字段。`market.py` 路由 `/sectors/industry` 优先调用 `get_sectors_local()`，导致当本地表有记录时返回纯 code+name。但 `sector_fetcher.py` 的 `_ak_industry_sectors()` 等 fallback 已有完整实时行情（price, change_pct, main_inflow 等 16 个字段），仅需调整路由优先级即可使用。

**目标**: `/sectors/industry` 和 `/sectors/concept` 返回带实时行情的数据，前端搜索框可显示涨跌幅颜色

**涉及文件**:
- `backend/app/routers/market.py`
- `backend/app/services/market_service.py`

#### 3a. 路由策略修改

当前路由优先查本地 `sectors` 表（仅 code+name），改为优先从 `sector_fetcher` 获取实时数据，本地表仅作搜索/下拉用：

```python
@router.get("/sectors/industry")
async def industry_sectors(limit: int = Query(200)) -> list[dict[str, Any]]:
    """行业板块列表（含实时行情）。"""
    return await asyncio.to_thread(fetch_industry_sectors, limit)
```

本地 `get_sectors_local()` 保留作为 `sync_sectors` 获取基础列表的后备，但路由不再优先用它。

#### 3b. 前端适配

`useSectorAnalysis.js` 中，列表数据已有 `change_pct` 字段后，在搜索结果项旁显示涨跌幅颜色：

```vue
<!-- SectorAnalysis.vue 搜索结果项 -->
<li v-for="(s, i) in filteredSectors" :key="s.sector_code">
  <span class="result-name">{{ s.sector_name }}</span>
  <span class="result-change" :class="s.change_pct >= 0 ? 'text-up' : 'text-down'">
    {{ s.change_pct > 0 ? '+' : '' }}{{ s.change_pct }}%
  </span>
  <span class="result-code">{{ s.sector_code }}</span>
</li>
```

### Phase 4 — LLM Prompt 注入 ❌ 待实施

**现状**: `llm_context.py` 的 `build_full_context()` 已包含 `include_sectors=True` 参数，通过 `pool_manager.get_sector_momentum()` 获取板块动量数据并注入上下文。但仅包含 momentum 排名，缺少财联社热点板块（`hot_plates`）、板块热度排行（`sector_heat`）数据。LLM prompt 仍无板块热点注入。

**目标**: 两份报告（市场研判报告 + 组合设计报告）都能引用板块和概念数据

**涉及文件**:
- `backend/app/analysis/llm.py`

#### 4a. 修复 `generate_advice()` 的板块数据注入

**当前问题**: llm.py 第 477-487 行遍历 `market_data` 过滤 `asset_type`，但 `market_data` 不包含板块条目（该数据源来自个股/ETF/商品行情，无板块类别）。

**修复方案**: 从 `pool_manager.get_sector_momentum()` 直接获取板块数据，构建独立的 `sector_summary`：

```python
# 替换现有 477-487 行
from ..services.pool_manager import pool_manager

pm = pool_manager
sector_momentum = pm.get_sector_momentum() or []
sector_lines = []
for item in sector_momentum[:15]:
    name = item.get("sector", item.get("sector_name", "?"))
    chg = item.get("change_pct", "")
    flow = item.get("main_inflow", "")
    typ = item.get("type", "industry")
    typ_label = "概念" if typ == "concept" else "行业"
    if chg != "":
        sector_lines.append(f"- **{name}**({typ_label}): 涨跌幅 {chg}%  资金流向 {flow}")
sector_summary = "\n".join(sector_lines) if sector_lines else "暂无板块热力数据。"
```

#### 4b. 增强 `_build_design_report_prompt()` (serve for `generate_design_report`)

**当前**: 只在 1122-1133 行有 "行业板块动量" 段落。

**增强**:

```python
# 1122 行后新增 "热点板块排行" 段落
if sector_momentum:
    lines.append("### 行业板块动量（申万一级，按当日强弱排名）")
    for item in sector_momentum[:10]:
        ...  # 现有逻辑
    
    # 新增：概念板块动量
    concept_items = [i for i in sector_momentum if i.get("type") == "concept"]
    if concept_items:
        lines.append("### 概念板块动量（按当日涨跌幅排名）")
        for item in concept_items[:10]:
            name = item.get("sector") or item.get("sector_name") or ""
            chg = item.get("change_pct")
            chg_txt = _fmt_pct(chg) if chg is not None else ""
            flow = item.get("main_inflow", "")
            flow_txt = f"  主力净流入: {flow}" if flow else ""
            lines.append(f"- {name}: {chg_txt}{flow_txt}")
        lines.append("")
```

同时新增一个 "热点板块" 段落，使用 `fetch_hot_plates` 数据：

```python
# 在 sector_momentum 段落之后
hot_plates = pm_cache.get("hot_plates", []) or []
if hot_plates:
    lines.append("### 今日热点板块（财联社）")
    for hp in hot_plates[:8]:
        name = hp.get("plate_name", hp.get("name", ""))
        reason = hp.get("reason", hp.get("hot_reason", ""))
        stocks = hp.get("stocks", hp.get("lead_stocks", []))
        stock_str = ", ".join([s.get("name", "") for s in stocks[:3]])
        lines.append(f"- **{name}**: {reason}")
        if stock_str:
            lines.append(f"  领涨: {stock_str}")
    lines.append("")
```

### Phase 5 — 综合研判与投资建议的板块数据注入 ❌ 待实施

**现状**: 三个路由（`llm_report` / `llm_report_stream` / `llm_advice_stream`）均未注入热点板块数据。`analysis.py` 中无 `_inject_market_context()` 公共函数。但 `build_full_context()` 已完成统一数据管道框架，注入只需在现有管道中加入 `hot_plates` 和 `sector_heat` 数据源。

**目标**: 确保 `generate_market_report()`（综合研判）和 `generate_advice()`（投资建议）及其流式变体都有板块数据

**涉及文件**: `backend/app/routers/analysis.py`

#### 5a. `llm_report` 路由（analysis.py:96-171）

**当前状态**: 该路由已标记 `# TODO: 未接入前端`（前端使用流式版本 `/llm-report/stream`），但仍保留作为非流式回退。其 `asyncio.gather` 采集的是 `get_all_realtime()` / `get_indices()` / `get_commodities()` / 新闻，**不含任何板块数据**。

**修复**: 在 `asyncio.gather` 之后增加板块动量获取：

```python
# 在现有的 asyncio.gather 之后增加
from ..services.pool_manager import pool_manager

sector_momentum = pool_manager.get_sector_momentum() or []
if not sector_momentum:
    # 缓存为空时降级直接采集
    from ..fetchers.sector_fetcher import fetch_industry_sectors, fetch_concept_sectors
    ind = await asyncio.to_thread(fetch_industry_sectors, 15) or []
    con = await asyncio.to_thread(fetch_concept_sectors, 15) or []
    sector_momentum = [...]  # 格式化为统一结构
```

#### 5b. `/llm-advice/stream` 路由（analysis.py:405-417）

**当前问题**: 流式版本直接使用 `agent.run_stream(prompt)`，绕过了 `generate_advice()` 的板块注入逻辑，完全不经过 pool_manager。

**修复**: 将非流式路由的智能注入逻辑（analysis.py:186-208）抽取为独立函数 `_inject_market_context(query, ctx)`，流式和非流式路由共同调用：

```python
# 抽取的公共函数
def _inject_market_context(query: str, ctx: dict) -> dict:
    """根据 query 关键词智能注入市场数据到 context。"""
    from ..services.pool_manager import pool_manager
    q = query.lower()
    injection_lines = []

    if any(kw in q for kw in ["大盘", "今天", "最新"]):
        ...  # 注入行情/市态

    if any(kw in q for kw in ["板块", "行业", "概念", "半导体", ...]):
        sector = pool_manager.get_sector_momentum() or []
        for item in sector[:5]:
            injection_lines.append(
                f"· {item.get('name','?')}: 涨跌幅 {item.get('change_pct',0):+.2f}%"
            )

    if injection_lines:
        ctx["market_snapshot"] = "\n".join(injection_lines)
    return ctx

# 流式路由中调用
@router.post("/llm-advice/stream")
async def llm_advice_stream(query, context=None):
    ctx = _inject_market_context(query, dict(context or {}))
    prompt = f"用户提问: {query}\n\n上下文: {json.dumps(ctx)}\n\n..."
    return _sse_stream(get_agent("advice").run_stream(prompt))
```

#### 5c. `/llm-report/stream` 路由（analysis.py:314-398）

**当前问题**: 流式研判报告同样只采集个股/指数/商品/新闻数据，**不含板块数据**。`generate_market_report()` → `_build_report_prompt()` → `_build_market_overview()` 完整调用链中没有任何板块/概念数据的入口。

**修复**: 与 5a 相同，在 `asyncio.gather` 之后增加板块动量获取，数据通过 `enriched_news` 或新增 `context` 参数传入：

```python
# 在 line 344（all_news 构建）之后增加
sector_momentum = pool_manager.get_sector_momentum() or []
if sector_momentum:
    sector_lines = []
    for item in sector_momentum[:10]:
        name = item.get("sector", item.get("sector_name", "?"))
        chg = item.get("change_pct", "")
        typ = item.get("type", "industry")
        sector_lines.append(f"【{typ}】{name}: {chg}%")
    enriched_news.append({
        "title": "【板块动量】" + " | ".join(sector_lines[:5])
    })
```

这样 `_build_market_overview()` 的「财经资讯」段落会自然包含热点板块摘要。

#### 5d. `_build_report_prompt()` / `_build_market_overview()`（llm.py:370-416, 621-660）

**当前问题**: `_build_market_overview()` 只格式化了指数、商品、主要标的和新闻，没有板块数据段落。`_build_report_prompt()` 要求 LLM 输出"强势板块/弱势板块及幅度"（第 650 行），但输入数据中无板块信息，LLM 只能编造或跳过。

**修复**（在 5c 注入 `enriched_news` 的基础上可选增强）:
- 在 `_build_market_overview()` 尾部增加板块段落（需增加 `sector_data` 参数）
- 或在 `_build_report_prompt()` 中增加 `sector_data` 输入

由于改动涉及函数签名变更，此修复优先级低于 5a-5c 的 news 注入方式，标记为 **P2-增强**。

---

### Phase 6 — 前端可视化 ❌ 待实施

**现状**: `frontend/src` 中无 sector 相关组件或页面。`market.py` 中 `/hot-plates`、`/sectors/heat`、`/stock-hot-rank`、`/sectors/industry-cls` 等 6 个路由均标记 `# TODO: 未接入前端`。需要前端 `api/index.js` 新增 API 方法并创建 SectorHeat 组件。

**目标**: MarketAnalysis 页面增加热点板块可视化

**涉及文件**:
- `frontend/src/components/market/SectorHeatMap.vue`（新建）
- `frontend/src/views/MarketAnalysis.vue`
- `frontend/src/api/index.js`

#### 6a. 新建 `SectorHeatMap.vue` 组件

功能需求：
- 两个 Tab：「行业排行」「概念排行」
- 每个 Tab 显示前 20 名涨跌幅排行
- 每行显示：排名、板块名称、涨跌幅（红涨绿跌）、主力净流入、涨跌家数
- 点击板块名称跳转到 `SectorAnalysis` 的对应板块详情

```vue
<template>
  <section class="section-card">
    <div class="section-header">
      <h2>板块热力排行</h2>
      <div class="tabs">
        <button :class="{ active: tab === 'industry' }" @click="tab='industry'">行业</button>
        <button :class="{ active: tab === 'concept' }" @click="tab='concept'">概念</button>
      </div>
    </div>
    <div class="heat-table">
      <div v-for="(s, i) in displaySectors" :key="s.sector_code || i" class="heat-row">
        <span class="rank">{{ i + 1 }}</span>
        <span class="name" @click="selectSector(s)">{{ s.sector_name }}</span>
        <span class="change" :class="s.change_pct >= 0 ? 'text-up' : 'text-down'">
          {{ _fmt(s.change_pct) }}
        </span>
        <span class="flow" :class="s.main_inflow >= 0 ? 'text-up' : 'text-down'">
          {{ s.main_inflow }}
        </span>
      </div>
    </div>
  </section>
</template>
```

#### 6b. 解除 `# TODO: 未接入前端` 路由

需要在前端接入的 API 路由：

| 路由 | 函数 | 对接组件 |
|------|------|----------|
| `GET /api/v1/market/sectors/industry` | `fetch_industry_sectors` | 已使用（SectorAnalysis 搜索框），但代码中 `# TODO: 未接入前端` 注释需一并清除 |
| `GET /api/v1/market/sectors/concept` | `fetch_concept_sectors` | 已使用，同上需清除 TODO 注释 |
| `GET /api/v1/market/hot-plates` | `fetch_hot_plates` | SectorHeatMap |
| `GET /api/v1/market/sectors/heat` | `fetch_sector_heat` | SectorHeatMap |
| `GET /api/v1/market/sectors/industry-cls` | `fetch_sector_industry_cls` | SectorHeatMap（备用） |
| `GET /api/v1/market/stock-hot-rank` | `fetch_stock_hot_rank` | 可单独展示热门个股 |
| `GET /api/v1/market/wind` | `fetch_market_wind` | 热点主线板块 |

---

### 5e. 部署前置条件

P3 的实时行情返回依赖本地 `sectors` 表注入，实施前需确保已运行：

```bash
cd backend && python -m scripts.sync_sectors
```

该脚本写入 SQLite `sectors` 表（含 `code` / `name` / `type`），供 `get_sectors_local()` 降级使用。若在 Docker 环境部署，需在首次启动时手动执行一次（或添加到 startup 脚本）。

---

## 4. 涉及文件清单

| 文件 | 改动类型 | Phase |
|------|----------|-------|
| `backend/app/services/market_trends.py` | 修改：`compute_sector_momentum()` 增强为行业+概念 | P1 |
| `backend/app/services/pool_manager.py` | 新增：`update_sector_cache()` 方法 + 3 个新缓存字段 | P2 |
| `backend/app/tasks/sector_refresh.py` | 新建：定时刷新板块缓存 | P2 |
| `backend/app/main.py` | 修改：注册 sector_refresh 定时任务 | P2 |
| `backend/app/routers/market.py` | 修改：取消 get_sectors_local 优先，返回实时数据 | P3 |
| `backend/app/analysis/llm.py` | 修改：`generate_advice()` 修复 + `_build_design_report_prompt()` 增强 | P4 |
| `backend/app/routers/analysis.py` | 修改：3 个路由注入板块数据（`llm_report`、`llm_report_stream`、`llm_advice_stream`），抽取 `_inject_market_context()` 公共函数 | P5 |
| `backend/scripts/sync_sectors.py` | 前置条件：实施前运行该脚本填充本地 sectors 表 | P0(部署) |
| `api-contracts/market/sectors-industry.md` | 新建：行业板块 API 契约 | P3 |
| `api-contracts/market/sectors-concept.md` | 新建：概念板块 API 契约 | P3 |
| `api-contracts/market/hot-plates.md` | 新建：热点板块 API 契约 | P6 |
| `frontend/src/components/market/SectorHeatMap.vue` | 新建：热点板块可视化组件 | P6 |
| `frontend/src/views/MarketAnalysis.vue` | 修改：嵌入 SectorHeatMap | P6 |
| `frontend/src/api/index.js` | 修改：新增 hot-plates / heat 等 API 方法 | P6 |
| `frontend/src/composables/useSectorAnalysis.js` | 修改：搜索结果展示涨跌幅 | P3,P6 |

---

## 5. 工作量估算

| Phase | 内容 | 文件数 | 预估时间 |
|-------|------|--------|----------|
| P1 | 数据采集增强 | 1 | 1.5h |
| P2 | 缓存写入 + 定时刷新 | 3 | 2h |
| P3 | API 返回实时行情 | 2 | 1h |
| P4 | LLM Prompt 注入（`generate_advice()` + `_build_design_report_prompt()`） | 1 | 2h |
| P5 | 3 个路由（`llm_report`、`llm_report_stream`、`llm_advice_stream`）注入 + 公共函数抽取 + `_build_report_prompt()` 可选增强 | 1 | 2h |
| P6 | 前端可视化（SectorHeatMap 组件 + API 接入 + 样式） | 4 | 4h |
| **合计** | | **16**（含 3 个契约文件 + 1 个部署前置） | **~12h** |

---

## 6. 验证方案

### 6.1 API 契约检查

P3 和 P6 涉及新增/修改 API，实施前先创建或更新契约文件：

- `api-contracts/market/sectors-industry.md` — 含实时行情字段
- `api-contracts/market/sectors-concept.md` — 同上
- `api-contracts/market/hot-plates.md` — 热点板块
- 每个文件从 `api-contracts/contract_template.md` 复制模板，填写路由、请求/响应结构
- 实现后逐字段核对响应是否符合契约

### 6.2 后端单测

后端单测集中在 `backend/tests/test_sector_data.py`（新建），mock 外部数据源：

| 测试名 | 测试内容 | 对应 Phase |
|--------|----------|-----------|
| `test_sector_momentum_includes_concepts()` | `compute_sector_momentum()` 返回行业+概念各至少 3 条，有 `type` 字段 | P1 |
| `test_sector_cache_write_read()` | `pool_manager.update_sector_cache()` 后 `get_sector_momentum()` 非空，含 `hot_plates` / `sector_heat` | P2 |
| `test_sector_api_returns_realtime()` | `GET /api/v1/market/sectors/industry` 返回条目含 `change_pct` / `main_inflow` | P3 |
| `test_concept_api_returns_realtime()` | `GET /api/v1/market/sectors/concept` 同上 | P3 |
| `test_hot_plates_api()` | `GET /api/v1/market/hot-plates` 返回 200 且为 list | P6 |
| `test_sector_heat_api()` | `GET /api/v1/market/sectors/heat` 返回 200 且为 list | P6 |
| `test_llm_report_has_sector_data()` | mock `pool_manager.get_sector_momentum()` 返回模拟数据后，`generate_market_report()` 输出包含板块名称 | P5 |
| `test_advice_has_sector_data()` | mock `pool_manager.get_sector_momentum()` 后，`generate_advice()` 的 prompt 包含板块数据 | P4 |

### 6.3 E2E 验证（`verify_e2e.py` 新增检查项）

在 `verify_e2e.py` 的 `check_all()` 函数内新增 `check_sector_data()` 调用：

```python
# verify_e2e.py 新增函数
def check_sector_data():
    """板块/概念数据不为空且有实时字段"""
    checks = 0
    for typ in ("industry", "concept"):
        resp = client.get(f"/api/v1/market/sectors/{typ}?limit=5")
        assert resp.status_code == 200, f"GET /sectors/{typ} failed: {resp.status_code}"
        data = resp.json()
        assert len(data) > 0, f"{typ} sector list is empty"
        assert "change_pct" in data[0], f"{typ} sector missing change_pct"
        assert "main_inflow" in data[0], f"{typ} sector missing main_inflow"
        checks += 1
    
    # 热板块检查（P6 完成后生效，之前可能 404）
    resp = client.get("/api/v1/market/hot-plates?limit=5")
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, list), "hot-plates should be a list"
        checks += 1
    
    return f"[PASS] check_sector_data ({checks} checks)"
```

### 6.4 LLM 报告质量验证

| 检查项 | 方法 | 通过标准 |
|--------|------|----------|
| Prompt 含板块数据 | 日志分析：`generate_advice()` 的 prompt 应包含板块名称 | 日志中无 "暂无板块热力数据" |
| 组合设计报告含板块 | 触发 WebSocket 设计报告，提取 `report_text` | 包含至少一个板块名称和涨跌幅数值 |
| 不出现默认值 | 检查最终输出在 LLM 渲染后 | 不包含 "暂无板块热力数据"、"暂无数据" |
| 概念板块区分 | 报告中有 "概念" 标签或与行业板块分开列示 | 文本匹配含 "概念" 或 "概念板块" |

---

## 7. 风险与注意事项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| akshare/levistock 接口超时 | 板块数据为空 | 现有 `_try_two` 降级链可用；缓存 miss 时返回上次成功值；P2 的 60s 定时刷新降低 miss 概率 |
| 概念板块数据量过大（>600 个） | 响应变慢 | `top_n=15` 截断，LLM 不需要全量数据 |
| APScheduler 任务泄漏 | 重复执行 | `max_instances=1, coalesce=True` 已可防泄漏 |
| 前端 SectorHeatMap 首次加载慢 | 首屏白屏 | 组件级懒加载 + 骨架屏 |
| 报告生成速度 | 240s 超时未变 | 板块数据只是文本拼接，不增加 LLM 调用耗时 |
| 非交易日板块数据无效 | 显示过时数据 | 结合 `market_calendar.is_trading_time()` 判断是否刷新；非交易日跳过 sector_cache 刷新 |
| **P3 响应格式变更破坏前端兼容性** | 前端 `useSectorAnalysis.js` 原预期 `{sector_code, sector_name}`，改为全量实时字段后旧前端可能报错 | P3 实施时同步更新前端；或路由保留向后兼容参数（如 `?realtime=false` 返回旧格式） |
| **`fetch_hot_plates()` / `fetch_sector_heat()` 仅 levistock 支持** | 无 akshare 降级，levistock 不可用时数据全空 | 增加超时保护（目前已在 `_cached` 中），缓存有效期内使用上次成功数据；监控 levistock 健康状态 |
| **`update_sector_cache()` 耗时过长** | 阻塞其他 APScheduler 任务 | 设置超时（`asyncio.wait_for(..., timeout=15)`），超时则本次跳过 |
| **`compute_concept_momentum()` 与现有 `fetch_concept_sectors()` 重复采集** | 在定时刷新和 API 两端都采集概念板块数据，浪费 | 统一使用 pool_manager 缓存，P2 完成后 API 和 LLM 都从缓存读取，消除重复采集 |

---

## 8. 实施顺序建议

```
Week 1                    Week 2
┌──────┬──────┬──────┬──────┬──────┬──────┐
│  P1  │  P2  │  P3  │  P4  │  P5  │  P6  │
│ 采集  │ 缓存  │ API  │Prompt│ 报告  │ 前端  │
└──────┴──────┴──────┴──────┴──────┴──────┘
   ↓      ↓      ↓      ↓      ↓      ↓
  测试   测试   测试  verify   verify  UI走查
```

- 建议 **P1~P4** 连续实施，每步跑单测确认
- P5 依赖 P4 但改动极小，可合并
- P6 前端可与后端并行开发
- 全部完成后运行 `verify_e2e.py` 确认全 PASS

---

## 附录

### A. pool_manager 新增缓存字段

```python
class PoolManager:
    def __init__(self):
        ...
        # 现有
        self._sector_momentum_cache: list[dict] | None = None
        self._sector_momentum_cache_ts: float = 0
        
        # 新增
        self._hot_plates_cache: list[dict] | None = None
        self._hot_plates_cache_ts: float = 0
        
        self._sector_heat_cache: list[dict] | None = None
        self._sector_heat_cache_ts: float = 0
```

### B. LLM Prompt 新增段落示例

```
## 二、热点板块

### 行业板块动量（申万一级）
- 银行: 第1/31名 当日+1.2%
- 非银金融: 第2/31名 当日+0.9%
...

### 概念板块动量
- CPO: +3.5%  主力净流入 12.3亿
- 光模块: +3.1%  主力净流入 8.7亿
...

### 今日热点板块（财联社）
- **半导体**: 政策利好叠加需求复苏
  领涨: 中芯国际, 北方华创
- **低空经济**: 各地政策密集出台
  领涨: 万丰奥威, 中信海直
```

### C. 前端 API 接入清单

```javascript
// frontend/src/api/index.js — 新增
marketApi: {
  ...existing,
  getHotPlates: (limit = 15) => fetchJson(`/api/v1/market/hot-plates?limit=${limit}`),
  getSectorHeat: (limit = 20) => fetchJson(`/api/v1/market/sectors/heat?limit=${limit}`),
  getStockHotRank: (limit = 50) => fetchJson(`/api/v1/market/stock-hot-rank?limit=${limit}`),
  getMarketWind: () => fetchJson('/api/v1/market/wind'),
}
```
