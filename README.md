# ETF Surge

> 中文文档：[README_CN.md](./README_CN.md)

A multi-asset real-time market analysis and ETF portfolio management system. It covers **A-shares, Hong Kong stocks, US stocks, gold, crude oil, and silver**, providing real-time quotes, portfolio management, technical analysis, and trading signals, with DeepSeek LLM integration for market interpretation and investment advice.

> Open the frontend in a browser to view total positions, real-time P&L, allocation, and signals. The backend pushes data over REST + WebSocket dual channels.

---

## ✨ New: AI-Powered Portfolio Design

The system now includes an **AI Portfolio Designer** that generates three risk-profile ETF portfolios (Aggressive / Balanced / Defensive) based on real-time market data, news, and macro indicators.

**Key capabilities:**
- **Hybrid output**: Returns both a complete Markdown report (`design_text`) with tables, allocation logic, and comparison matrix, plus structured JSON (`plans`) for programmatic use
- **Data-driven**: Every allocation decision cites specific market data (price changes, fund flows, news catalysts, valuations)
- **Three risk tiers**: Aggressive (≥90% equity, tech/growth focus), Balanced (65-85% equity, mixed), Defensive (50-75% equity, high-dividend/low-vol focus)
- **Comparison table**: Side-by-side view of all three portfolios (holdings count, equity %, tech %, defensive %, cash %, expected volatility, core holdings)
- **One-click apply**: Deploy any generated portfolio to your account via `/api/v1/portfolio/apply-design`

**Frontend**: New "完整报告 / 方案卡片" tabs in the Design panel — view the full Markdown report or interact with structured cards.

---

## Features

- **Multi-asset real-time quotes**: stocks / ETFs / commodities across markets, with both real-time and historical K-line data.
- **ETF portfolio management**: custom portfolios, target weights (decimals, e.g. `0.3` = 30%), holdings and position sizing.
- **Real-time P&L**: daily P&L estimation and return calculation.
- **Technical analysis**: MA, MACD, RSI, KDJ, Bollinger Bands.
- **Trading signals**: aggregated buy/sell signals from multiple indicators.
- **News monitoring**: Caixin headlines, macro policy, and international market news.
- **LLM analysis**: DeepSeek LLM for market interpretation and investment advice.
- **WebSocket push**: real-time quotes / news / portfolio updates without polling.
- **AI Portfolio Design**: generate three risk-profile ETF portfolios (Aggressive / Balanced / Defensive) with hybrid Markdown + JSON output, data-cited rationale, comparison table, and one-click apply.

---

## Architecture

```
                         ┌─────────────────────────────┐
   Browser (Vue 3)  ◄────►│  Frontend  Vite / nginx      │
   Dashboard / Views      │  Pinia state · ECharts       │
                         └───────────┬─────────────────┘
                                     │  REST (/api) + WS (/ws)
                                     ▼
                         ┌─────────────────────────────┐
                         │  Backend  FastAPI (async)     │
                         │  routers: market/portfolio/  │
                         │    analysis/news/ws          │
                         └───┬───────────┬───────────┬──┘
                             │           │           │
                    ┌────────▼──┐ ┌──────▼─────┐ ┌────▼──────────┐
                    │ services  │ │ analysis   │ │ tasks         │
                    │ market/   │ │indicators/ │ │market_refresh │
                    │ portfolio │ │signal/llm  │ │(APScheduler   │
                    │ cache(2L) │ │(DeepSeek)  │ │ 15s refresh)  │
                    │ registry  │ └────────────┘ └───────────────┘
                    └─────┬──────┘
                          │ route() w/ circuit breaker
            ┌─────────────┼──────────────────────────────┐
            ▼             ▼             ▼                 ▼
      akshare       yfinance       tushare          stooq / levistock
      (A/HK/cmd)    (US)          (token)          (fallback)
            │
            ▼  news_fetcher → Caixin / macro / global
                         ┌──────────────┐      ┌──────────────┐
                         │ Cache L1 mem  │◄────►│ Cache L2 Redis│
                         │ (always on)   │      │ (optional,    │
                         │               │      │  auto-degrade)│
                         └──────────────┘      └──────────────┘
                         ┌──────────────┐
                         │ SQLite        │  data/portfolio.db
                         │ (SQLAlchemy)  │
                         └──────────────┘
```

**Component responsibilities**

| Layer | Module | Responsibility |
|---|---|---|
| Entry | `app/main.py` | FastAPI lifespan: init DB, Redis, start market scheduler; register routers & CORS; `/health` probe |
| Config | `app/config.py` | `pydantic-settings` reads `.env` (DB / Redis / CORS / LLM …) |
| Data | `app/database.py` | async SQLAlchemy (`aiosqlite`), SQLite at `data/portfolio.db` |
| Fetch | `app/fetchers/*` | akshare, yfinance, tushare, stooq, levistock, news collectors |
| Route | `app/services/source_registry.py` | source health + circuit breaker + priority routing (auto-failover) |
| Cache | `app/services/cache_service.py` | L1 in-process `MemoryCache` (always on) + L2 `RedisCache` (auto-degrade if unavailable) |
| Biz | `app/services/market_service.py`, `portfolio_service.py` | quote aggregation, portfolio & position calculation |
| Analysis | `app/analysis/indicators.py`, `signal.py`, `llm.py` | indicators, signal aggregation, DeepSeek (httpx) |
| Scheduler | `app/tasks/market_refresh.py` | APScheduler refreshes quote cache every 15s to keep hot data fresh |
| API | `app/routers/*` | REST + WebSocket routes |
| Frontend | `frontend/src` | Vue 3 + Pinia + ECharts + `useMarketWS` subscription |

---

## Implementation approach (key design)

1. **Multi-source + circuit breaker (resilience)**
   Free quote sources are frequently rate-limited or flaky. `source_registry.SourceRegistry` tracks per-source consecutive failures and a cooldown window: once failures hit a threshold the source is cooled down and skipped, and `route()` tries available sources by priority, returning on first success. Multiple free sources back each other up and unstable ones are auto-isolated.

2. **Two-tier cache + graceful degradation (no hard Redis dependency)**
   - L1 `MemoryCache`: in-process TTL cache, no external dependency, always available.
   - L2 `RedisCache`: cross-process shared cache; `init()` probes connectivity and, if unreachable, sets `_available=False` so all reads/writes safely become no-ops.
   - Therefore the app **runs fully without Redis**; only cross-process / post-restart cache sharing is lost.

3. **Async + scheduled warm-up**
   Everything is `async`; SQLite uses `aiosqlite`. On startup APScheduler starts a 15s interval job `refresh_market_cache` that warms the quote cache, avoiding real-time fetches on request (lower latency, less source pressure).

4. **WebSocket real-time push**
   Quotes, news, and portfolio changes are pushed via `/ws/market/{symbol}`, `/ws/news`, `/ws/portfolio`; the frontend subscribes through `composables/useMarketWS.js` instead of polling.

5. **LLM integration**
   `analysis/llm.py` calls DeepSeek (OpenAI-compatible) via `httpx` to generate market reports and investment advice; model / key come from config.

---

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy(async) · akshare / yfinance · APScheduler · httpx |
| Frontend | Vue 3 · Vite · Vue Router · Pinia · ECharts(vue-echarts) · axios |
| Cache | in-process memory cache (default) + optional Redis |
| Database | SQLite (SQLAlchemy async; data layer abstracted for other RDBMS) |
| LLM | DeepSeek API (OpenAI-compatible) |
| Deploy | Docker / docker-compose (profiles: dev / prod) |

---

## Project structure

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry + lifespan (init DB / Redis / scheduler)
│   │   ├── config.py            # pydantic-settings config
│   │   ├── database.py          # async SQLAlchemy / SQLite
│   │   ├── models/              # ORM models + Pydantic schemas
│   │   ├── fetchers/            # multi-source (akshare, yfinance, tushare, stooq, levistock, news)
│   │   ├── services/            # source_registry(circuit breaker) / cache_service / market·portfolio_service
│   │   ├── analysis/            # indicators / signal / llm(DeepSeek)
│   │   ├── routers/             # market / portfolio / analysis / news / ws
│   │   ├── tasks/               # market_refresh (APScheduler 15s)
│   │   └── utils/               # proxy utils
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/          # Dashboard / HoldingsView / PortfolioManager / AnalysisView
│   │   ├── stores/              # Pinia: market / portfolio / toast
│   │   ├── composables/         # useMarketWS (WebSocket)
│   │   ├── api/                 # axios client (/api proxy)
│   │   └── router/              # routes
│   ├── Dockerfile               # builder / dev / nginx multi-stage
│   └── nginx.conf
├── docker-compose.yml           # profiles: dev(hot-reload) / prod(baked)
└── data/                        # SQLite data file (volume mounted)
```

---

## Quick start

### Option A: Local development (no Docker)

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env        # fill in DEEPSEEK_API_KEY (see env vars below)
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

## Environment variables

`backend/.env` (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | DB connection | `sqlite+aiosqlite:///./data/portfolio.db` |
| `REDIS_URL` | Redis connection (empty / unreachable → memory cache) | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | Allowed frontend origins, comma-separated | `http://localhost:5173` |
| `DEEPSEEK_API_KEY` | DeepSeek API key (required for LLM) | empty |
| `TUSHARE_TOKEN` | Tushare token (optional, for Tushare source) | empty |
| `LLM_PROVIDER` | LLM provider | `deepseek` |
| `LLM_MODEL` | LLM model name | `deepseek-v4-flash` |

---

## API overview

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/market/realtime` | All-asset real-time quotes |
| GET | `/api/v1/market/realtime/{symbol}` | Single-asset quote |
| GET | `/api/v1/market/history/{symbol}` | Historical K-line |
| GET | `/api/v1/market/search?keyword=` | Search ETF |
| GET | `/api/v1/market/indicators/{symbol}` | Technical indicators |
| GET | `/api/v1/market/signal/{symbol}` | Buy/sell signal |
| GET/POST | `/api/v1/portfolio/etfs` | Portfolio CRUD |
| POST | `/api/v1/portfolio/calculate` | Position calculation |
| POST | `/api/v1/portfolio/daily-pnl` | Daily P&L |
| POST | `/api/v1/portfolio/apply-design` | Apply AI-generated portfolio design |
| GET | `/api/v1/news/headlines` | Caixin headlines |
| GET | `/api/v1/news/macro` | Macro policy |
| GET | `/api/v1/news/global` | International market |
| POST | `/api/v1/analysis/llm-report` | LLM market report |
| POST | `/api/v1/analysis/llm-advice` | LLM investment advice |
| POST | `/api/v1/analysis/portfolio-design` | AI portfolio design (Aggressive / Balanced / Defensive) |

### WebSocket

| Path | Description |
|---|---|
| `WS /ws/market/{symbol}` | Real-time quote push |
| `WS /ws/news` | News update push |
| `WS /ws/portfolio` | Portfolio update push |

---

## Notes

- **ETF target weights** are stored as decimals (`0.3` = 30%); the API takes / returns decimals.
- **akshare encoding**: returned column names may be latin1 mojibake; the fetch layer runs `_decode_df()`.
- **Persistence**: portfolio data lives in SQLite (`data/portfolio.db`); under Docker it is volume-mounted via `./data`, so it survives container recreation.
- **Health check**: `GET /health` returns `{"status":"ok"}`.
