# Market Analysis Module Optimization Plan / 行情分析模块优化方案

> Status: **🔄 PARTIALLY COMPLETED (V5)** — 2026-07-26 audit update.
>
> | Phase | Claimed | Actual State |
> |-------|:------:|:------------:|
> | **Phase A** (Unified search) | ✅ Completed | ✅ Backend `search_unified()` implemented; need to verify frontend consumption |
> | **Phase B** (Unified analysis flow) | ✅ Completed | ✅ Backend routing exists; need to verify |
> | **Phase C** (Frontend merge) | ✅ Completed | ✅ `UnifiedAnalysis.vue` replaces 3 old components |
> | **Phase D** (AI advisor streaming) | 🟡 **Partially** | Streaming backend exists (`build_full_context()`, `_build_advice_stream_prompt()`), but **3 concrete gaps remain**: (1) `/llm-advice/stream` endpoint does NOT pass `market` from request to `build_full_context()` (always defaults to "A"), (2) Frontend `AiAdvisor.vue` has `marketTab` prop but sends `{ query: q }` — **no `market` field** in API call, (3) Always queries A-share data |
> | **Phase E** (Market report quality) | 🟡 **Partially** | `LLMReportRequest` has `market` field, `resolve_market_context()` exists, but **3 concrete gaps remain**: (1) `_build_report_prompt()` still uses **original 4 sections** (Sections 0 & 5 NOT added — verified at llm.py:636-659), (2) Still **pseudo-streaming** (generate full report → 100-char chunks, verified at analysis.py:377-386), (3) `llm_report_stream` sets `include_sectors=False` (analysis.py:329), so **all sector data is explicitly excluded** from streaming reports |
>
> **2026-07-26 审计结论**：Phase D 和 E 的**后端数据管道统一层**已实现（`build_full_context()`、`_build_advice_stream_prompt()`），但**市场感知联动的核心——market 参数的端到端传递和 LLM prompt 增强——仍未完成**。这 5 项缺口形成了 Phase 5.1（市场感知联动）的实施输入。
>
> **2026-07-27 第一次更新**：Phase 5.1（市场感知联动）已通过跨 Phase 全栈实施完成。`core/market_context.py` + `services/market_router.py` 已上线，各端点已增加 market 参数感知。
>
> **2026-07-27 第二次更新（代码审计校准）**：经实际代码验证，5 项缺口仍有 **4 项未闭合**：
> - Phase D (1) `/llm-advice/stream` 的 market 参数 → ❌ `analysis.py:324` 未传 `market=`，默认 "A"
> - Phase D (2) 前端 AiAdvisor marketTab → ❌ `AiAdvisor.vue:53` 发送 `{ query: q }`，无 market
> - Phase D (3) 始终查 A 股 → ❌ `build_full_context()` 无 market 参数，默认 "A"
> - Phase E (1) 报告只 4 节 → ❌ `llm.py:636-659` 仍是 4 节，缺 Section 0/5
> - Phase E (2) 伪流式 → ❌ `analysis.py:377-386` 首先生成完整 report 再切块
> - Phase E (3) 板块数据排除 → 🟡 market_router 已解决数据路由，但 `include_sectors=False` 导致丢失
>
> See `docs/implementation-master-plan.md` Phase 5.1 for details.

---

## TOC / 目录

1. [Context & Problem Summary / 背景与问题汇总](#1-context--problem-summary)
2. [Scope Overview / 范围总览](#2-scope-overview)
3. [Phase A — Unified Search Backend / 统一搜索后端](#3-phase-a--unified-search-backend)
4. [Phase B — Unified Analysis Flow / 统一分析编排](#4-phase-b--unified-analysis-flow)
5. [Phase C — Unified Analysis Frontend Component / 前端合并组件](#5-phase-c--unified-analysis-frontend-component)
6. [Phase D — AI Advisor Streaming & Data Pipeline / AI顾问流式+数据管道修复](#6-phase-d--ai-advisor-streaming--data-pipeline)
7. [Phase E — Market Report Quality Enhancement / 市场研判质量增强](#7-phase-e--market-report-quality-enhancement)
8. [API Contracts / API 契约](#8-api-contracts)
9. [Endpoint Deprecation Plan / 端点废弃计划](#9-endpoint-deprecation-plan)
10. [Implementation Order & Dependencies / 实施顺序与依赖](#10-implementation-order--dependencies)
11. [Risks & Mitigations / 风险与应对](#11-risks--mitigations)
12. [Verification Plan / 验证方案](#12-verification-plan)

---

## 1. Context & Problem Summary

### Current State

The `MarketAnalysis.vue` page (`frontend/src/views/MarketAnalysis.vue`) renders 6 section cards, with a top-bar `marketTab` switcher (A / HK / US / global) that is wired to child components but **not used for data filtering**:

| # | Component | Input? | Calls Backend? | Status |
|---|-----------|--------|---------------|--------|
| 1 | `MarketReport` | Button only | ✅ (both SSE & non-streaming) | Working but no market awareness |
| 2 | `WatchlistPanel` | Text + search | ⚠️ partial (search only covers ETFs) | Working but broken search |
| 3 | `AiAdvisor` | Text input | ✅ (non-streaming) | Returns empty template |
| 4 | `SectorAnalysis` | Text input | ❌ (`// TODO: integrate with real API`) | Broken — only shows "分析板块: {q}" |
| 5 | `SymbolAnalysis` | Text input | ❌ (`// TODO: chart + indicator fetch`) | Broken — only shows "已选择: {symbol}" |
| 6 | `IndexAnalysis` | Text input | ❌ (`// TODO: integrate with real API`) | Broken — only shows "分析指数: {q}" |

### 6 Identified Problems

| Problem | Root Cause | Impact |
|---------|-----------|--------|
| **P1** Market report lacks actionable advice | Prompt explicitly forbids portfolio allocation suggestions | Users get diagnosis without prescription |
| **P2** Watchlist search doesn't autocomplete stocks | `search_etf()` only queries ETFs, not stocks | Typing "贵州茅台" returns empty |
| **P3** AI advisor returns empty template | context data fields are empty — `generate_advice()` reads `context.market_data` etc but frontend only passes `include_market_data: true` flag | LLM receives insufficient data, outputs skeleton |
| **P4** Sector analysis shows placeholder text | `SectorAnalysis.vue` has `// TODO: integrate with real API` | No real analysis |
| **P5** Symbol analysis shows placeholder text | `SymbolAnalysis.vue` has `// TODO: chart + indicator fetch` | No real analysis |
| **P6** Index analysis shows placeholder text | `IndexAnalysis.vue` has `// TODO: integrate with real API` | No real analysis |

### Key Root Cause Chain: Broken Search (P2)

```
WatchlistPanel.doSearch()
  → marketApi.search(kw) → GET /api/v1/market/search
    → search_etf(keyword)  ← ONLY looks up akshare fund_etf_spot_em (ETF only)
      → ❌ "贵州茅台" returns empty array
```

A fully-functional stock search endpoint exists at `GET /api/v1/market/search/stocks` (pinyin/first-letter/symbol/name fuzzy matching via `instruments` table) but is marked `# TODO: 未接入前端`.

### Key Root Cause Chain: AI Advisor Empty Template (P3)

```
AiAdvisor.send()
  → analysisApi.llmAdvice(query, { include_market_data: true, ... })
    → POST /api/v1/analysis/llm-advice?query=xxx
      → llm_advice() does smart injection → only populates ctx["market_snapshot"]
        → generate_advice(query, ctx)
          → context.get("market_data", [])       ← empty (frontend sent flag, not data)
          → context.get("news", [])               ← empty
          → context.get("portfolio", [])           ← empty
          → context.get("market_snapshot", "")     ← only field populated
          → context.get("market_regime", "")       ← not set
          → context.get("market_sentiment", {})    ← not set
          → PROMPT: "暂无实时指数数据" / "暂无板块热力数据" / "暂无重大新闻"
            → LLM outputs empty shell template
```

### Unused Backend Streaming Endpoints (P4, P5, P6)

Backend has fully functional streaming endpoints that the frontend never calls:

| Backend Endpoint | Frontend Consumes? | Status |
|-----------------|-------------------|--------|
| `POST /api/v1/analysis/sector-analysis/stream` | ❌ | Ready but unused |
| `POST /api/v1/analysis/symbol-analysis/stream` | ❌ | Ready but unused |

---

## 2. Scope Overview

### What We Are Doing

| Item | Action | Backend Changes | Frontend Changes |
|------|--------|----------------|-----------------|
| **A** Unified search backend | Replace `GET /market/search` with multi-source search; incorporate `/search/stocks`; add `market` filter param | 2 files (market router + service) | 0 (same API URL) |
| **B** Unified analysis flow | New `POST /analysis/unified-analysis/stream` routing endpoint | 1 file (analysis router) | 0 (consumed by C) |
| **C** Merge 3 component cards | Create `UnifiedAnalysis.vue`, delete 3 old ones, replace 3 refs in parent | 0 | 3 deleted, 1 created, 1 edited |
| **D** AI advisor streaming | Frontend switch to SSE; backend enhance `/llm-advice/stream` with pool_manager injection; deprecate non-streaming | 1 file (analysis router) | 1 file (AiAdvisor.vue) |
| **E** Market report quality + market awareness | Add action advice to prompt; inject market-aware data; switch to true streaming | 2 files (router + llm.py) | 0 |

### Key Design Decision: Market-Aware Data Flow

```
MarketAnalysis.vue: marketTab (A|HK|US|global)
  ├──→ MarketReport: collects indices/market_data matching marketTab
  ├──→ WatchlistPanel: search filters by marketTab
  ├──→ AiAdvisor: injects marketTab-specific data into prompt
  └──→ UnifiedAnalysis:
        ├── Search: filters by marketTab
        ├── Quick examples: market-aware
        └── Analysis: passes market/asset_type to backend
```

### What We Are NOT Doing

- Not merging `MarketReport` or `AiAdvisor` or `WatchlistPanel` — they have different interaction patterns
- Not rewriting the strategy engine, factor model, or factor registry
- Not changing the portfolio design flow (`POST /portfolio/design-async`)
- Not adding new UI features beyond the merge (no new charts, no new card types)
- Not implementing HK stock name search from remote APIs — limited to local instruments table
- Not implementing real-time US stock name search — limited to a curated static list + common ETFs
- Not generating dedicated sector analysis for HK/US markets (A-share only)

---

## 3. Phase A — Unified Search Backend

### 3.1 Goal

Replace the existing `GET /api/v1/market/search` (ETF-only) with a multi-source unified search that covers stocks, ETFs, sectors, and indices across all 4 markets (A/HK/US/global). The old `/search/stocks` endpoint is folded in.

The frontend API call `marketApi.search(kw)` → `GET /market/search?keyword=...` stays the same URL — only backend behavior changes.

### 3.2 Current State

**Route** (`market.py:71`):
```python
@router.get("/search")
async def search(keyword: str = Query("")) -> list[dict[str, Any]]:
    return await search_etf(keyword)  # ETF only
```

**Backend** (`market_service.py:392`): `search_etf()` queries `instruments` table first, falls back to akshare ETF cache. Both are ETF/stock oriented but the fallback cache is ETF-only.

**Sibling endpoints:**
- `/search/stocks` (`market.py:77`) — A-share stock search via `instruments` table, marked `# TODO: 未接入前端`
- `search_indices()` (`market_service.py:466`) — index search via `IndexMeta` table, not exposed

### 3.3 New Implementation

#### Route (replace existing `/search`)

```python
@router.get("/search")
async def search(
    keyword: str = Query(""),
    market: str = Query("A"),      # A | HK | US | global
    limit: int = Query(10),
    include_sectors: bool = Query(False),  # sectors only for A market
) -> list[dict[str, Any]]:
    """Multi-source unified search. Replaces old ETF-only search."""
    results = await search_unified(keyword, market, limit, include_sectors)
    return results
```

#### Unified Search Function

```python
async def search_unified(
    keyword: str,
    market: str = "A",
    limit: int = 10,
    include_sectors: bool = False,
) -> list[dict[str, Any]]:
    """Parallel search across 3-4 data sources, filtered by market."""
    
    tasks = []
    
    # 1. instruments table (stocks + ETFs)
    tasks.append(_search_instruments(keyword, market))
    
    # 2. IndexMeta table (indices)
    tasks.append(_search_indices(keyword, market))
    
    # 3. Sectors (industry + concept, A market only)
    if include_sectors and market in ("A", "global"):
        tasks.append(_search_sectors(keyword))
    
    # 4. US curated list (US market only, no remote API)
    if market in ("US", "global"):
        tasks.append(_search_us_curated(keyword))
    
    # Gather with 2s timeout — any source that times out is silently dropped
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Merge & dedup (prefer stock > etf > sector > index on same symbol)
    seen = set()
    merged = []
    for result in results:
        if isinstance(result, list):
            for item in result:
                dedup_key = f"{item['type']}:{item['symbol']}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    merged.append(item)
    
    return merged[:limit]
```

#### Market Filtering Rules

| `market` param | instruments filter | indices filter | sectors | US list |
|---------------|-------------------|----------------|---------|---------|
| `"A"` | `market == "A"` | `market == "CN"` | ✅ | ❌ |
| `"HK"` | `market == "HK"` | `market == "HK"` | ❌ | ❌ |
| `"US"` | `market == "US"` | `market == "US"` | ❌ | ✅ |
| `"global"` | no filter | no filter | ✅ | ✅ |

**Note**: HK stock search capability depends on the `instruments` table being populated with HK stocks. If the table is sparse or empty, HK search will return limited results. This is a known data-population limitation, not a code bug.

**Note**: `WatchlistPanel` calls `marketApi.search(kw)` without a `market` filter — it gets results from all markets and filters by `marketTab` client-side. This is intentional and unchanged by Phase A.

#### US Curated List (Static)

Since there's no reliable low-latency US stock search API from China, maintain a static JSON array of ~80-100 common US symbols at `backend/data/us_symbols.json`:

```json
[
  {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "type": "etf", "market": "US"},
  {"symbol": "QQQ", "name": "Invesco QQQ Trust", "type": "etf", "market": "US"},
  {"symbol": "AAPL", "name": "Apple Inc.", "type": "stock", "market": "US"},
  {"symbol": "MSFT", "name": "Microsoft Corp.", "type": "stock", "market": "US"},
  {"symbol": "TSLA", "name": "Tesla Inc.", "type": "stock", "market": "US"},
  {"symbol": "AMZN", "name": "Amazon.com Inc.", "type": "stock", "market": "US"},
  ...
]
```

Search is simple string match on `symbol` or `name`. This file is a one-time creation and can be extended as needed.

#### Return Format

Each result item has a `type` field for the frontend to render type-specific UI:

```json
[
  {"symbol": "600519", "name": "贵州茅台", "type": "stock", "market": "A"},
  {"symbol": "00700",  "name": "腾讯控股",  "type": "stock", "market": "HK"},
  {"symbol": "SPY",    "name": "SPDR S&P 500 ETF", "type": "etf", "market": "US"},
  {"symbol": "BK0477", "name": "半导体",     "type": "sector", "market": "A", "sector_type": "industry"},
  {"symbol": "000300", "name": "沪深300",    "type": "index",  "market": "CN"},
  {"symbol": "HSI",    "name": "恒生指数",   "type": "index",  "market": "HK"},
]
```

Supported `type` values: `"stock"`, `"etf"`, `"sector"`, `"index"`.

For `type="sector"`, a `sector_type` field indicates `"industry"` or `"concept"`.

### 3.4 Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/market.py` | Replace `search()` implementation; keep `/search/stocks` as internal; ~20 lines changed |
| `backend/app/services/market_service.py` | Add `search_unified()`, `_search_instruments()`, `_search_sectors()`, `_search_us_curated()`; adjust `search_etf()` signature; ~80 lines added |
| `backend/data/us_symbols.json` | NEW — curated US symbol list; ~80 lines |
| `frontend/src/api/index.js` | No change — `marketApi.search(kw)` still maps to `GET /market/search` |

---

## 4. Phase B — Unified Analysis Flow

### 4.1 Goal

One streaming endpoint that accepts any keyword/type and internally routes to the correct analysis handler. The frontend never needs to know which specific backend endpoint to call.

### 4.2 New Request Model

```python
class UnifiedAnalysisRequest(BaseModel):
    keyword: str                     # original user input
    symbol: str = ""                 # resolved symbol (from search or auto-detect)
    name: str = ""                   # resolved display name
    type: str = "auto"               # "symbol" | "sector" | "index" | "auto"
    asset_type: str = "A"            # A | HK | US (for symbol type)
    sector_type: str = "industry"    # industry | concept (for sector type)
    market: str = "A"                # A | HK | US | global (for market context)
```

### 4.3 Auto-Detect Logic

When `type="auto"`, the backend infers the type from the input string:

```python
INDEX_SYMBOL_SET = {
    "000001", "399001", "399006", "000300", "000688", "000016",
    "HSI", "HSTECH", "HSCEI", "SPX", "IXIC", "DJI", "NDX",
}

def _auto_detect(keyword: str) -> dict:
    kw = keyword.strip()
    
    # Sector code: BK + 4 digits
    if re.match(r'^BK\d{4}$', kw, re.I):
        return {"type": "sector", "symbol": kw.upper(), "sector_type": "industry", "market": "A"}
    
    # Known index symbols (case-insensitive for letters)
    if kw.upper() in INDEX_SYMBOL_SET or re.match(r'^(000|399)\d{3}$', kw):
        return {"type": "index", "symbol": kw}
    
    # 6-digit → A-share stock or ETF
    if re.match(r'^\d{6}$', kw):
        return {"type": "symbol", "symbol": kw, "asset_type": "A", "market": "A"}
    
    # 5-digit → HK stock
    if re.match(r'^\d{5}$', kw):
        return {"type": "symbol", "symbol": kw, "asset_type": "HK", "market": "HK"}
    
    # Letter code (e.g. SPY, AAPL, 00700) → symbol
    if re.match(r'^[A-Za-z]{2,}$', kw):
        return {"type": "symbol", "symbol": kw.upper(), "asset_type": "US" if kw.isascii() else "HK", "market": "US"}
    
    # Fallback: defer to search (the frontend should have resolved via autocomplete)
    return {"type": "symbol", "symbol": kw, "asset_type": "A", "market": "A"}
```

### 4.4 Internal Routing Logic

```python
@router.post("/unified-analysis/stream")
async def unified_analysis_stream(req: UnifiedAnalysisRequest):
    """Unified streaming analysis: routes to correct internal handler by type."""
    
    # Auto-detect if type not explicitly provided
    if req.type == "auto" or not req.type:
        detected = _auto_detect(req.keyword)
        req.type = detected["type"]
        req.symbol = detected.get("symbol") or req.symbol
        req.sector_type = detected.get("sector_type") or req.sector_type
        # If auto-detect can't determine market (fell to default "A"),
        # use the explicit frontend market context (e.g. HK tab)
        detected_market = detected.get("market", "A")
        if detected_market == "A" and req.market not in ("A", ""):
            req.asset_type = req.market
            req.market = req.market
        else:
            req.asset_type = detected.get("asset_type") or req.asset_type
            req.market = detected_market or req.market
    
    # Route to existing endpoints
    if req.type == "sector":
        # Sector analysis is A-share only
        if req.market not in ("A", "global"):
            raise HTTPException(400, "板块概念分析仅支持A股市场")
        sector_req = SectorAnalysisRequest(
            sector_code=req.symbol,
            sector_type=req.sector_type,
            sector_name=req.name,
        )
        return await sector_analysis_stream(sector_req)
    
    elif req.type == "index":
        # Reuse symbol endpoint with asset_type="index"
        sym_req = SymbolAnalysisRequest(
            symbol=req.symbol,
            name=req.name,
            asset_type="index",
        )
        return await symbol_analysis_stream(sym_req)
    
    elif req.type == "symbol":
        sym_req = SymbolAnalysisRequest(
            symbol=req.symbol,
            name=req.name,
            asset_type=req.asset_type,
        )
        return await symbol_analysis_stream(sym_req)
    
    else:
        raise HTTPException(400, f"不支持的标类型: {req.type}")
```

### 4.5 Market Awareness in Underlying Endpoints

The `symbol_analysis_stream` endpoint already accepts `asset_type` (A/HK/US). The unified endpoint ensures this is properly set based on the detected market:

- `asset_type="A"` → A-stock data pipeline (Sina/akshare)
- `asset_type="HK"` → HK stock data pipeline (Sina/Tencent)
- `asset_type="US"` → US stock pipeline (TwelveData/Finnhub)
- `asset_type="index"` → index data pipeline

### 4.6 What This Preserves

- `sector_analysis_stream` endpoint — unchanged, still callable directly
- `symbol_analysis_stream` endpoint — unchanged, still callable directly
- All existing prompts — unchanged
- All existing LLM functions — unchanged

### 4.7 Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/analysis.py` | Add `UnifiedAnalysisRequest` + `/unified-analysis/stream` route (~45 lines) |
| `frontend/src/api/index.js` (analysisApi) | Add `unifiedAnalysisStream()` method (+2 lines) |

---

## 5. Phase C — Unified Analysis Frontend Component

### 5.1 Goal

Replace 3 broken TODO components with 1 working `UnifiedAnalysis` component. Final layout becomes 4 cards instead of 6:

```
MarketAnalysis.vue (new layout)
├── 📊 市场综合研判      ← MarketReport (unchanged)
├── ⭐ 自选列表           ← WatchlistPanel (unchanged)
├── 💬 AI 投资顾问        ← AiAdvisor (streaming upgrade in Phase D)
└── 🔍 标的深度分析       ← UnifiedAnalysis 🆕 (replaces Sector/Symbol/Index)
```

### 5.2 Component Architecture

```
UnifiedAnalysis.vue
├── Section header (title + description)
├── Search + input row
│   ├── SearchInput.vue (reusable autocomplete component)
│   │   ├── Text input with debounced search
│   │   └── Dropdown: type badge + symbol + name
│   └── Analysis button
├── Selected target display
│   ├── Type badge + symbol + name
│   ├── Market label (A/HK/US)
│   └── Quick example chips (market-aware)
├── Loading state (loading bar animation)
├── Result area (v-html renderMarkdown)
└── Error display
```

### 5.3 Search Autocomplete: `SearchInput.vue`

Reusable component at `frontend/src/components/ui/SearchInput.vue`:

```vue
<template>
  <div class="search-wrap">
    <input v-model="text" @input="onInput" @keydown.down.prevent="down"
           @keydown.up.prevent="up" @keydown.enter.prevent="selectCurrent"
           :placeholder="placeholder" class="text-input" />
    <ul v-if="suggestions.length" class="search-dropdown">
      <li v-for="(s, i)" :class="{ active: i === idx }"
          @click="pick(s)" @mouseenter="idx = i">
        <span class="type-badge" :class="s.type">{{ typeLabel(s.type) }}</span>
        <span class="s-symbol">{{ s.symbol }}</span>
        <span class="s-name">{{ s.name }}</span>
      </li>
    </ul>
  </div>
</template>
```

**Props:** `placeholder`, `debounceMs` (default 250), `minChars` (default 1),
`market` (default 'A', filters search), `includeSectors` (default false)

**Emits:** `@select(item)` — emits the selected `{symbol, name, type, market, sector_type}` object

**Search call:** `marketApi.search(text, { market: props.market })` → `GET /api/v1/market/search?keyword=xxx&market=A`

### 5.4 Market-Aware Quick Examples

```vue
<div v-if="!selected" class="quick-chips">
  <span class="chip-label">{{ $t('try_analyzing') }}:</span>
  <button v-for="ex in visibleExamples" :key="ex.code"
          class="chip" @click="quickSelect(ex)">
    {{ ex.label }}
  </button>
</div>
```

Examples by market:

```javascript
const EXAMPLES = {
  A: [
    { code: '510050', label: '上证50ETF', type: 'symbol', assetType: 'A', market: 'A' },
    { code: '159915', label: '创业板ETF', type: 'symbol', assetType: 'A', market: 'A' },
    { code: 'BK0477', label: '半导体板块', type: 'sector', market: 'A' },
    { code: '000300', label: '沪深300', type: 'index', market: 'CN' },
  ],
  HK: [
    { code: '00700', label: '腾讯控股', type: 'symbol', assetType: 'HK', market: 'HK' },
    { code: '09988', label: '阿里巴巴', type: 'symbol', assetType: 'HK', market: 'HK' },
    { code: 'HSI', label: '恒生指数', type: 'index', market: 'HK' },
  ],
  US: [
    { code: 'SPY', label: '标普500ETF', type: 'symbol', assetType: 'US', market: 'US' },
    { code: 'QQQ', label: '纳斯达克ETF', type: 'symbol', assetType: 'US', market: 'US' },
    { code: 'AAPL', label: 'Apple', type: 'symbol', assetType: 'US', market: 'US' },
    { code: 'SPX', label: '标普500', type: 'index', market: 'US' },
  ],
  global: [
    { code: '000001', label: '上证指数', type: 'symbol', assetType: 'A', market: 'A' },
    { code: 'HSI', label: '恒生指数', type: 'index', market: 'HK' },
    { code: 'SPX', label: '标普500', type: 'index', market: 'US' },
    { code: 'IXIC', label: '纳斯达克', type: 'index', market: 'US' },
  ],
}

const visibleExamples = computed(() => EXAMPLES[props.marketTab] || EXAMPLES.A)
```

### 5.5 `selectedSymbol` Prop Support

When `selectedSymbol` prop is provided (from watchlist click → `onSelectSymbol`):

```javascript
watch(() => props.selectedSymbol, (val) => {
  if (val && val !== lastAnalyzed.value) {
    query.value = val
    search.value = val  // skip autocomplete
    nextTick(() => doAnalyze())
  }
})
```

### 5.6 Analysis Flow

```javascript
async function doAnalyze() {
  const q = query.value.trim()
  if (!q) return

  loading.value = true
  error.value = ''
  result.value = ''
  lastAnalyzed.value = q

  // Build payload from resolved state
  const sel = selectedItem.value
  const payload = sel
    ? {
        keyword: q,
        symbol: sel.symbol,
        name: sel.name,
        type: sel.type || 'auto',
        asset_type: sel.assetType || props.marketTab,
        sector_type: sel.sector_type || '',
        market: sel.market || props.marketTab,
      }
    : { keyword: q, type: 'auto', market: props.marketTab }

  try {
    await startStream('/unified-analysis/stream', payload, (token) => {
      result.value += token
    })
  } catch (e) {
    error.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    loading.value = false
  }
}
```

### 5.7 Layout Change in MarketAnalysis.vue

**Before (6 cards):**
```vue
<div ref="anchorSector" class="section-anchor"></div>
<SectorAnalysis :marketTab="marketTab" />

<div ref="anchorSymbol" class="section-anchor"></div>
<SymbolAnalysis :marketTab="marketTab" :selectedSymbol="selectedSymbol" />

<div ref="anchorIndex" class="section-anchor"></div>
<IndexAnalysis :marketTab="marketTab" />
```

**After (4 cards):**
```vue
<div ref="anchorSymbol" class="section-anchor"></div>
<UnifiedAnalysis :marketTab="marketTab" :selectedSymbol="selectedSymbol" />
```

### 5.8 Quick bar navigation update

The `quick-bar` in MarketAnalysis.vue needs to remove "板块", "个股/ETF", "指数" buttons and replace with one "标的分析" button:

```vue
<button class="qb-btn" @click="scrollTo('symbol')" title="标的深度分析">
  <span class="qb-icon">🔍</span>
  <span class="qb-label">标的分析</span>
</button>
```

Then remove the corresponding entries from `anchorMap` for `sector` and `index`.

### 5.9 Files Changed/Created

| File | Action | Reason |
|------|--------|--------|
| `frontend/src/components/market/UnifiedAnalysis.vue` | **NEW** ~200 lines | Main merged component |
| `frontend/src/components/ui/SearchInput.vue` | **NEW** ~100 lines | Reusable autocomplete |
| `frontend/src/views/MarketAnalysis.vue` | EDIT | Swap 3 refs for 1; update quick-bar |
| `frontend/src/components/market/SectorAnalysis.vue` | DELETE | Replaced |
| `frontend/src/components/market/SymbolAnalysis.vue` | DELETE | Replaced |
| `frontend/src/components/market/IndexAnalysis.vue` | DELETE | Replaced |

---

## 6. Phase D — AI Advisor Streaming & Data Pipeline

### 6.1 Problem Summary

Two problems in the current AI advisor:

1. **Non-streaming UX**: `AiAdvisor.vue` calls `POST /api/v1/analysis/llm-advice` and waits for the full response. No progressive rendering.
2. **Data pipeline broken**: `generate_advice()` expects structured context fields (`market_data`, `news`, `portfolio`, etc.) but the middle layer only populates `market_snapshot` as a text string.

### 6.2 Fix Strategy

**Approach: Frontend switches to streaming; Backend enhances the streaming endpoint with market-aware data injection; non-streaming endpoint deprecated.**

```
Before:
  AiAdvisor.vue → POST /analysis/llm-advice (non-streaming) → waits → full response
  
After:
  AiAdvisor.vue → POST /analysis/llm-advice/stream?query=xxx&market=A (SSE)
                  → backend injects pool_manager data into streaming prompt
                  → frontend renders tokens progressively
```

### 6.3 Backend Changes

#### 6.3.1 Enhance `/llm-advice/stream` (analysis.py:405)

The current streaming endpoint is minimal — it only appends `context` as JSON to a simple prompt:

```python
# Current (too simple):
prompt = f"用户提问: {query}\n\n"
if context:
    prompt += f"上下文信息: {json.dumps(context, ensure_ascii=False)}"
```

This needs to be enhanced with the same pool_manager data injection that the non-streaming endpoint does (but better):

```python
async def llm_advice_stream(
    query: str = Query(...),
    context: dict | None = None,
    market: str = Query("A"),  # NEW: market parameter
):
    """流式投资建议问答 — 自动注入市场数据。"""
    ctx = dict(context or {})
    
    # Auto-inject market data from pool_manager
    try:
        ctx["market_regime"] = pool_manager.get_market_regime() or ""
        ctx["market_sentiment"] = pool_manager.get_market_sentiment() or {}
        
        # Market-aware index data
        if market in ("A", "global"):
            idx_data = pool_manager.get_index_realtime() or []
            ctx.setdefault("market_data", []).extend(idx_data[:8])
        
        # News (market-agnostic)
        ctx["news"] = (pool_manager.get_news() or [])[:10]
        
        # Sector momentum (A-share only)
        if market in ("A", "global"):
            sector_data = pool_manager.get_sector_momentum() or []
            for s in sector_data[:5]:
                ctx.setdefault("market_data", []).append({
                    "name": s.get("name"),
                    "change_pct": s.get("change_pct"),
                    "asset_type": "sector",
                })
        
        # Try portfolio context
        try:
            from ..services.portfolio_service import get_all_holdings
            portfolio = await get_all_holdings()
            if portfolio:
                ctx["portfolio"] = portfolio[:10]
        except Exception:
            pass
    except Exception as e:
        logger.debug("[llm-advice-stream] data injection: %s", e)
    
    # Build prompt with structured data
    prompt = _build_advice_stream_prompt(query, ctx)
    
    agent = get_agent("advice")
    return _sse_stream(agent.run_stream(prompt))
```

#### 6.3.2 `_build_advice_stream_prompt()` (new helper in `llm.py`)

This constructs a rich prompt from the injected data, similar to `generate_advice()` but simpler:

```python
def _build_advice_stream_prompt(query: str, ctx: dict) -> str:
    lines = [f"用户提问: {query}", ""]
    
    regime = ctx.get("market_regime", "")
    if regime:
        lines.append(f"## 市场背景\n- 市场状态: {regime}")
    
    sentiment = ctx.get("market_sentiment", {})
    if sentiment:
        s_lbl = sentiment.get("sentiment_label", "")
        s_idx = sentiment.get("sentiment_index", "")
        if s_lbl and s_idx:
            lines.append(f"- 市场情绪: {s_lbl} ({s_idx}/100)")
    
    market_data = ctx.get("market_data", [])
    if market_data:
        lines.append("\n## 实时行情")
        for item in market_data[:8]:
            name = item.get("name", "?")
            price = item.get("price", "N/A")
            chg = item.get("change_pct", "")
            if chg != "":
                lines.append(f"- {name}: {price} ({chg:+.2f}%)")
    
    news = ctx.get("news", [])
    if news:
        lines.append("\n## 近期资讯")
        for n in news[:5]:
            lines.append(f"- {n.get('title', '')[:80]}")
    
    portfolio = ctx.get("portfolio", [])
    if portfolio:
        lines.append("\n## 持仓信息")
        for p in portfolio:
            w = p.get("target_weight", 0) or 0
            lines.append(f"- {p.get('name','?')}({p.get('symbol','?')}): {w*100:.1f}%")
    
    lines.append("""
请按以下框架回答：
1. 直接回答用户问题，引用具体数据
2. 给出判断依据
3. 如涉及操作，给出分析和建议（不构成投资指令）

使用 Markdown 格式，控制 500 字以内。
""")
    
    return "\n".join(lines)
```

### 6.4 Frontend Changes

Switch `AiAdvisor.vue` from `analysisApi.llmAdvice()` to `analysisApi.llmAdviceStream()`:

```vue
<script setup>
import { useLLMStream } from '../../composables/useLLMStream'
// No longer need: import { analysisApi } from '../../api'

const props = defineProps({ marketTab: { type: String, default: 'A' } })
const { start: startStream } = useLLMStream()

async function send() {
  const q = query.value.trim()
  if (!q || loading.value) return
  loading.value = true
  response.value = ''
  error.value = ''
  try {
    await startStream('/llm-advice/stream', {}, (token) => {
      response.value += token
    }, { query: q, market: props.marketTab })
  } catch (e) {
    error.value = '提问失败：' + (e?.message || '网络错误')
  } finally {
    loading.value = false
  }
}
</script>
```

**Note**: The `useLLMStream` composable's `start(endpoint, body, onToken, params)` already supports URL query params via the 4th argument — see `frontend/src/api/index.js`:

```javascript
// Existing pattern (api/index.js):
analysisApi: {
  llmAdviceStream: (query, context, onToken, onDone) => 
    streamPost('/analysis/llm-advice/stream', context, onToken, onDone, { query }),
```

But the composable uses `fetch()` directly, not the `api` module. So we need to either:
- (a) Add a `params` parameter to `useLLMStream.start()`
- (b) Or modify `/llm-advice/stream` to accept query as a body field instead of URL param

**Recommendation**: (b) — modify the endpoint to accept `query` in the request body alongside `context` and `market`. This keeps the composable clean.

### 6.5 Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/analysis.py` | Enhance `/llm-advice/stream` with pool_manager injection + market param; deprecate non-streaming `/llm-advice` (~50 lines changed) |
| `backend/app/analysis/llm.py` | Add `_build_advice_stream_prompt()` helper (~40 lines) |
| `frontend/src/components/market/AiAdvisor.vue` | Switch to streaming; adapt to new endpoint signature (~15 lines changed) |
| `frontend/src/composables/useLLMStream.js` | (optional) No change if endpoint accepts query in body |

---

## 7. Phase E — Market Report Quality Enhancement

### 7.1 Overview

The market report (`MarketReport.vue` → `GET /api/v1/analysis/llm-report/stream`) currently:

- Explicitly forbids any action advice
- Has 4 generic sections with no regime label
- Uses pseudo-streaming (full LLM completion → chunked into SSE tokens)
- Ignores `marketTab` — always reports on the same set of A-share indices

### 7.2 Changes

#### 7.2.1 Market-Aware Data Collection (analysis.py)

Modify `LLMReportRequest` to include `market` field, and update `llm_report_stream()` to use it:

```python
# Updated request model
class LLMReportRequest(BaseModel):
    symbols: list[str] | None = None
    market: str = "A"  # NEW: A | HK | US | global
```

```python
# Updated endpoint — reads market from body, not query param
@router.post("/llm-report/stream")
async def llm_report_stream(req: LLMReportRequest):
    market = req.market  # from request body
```

Data collection changes:

| marketTab | Indices to Fetch | Market Data Focus |
|-----------|-----------------|-------------------|
| `"A"` | A-share majors (000001, 399001, 399006, 000300, 000688) | A-share sectors |
| `"HK"` | HSI, HSTECH, HSCEI | HK market data |
| `"US"` | SPX, IXIC, DJI, VIX | US market indices |
| `"global"` | All of the above | Combined |

```python
# Market-aware index filtering
idx_filter = {
    "A": {"000001", "399001", "399006", "000300", "000688", "000016"},
    "HK": {"HSI", "HSTECH", "HSCEI", "HK50"},
    "US": {"SPX", "IXIC", "DJI", "VIX", "NDX"},
    "global": None,  # no filter
}
```

#### 7.2.2 Prompt Changes (`_build_report_prompt` in llm.py)

**Add Section 0: 📌 综合研判结论**

```
## 0. 综合研判结论

| 维度 | 判定 |
|------|------|
| 大盘市态 | 🟢 偏多 / 🟡 震荡 / 🔴 偏空 |
| 情绪定位 | 乐观 / 中性 / 悲观 |
| 风格偏向 | 大盘价值 / 小盘成长 / 均衡 |
| 量价配合 | 放量上涨 / 缩量调整 / 放量滞涨 / 缩量下跌 |

给出判定依据，引用具体指标数值。
```

**Add Section 5: 💡 操作建议**

```
## 5. 操作建议

> 注意：以下建议基于当前市场环境，不构成投资指令，仅供参考。

- **仓位建议**: 如"建议仓位 5-7 成"
- **风格倾向**: 如"短期偏向防御，关注高股息板块"
- **关注板块**: 2-3 个值得关注的板块及理由
- **风险板块**: 1-2 个需要回避的板块及理由
```

The original restriction ("严禁给出任何具体组合的仓位配置、买卖清单或调仓指令") is retained for portfolio-level instructions but relaxed to allow market-level directional advice.

**Structural improvements to existing sections:**

- Add **跨周期对比** requirement (昨日 vs 今日 vs 本周 vs 本月)
- Add **关键阈值判断** (指数是否突破某均线/支撑位/压力位)
- Require **具体数据引用** for every claim

#### 7.2.3 Switch to True Streaming

Current approach (pseudo-streaming):

```python
report = await generate_market_report(...)  # waits for full LLM completion
chunk_size = 100
for i in range(0, len(report), chunk_size):
    yield f"event: token\ndata: {json.dumps({'token': report[i:i+100]})}\n\n"
```

New approach (true streaming):

```python
# Build a comprehensive prompt with market data + regime + sentiment + sector momentum
prompt = _build_report_prompt(
    indices, commodities, market_data, indicators, news, macro_news,
    market_regime=regime, market_sentiment=sentiment, sector_momentum=sector_momentum,
)

agent = get_agent("market_report")
return _sse_stream(agent.run_stream(prompt))
```

This requires modifying `_build_report_prompt()` to accept additional structured arguments (regime, sentiment, sector momentum) and weave them into the prompt text.

### 7.3 Files Changed

| File | Change |
|------|--------|
| `backend/app/analysis/llm.py` | Modify `_build_report_prompt()` — add sections 0 & 5, accept structured regime/sentiment/sector data (~40 lines) |
| `backend/app/routers/analysis.py` | Modify `LLMReportRequest` + `llm_report_stream()` — add `market` to body, market-aware data collection, true streaming (~30 lines) |
| `frontend/src/components/market/MarketReport.vue` | Pass `market: props.marketTab` in request body (~3 lines) |

---

## 8. API Contracts

### 8.1 Unified Search (replaces old)

```
GET /api/v1/market/search?keyword={keyword}&market={market}&limit={limit}
```

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| keyword | string | No | "" | Search keyword (name, symbol, pinyin) |
| market | string | No | "A" | "A" \| "HK" \| "US" \| "global" |
| limit | integer | No | 10 | Max results |
| include_sectors | boolean | No | false | Include sector results (A only) |

**Response 200:**
```json
[
  {"symbol": "600519", "name": "贵州茅台", "type": "stock",  "market": "A"},
  {"symbol": "00700",  "name": "腾讯控股", "type": "stock",  "market": "HK"},
  {"symbol": "SPY",    "name": "SPDR S&P 500 ETF", "type": "etf", "market": "US"},
  {"symbol": "BK0477", "name": "半导体",   "type": "sector", "market": "A", "sector_type": "industry"},
  {"symbol": "000300", "name": "沪深300",  "type": "index",  "market": "CN"},
  {"symbol": "HSI",    "name": "恒生指数", "type": "index",  "market": "HK"},
]
```

### 8.2 Unified Analysis Stream

```
POST /api/v1/analysis/unified-analysis/stream
Content-Type: application/json

{
  "keyword": "贵州茅台",
  "symbol": "600519",
  "name": "贵州茅台",
  "type": "symbol",
  "asset_type": "A",
  "sector_type": "",
  "market": "A"
}
```

**Response:** Standard SSE stream (see §8.4).

**Error response (400):**
```json
{"detail": "板块概念分析仅支持A股市场"}
```

### 8.3 AI Advisor Stream (enhanced)

```
POST /api/v1/analysis/llm-advice/stream
Content-Type: application/json

{
  "query": "今天行情怎么看？",
  "market": "A",
  "context": {}
}
```

**Response:** Standard SSE stream.

### 8.4 SSE Stream Format (all endpoints consistent)

```
event: token
data: {"token": "## 贵州茅台 (600519) 深度分析\n\n"}

event: token
data: {"token": "### 实时行情\n- 当前价格: 1523"}

event: done
data: {"full_text": "...", "usage": {...}, "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"}

event: error
data: {"code": "STREAM_ERROR", "message": "..."}
```

### 8.5 Contract File Locations

New/modified API contracts go in:

| Contract | File |
|----------|------|
| Unified Search | `api-contracts/market/unified-search.md` (NEW) |
| Unified Analysis | `api-contracts/analysis/unified-analysis.md` (NEW) |
| AI Advisor Stream | `api-contracts/analysis/llm-report.md` (UPDATE existing) |
| Market Report | `api-contracts/analysis/llm-report.md` (UPDATE existing) |

---

## 9. Endpoint Deprecation Plan

| Endpoint | Action | When |
|----------|--------|------|
| `GET /api/v1/market/search` | **Replace** with unified version | Phase A |
| `GET /api/v1/market/search/stocks` | **Keep** as internal (no frontend refs) | Phase A |
| `POST /api/v1/analysis/llm-report` | **Deprecate** — keep in code but add deprecation warning log; mark `# DEPRECATED` | Phase E |
| `POST /api/v1/analysis/llm-advice` | **Deprecate** — same treatment | Phase D |
| `POST /api/v1/analysis/llm-report/stream` | **Keep** — enhanced with market param | Phase E |
| `POST /api/v1/analysis/llm-advice/stream` | **Keep** — enhanced with market param + pool_manager injection | Phase D |
| `POST /api/v1/analysis/sector-analysis/stream` | **Keep** — directly callable; also accessible via unified endpoint | — |
| `POST /api/v1/analysis/symbol-analysis/stream` | **Keep** — directly callable; also accessible via unified endpoint | — |
| `POST /api/v1/analysis/unified-analysis/stream` | **NEW** — single entry point for all analysis types | Phase B |
| `GET /api/v1/market/search/unified` | **Not needed** — unified replaces the original endpoint directly | — |

---

## 10. Implementation Order & Dependencies

### Dependency Graph

```
Phase A (Unified Search Backend)
    ↓ (frontend uses same API URL)
Phase B (Unified Analysis Backend Endpoint)
    ↓
Phase C (Frontend Merged Component: UnifiedAnalysis.vue)
    ↑ depends on A + B

Phase D (AI Advisor Streaming + Data Pipeline)
    ↑ independent from A/B/C

Phase E (Market Report Quality + Market Awareness)
    ↑ independent from A/B/C/D
```

### Recommended Order

| Step | Phase | Description | Est. Effort | Depends On |
|------|-------|-------------|------------|------------|
| 1 | A | Backend: replace `/search` with multi-source unified search | 3-4h | None |
| 2 | B | Backend: new `/unified-analysis/stream` routing endpoint | 1-2h | None (can be done in parallel with 1) |
| 3 | C | Frontend: UnifiedAnalysis.vue + SearchInput.vue + delete 3 + edit parent | 4-5h | A + B |
| 4 | — | **Milestone: P2/P4/P5/P6 verified** | 0.5h | 1-3 done |
| 5 | D | Backend: enhance `/llm-advice/stream`; Frontend: switch to streaming | 2-3h | None |
| 6 | — | **Milestone: P3 verified** | 0.5h | 5 done |
| 7 | E | Backend: market-aware report + prompt upgrade + true streaming | 2-3h | None |
| 8 | — | **Milestone: P1 verified** | 0.5h | 7 done |
| 9 | — | Full E2E verification | 1h | All done |

**Total estimated effort: 13-19 hours** (backend ~8-12h, frontend ~5-7h).

### Parallelization Options

- **Step 1 (A) + Step 2 (B)**: Can be done in parallel (no overlap)
- **Step 5 (D) + Step 7 (E)**: Can be done in parallel (no overlap, no shared files)
- **Steps 1-3** must be sequential (frontend depends on backend API contracts being finalized)

---

## 11. Risks & Mitigations

### Risk 1: `selectedSymbol` Prop Breakage

**Description**: `MarketAnalysis.vue` passes `:selectedSymbol="selectedSymbol"` from watchlist clicks. After merge, `UnifiedAnalysis.vue` must consume it.

**Mitigation**: Explicit watch with dedup guard — `watch(() => props.selectedSymbol, val => { if (val && val !== lastAnalyzed) doAnalyze() })`. Add to test checklist.

### Risk 2: HK Instruments Table May Be Sparse

**Description**: The `instruments` table might not be fully populated with HK stocks. HK-market search could return few results.

**Mitigation**: Document as known limitation. If the table is empty for HK, the search will fall through to any cached data. For minimum viable product, HK search accuracy is acceptable if it finds major stocks (00700, 09988, etc.).

### Risk 3: Sector Analysis Only Works for A-Share

**Description**: Sector codes (BK0477 format) are an A-share East Money concept. HK/US don't have equivalent codes.

**Mitigation**: Backend unified analysis endpoint explicitly returns `400` with "板块概念分析仅支持A股市场" when sector analysis is requested for HK/US. Frontend hides the "板块" quick example chip when `marketTab !== 'A'`.

### Risk 4: Index Analysis Uses Symbol Analysis Prompt

**Description**: Index analysis routes to `symbol_analysis_stream` with `asset_type="index"`. The LLM prompt mentions "个股/ETF" which is slightly inaccurate for indices.

**Mitigation**: Acceptable for v1. The actual analysis content (technical indicators, trends, support/resistance) is still useful. A future improvement could add an index-specific prompt file. Note in code: `# TODO: add index-specific prompt`.

### Risk 5: US Search Coverage Limited

**Description**: US market search relies on a static curated list (~80 symbols). Users searching for less common US symbols won't find them.

**Mitigation**: Document as known limitation. The curated list covers the most commonly traded US ETFs and stocks by Chinese retail investors. The list can be extended easily.

### Risk 6: True Streaming First-Token Latency

**Description**: True streaming (`agent.run_stream`) shows the first token only when the LLM has started generating. If the provider is slow to first token, the user sees a blank loading bar longer.

**Mitigation**: Keep the existing loading bar animation. Add a status message after 5 seconds: "正在等待 AI 响应…".

---

## 12. Verification Plan

### Unit Tests

| Test | File | What to Verify |
|------|------|---------------|
| `test_search_unified.py` | `backend/tests/` | Returns correct types per market filter; timeout handling; dedup; US curated list |
| `test_search_unified_market_filter.py` | `backend/tests/` | A filter excludes HK/US; HK filter returns HK symbols; global returns all |
| `test_unified_analysis_route.py` | `backend/tests/` | Auto-detect patterns; correct routing to underlying endpoints; sector-for-HK returns 400 |
| `test_advice_stream_data_injection.py` | `backend/tests/` | `/llm-advice/stream` with `market=A` injects A-share indices; `market=HK` injects HSI |
| `test_market_report_market_aware.py` | `backend/tests/` | Report for `market=HK` includes HSI; report for `market=A` includes 上证 |

### Frontend Component Tests

| Test | File | What to Verify |
|------|------|---------------|
| `SearchInput.spec.js` | `frontend/src/test/` | Debounce; suggestion rendering; keyboard navigation; type badges |
| `UnifiedAnalysis.spec.js` | `frontend/src/test/` | `selectedSymbol` prop triggers analysis; search → analyze flow; market-aware examples |
| `AiAdvisor.spec.js` | `frontend/src/test/` | Streaming renders progressively; market prop passed to API |

### E2E Verification (update `verify_e2e.py`)

Add checks for:

1. **Unified search (A)**: `GET /api/v1/market/search?keyword=茅台&market=A` → returns items with `type: "stock"`
2. **Unified search (HK)**: `GET /api/v1/market/search?keyword=腾讯&market=HK` → returns items with `market: "HK"`
3. **Unified analysis**: `POST /api/v1/analysis/unified-analysis/stream` with symbol type → SSE stream with tokens
4. **Unified analysis (sector for HK → 400)**: `sector` type + `market=HK` → 400 error
5. **AI advisor stream**: `POST /api/v1/analysis/llm-advice/stream?query=今天行情如何` → substantive SSE stream
6. **Market report**: `POST /api/v1/analysis/llm-report/stream` with `{"symbols": null, "market": "A"}` → includes 操作建议 section

### Manual Verification Checklist

- [ ] Switch to **A** tab → type "茅台" → dropdown shows贵州茅台 (stock) + 白酒ETF (etf)
- [ ] Switch to **HK** tab → type "腾讯" → dropdown shows 腾讯控股 (stock)
- [ ] Switch to **US** tab → type "SP" → dropdown shows SPY + SPX + other US symbols
- [ ] Select any → click 分析 → streaming Markdown renders progressively
- [ ] Click a watchlist item → UnifiedAnalysis auto-analyzes (no manual click needed)
- [ ] Switch to **HK** tab → try type "半导体" in quick examples → no sector chip shown
- [ ] AI advisor: ask "今天行情怎么看" in A mode → substantive A-share data
- [ ] AI advisor: switch to HK tab → ask same question → HK market data in response
- [ ] Market report: generate in A mode → has 综合研判结论 + 操作建议 + A-share data
- [ ] Market report: switch to US mode → generate → shows SPX/IXIC data
- [ ] Quick bar only shows "标的分析" instead of 3 separate buttons
- [ ] Old WatchlistPanel search still works (same API URL, enriched results)

---

*End of plan (V3). Reviewed and ready for implementation.*
