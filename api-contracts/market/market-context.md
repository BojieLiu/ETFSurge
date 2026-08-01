# Market Context / 市场上下文服务

> Phase 5.1 — Market-awareness linkage. Provides unified market context resolution and data routing.

---

## 1. 概述 / Overview

**功能描述**: Provides a `MarketContext` data class and `resolve_market_context()` factory for all market-aware operations. Each endpoint that needs market-specific data (indices, regime, news, sectors) uses `resolve_market_context(market)` to get the correct configuration for the given market.

**触发场景**: Called by any endpoint that accepts a `market` parameter (`"A"|"HK"|"US"|"global"`).

---

## 2. MarketContext Data Class / 数据类

```python
@dataclass
class MarketContext:
    market: str  # "A" | "HK" | "US" | "global"

    @property
    def index_symbols(self) -> set[str]:
        # A: {"000001", "399001", "399006", "000688", "000300"}
        # HK: {"^HSI", "^HSCE", "^HSTECH"}
        # US: {"^GSPC", "^IXIC", "^DJI"}
        # global: empty set

    @property
    def title(self) -> str:
        # "A股" | "港股" | "美股" | "全球市场"

    @property
    def regime_broad_index(self) -> str | None:
        # A: "000001", HK: "^HSI", US: "^GSPC", global: None

    @property
    def supports_sector_analysis(self) -> bool:
        # Only A has mature sector data

    @property
    def supports_portfolio_design(self) -> bool:
        # Only A has complete ETF candidate pool

    @property
    def supports_regime_detection(self) -> bool:
        # A and US have feasible data

def resolve_market_context(market: str) -> MarketContext:
    """Unified market context resolution. Defaults to 'A' for backward compatibility."""
```

---

## 3. Market Router Service / 数据路由服务

**功能描述**: `services/market_router.py` provides 5 async routing functions that dispatch data requests to the correct data source based on market:

| Function | Purpose |
|----------|---------|
| `get_market_indices(market)` | Return indices relevant to market |
| `get_market_realtime(market, symbols)` | Route realtime quotes by market |
| `get_market_history(market, symbol, period)` | Route historical K-line by market |
| `get_market_news(market, max_count)` | Route news by market |
| `get_market_sectors(market, sector_type)` | Route sector data by market |

---

## 4. Sector Analysis Stream / 板块分析流式端点

```
POST /api/v1/analysis/sector-analysis/stream
```

### 请求体 / Request Body

```json
{
  "sector_code": "<string>",
  "sector_type": "industry",
  "sector_name": "",
  "market": "A"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| sector_code | string | required | Sector code |
| sector_type | string | "industry" | "industry" or "concept" |
| sector_name | string | "" | Sector display name |
| market | string | "A" | "A" \| "HK" \| "US" \| "global" |

### 响应 / Response

SSE stream. When market != "A", returns empty sector data with prompt noting "该市场暂无板块分析数据".

> **v2.0 (F2-7 步骤F)**: `sector_code` 支持热板块/热度的 `cls` 前缀代码（如 `cls82558`）。
> 后端按「名称优先 → cls 数字段匹配 BK」归一化；映射失败返回 `404 {"detail": "板块映射失败：..."}`，
> 前端降级为板块搜索。

---

## 5. Symbol Analysis Stream / 标的分析流式端点

```
POST /api/v1/analysis/symbol-analysis/stream
```

### 请求体 / Request Body

```json
{
  "symbol": "<string>",
  "name": "",
  "asset_type": "A"
}
```

### 响应 / Response

SSE stream. LLM prompt injected with correct market context.

---

## 6. Design Async / 异步组合设计

```
POST /api/v1/portfolio/design-async
```

### 请求体 / Request Body

```json
{
  "capital": 500000,
  "constraints": {},
  "market": "A"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| capital | number | 500000 | Total capital |
| constraints | object | null | Optional constraints |
| market | string | "A" | "A" \| "HK" \| "US" \| "global". Non-A returns `status: "unsupported"` |

### 响应 / Response (202)

```json
{
  "task_id": 123,
  "status": "pending",
  "created_at": "..."
}
```

When market != "A":
```json
{
  "task_id": null,
  "status": "unsupported",
  "message": "组合设计当前仅支持 A 股市场（沪市/深市 ETF）。港股和美股市场的组合设计功能正在规划中。"
}
```

---

## 7. LLM Report Stream / 市场研判报告流式端点

```
POST /api/v1/analysis/llm-report/stream
```

### 请求体 / Request Body

```json
{
  "symbols": null,
  "market": "A"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| symbols | list[string] | null | Optional symbol filter |
| market | string | "A" | "A" \| "HK" \| "US" \| "global". Controls major_symbols filtering |

---

## 8. Pool Manager Regime Cache / 市态缓存

Change `_regime_cache` from `str | None` to `dict[str, str]` to support per-market regime caching:

```python
# Before
_regime_cache: str | None = None

# After
_regime_cache: dict[str, str] = {}
```

---

## 9. Search — Already Implemented ✅

`GET /api/v1/market/search?keyword=...&market=A` already supports market parameter. No changes needed.

---

## Frontend-Backend Checklist

- [ ] Backend: `core/market_context.py` created with MarketContext + resolve_market_context()
- [ ] Backend: `services/market_router.py` created with 5 routing functions
- [ ] Backend: `routers/analysis.py` SectorAnalysisRequest.market added
- [ ] Backend: `routers/analysis.py` llm-report/stream uses market param for major_symbols filtering
- [ ] Backend: `routers/portfolio.py` design-async accepts market param
- [ ] Backend: `services/strategy_design.py` generate_enhanced_design accepts market param
- [ ] Backend: `services/pool_manager.py` regime cache changed to dict[str,str]
- [ ] Backend: `services/pool_manager.py` update_market_regime accepts market param
- [ ] Backend: `services/market_trends.py` detect_market_regime retains multi-market support
- [ ] Backend: `services/llm_context.py` build_full_context uses market_router for data routing
- [ ] Frontend: `api/index.js` designAsync passes market param
- [ ] Frontend: `DashboardAiTools.vue` passes marketTab
- [ ] Tests: `tests/test_market_context.py` created with unit tests
- [ ] Tests: MarketContext properties verified for all 4 markets
- [ ] Tests: design-async unsupported market behavior verified
