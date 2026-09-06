# ETF Surge

> 中文版：[README_CN.md](./README_CN.md)

A multi-asset real-time market analysis and ETF portfolio management platform covering **A-shares, Hong Kong, US stocks, gold, crude oil, and silver**. It was built to make AI-assisted investing fast, reliable, and auditable — combining an AI portfolio designer, a live factor model, and LLM-powered market analysis, with the entire market-data layer running on free sources.

FastAPI (async) backend + Vue 3 (Pinia + ECharts) frontend. Data moves over REST, WebSocket, and SSE. Quotes are cached at 5–15s per market, sector boards refresh every 60s, regime/sentiment/news every 120s.

---

## Why this exists

The starting point was a human problem: **nobody can watch the whole market**. Manually tracking every asset class, every sector, and the day's news is slow, subjective, and inevitably narrow — analysis bends toward what you already believe, misses what you aren't looking at, and arrives late. This system exists to fill that gap: it collects the data and runs the first-pass analysis across the full market, at a speed and breadth no person can match.

The obvious shortcut — just ask an AI chatbot — fixes the coverage problem but creates five new ones:

1. **Data latency.** Knowledge bases and web search give a model a "present" that is hours or even days stale — and the model won't tell you it's stale. It may misstate the date, or confidently analyze "market data" for a point in time that hasn't happened yet. Real-time prices, intraday sentiment, and today's news are exactly what a chat tool is worst at.
2. **Hallucination.** LLMs confidently invent numbers, tickers, and "trends" that don't exist. In investment decisions, a fabricated figure is worse than no figure.
3. **Style drift.** Ask the same question twice and the answer comes back differently — different structure, different emphasis. You can't build a repeatable process on answers that change shape every time.
4. **Non-reproducible.** The same inputs should produce the same portfolio. A chat model won't.
5. **Non-auditable.** When a decision goes wrong, you need to know why: which factor, which data source, which assumption. A chat log can't tell you.

ETF Surge exists to answer those five problems head-on, not to be "another AI tool". The engineering choices in this repo all flow from them:

- **Ground the LLM in live data.** Every analysis runs against a real-time data layer — quotes, K-lines, indicators, factor scores — fetched at request time. The model writes prose about data it can actually see, instead of inventing.
- **Deterministic where it matters.** Portfolio allocation is computed by a pure-function engine with zero I/O: same inputs, same outputs, every time. LLM prose is decoration on top of engine output, never the source of truth.
- **A factor model with statistical checks.** 38 live factors with daily IC tracking give analysis a factual backbone — whether a factor works is a statistical question, not a model's assertion.
- **Everything is auditable.** Designs are persisted, factor scores stored, token usage logged, data-source health monitored. You can reconstruct why a portfolio looks the way it does.

And because the whole thing runs on free data sources, there's a hard constraint underneath: **the data layer has to survive flaky providers**. akshare, Sina, Tencent, EastMoney, levistock, mootdx — each works most of the time and fails in its own way. So every data chain carries a fallback chain behind a circuit breaker; empty results count as misses, not failures; and when every source is down, the API says so instead of serving stale or fabricated numbers. A system that helps you invest must never quietly hand you bad data.

That resilience work is most of this repo — not because it's glamorous, but because it's the difference between a demo and a tool you'd actually trust with a decision.

---

## Features

### Market data

- **Six asset classes** — A-shares, HK stocks, US stocks, gold, crude oil, silver: realtime quotes, K-line history, technical indicators (MA / MACD / RSI / KDJ / BOLL / ATR / VWAP), and composite buy / sell signals.
- **Watchlist** with live enrichment: per-item fallback, T-1 close snapshot fallback off-hours, and a normalized 7-field realtime contract (`price / change_pct / volume / as_of / is_estimated / estimate_source / data_source`) so the UI never guesses what a field means.
- **Sector & concept boards** with rotation, heat ranking, hot plates (A / HK), and hot-stock ranking — all market-scoped per tab.
- **Unified search** across symbols, sectors, and indices, with multi-level fallback (instruments table → levistock → static A-stock base → ETF list); the sector/index modes hit the in-memory sector cache and the `indices_meta` table directly (post round52 R177 this covers CSI custom indices such as dividend-low-volatility).
- **Fund NAV** for OTC funds; **fundamentals** (PE / PB, fund flow) for A-shares and US indices.

### AI portfolio design

- `POST /portfolio/design-async` generates **three risk-profile ETF portfolios** (Defensive / Balanced / Aggressive) from live factor scores.
- The **strategy engine** (`app/engine/`) is a pure-function package: allocation, layer budgets, rationale, risk controls, composite signal, correlation, pool balancing — zero I/O, with purity enforced by an AST gate in CI. **Determinism in practice**: given the same market snapshot, the three plans are identical every single run — that is what "reproducible" means in engineering terms.
- Three layers per strategy, per-profile budget tables, and hard risk constraints (single holding ≤ 30%, sector concentration < 40%, correlation cap). Same-index / same-theme candidates are deduplicated via the taxonomy family table, preventing duplicate exposure like "two CSI-A500 ETFs at 20% and 5%".
- Async pipeline: data + engine first → `quick_ready` (plans pushed before the LLM report finishes) → LLM report → notification. If data is degraded, it falls back to a **static degraded design** instead of fabricating one.
- **Consistency validation**: the LLM cannot introduce ETFs outside the candidate pool — violations get a correction footnote, not silent acceptance.

### Factor model

- **193 factors defined** in `factor_definitions.yaml`; **38 with live compute functions** across 9 categories (technical, style, sentiment, alternative, theme, microstructure, etf_specific, china_specific, macro).
- **Daily IC tracking** — IC (information coefficient) measures how well "yesterday's factor score" correlates with "today's actual move": recorded daily as Spearman rank correlation with Newey–West standard errors. A factor only "graduates" after ≥ 250 trading days of IC history with a t-statistic ≥ 2 and |IR| ≥ 0.5 — **statistics decide, not vibes**.
- IC history is backfilled at startup, persisted to SQLite, and exposed per-factor via `/factors/active` (mean IC, IR, t-stat, zero-ratio, status).

### LLM analysis suite

- **Market report** (`/analysis/llm-report/stream`), **investment advisor Q&A** (`/analysis/llm-advice/stream`), **symbol / sector deep-dive** (`/analysis/symbol-analysis/stream`, `/sector-analysis/stream`), and **news impact analysis**.
- The four analysis endpoints are **SSE streaming**: the first byte is emitted immediately and heavy I/O is deferred, so the client sees progress instead of silence.
- **Provider failover**: OpenCode Zen primary, DeepSeek fallback, distinct timeouts per provider.

### Observability

- **Token monitor** — per-function LLM token usage, hour/day/month time-series, failure log (in-memory ring flushed to SQLite).
- **Source monitor** — per-source health, event timeline, circuit-breaker states, connection-pool and thread-pool stats.
- **Factor model view** — IC statistics per factor, category coverage, significance status.
- **Runtime config editor** — change API keys in the UI without a restart (DB overrides on top of `.env`).
- **Warmup status** endpoint and health probes on every data source every 120s.

### Agentic layer (v7 upgrade)

The LLM module is upgraded from "single prompt → report" to a production agent stack:

- **MCP tool layer** — 4 stdio MCP servers (`quote` / `factor` / `portfolio` / `news`) wrap the real production chains (multi-source failover, the 38-factor pure-function engine, async strategy-check pipeline, news buckets). Every tool output carries a traceable envelope `{data, as_of, source, degraded}`; failures degrade honestly instead of fabricating data. Callable from any MCP host (`python -m app.mcp_servers.quote_server`) or in-process by the agent loop.
- **Plan-and-Execute loop with guardrails** — step budget (10, truncation → partial results), tiered time budgets sourced from one module (strategy check 90s / design report 120s), loop detection (same tool + same args twice → terminate), tool whitelist (PermissionError on unregistered tools), write-confirmation gate (order/trade actions require explicit confirm), and output schema validation (every step output must carry a `source` — numbers must be traceable).
- **Evals with CI gates** — golden sets in 5 categories (quotes / factors / format compliance / refusal anti-hallucination / multi-step). Blocking gates: overall ≥95%, refusal zero-hallucination 100%, format 100%. `python -m scripts.evals.ci_gate`.
- **Trace + cost accounting** — every run lands a structured trace (JSONL + SQLite `agentic_runs` with per-run cost); model price table with a $0.5 per-run budget circuit-breaker (`agentic_budget_exceeded` warning).

> STAR one-liner: "I hardened a live portfolio system's LLM module into a production agent stack — MCP tool layer over real failover chains, a guardrailed Plan-and-Execute loop where every number is source-traceable, golden-set evals gating CI at 95%+, and per-run cost tracing."

---

## Architecture

```
 Browser (Vue 3 · Pinia · ECharts · PWA)
 Dashboard / Market / Portfolio / News / Token / Source / Config
        │   REST (/api/v1) + WebSocket (/api/v1/ws) + SSE (/analysis/*/stream)
        ▼
 ┌───────────────────────────────────────────────┐
 │ FastAPI (async)                                │
 │ lifespan: warmup sequence (7 staged tasks) ·   │
 │   background loops: sector 60s · regime+sent.  │
 │   120s · news 120s · IC persistence 120s ·     │
 │   health 120s                                  │
 │ routers: market portfolio analysis news        │
 │          factors admin system ws               │
 └───────────────┬───────────────────────────────┘
                 │
 ┌───────────────▼───────────────────────────────┐
 │ tasks (async workers)                          │
 │ task_manager · design_pipeline (quick_ready)   │
 │ strategy_check_worker · design_report          │
 │ news_refresh · sector_refresh                  │
 └───────────────┬───────────────────────────────┘
                 │
 ┌───────────────▼───────────────────────────────┐
 │ agentic/ (v7 upgrade · Plan-and-Execute)       │
 │ AgentLoop (step/time budgets · write-confirm   │
 │   gate · output schema validation)             │
 │ Executor (tool whitelist · loop detection)     │
 │ trace_store (JSONL + SQLite cost rows)         │
 │ cost (model price table · $0.5 run budget)     │
 └───────────────┬───────────────────────────────┘
                 │ in-process MCP handlers
 ┌───────────────▼───────────────────────────────┐
 │ mcp_servers/ (4 stdio servers · MCP SDK 1.x)   │
 │ quote (realtime/bars) · factor (snapshot)      │
 │ portfolio (strategy_check 2-phase)             │
 │ news (financial search)                        │
 │ every envelope: {data, as_of, source, degraded}│
 └───────────────┬───────────────────────────────┘
                 │
 ┌───────────────▼───────────────────────────────┐
 │ services (orchestration)                       │
 │ market_data_hub (mixin package) · strategy_    │
 │   design · market_service · portfolio package  │
 │ llm_context · market_trends · etf_classifier   │
 └───────────────┬───────────────────────────────┘
                 │ pure calls, no I/O
 ┌───────────────▼───────────────────────────────┐
 │ engine/ (pure functions · AST purity gate)     │
 │ allocation_engine · budgets · composite_signal │
 │ correlation · pool_balancing · rationale ·     │
 │ risk_controls                                  │
 └───────────────┬───────────────────────────────┘
                 │ factor scores
 ┌───────────────▼───────────────────────────────┐
 │ factors/ · fetchers/                           │
 │ factor_registry (38 implemented / 193 defined) │
 │ ic_tracker (Spearman IC · Newey-West)          │
 │ SourceRegistry (circuit breaker + priority)    │
 │ china_market · global_markets · etf_scanner    │
 │ sector · news · fundamentals · fund · macro    │
 └───────┬──────────────────┬──────────────┬──────┘
         │                  │              │
 ┌───────▼──────┐  ┌────────▼───────┐  ┌────▼────────────┐
 │ L1 in-process│  │ L2 Redis       │  │ SQLite          │
 │ MemoryCache  │◄►│ (default in    │  │ portfolio.db    │
 │ (TTL, always │  │  Docker, auto- │  │ token_usage.db  │
 │  available)  │  │  degrade)      │  │ source.db       │
 └──────────────┘  └────────────────┘  └─────────────────┘
```

### Data source fallback chains

Every chain goes through `SourceRegistry.route()` — sources in cooldown are skipped, the first source returning valid data wins:

| Asset / Operation | Fallback chain |
|---|---|
| A-share realtime (single) | mootdx → Tencent → Sina → TickFlow |
| A-share realtime (batch) | mootdx → Tencent → Sina |
| HK realtime | Sina → Tencent → EastMoney → TickFlow |
| A-share daily K-line | stocks: mootdx → Sina → NetEase · ETF: Sina → NetEase → BaoStock → TickFlow |
| A-share intraday K-line (15m/30m/1h/4h) | Sina → akshare EastMoney |
| CN indices | Sina (s_sh) → mootdx → Tencent |
| ETF full scan | Sina + Tencent → EastMoney (push2 → push2delay) → akshare spot |
| US realtime | TwelveData → Finnhub |
| HK / US history | Tencent (HK) → akshare → Finnhub → AlphaVantage |
| Sectors / concepts | levistock → akshare |
| Fund NAV / OTC | akshare (EastMoney) |

### Key design decisions

1. **Circuit breaker with a "miss ≠ failure" rule** — `SourceRegistry` keeps a failure counter and cooldown per source. Consecutive failures (≥ 3, any HTTP 4xx/5xx, or a < 500ms fast-fail) put a source into cooldown with exponential backoff capped at 600s. Empty results are recorded as *misses*, so a source stays healthy even when individual tickers don't exist. **Analogy: the circuit breaker is the breaker panel in your home — it trips to protect the wiring; but "this one light is off" doesn't mean a blackout, which is exactly why we separate "no data" from "source is down".**
2. **Pure-function strategy engine** — `engine/` has zero I/O and zero dependencies outside itself, enforced statically by `scripts/check_engine_purity.py` (AST). Deterministic allocation means the engine is unit-testable without mocking anything. **Like a calculator: press the same keys, get the same number — allocation has no "inspiration", only arithmetic.**
3. **Two-level cache with graceful degradation** — L1 in-process `MemoryCache` (always available) + L2 `RedisCache` (cross-process, auto-degrades to no-op when unreachable). The system runs fully without Redis; Docker prod ships one by default.
4. **LLM failover + consistency guard** — OpenCode Zen primary / DeepSeek fallback; `_validate_report_consistency()` rewrites out-of-pool ETF picks with correction footnotes instead of accepting them.
5. **Async task pipeline with partial results** — design tasks write plans to the DB (`quick_ready`) *before* the slow LLM report finishes, so users see strategy results in seconds rather than after a 60s+ report.
6. **Market calendar** — `market_calendar.py` knows A-share / HK / US sessions. Off-hours return estimated NAV or last close instead of stale "live" prices, and the field `estimate_source` tells the UI what it's looking at.
7. **Honest degradation** — when data is unavailable, the API says so (degraded precision, `data_available=false`, `estimate_source=...`). The frontend renders those states explicitly — loading / empty / error / slow all have distinct UI.
8. **Performance as a constraint, not an afterthought** — the 120s background loops keep the hot path warm; 24h last-ok disk caches for indices and K-lines cut network calls at startup; SSE streams emit the first byte immediately.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · httpx · asyncio background loops |
| Data sources | mootdx · Sina · Tencent · akshare · NetEase · EastMoney · TickFlow · BaoStock · levistock (CLS) · TwelveData · Finnhub · AlphaVantage · multpl · Yahoo (US index PE/PB) |
| Cache | In-process MemoryCache (default) + optional Redis (auto-degrade) |
| Database | SQLite via aiosqlite (`portfolio.db` + `token_usage.db` + `source.db`), data layer abstracted. `portfolio.db` runs a fixed **DELETE journal mode + synchronous=FULL** (round38 R139: WAL suffered repeated page corruption under concurrent dual writers) — back up with `sqlite3 portfolio.db "VACUUM INTO 'backup.db'"`, or copy the whole file while writes are paused |
| LLM | OpenCode Zen (primary) · DeepSeek (fallback) — OpenAI-compatible |
| Frontend | Vue 3.5 · Vite 5 · Vue Router · Pinia · ECharts (vue-echarts) · axios · marked |
| Testing | pytest (async) · vitest + jsdom · @vue/test-utils · Playwright (E2E) |
| Deploy | Docker / docker-compose (profiles: dev / prod) · nginx (prod) · PWA |

---

## Project Structure

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry + lifespan (warmup sequence + background loops)
│   │   ├── config.py            # pydantic-settings (.env)
│   │   ├── database.py          # async SQLAlchemy / SQLite (DELETE journal + busy_timeout)
│   │   ├── models/              # ORM models + Pydantic schemas
│   │   ├── fetchers/            # data source modules (each with its own fallback chain)
│   │   │   ├── china_market.py      # A/HK quotes, K-lines, indices
│   │   │   ├── global_markets_fetcher.py  # US/HK (TwelveData/Finnhub/AlphaVantage)
│   │   │   ├── etf_scanner.py       # full ETF scan pipeline
│   │   │   ├── sector_fetcher.py · levistock_fetcher.py · news_fetcher.py
│   │   │   ├── fundamentals_fetcher.py · fund_fetcher.py · macro_fetcher.py
│   │   │   ├── hk_hot_fetcher.py · sync_instruments.py · sync_indices*.py
│   │   ├── services/            # orchestration layer
│   │   │   ├── hub/             # MarketDataHub mixin package (kline/realtime/sector/news/pool/...)
│   │   │   ├── portfolio/       # crud · allocation · pnl · pricing · strategy_check · transfer
│   │   │   ├── market_data_hub.py · strategy_design.py · market_service.py
│   │   │   ├── market_trends.py · llm_context.py · etf_classifier.py
│   │   │   ├── pool_audit.py · instruments_sync.py · indices_meta_sync.py
│   │   │   └── source_health.py     # health probe loop
│   │   ├── engine/              # PURE-FUNCTION strategy engine (no I/O — AST-enforced)
│   │   │   ├── allocation_engine.py · budgets.py · composite_signal.py
│   │   │   ├── correlation.py · pool_balancing.py · rationale.py · risk_controls.py
│   │   ├── factors/             # factor model
│   │   │   ├── factor_registry.py     # 38 implemented / 193 defined
│   │   │   ├── factor_definitions.yaml
│   │   │   └── ic_tracker.py          # Spearman IC · Newey-West
│   │   ├── analysis/            # indicators · signal · llm · provider failover · text pipeline
│   │   ├── tasks/               # task_manager · design_report · strategy_check_worker
│   │   │   ├── market_refresh.py · news_refresh.py · sector_refresh.py
│   │   ├── routers/             # market portfolio analysis news factors admin system ws
│   │   ├── monitor/             # token_usage · source_events · probes
│   │   ├── agentic/             # v7: agent_loop · executor · trace_store · cost · lg_agent
│   │   ├── mcp_servers/         # 4 stdio MCP servers (quote/factor/portfolio/news)
│   │   └── core/                # source_registry · cache_service · ttl · async_utils
│   │                            # market_calendar · regime · factor_aggregate · fast_json
│   ├── scripts/evals/           # golden sets (64 jsonl cases) + ci_gate + harness + scorers (v7 evals)
│   ├── tests/                   # 3,100+ pytest cases (external calls mocked)
│   ├── scripts/                 # patrol.py · verify_e2e.py · data_health_check.py
│   │                            # smoke_startup.py · verify_perf.py · check_routes.py
│   │                            # check_engine_purity.py · audit_async_blocking.py · ...
│   ├── requirements.txt · Dockerfile · .env.example
├── frontend/
│   ├── src/
│   │   ├── views/               # Dashboard · MarketAnalysis · PortfolioAnalysis
│   │   │                        # NewsView · AiDesign · ConfigView · system
│   │   ├── components/          # 36 components (dashboard / design / market / analysis / ui)
│   │   │   ├── PortfolioAnalysis.vue · NewsView.vue · TokenMonitor.vue
│   │   │   ├── SourceMonitor.vue · FactorModelView.vue · GlobalIndicesStrip.vue
│   │   ├── stores/              # Pinia: market · portfolio · task · warmup · toast · loading
│   │   ├── composables/         # useNewsWS · useTaskWS · useLLMStream · useMarketSearch
│   │   ├── api/                 # axios clients (/api/v1 base)
│   │   ├── router/              # Vue Router config
│   │   └── styles/              # theme.css (design tokens · dark mode · red-up/green-down)
│   ├── *.spec.js under src/     # vitest cases (components & utils)
│   ├── e2e/                     # 16 Playwright E2E specs
│   ├── nginx.conf · Dockerfile  # multi-stage (dev / prod)
│   └── package.json
├── api-contracts/               # 59 bilingual API contract files (frontend-backend alignment)
├── docker-compose.yml           # profiles: dev (hot-reload) / prod (baked + nginx) + diag overlay
├── docs/                        # design docs · optimization plans · round reviews (archived/ = closed rounds)
├── data/                        # SQLite DBs (volume-mounted in Docker)
├── start.ps1 · stop.ps1 · start.bat · stop.bat · restart.bat
└── AGENTS.md                    # engineering conventions (TDD · anti-fake-completion · commit rules · ...)
```

---

## Quick Start

### Option A: Local development (no Docker)

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env        # fill in API keys (see below)

uvicorn app.main:app --reload

# 2. Frontend (separate terminal — Windows must use shell)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 . Backend is at http://localhost:8000 .
> No Redis? No problem — the cache auto-degrades to in-process memory.

### Option B: Docker (one compose file, profile switch)

```bash
# Dev: source mounted + hot reload → http://localhost:5173
docker-compose up --build --profile dev

# Prod: baked images + nginx → http://localhost
docker-compose up --build --profile prod
```

- `dev` mounts `./backend` and `./frontend`; backend runs `uvicorn --reload`, frontend runs the Vite dev server. Edits apply instantly.
- `prod` packages backend + Redis + nginx (built frontend); `/api` and `/ws` are reverse-proxied to the backend.
- `dev` requires `backend/.env` to exist. Vite's `/api` and `/ws` proxies point at `backend-dev` inside the container and fall back to `localhost:8000` locally.
- For diagnostics there is a `docker-compose.diag.yml` overlay (injects PROFILE_WARMUP=1 warmup profiling).

---

## Environment Variables

`backend/.env` (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | DB connection (also derives `DATA_DIR` for caches) | `sqlite+aiosqlite:///{DATA_DIR}/portfolio.db` |
| `REDIS_URL` | Redis connection (unreachable → memory cache) | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | Allowed frontend origins, comma-separated | `http://localhost:5173,http://127.0.0.1:5173` |
| `DEEPSEEK_API_KEY` | DeepSeek key (LLM fallback) | empty |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen key (LLM primary) | empty |
| `FINNHUB_API_KEY` / `TWELVEDATA_API_KEY` / `ALPHAVANTAGE_API_KEY` / `TUSHARE_TOKEN` / `FRED_API_KEY` | Optional data-source keys | empty |
| `LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` | LLM provider failover order | `opencode_zen` / `deepseek` |
| `LLM_MODEL` | LLM model name | `deepseek-v4-flash` |
| `WARMUP_BUDGET_S` | Startup warmup budget | `30` |
| `ETF_FAST_JSON` | demjson shim (akshare hotspot fix), default on | `1` |

---

## API Overview

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/market/realtime` · `/realtime/{symbol}` | All-asset / single-asset quotes |
| GET | `/api/v1/market/realtime/batch` | Batch quotes (A/HK/US parallel) |
| GET | `/api/v1/market/realtime/portfolio` | Portfolio realtime |
| GET | `/api/v1/market/history/{symbol}` · `/chart/{symbol}` | K-line history · chart series |
| GET | `/api/v1/market/indicators/{symbol}` · `/signal/{symbol}` | Technical indicators · composite signal |
| GET | `/api/v1/market/search` | Unified symbol/sector/index search (params: `keyword` + `kind`) |
| GET | `/api/v1/market/indices/global` | Global indices (region-grouped) |
| GET | `/api/v1/market/sectors/industry` · `/concept` · `/rotation` · `/heat` | Sector boards |
| GET | `/api/v1/market/hot-plates` · `/stock-hot-rank` | Hot plates / hot stocks (A/HK) |
| GET/POST/PUT/DELETE | `/api/v1/market/watchlist` | Watchlist CRUD |
| GET/POST | `/api/v1/portfolio/etfs` | Holdings CRUD |
| POST | `/api/v1/portfolio/calculate` · `/daily-pnl` | Position sizing · daily P&L |
| GET | `/api/v1/portfolio/pnl-history` · `/drift-check` · `/timeline` | Cumulative P&L · drift · activity |
| GET/POST | `/api/v1/portfolio/export` · `/import` | CSV export / import |
| POST | `/api/v1/portfolio/design-async` · `/strategy-check-async` | Async design / strategy check |
| GET | `/api/v1/portfolio/designs` · `/designs/{id}` · `/tasks` · `/strategy-checks` | History + task status |
| POST | `/api/v1/portfolio/apply-design` | Apply an AI-generated portfolio |
| POST | `/api/v1/analysis/llm-report/stream` · `/llm-advice/stream` | SSE: market report · advisor Q&A |
| POST | `/api/v1/analysis/symbol-analysis/stream` · `/sector-analysis/stream` | SSE: symbol/sector deep-dive |
| POST | `/api/v1/analysis/news-impact` | News impact on holdings |
| GET | `/api/v1/news/headlines` · `/all` · `/macro` · `/global` · `/stock/{symbol}` · `/research/{symbol}` | News feeds (`/all` = three-bucket aggregate, round52 R178) |
| GET | `/api/v1/factors/model` · `/active` | Factor model overview · active factors w/ IC |
| GET | `/api/v1/admin/token-usage*` | LLM token usage (summary / timeseries / failures) |
| GET | `/api/v1/admin/sources/*` | Data-source health / events / circuit breakers |
| GET/PUT/DELETE | `/api/v1/admin/config` | Runtime config (API keys etc.) |
| GET | `/api/v1/admin/factor-health` · `/metrics` · `/llm/health` | Health & metrics |
| GET | `/api/v1/system/warmup` | Startup warmup status |
| GET | `/health` | Liveness (`{"status":"ok"}`) |

### WebSocket Endpoints

| Path | Description |
|---|---|
| `WS /api/v1/ws/market/{symbol}` | Realtime quote streaming (backend in place; frontend mainly consumes the portfolio channel) |
| `WS /api/v1/ws/news` | News push (snapshot on connect) |
| `WS /api/v1/ws/portfolio` | Portfolio change broadcasts (`portfolio_changed`) |
| `WS /api/v1/ws/task-notifications` | Background task progress |

> Paths carry the `/api/v1` prefix; on a 403 handshake check the prefix first.

---

## Testing & QA

The project runs a **TDD workflow** with a layered test strategy — and enforces it with gates, not just good intentions:

```bash
# Full orchestration (L1 unit → L5 frontend) — the day-to-day dev loop
cd backend && python scripts/patrol.py --diff

# Backend unit tests (pytest, external calls mocked)
cd backend && python -m pytest

# Frontend unit tests (vitest + jsdom)
cd frontend && npm test

# E2E chain verification (backend must be running)
cd backend && python scripts/verify_e2e.py

# Frontend build check
cd frontend && npm run build

# Playwright E2E
cd frontend && npm run test:e2e:smoke
```

**Scale**: ~3,100 backend pytest cases · frontend vitest component/util cases + 16 Playwright E2E specs · 59 API contract files.

**Engineering gates** (all enforced by `.githooks/pre-commit` or `patrol.py`):
- `check_engine_purity.py` — AST gate: `engine/` must not import services/fetchers/tasks or use I/O.
- `audit_async_blocking.py` — AST gate: no synchronous I/O inside `async def` (must use `run_sync` / `to_thread`).
- `check_routes.py` — every registered route must exist in `api-contracts/`.
- `audit_unused_symbols.py` — dead-code audit with a frozen baseline (fails only on *new* dead symbols).
- `check_api_usage.py` — no frontend API methods defined but never called.
- `data_health_check.py` — data-pipeline health (source reachability, factor variance, layer depth).
  ⚠️ Checker verdicts need cross-verification against the production path (round53 lesson: a bare compute() missing injections caused 3 rounds of false alarms).
- `verify_perf.py` — soft performance gate (watchlist ≤ 3s, search ≤ 1s, factor-health ≤ 2s).

**Testing principles**: external network / LLM calls must be mocked in unit tests; `verify_e2e.py` asserts real values (not just HTTP 200 / non-empty); performance checks are a soft gate that records known debt instead of blocking delivery.

---

## Development Practices

- **Contract first**: every feature starts with a bilingual contract in `api-contracts/`, then backend + frontend implement against it.
- **Anti-fake-completion**: a feature is done only when tests pass *and* a reality check confirms real callers, real data paths, and honest UI states (loading / empty / error / slow all render distinctly).
- **Red up, green down** — UI follows Chinese convention; tokens live in `theme.css`.
- **Weights are decimals** (`0.3` = 30%), never renormalized — `target_amount = total_capital × target_weight`, cash is the remainder.
- **akshare encoding** — latin1 mojibake in column names is normalized by `_decode_df()`.
- **`async def` ≠ non-blocking** — synchronous I/O inside async functions must go through `run_sync` / `to_thread`.
- **Commit messages in English only** (a commit-msg hook hard-rejects CJK), format in AGENTS.md; commits go through Git Bash.

---

## Known Limitations

Honest assessment (details in `docs/`):

- **Free sources are flaky by nature.** EastMoney `push2` throttles, akshare enters cooldowns, DeepSeek can time out under load. Fallback chains and circuit breakers absorb most of it; during sustained outages some endpoints return explicit `data source unavailable` degradations rather than stale or fake data.
- **Factor coverage is still accumulating.** 38 of 193 defined factors are implemented; most live factors need ≥ 250 trading days of IC history to reach "significant" status, so early stats read `no_data / accumulating` by design.
- **US index PE/PB** relies on free-tier multpl / Yahoo quoteSummary data and can be `None` when those sources are unreachable.
- **HK/US individual-stock search** depends on instruments sync completing; in constrained container environments the A-share stock segment can time out (a static A-stock base covers the common case).
- **SSE is unidirectional** — server → client only. Fine for streaming analysis; not a chat transport.
- **Single-node deployment** — SQLite suits single-instance; multi-user / horizontal scaling would need PostgreSQL and a message broker.

---

## License

MIT License — see [LICENSE](./LICENSE)
