# ETF Surge — Multi-Asset Real-Time Market Analysis & ETF Portfolio Management System

> **中文文档**: [README.md](./README.md) | **English Documentation**: [README_EN.md](./README_EN.md)

---

## 🚀 Overview

**ETF Surge** is a production-grade, full-stack financial application that provides **real-time multi-asset market analysis** and **ETF portfolio management**. It covers **A-shares, Hong Kong stocks, US stocks, Gold, Crude Oil, and Silver** — delivering real-time quotes, technical analysis, trading signals, news monitoring, and LLM-powered investment insights.

Built with **FastAPI (async)** + **Vue 3 (Pinia + ECharts)**, it pushes live data via **REST + WebSocket dual channels** with a **15-second market refresh cycle** powered by APScheduler.

---

## ✨ Key Features

### 📊 Multi-Asset Real-Time Quotes
| Asset Class | Coverage | Data Sources |
|-------------|----------|--------------|
| **A-Share ETFs/Stocks** | Real-time + K-line | mootdx → Sina → Tencent (failover chain) |
| **Hong Kong ETFs/Stocks** | Real-time + K-line | Sina → Tencent |
| **US ETFs/Stocks** | Real-time + K-line | yfinance |
| **Indices** | Real-time + K-line | mootdx → Tencent |
| **Futures (Gold/Oil/Silver)** | Real-time + K-line | mootdx |
| **News** | Caixin headlines, macro policy, international | akshare |

> **Data Resilience**: Multi-source fallback chains with circuit breakers ensure reliability even when individual sources fail.

### 💼 ETF Portfolio Management
- **Custom portfolios** with target weights stored as decimals (e.g., `0.3 = 30%`)
- **Holdings & position sizing** with real-time valuation
- **Daily P&L estimation** and return calculation
- **SQLite persistence** (`data/portfolio.db`) with Docker volume mounting
- **Rebalancing suggestions** via LLM analysis

### 📈 Technical Analysis & Signals
- **Indicators**: MA, MACD, RSI, KDJ, Bollinger Bands
- **Signal aggregation**: Multi-indicator buy/sell consensus
- **Real-time computation** on historical K-line data

### 📰 News & LLM Intelligence
- **Multi-source news aggregation**: Caixin, macro policy, international markets
- **DeepSeek LLM integration** for:
  - Market interpretation
  - Investment advice generation
  - Portfolio rebalancing recommendations
  - Risk assessment

### ⚡ Real-Time WebSocket Push
| Channel | Path | Payload |
|---------|------|---------|
| Market Quotes | `/ws/market/{symbol}` | Real-time price, change, volume |
| News | `/ws/news` | Latest headlines with timestamps |
| Portfolio | `/ws/portfolio` | Position updates, P&L changes |

> No polling needed — backend pushes updates every 15s via APScheduler.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (Vue 3 + Pinia)                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ Dashboard   │  │ Portfolio    │  │ Market Analysis        │  │
│  │ (P&L, Alloc)│  │ Manager      │  │ (Charts, Signals)      │  │
│  └──────┬──────┘  └──────┬───────┘  └───────────┬────────────┘  │
└─────────┼────────────────┼──────────────────────┼───────────────┘
          │ REST (/api)    │ WS (/ws)             │
          ▼                ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI async)                     │
│  ┌──────────────┐ ┌─────────────┐ ┌────────────┐ ┌───────────┐  │
│  │ market       │ │ portfolio   │ │ analysis   │ │ news      │  │
│  │ router       │ │ router      │ │ router     │ │ router    │  │
│  └──────┬───────┘ └──────┬──────┘ └─────┬──────┘ └─────┬────┘  │
└─────────┼────────────────┼───────────────┼─────────────┼───────┘
          │                │               │             │
          ▼                ▼               ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Services Layer                            │
│  ┌──────────────────┐ ┌──────────────────┐ ┌────────────────┐  │
│  │ Market Service   │ │ Portfolio Svc    │ │ Analysis Svc   │  │
│  │ (2-level cache)  │ │ (SQLite + Redis) │ │ (Indicators,   │  │
│  │ Registry pattern │ │                  │ │  Signals, LLM) │  │
│  └────────┬─────────┘ └────────┬─────────┘ └───────┬────────┘  │
└───────────┼─────────────────────┼────────────────────┼──────────┘
            │                     │                    │
            ▼                     ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Source Router (Circuit Breaker)         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ akshare  │  │ yfinance │  │ tushare  │  │ stooq/levistock│  │
│  │(A/HK/CMD)│  │(US)      │  │(token)   │  │ (fallback)     │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Background Jobs**: APScheduler runs `refresh_market_cache()` every **15 seconds** with timeout protection.

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI (async), Pydantic v2, SQLAlchemy 2.0, APScheduler |
| **Data Sources** | akshare, mootdx, yfinance, tushare, stooq, levistock |
| **Caching** | Redis (2-level: memory + Redis) with circuit breaker |
| **Database** | SQLite (portfolio) + Redis (cache) |
| **LLM** | DeepSeek API (httpx async client) |
| **Frontend** | Vue 3, Pinia, ECharts, Vite, Vue Router |
| **Deployment** | Docker Compose (dev/prod profiles), nginx (prod) |

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose (recommended)
- OR: Python 3.11+, Node.js 18+, Redis

### Option 1: Docker (Recommended)

```bash
# Development mode - hot reload, Vite dev server
docker-compose up --build --profile dev
# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
# WebSocket: ws://localhost:8000/ws/...

# Production mode - nginx + baked images
docker-compose up --build --profile prod
# http://localhost (nginx serves frontend, proxies /api & /ws)
```

> **Note**: Dev mode requires `backend/.env` with `DEEPSEEK_API_KEY`. See `backend/.env.example`.

### Option 2: Local Development (No Docker)

```bash
# Terminal 1 - Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # Add DEEPSEEK_API_KEY
uvicorn app.main:app --reload

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev
```

---

## 📁 Project Structure

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry, lifespan, routers
│   │   ├── config.py            # Pydantic Settings (.env)
│   │   ├── database.py          # SQLite + SQLAlchemy async
│   │   ├── fetchers/
│   │   │   └── akshare_fetcher.py  # Multi-source data fetching
│   │   ├── analysis/
│   │   │   ├── indicators.py    # TA: MA, MACD, RSI, KDJ, BB
│   │   │   ├── signals.py       # Signal aggregation
│   │   │   └── llm.py           # DeepSeek integration
│   │   ├── services/
│   │   │   ├── market_service.py   # 2-level cache + registry
│   │   │   ├── portfolio_service.py
│   │   │   └── cache_service.py    # Redis wrapper
│   │   ├── routers/
│   │   │   ├── market.py        # /api/market/*
│   │   │   ├── portfolio.py     # /api/portfolio/*
│   │   │   ├── analysis.py      # /api/analysis/*
│   │   │   ├── news.py          # /api/news/*
│   │   │   └── ws.py            # WebSocket endpoints
│   │   └── tasks/
│   │       └── market_refresh.py # 15s APScheduler job
│   ├── data/portfolio.db        # SQLite (Docker volume)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Dashboard.vue        # Total P&L, allocation, signals
│   │   │   ├── PortfolioManager.vue # CRUD holdings, target weights
│   │   │   ├── MarketAnalysis.vue   # Charts, indicators, signals
│   │   │   └── AnalysisView.vue     # LLM insights, news
│   │   ├── stores/
│   │   │   └── portfolio.js     # Pinia store (holdings, WS sync)
│   │   ├── api/client.js        # Axios + WS wrappers
│   │   └── App.vue
│   ├── nginx.conf               # Prod reverse proxy
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml           # Profiles: dev / prod
└── README.md
```

---

## 🔧 Configuration

### Backend `.env` (required for LLM features)
```bash
# DeepSeek API (get from https://platform.deepseek.com)
DEEPSEEK_API_KEY=<DEEPSEEK_API_KEY>

# Optional: Redis (default localhost:6379)
REDIS_URL=redis://localhost:6379/0

# Optional: Tushare token for enhanced A-share data
TUSHARE_TOKEN=your_token

# CORS origins (comma-separated)
CORS_ORIGINS=http://localhost:5173,http://localhost
```

### Frontend Vite Proxy (dev only)
```js
// vite.config.ts
server: {
  proxy: {
    '/api': 'http://localhost:8000',
    '/ws': { target: 'ws://localhost:8000', ws: true }
  }
}
```
> In Docker dev mode, proxy targets `backend-dev` container automatically.

---

## 📡 API Reference (Key Endpoints)

### Market Data
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/market/quote/{symbol}` | Real-time quote |
| GET | `/api/market/history/{symbol}` | K-line history (daily/weekly/monthly) |
| GET | `/api/market/search` | Symbol search |
| GET | `/api/market/realtime` | Batch quotes (query: `symbols=510300,510500`) |

### Portfolio
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/portfolio/` | List all portfolios |
| POST | `/api/portfolio/` | Create portfolio |
| GET | `/api/portfolio/{id}` | Portfolio detail + positions |
| PUT | `/api/portfolio/{id}/holdings` | Update holdings (target weights) |
| GET | `/api/portfolio/{id}/pnl` | Real-time P&L |

### Analysis
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analysis/indicators/{symbol}` | Technical indicators |
| GET | `/api/analysis/signals/{symbol}` | Aggregated trading signals |
| POST | `/api/analysis/llm/portfolio-advice` | LLM portfolio recommendation |
| POST | `/api/analysis/llm/market-interpretation` | LLM market commentary |

### WebSocket
```js
// Market quotes
const ws = new WebSocket('ws://localhost:8000/ws/market/510300');
ws.onmessage = (e) => console.log(JSON.parse(e.data));

// Portfolio updates
const ws = new WebSocket('ws://localhost:8000/ws/portfolio');
```

---

## 🐳 Docker Deployment Details

### `docker-compose.yml` Profiles
```yaml
services:
  backend-dev:    # profile: dev
    build: ./backend
    volumes: [./backend:/app, data:/app/data]
    environment: [DEEPSEEK_API_KEY, REDIS_URL]
    ports: ["8000:8000"]

  frontend-dev:   # profile: dev
    build: ./frontend
    volumes: [./frontend:/app, /app/node_modules]
    ports: ["5173:5173"]

  backend-prod:   # profile: prod
    build: ./backend
    volumes: [data:/app/data]
    environment: [DEEPSEEK_API_KEY, REDIS_URL]

  frontend-prod:  # profile: prod (nginx)
    build: ./frontend
    ports: ["80:80"]

  redis:
    image: redis:7-alpine
    volumes: [redis_data:/data]

volumes:
  data:
  redis_data:
```

### Production Checklist
- [ ] Set `DEEPSEEK_API_KEY` in environment
- [ ] Configure `CORS_ORIGINS` for your domain
- [ ] Use managed Redis (ElastiCache, Azure Cache, etc.)
- [ ] Enable HTTPS via reverse proxy (Traefik, Nginx Proxy Manager)
- [ ] Set up log aggregation (Loki, ELK)

---

## 🧪 Development Notes

### Data Source Encoding Fix
akshare returns Chinese columns as latin1-encoded garbage. The fetcher includes `_decode_df()` to fix:
```python
def _decode_df(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.str.encode('latin1').str.decode('utf-8')
    return df
```

### ETF Weight Convention
- **Storage**: Decimal (0.3 = 30%)
- **API I/O**: Decimal (not percentage)
- **Frontend display**: ×100 with % sign

### WebSocket Message Format
```json
// Market quote
{"symbol": "510300", "price": 3.456, "change_pct": 1.23, "volume": 123456, "ts": 1699999999}

// Portfolio update
{"portfolio_id": 1, "holdings": [...], "total_pnl": 1234.56, "ts": 1699999999}
```

---

## 📸 Screenshots

> Add screenshots here: Dashboard (total P&L, allocation pie), Portfolio Manager (holdings table), Market Analysis (ECharts candlestick + indicators), Analysis View (LLM insights).

---

## 🤝 Contributing

1. Fork the repo
2. Create feature branch: `git checkout -b feat/amazing-feature`
3. Commit changes: `git commit -m 'feat: add amazing feature'`
4. Push: `git push origin feat/amazing-feature`
5. Open a Pull Request

### Code Style
- Backend: `ruff format && ruff check` (Python)
- Frontend: `npm run lint && npm run format` (ESLint + Prettier)

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- **akshare** — Comprehensive Chinese financial data
- **mootdx** — High-performance TDX protocol access
- **yfinance** — Yahoo Finance Python wrapper
- **DeepSeek** — LLM API for financial reasoning
- **Vue 3 + Pinia + ECharts** — Modern reactive frontend stack

---

## 📞 Support & Discussion

- **Issues**: [GitHub Issues](https://github.com/your-org/ETF_Surge/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/ETF_Surge/discussions)

---

> ⚠️ **Disclaimer**: This software is for educational and research purposes only. Not financial advice. Always do your own due diligence before making investment decisions.