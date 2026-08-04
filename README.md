# ETF Surge

> 中文文档：[README_CN.md](./README_CN.md)

A production-grade, full-stack multi-asset real-time market analysis and ETF portfolio management system. Covers **A-shares, Hong Kong stocks, US stocks, gold, crude oil, and silver** — delivering real-time quotes, technical analysis, trading signals, news monitoring, and LLM-powered investment insights.

Built with **FastAPI (async)** + **Vue 3 (Pinia + ECharts)**, pushing live data over **REST + WebSocket dual channels** with a **15-second market refresh cycle**.

---

## Features

- **Multi-asset real-time quotes**: stocks / ETFs / commodities across A-share, Hong Kong, and US markets, with both real-time and historical K-line data.
- **ETF portfolio management**: custom portfolios, target weight (decimal, e.g. `0.3` = 30%), holdings and position sizing.
- **AI Portfolio Designer**: generates three risk-profile ETF portfolios (Aggressive / Balanced / Defensive) based on real-time market data, news, and macro indicators. Includes a **pure-function strategy engine** with factor scoring, dynamic budgeting, rationale generation, and risk controls.
- **33-factor core model**: K-line momentum, volume analysis, volatility, KDJ, MACD, RSI, Bollinger Bands, industry diversification, premium/discount, comprehensive signals, and more — computed via FactorRegistry (33 core factors, all with real compute functions) with IC tracking.
- **Asynchronous task system**: background task management for portfolio design, strategy checking, and market report generation with WebSocket progress push.
- **Technical analysis**: MA, MACD, RSI, KDJ, Bollinger Bands, and aggregated buy/sell trading signals.
- **News monitoring**: Caixin headlines, macro policy, international market news — with level/stars classification.
- **LLM integration**: DeepSeek / OpenCode Zen for market interpretation, investment advice, and report generation, with automatic provider failover.
- **WebSocket push**: real-time quotes, news, portfolio updates, task notifications, and design report streaming — no polling needed.
- **LLM token usage monitoring**: tracks DeepSeek/OpenCode Zen API consumption with a dedicated TokenMonitor page — time-series charts, per-function breakdown, and failure log.
- **PWA support**: installable as a desktop/mobile app with service worker caching.
- **Multi-source data resilience**: each asset class routes through its own source fallback chain under a unified circuit-breaker router (`SourceRegistry`) — continuous failures cool a source down with exponential backoff, and a healthy alternative is picked automatically.

---

## Architecture

```
                         ┌─────────────────────────────────────┐
    Browser (Vue 3) ◄────►  Frontend  Vite / nginx / PWA       │
    Dashboard / Views     │  Pinia state · ECharts · WS        │
                         └───────────┬─────────────────────────┘
                                     │  REST (/api) + WS (/ws)
                                     ▼
                         ┌─────────────────────────────────────┐
                         │  Backend  FastAPI (async)            │
                         │  lifespan: scheduler · health probes │
                         │  routers: market / portfolio /      │
                         │    analysis / news / ws / admin      │
                         └────────────┬────────────────────────┘
                                      │
                    ┌─────────────────▼────────────────────┐
                    │  tasks (async)                       │
                    │  TaskManager · design / check /      │
                    │  report workers · design_report      │
                    │  (consistency check)                 │
                    │  WS progress push ──► frontend       │
                    └─────────────────┬────────────────────┘
                                      │
                                      ▼
                    ┌───────────────────────────────────────┐
                    │  services · strategy_design           │
                    │  (orchestrator)                       │
                    │  portfolio · market · market_trends · │
                    │  llm_context                          │
                    └─────────────────┬─────────────────────┘
                                      │ calls
                                      ▼
                    ┌───────────────────────────────────────┐
                    │  engine/ (pure functions, no IO)      │
                    │  allocation_engine · budgets ·        │
                    │  rationale · risk_controls            │
                    └─────────────────┬─────────────────────┘
                                      │ factor scores
                                      ▼
                    ┌───────────────────────────────────────┐
                    │  market_data_hub (unified pipeline)   │
                    │  factor matrix · pool · regime ·      │
                    │  sentiment · news                     │
                    └─────────────────┬─────────────────────┘
                                      │ get_factor_matrix
                                      ▼
                    ┌───────────────────────────────────────┐
                    │  factors/ · fetchers                  │
                    │  factor_registry (33-dim, IC)         │
                    │  SourceRegistry (circuit breaker +    │
                    │  priority routing)                    │
                    │  china_market (mootdx→Tencent→Sina→   │
                    │  akshare→NetEase)                     │
                    │  global_markets (TwelveData→Finnhub)  │
                    │  · levistock · news                   │
                    └─────────────────┬─────────────────────┘
                                      │
            ┌─────────────────────────┼───────────────────┐
            ▼                         ▼                   ▼
    ┌────────────────┐      ┌────────────────┐   ┌───────────────────┐
    │ L1 Memory      │      │ L2 Redis       │   │ SQLite (async     │
    │ Cache (TTL)    │◄────►│ (optional,     │   │ SQLAlchemy)       │
    │ always avail   │      │ auto-degrade)  │   │ → data/portfolio  │
    └────────────────┘      └────────────────┘   │   .db             │
                                                 └───────────────────┘
```

### Data Source Fallback Chains

Each chain is routed through `SourceRegistry.route()` — sources in cooldown are skipped, and the first source returning valid data wins:

| Asset / Operation | Fallback chain |
|---|---|
| A-share realtime (single & batch) | mootdx → Tencent (QQ) → Sina |
| HK realtime | Sina → Tencent (QQ) → EastMoney (akshare) |
| A-share daily K-line | mootdx → Sina → akshare → NetEase |
| A-share intraday K-line (15m/30m/1h) | Sina → akshare (EastMoney minutes) |
| CN indices | Sina (s_sh) → mootdx → Tencent (QQ) |
| ETF full scan (base data) | Sina + Tencent → EastMoney (push2 → push2delay) → akshare spot |
| US realtime | TwelveData → Finnhub |
| HK/US history | akshare → Finnhub candles → AlphaVantage |
| Sectors / concepts | levistock → akshare |
| Fund NAV / OTC | akshare (EastMoney) |

### Key Design Decisions

1. **Pure-function strategy engine (`engine/`)**: `allocation_engine.py`, `budgets.py`, `rationale.py`, `risk_controls.py` — zero I/O, zero external dependencies. Fully deterministic allocation logic using factor scores and market regime.
2. **Unified data pipeline (`market_data_hub.py`)**: single entry point for factor matrix, candidate pools, market regime, sentiment, sector momentum, and news cache.
3. **Factor registry (`factors/factor_registry.py`)**: 33 core factors computed from market data (momentum, volume, volatility, KDJ, MACD, RSI, Bollinger, industry diversification, premium/discount, composite signal) with IC tracking and circuit breaker protection.
4. **Multi-source + circuit breaker (`source_registry.py`)**: each data source keeps its own failure counter and cooldown. `route()` tries sources by priority; consecutive failures (≥3, or any HTTP 4xx/5xx, or sub-500ms fast-fail) put a source into cooldown with exponential backoff (60s → 120s → 240s → 480s → 600s max). Empty results are recorded as *misses*, not failures, so healthy sources are never polluted by missing tickers. Multiple free sources complement each other.
5. **Two-level cache with graceful degradation**: L1 `MemoryCache` (in-process TTL, always available) + L2 `RedisCache` (cross-process, auto-degrades to no-op if unavailable). No Redis required.
6. **LLM failover**: primary `opencode_zen` provider, fallback `deepseek` provider — automatic retry with configurable timeouts.
7. **Health probes**: background health check loop probes mootdx / sina / tencent / akshare / levistock / dongfang / thread pools every 120s, feeding the same circuit-breaker state.
8. **Async task system (`tasks/task_manager.py`)**: generic TaskManager supports design / check / report task types. Workers registered via `worker_registry.py`. Tasks push progress over WebSocket (`/ws/task-notifications`) and persist results.
9. **Market calendar** (`core/market_calendar.py`): detects A-share / Hong Kong trading hours. Off-exchange hours return estimated NAV values instead of stale prices.
10. **Consistency validation** (`tasks/design_report.py`): `_validate_report_consistency()` prevents LLM from introducing ETFs outside the candidate pool, appending correction footnotes when violations are detected.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · APScheduler · httpx |
| Data Sources | china_market (mootdx/Sina/Tencent/akshare/NetEase/EastMoney) · global_markets (TwelveData/Finnhub/AlphaVantage) · levistock · akshare (HK/US/ETF) |
| Cache | In-process MemoryCache (default) + optional Redis (auto-degrade) |
| Database | SQLite via aiosqlite (data layer abstracted for other RDBMS) |
| LLM | DeepSeek API / OpenCode Zen (OpenAI-compatible, automatic failover) |
| Frontend | Vue 3 · Vite · Vue Router · Pinia · ECharts (vue-echarts) · axios · marked |
| Testing | pytest (async) · vitest + jsdom · @vue/test-utils · Playwright (E2E) |
| Deploy | Docker / docker-compose (profiles: dev / prod) · nginx (prod) |

---

## Project Structure

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry + lifespan (DB/Redis/scheduler/health)
│   │   ├── config.py            # pydantic-settings (.env)
│   │   ├── database.py          # async SQLAlchemy / SQLite
│   │   ├── models/              # ORM models + Pydantic schemas
│   │   ├── fetchers/            # data source modules
│   │   │   ├── china_market.py  # A/HK/CN-indices (mootdx→Tencent→Sina→akshare→NetEase)
│   │   │   ├── global_markets_fetcher.py  # US/HK (TwelveData/Finnhub/yfinance-legacy)
│   │   │   ├── etf_scanner.py   # Full ETF scan (Sina+Tencent→EastMoney→akshare)
│   │   │   ├── levistock_fetcher.py / sector_fetcher.py / news_fetcher.py
│   │   │   ├── fundamentals_fetcher.py / fund_fetcher.py / macro_fetcher.py
│   │   │   └── akshare_fetcher.py / ttj_fetcher.py / benchmark_stocks.py
│   │   ├── services/            # Business logic layer
│   │   │   ├── source_registry.py   # Circuit breaker + priority routing
│   │   │   ├── cache_service.py     # 2-level cache (memory + Redis)
│   │   │   ├── market_data_hub.py   # Unified data pipeline
│   │   │   ├── strategy_design.py   # Orchestrator (thin, delegates to engine/)
│   │   │   ├── market_service.py    # Real-time quotes / global indices
│   │   │   ├── portfolio_service.py # Allocation / P&L / NAV estimation
│   │   │   ├── market_trends.py     # Regime detection + ETF trends
│   │   │   └── source_health.py     # Health probe loop
│   │   ├── engine/              # Pure-function strategy engine (no I/O)
│   │   │   ├── allocation_engine.py # Core allocator (factor-sort)
│   │   │   ├── budgets.py           # Layer budgets + dynamic adjustment
│   │   │   ├── rationale.py         # Data-driven selection rationale
│   │   │   └── risk_controls.py     # Constraints (single ≤30%, sector <40%)
│   │   ├── factors/             # Factor model
│   │   │   ├── factor_registry.py   # 33-factor core computation
│   │   │   ├── factor_definitions.yaml
│   │   │   └── ic_tracker.py        # Information coefficient tracking
│   │   ├── analysis/            # Analysis modules
│   │   │   ├── indicators.py       # MA/MACD/RSI/KDJ/Bollinger
│   │   │   ├── signal.py           # Aggregated trading signals
│   │   │   ├── llm.py              # DeepSeek/OpenCode integration
│   │   │   ├── provider.py         # LLM provider failover
│   │   │   └── text_pipeline.py / registry.py / runtime.py
│   │   ├── monitor/             # LLM token usage tracking + health probes
│   │   ├── routers/             # REST + WebSocket routes
│   │   │   ├── market.py / portfolio.py / analysis.py
│   │   │   ├── news.py / ws.py / admin.py / factors.py / system.py
│   │   ├── tasks/               # Background task system
│   │   │   ├── task_manager.py       # Generic TaskManager
│   │   │   ├── worker_registry.py    # Worker dispatch
│   │   │   ├── design_tasks.py       # Design/report workers
│   │   │   ├── report_worker.py      # Async market report
│   │   │   ├── strategy_check_worker.py
│   │   │   ├── design_report.py      # LLM report pipeline
│   │   │   └── market_refresh.py     # 15s refresh scheduler
│   │   ├── core/                # Cross-cutting utilities
│   │   │   ├── ttl.py / async_utils.py / market_calendar.py / market_context.py
│   │   │   └── logging.py / config_manager.py
│   │   └── utils/               # decode (latin1), proxy helpers
│   ├── tests/                   # pytest suite (mock external calls)
│   ├── scripts/                 # verify_e2e.py, sync scripts
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/          # Vue components
│   │   │   ├── layout/         # AppLayout, PageHeader, PageContainer, Section
│   │   │   ├── dashboard/      # SummaryCards, AllocationPieChart, PnLBarChart, etc.
│   │   │   ├── design/         # DesignWizard, DesignResult, DesignHistory, etc.
│   │   │   ├── market/ / analysis/ / ui/  # sub-component dirs
│   │   │   ├── PortfolioAnalysis.vue / PortfolioManager.vue / Dashboard.vue
│   │   │   ├── NewsView.vue / GlobalIndicesStrip.vue
│   │   │   ├── TaskIndicator.vue / TaskProgress.vue / TokenMonitor.vue
│   │   │   └── SourceMonitor.vue / FactorICView.vue / ConfigView.vue
│   │   ├── views/              # Route-level pages (DashboardAiTools.vue, MarketAnalysis.vue, ...)
│   │   ├── stores/             # Pinia: market, portfolio, task, toast, loading
│   │   ├── composables/        # useMarketWS, useNewsWS (WebSocket clients)
│   │   ├── api/                # axios client (/api/v1 base)
│   │   └── router/             # Vue Router config
│   ├── e2e/                    # Playwright E2E tests
│   ├── nginx.conf
│   ├── Dockerfile              # Multi-stage (dev / prod)
│   └── package.json
├── api-contracts/              # API contract files (bilingual)
├── docker-compose.yml          # Profiles: dev (hot-reload) / prod (baked)
├── docs/                       # Design docs and optimization plans
├── prompt_eval/                # LLM prompt evaluation framework
├── data/                       # SQLite DB (volume mounted in Docker)
├── start.ps1 / stop.ps1        # PowerShell management scripts
└── restart.bat                 # One-click restart
```

---

## Quick Start

### Option A: Local development (no Docker)

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env        # fill in API keys (see env vars below)
uvicorn app.main:app --reload

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 . Backend is at http://localhost:8000 .
> Runs without Redis locally too: cache auto-degrades to in-process memory.

### Option B: Docker (single compose, profile switch)

```bash
# Dev: source mounted + hot reload, open http://localhost:5173
docker-compose up --build --profile dev

# Prod: baked images + nginx, open http://localhost
docker-compose up --build --profile prod
```

- `dev`: backend `uvicorn --reload` (mounts `./backend`), frontend Vite dev server (mounts `./frontend`). Edits apply instantly.
- `prod`: backend + Redis + nginx (built frontend) packaged; `/api` and `/ws` reverse-proxied to backend by nginx.
- `dev` requires `backend/.env` to exist. Vite's `/api` and `/ws` proxies auto-point to `backend-dev` inside the container and fall back to `localhost:8000` for local dev — no config change needed.

---

## Environment Variables

`backend/.env` (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | DB connection | `sqlite+aiosqlite:///./data/portfolio.db` |
| `REDIS_URL` | Redis connection (empty/unreachable → memory cache) | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | Allowed frontend origins, comma-separated | `http://localhost:5173` |
| `DEEPSEEK_API_KEY` | DeepSeek API key (LLM fallback) | empty |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen API key (LLM primary) | empty |
| `FINNHUB_API_KEY` | Finnhub key (optional) | empty |
| `TWELVEDATA_API_KEY` | Twelve Data key (optional) | empty |
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage key (optional) | empty |
| `TUSHARE_TOKEN` | Tushare token (optional) | empty |
| `FRED_API_KEY` | FRED key (optional) | empty |
| `LLM_PROVIDER` | Simple LLM provider (bypassed when primary/fallback set) | `deepseek` |
| `LLM_PRIMARY_PROVIDER` | Primary LLM provider | `opencode_zen` |
| `LLM_FALLBACK_PROVIDER` | Fallback LLM provider (auto-retry on failure) | `deepseek` |
| `LLM_MODEL` | LLM model name | `deepseek-v4-flash` |

---

## API Overview

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/market/realtime` | All-asset real-time quotes |
| GET | `/api/v1/market/realtime/{symbol}` | Single-asset quote |
| GET | `/api/v1/market/history/{symbol}` | Historical K-line |
| GET | `/api/v1/market/indices/global` | Global indices |
| GET | `/api/v1/market/search?keyword=` | Search ETF |
| GET | `/api/v1/market/indicators/{symbol}` | Technical indicators |
| GET | `/api/v1/market/signal/{symbol}` | Buy/sell signal |
| GET/POST | `/api/v1/portfolio/etfs` | Portfolio CRUD |
| POST | `/api/v1/portfolio/calculate` | Position calculation |
| POST | `/api/v1/portfolio/daily-pnl` | Daily P&L |
| GET | `/api/v1/portfolio/designs` | List AI design history |
| GET | `/api/v1/portfolio/designs/{id}` | AI design detail |
| POST | `/api/v1/portfolio/design-async` | Submit async portfolio design |
| POST | `/api/v1/portfolio/apply-design` | Apply AI-generated portfolio |
| POST | `/api/v1/portfolio/strategy-check-async` | Submit async strategy check |
| GET | `/api/v1/news/headlines` | Caixin headlines |
| GET | `/api/v1/news/macro` | Macro policy |
| GET | `/api/v1/news/global` | International market |
| POST | `/api/v1/analysis/portfolio-design` | AI portfolio design |
| POST | `/api/v1/analysis/llm-report` | LLM market report |
| POST | `/api/v1/analysis/llm-advice` | LLM investment advice |
| GET | `/api/v1/admin/token-usage` | Token usage summary |
| GET | `/api/v1/admin/token-usage/timeseries` | Token usage time-series |
| GET | `/api/v1/admin/token-usage/failures` | Recent LLM failures |
| GET | `/health` | Health check (`{"status":"ok"}`) |

### WebSocket Endpoints

| Path | Description |
|---|---|
| `WS /ws/market/{symbol}` | Real-time quote streaming |
| `WS /ws/news` | News update push |
| `WS /ws/portfolio` | Portfolio update push |
| `WS /ws/task-notifications` | Background task progress |
| `WS /ws/design-report/{session_id}` | Streaming design report |

---

## Testing

The project follows a **TDD workflow** with a layered test strategy:

```bash
# Backend unit tests (pytest, mocked external calls)
cd backend && python -m pytest

# Frontend unit tests (vitest + jsdom)
cd frontend && npm test

# E2E verification (requires running backend)
cd backend && python scripts/verify_e2e.py

# Frontend build check
cd frontend && npm run build

# E2E tests (Playwright)
cd frontend && npm run test:e2e:smoke
```

**Key testing principles:**
- External network / LLM (akshare, DeepSeek, yfinance) **must be mocked** in unit tests
- `verify_e2e.py` checks: health → market data → portfolio design → news → WebSocket → admin endpoints
- API contracts in `api-contracts/` enforce frontend-backend alignment

---

## Known Issues

Honest assessment of current limitations (tracked in `docs/`):

- **Free data sources are rate-limited / flaky by nature**: EastMoney `push2` / index endpoints throttle (remote disconnect), akshare goes into cooldown windows, and DeepSeek can time out under load. The fallback chains and circuit breakers absorb most of this; during sustained outages some endpoints return honest "data source unavailable" degradations rather than stale or fake data. (ref: `docs/archived/round6-diagnosis-and-optimization-plan.md`)
- **mootdx needs a bootstrap server in fresh environments** ~~— A code-level fix is planned (R6-F1).~~ **已修复（R6-F1, round6 §十）**: container fallback probes a known-good server when `~/.mootdx/config.json` BESTIP cache is empty, so first connection no longer spins in containers/CI.
- **Sector/concept analysis truncates at 200** ~~(R6-04)~~ **已修复（R6-F3）**: `limit` raised to 500, large daily decliners (e.g. semiconductors) no longer fall outside the window.
- **Design report metric labeling** ~~(R6-05)~~ **已修复（R6-F4）**: design reports now use raw RSI/MACD indicator values instead of normalized factor scores.
- **Two independent signal systems** ~~(R6-06)~~ **已修复（R6-F5）**: `strategy-check` tech_signal and `/market/signal` now derive from the same indicator source; UI labels each column's provenance (实时技术信号 vs 因子分主导).
- **LLM streaming can drop mid-stream** ~~— retries are not yet automatic (R6-09).~~ **已修复（R6-F9）**: automatic retry with backoff on empty/short streamed responses.
- **Sentiment / style factors (F19) return `no_data`** when EastMoney sentiment endpoints are unavailable — expected during cooldown windows, not a data-integrity bug.
- **Index realtime ("今日涨跌") could be fully unavailable** when EastMoney `push2` throttles — **已修复（R6-F6/F8）**: advice snapshots fall back to the index cache, and `get_index_realtime` now has a push2delay fallback for the major A-share indices.
- **ETF list cache did not survive container rebuilds** (R6-08) — **已修复（R6-F7）**: cache file persists under the mounted `DATA_DIR` volume.
- **Design-quality blind spots** — **已修复（round6 §14/§15）**: satellite pool gets non-tech theme quota (F4), dividends are barred from the satellite layer (F5), core growth-wide-basis concentration is capped at 40% (F6), verify_e2e asserts satellite ≥4 with ≥2 non-tech themes (F7), and factor scores in holdings show Chinese labels with value-range hints (F11).
- **Hot spots ignored the market tab** (HK/US still showed A-share data) — **已修复（F16）**: all three hot-spot endpoints accept `market=A/HK/US`; HK now aggregates push2delay industry plates/stocks, US returns an explicit "not supported" signal.
- **Strategy-check LLM could stall the full 60s** on a slow response — **已修复（F9）**: timeout lowered to 30s with a rule-engine fallback and distinct rate-limit/timeout/server-error copy (R6-F13).
- **`pre-commit` pytest could hang ~1h** on a network-blocked test — **已修复（F23）**: global `--timeout`, an autouse socket-block fixture, and an outer pre-commit timeout now keep the gate bounded.

## Roadmap

Planned work, roughly in priority order (detailed plans in `docs/archived/round6-diagnosis-and-optimization-plan.md`):

1. **P0 — Container-first reliability** ✅ 已实施: code-level mootdx bootstrap (R6-F1); `verify_e2e` warmup gate field (`total_elapsed`) (R6-F2); sector/concept `limit` 500 (R6-F3).
2. **P1 — Report quality** ✅ 已实施: design-report RSI/MACD raw indicator alignment (R6-F4); unified signal source (R6-F5); design-quality gates (F4-F7); Chinese factor labels (F11); build-position column (R6-F15).
3. **P1 — LLM resilience** ✅ 已实施: automatic retry on streaming drop (R6-F9); 30s timeout + distinct failure copy (F9/R6-F13); DeepSeek + OpenCode Zen failover warm.
4. **P2 — Startup performance** ✅ 已实施: `etf_list_cache.json` persisted to the mounted volume (R6-F7); `instruments` table auto-sync at startup + daily scheduler (F17).
5. **P3 — Test-guard rails** ✅ 已实施: Docker build + fresh-environment smoke note (R6-F16/F17); meta-checks on warmup gate (R6-F18); LLM end-to-end assertions (R6-F20); global pytest timeout + socket block + pre-commit outer timeout (F23).
6. **P3 — Backtest module**: current factors are computed live with IC tracking; a historical backtest harness would validate factor efficacy over time.
7. **P3 — Database upgrade**: SQLite works for single-node; abstracting to PostgreSQL opens multi-user / production deployment paths.

---

## Development Practices

- **API contract first**: new features start with a contract in `api-contracts/`, then implement backend + frontend against it.
- **Run `verify_e2e.py`** before every commit to confirm the core pipeline is intact.
- **Red up, green down**: UI uses Chinese convention — red for gains, green for losses.
- **ETF weights**: stored as decimals (`0.3` = 30%), API takes/returns decimals, frontend displays as percentages.
- **akshare encoding**: latin1 mojibake in column names is handled by `_decode_df()`.
- **No weight normalization**: `target_amount = total_capital * target_weight`; cash = remainder.

---

## Notes

- **Persistence**: portfolio data lives in SQLite (`data/portfolio.db`); Docker volume-mounts `./data` to survive container recreation.
- **PWA**: frontend supports progressive web app installation with service worker caching.
- **Disclaimer**: This software is for educational and research purposes only. Not financial advice.

## License

MIT License — see [LICENSE](LICENSE)
