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
                         └───┬───────────┬──────────────┬───────┘
                             │           │              │
                    ┌────────▼──┐ ┌──────▼──────┐ ┌────▼──────────┐
                    │ services  │ │ analysis    │ │ tasks         │
                    │ market/   │ │ indicators/ │ │ TaskManager   │
                    │ portfolio │ │ signal/llm  │ │ (design/check │
                    │ market_   │ │ text_       │ │  /report)     │
                    │ data_hub  │ │ pipeline*   │ │ · worker_reg  │
                    │ strategy_ │ │ (DeepSeek/  │ │ · 90s timeout │
                    │ design    │ │  OpenCode)  │ └──────┬────────┘
                    │ source_   │ └─────────────┘        │WS push
                    │ registry  │                        ▼
                    │ (circuit  │               ┌────────────────┐
                    │  breaker) │               │ design_report  │
                    │ cache_    │               │ compose_and_   │
                    │ service   │               │ push_report()  │
                    │ (2-level) │               │ consistency    │
                    └─────┬─────┘               │  validation    │
                          │                     └────────────────┘
             ┌────────────┼──────────────────────────────┐
              ▼            ▼              ▼
        china_market  global_markets  twelvedata/     levistock
        (mootdx/      (TwelveData →  finnhub         (sector)
         sina/         Finnhub for   (free tiers)
         tencent/      US/HK)
         akshare/
         eastmoney)
             │
             ▼  news_fetcher → Caixin / macro / global
             ▼  sector_fetcher / fund_fetcher / fundamentals_fetcher / ttj_fetcher
                         ┌──────────────┐      ┌──────────────┐
                         │ L1 Memory    │◄────►│ L2 Redis     │
                         │ Cache (TTL)  │      │ (optional,   │
                         │ always avail │      │ auto-degrade)│
                         └──────────────┘      └──────────────┘
                         ┌───────────────────────────┐
                         │ SQLite (SQLAlchemy async)  │ → data/portfolio.db
                         └───────────────────────────┘
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

- **Free data sources are rate-limited / flaky by nature**: EastMoney `push2` / index endpoints throttle (remote disconnect), akshare goes into cooldown windows, and DeepSeek can time out under load. The fallback chains and circuit breakers absorb most of this; during sustained outages some endpoints return honest "data source unavailable" degradations rather than stale or fake data. (ref: `docs/round6-diagnosis-and-optimization-plan.md`)
- **mootdx needs a bootstrap server in fresh environments**: the first connection relies on `~/.mootdx/config.json` BESTIP cache; in containers/CI it may spin before falling back to Tencent/Sina. A code-level fix is planned (R6-F1).
- **Sector/concept analysis truncates at 200**: large daily decliners (e.g. semiconductors) can fall outside the top-200 window and return 404 "sector mapping failed" (R6-04).
- **Design report metric labeling**: some RSI/MACD figures in reports come from normalized factor scores rather than raw indicator values — misleading scale (R6-05).
- **Two independent signal systems**: `strategy-check` tech_signal (factor registry) vs `/market/signal` (rule-based) can disagree on the same symbol (R6-06).
- **LLM streaming can drop mid-stream**: occasionally the first streamed response contains only the disclaimer; retries are not yet automatic (R6-09).
- **Sentiment / style factors (F19) return `no_data`** when EastMoney sentiment endpoints are unavailable — expected during cooldown windows, not a data-integrity bug.

## Roadmap

Planned work, roughly in priority order (detailed plans in `docs/round6-diagnosis-and-optimization-plan.md`):

1. **P0 — Container-first reliability**: code-level mootdx bootstrap (no manual config copy in containers/CI); fix `verify_e2e` warmup gate field mismatch; lift sector/concept `limit` truncation. (R6-F1/F2/F3)
2. **P1 — Report quality**: align design-report RSI/MACD labels with raw indicator values; unify the two signal systems; stabilize cross-plan factor scores (z-score normalization within plan). (R6-05/06/07)
3. **P1 — LLM resilience**: automatic retry on streaming drop; keep DeepSeek + OpenCode Zen failover warm. (R6-09)
4. **P2 — Startup performance**: persist `etf_list_cache.json` to the mounted volume so warmup skips full rescans; profile the warmup path after mootdx fix. (R6-08)
5. **P3 — Test-guard rails**: add Docker build + fresh-environment smoke test to the gate; add meta-checks so gate assertions are real assertions; LLM end-to-end assertions with real chain. (R6-01/02/03 blind spots)
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
