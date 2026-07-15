# ETF Surge（ETF 破浪者）

> 主文档（英文）：[README.md](./README.md)

多资产实时行情分析与 ETF 组合管理系统。覆盖 **A 股、港股、美股、黄金、原油、白银** 六大类资产，提供实时行情、组合管理、技术分析与买卖信号，并接入 DeepSeek 大模型做市场解读与投资建议。

> 浏览器打开前端即可查看总仓位、实时盈亏、分配与信号；后端通过 REST + WebSocket 双通道推送数据。

---

## ✨ 新增：AI 智能组合设计

系统新增 **AI 组合设计师**，基于实时行情、资讯与宏观指标，生成进攻型 / 平衡型 / 防御型三档 ETF 组合方案。

**核心能力：**
- **双轨输出**：同时返回完整 Markdown 报告（`design_text`，含表格、配置逻辑、对比表）与结构化 JSON（`plans`），既供人类阅读又供程序调用
- **数据驱动**：每个配置决策引用具体行情数据（涨跌幅、资金流向、新闻催化、估值分位）
- **三档风险梯度**：进攻型（权益 ≥90%，科技/成长主导）、平衡型（权益 65-85%，主线与防御均衡）、防御型（权益 50-75%，高股息/低波动为主）
- **对比速览表**：三组合并列对比（标的数、权益占比、科技/弹性占比、高股息/防御占比、现金占比、预期波动、核心品种）
- **一键应用**：通过 `/api/v1/portfolio/apply-design` 将任一方案落地至账户

**前端**：设计面板新增"完整报告 / 方案卡片"两个 Tab —— 既可阅读完整 Markdown 报告，也可用结构化卡片交互。

---

## 功能特性

- **多资产实时行情**：股票 / ETF / 商品跨市场行情，支持实时与历史 K 线。
- **ETF 组合管理**：自定义组合、目标权重（小数，如 `0.3` = 30%）、持仓与仓位计算。
- **实时盈亏**：当日盈亏预估、收益率计算。
- **技术分析**：MA、MACD、RSI、KDJ、布林带等指标。
- **买卖信号**：多指标聚合生成综合买卖信号。
- **资讯监控**：财新头条、宏观政策、国际市场快讯。
- **LLM 分析**：接入 DeepSeek 大模型做市场解读与投资建议。
- **WebSocket 推送**：行情 / 资讯 / 组合变更实时推送，无需轮询。
- **AI 组合设计**：生成进攻/平衡/防御三档 ETF 组合，双轨 Markdown + JSON 输出、数据引用理由、对比表、一键应用。

---

## 系统架构

```
                         ┌─────────────────────────────┐
   浏览器 (Vue 3)  ◄────►│  前端  Vite / nginx          │
   Dashboard / Views     │  Pinia 状态 · ECharts 图表    │
                         └───────────┬─────────────────┘
                                     │  REST (/api) + WS (/ws)
                                     ▼
                         ┌─────────────────────────────┐
                         │  后端  FastAPI (async)        │
                         │  routers: market/portfolio/  │
                         │    analysis/news/ws          │
                         └───┬───────────┬───────────┬──┘
                             │           │           │
                    ┌────────▼──┐ ┌──────▼─────┐ ┌────▼──────────┐
                    │ services  │ │ analysis   │ │ tasks         │
                    │ market/   │ │indicators/ │ │market_refresh │
                    │ portfolio │ │signal/llm  │ │(APScheduler   │
                    │ cache(2层)│ │(DeepSeek)  │ │ 15s 刷新)     │
                    │ registry  │ └────────────┘ └───────────────┘
                    └─────┬──────┘
                          │ route() 带熔断器
             ┌─────────────┼──────────────────────────────┐
             ▼             ▼             ▼                 ▼
       china_market  yfinance       tushare          stooq / levistock
       (A/港/商品)   (美股)        (需 token)        (备用源)
       (akshare+
        sina+qq)
             │
             ▼  news_fetcher → 财新 / 宏观 / 国际
                         ┌──────────────┐      ┌──────────────┐
                         │ 缓存 L1 内存  │◄────►│ 缓存 L2 Redis │
                         │ (始终可用)    │      │ (可选, 自动降级)│
                         └──────────────┘      └──────────────┘
                         ┌──────────────┐
                         │ SQLite        │  data/portfolio.db
                         │ (SQLAlchemy)  │
                         └──────────────┘
```

**组件职责**

| 层 | 模块 | 职责 |
|---|---|---|
| 入口 | `app/main.py` | FastAPI 生命周期：初始化 DB、Redis、启动行情调度器；注册路由与 CORS；`/health` 探针 |
| 配置 | `app/config.py` | `pydantic-settings` 读取 `.env`（DB / Redis / CORS / LLM 等） |
| 数据 | `app/database.py` | 异步 SQLAlchemy（`aiosqlite`），SQLite 落盘 `data/portfolio.db` |
| 采集 | `app/fetchers/*` | china_market（A 股/港股/商品，基于 akshare+sina+qq）、yfinance（美股）、tushare、stooq、levistock、news、sector 多源采集 |
| 路由 | `app/services/source_registry.py` | 数据源健康度 + 熔断器 + 优先级路由（失败自动切换备用源） |
| 缓存 | `app/services/cache_service.py` | L1 进程内 `MemoryCache`（异步，始终可用）+ `SyncMemoryCache`（同步 fetcher 的线程安全缓存封装）+ L2 `RedisCache`（不可用时自动降级） |
| 业务 | `app/services/market_service.py`、`portfolio_service.py` | 行情聚合、组合与仓位计算，场外 ETF 净值估算 |
| 核心 | `app/core/ttl.py`、`async_utils.py`、`market_calendar.py` | 统一 `CACHE_TTL` 字典、`run_sync()` 同步→异步桥接、A 股交易时间判断 |
| 工具 | `app/utils/decode.py` | `decode_df()` 拉丁编码列名与列值解码器（用于 akshare 乱码修复） |
| 分析 | `app/analysis/indicators.py`、`signal.py`、`llm.py` | 技术指标、买卖信号聚合、DeepSeek 解读（httpx） |
| 调度 | `app/tasks/market_refresh.py` | APScheduler 每 15s 刷新行情缓存，保持热点数据新鲜 |
| 接口 | `app/routers/*` | REST + WebSocket 路由 |
| 前端 | `frontend/src` | Vue 3 + Pinia + ECharts + `useMarketWS` 订阅推送 |

---

## 实现方案（关键设计）

1. **多数据源 + 熔断器（提高稳定性）**
   免费行情源经常限流 / 抖动。`source_registry.SourceRegistry` 维护每个源的连续失败计数与冷却时间：某源失败达到阈值即进入冷却期被跳过，`route()` 按优先级依次尝试可用源，任一成功即返回。多个免费源互为补充、自动隔离不稳定源。

2. **两级缓存 + 优雅降级（不强依赖 Redis）**
   - L1 `MemoryCache`：进程内 TTL 缓存，无外部依赖，始终可用。
   - L2 `RedisCache`：跨进程共享缓存；`init()` 探测连通性，连不上则 `_available=False`，所有读写安全降级为无操作。
   - 因此**没有 Redis 也能完整运行**，只是失去跨进程 / 跨重启的缓存共享。

3. **异步 + 定时预热**
   全程 `async`，SQLite 用 `aiosqlite`。启动时 APScheduler 起一个 15s 间隔任务 `refresh_market_cache` 预热行情缓存，避免请求时再去实时拉取造成延迟与源压力。

4. **WebSocket 实时推送**
   行情、资讯、组合变更通过 `/ws/market/{symbol}`、`/ws/news`、`/ws/portfolio` 主动推送；前端 `composables/useMarketWS.js` 订阅，避免轮询。

5. **统一 TTL 与 SyncMemoryCache**
   所有缓存 TTL 集中在 `core/ttl.py` 的 `CACHE_TTL` 字典，消除散落在各模块的魔法数字。新增 `SyncMemoryCache` 以线程安全的方式封装 `MemoryCache`，供 levistock、news_fetcher、sector_fetcher 等同步 fetcher 使用，替代原有的 `_CACHE` 私有字典。

6. **场外 ETF 净值估算**
   对于不在交易时间的交易所，`market_service.get_portfolio_realtime()` 回退到 ETF 的最新净值（NAV），并在返回中标记 `is_estimated: true` 和 `estimate_source`（如 `"nav"`、`"prev_close"`）。前端可据此展示为估算值而非过时价。

7. **同步→异步桥接（`run_sync`）**
   `core/async_utils.run_sync()` 标准化地将同步 fetcher 用 `asyncio.to_thread()` + 超时封装，替代散落在 routers 中的 `asyncio.to_thread` 直接调用。

8. **交易日历**
   `core/market_calendar.is_trading_time()` 判断 A 股 / 港股是否处于交易时段，供业务层决定获取实时行情还是返回估算值。

9. **LLM 集成**
   `analysis/llm.py` 通过 `httpx` 调用 DeepSeek（OpenAI 兼容协议），生成市场报告与投资建议，模型 / key 走配置。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy(async) · akshare / yfinance · APScheduler · httpx |
| 前端 | Vue 3 · Vite · Vue Router · Pinia · ECharts(vue-echarts) · axios |
| 缓存 | 进程内内存缓存（默认）+ 可选 Redis |
| 数据库 | SQLite（SQLAlchemy 异步；数据层抽象，便于切换到其他关系型数据库） |
| LLM | DeepSeek API（OpenAI 兼容） |
| 部署 | Docker / docker-compose（profiles: dev / prod） |

---

## 目录结构

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan(初始化 DB / Redis / 调度器)
│   │   ├── config.py            # pydantic-settings 配置
│   │   ├── database.py          # 异步 SQLAlchemy / SQLite
│   │   ├── models/              # ORM 模型 + Pydantic schemas
│   │   ├── fetchers/            # 多源采集：china_market、yfinance、tushare、stooq、levistock、news、sector
│   │   ├── services/            # source_registry(熔断器) / cache_service / market·portfolio_service
│   │   ├── analysis/            # indicators / signal / llm(DeepSeek)
│   │   ├── routers/             # market / portfolio / analysis / news / ws
│   │   ├── tasks/               # market_refresh (APScheduler 15s)
│   │   ├── core/                # ttl / async_utils / market_calendar
│   │   └── utils/               # decode（拉丁编码解码器）/ proxy 等工具
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/          # Dashboard / HoldingsView / PortfolioManager / AnalysisView
│   │   ├── stores/              # Pinia: market / portfolio / toast
│   │   ├── composables/         # useMarketWS (WebSocket)
│   │   ├── api/                 # axios 客户端 (/api 代理)
│   │   └── router/              # 路由
│   ├── Dockerfile               # builder / dev / nginx 三阶段
│   └── nginx.conf
├── docker-compose.yml           # profiles: dev(热更新) / prod(烘焙)
└── data/                        # SQLite 数据文件 (volume 挂载)
```

---

## 快速开始

### 方式一：本地开发（无需 Docker）

```bash
# 1. 后端
cd backend
pip install -r requirements.txt
cp .env.example .env        # 填入 DEEPSEEK_API_KEY（见文末环境变量）
uvicorn app.main:app --reload

# 2. 前端（另开终端）
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。后端默认 http://localhost:8000 。
> 本地未装 Redis 也能跑：缓存自动降级为进程内内存缓存。

### 方式二：Docker（同一份 compose，profiles 切换）

```bash
# 开发态：源码挂载 + 热更新，浏览器开 http://localhost:5173
docker-compose up --build --profile dev

# 生产态：镜像烘焙 + nginx，浏览器开 http://localhost
docker-compose up --build --profile prod
```

- `dev`：后端 `uvicorn --reload`（挂载 `./backend`）、前端 Vite dev server（挂载 `./frontend`）。改代码即时生效。
- `prod`：后端 + Redis + nginx（前端构建产物）打包，`/api`、`/ws` 由 nginx 反代到 backend。
- `dev` 模式依赖 `backend/.env` 已存在；Vite 的 `/api`、`/ws` 代理在容器内自动指向 `backend-dev`，本地开发则回落 `localhost:8000`，无需改配置。

---

## 环境变量

`backend/.env`（可参考 `.env.example`）：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | 数据库连接 | `sqlite+aiosqlite:///./data/portfolio.db` |
| `REDIS_URL` | Redis 连接（留空或连不上则降级内存缓存） | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | 允许的前端源，逗号分隔 | `http://localhost:5173` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（LLM 功能必需） | 空 |
| `TUSHARE_TOKEN` | Tushare token（使用 Tushare 源时可选） | 空 |
| `LLM_PROVIDER` | LLM 提供商 | `deepseek` |
| `LLM_MODEL` | LLM 模型名 | `deepseek-v4-flash` |

---

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/market/realtime` | 全资产实时行情 |
| GET | `/api/v1/market/realtime/{symbol}` | 单资产行情 |
| GET | `/api/v1/market/history/{symbol}` | 历史 K 线 |
| GET | `/api/v1/market/search?keyword=` | 搜索 ETF |
| GET | `/api/v1/market/indicators/{symbol}` | 技术指标 |
| GET | `/api/v1/market/signal/{symbol}` | 买卖信号 |
| GET/POST | `/api/v1/portfolio/etfs` | 组合管理 CRUD |
| POST | `/api/v1/portfolio/calculate` | 仓位计算 |
| POST | `/api/v1/portfolio/daily-pnl` | 当日盈亏 |
| GET | `/api/v1/news/headlines` | 财新头条 |
| GET | `/api/v1/news/macro` | 宏观政策 |
| GET | `/api/v1/news/global` | 国际市场 |
| POST | `/api/v1/analysis/portfolio-design` | AI 组合设计（生成进攻/平衡/防御三档 ETF 组合） |
| POST | `/api/v1/analysis/llm-report` | LLM 市场报告 |
| POST | `/api/v1/analysis/llm-advice` | LLM 投资建议 |

### WebSocket

| 路径 | 说明 |
|---|---|
| `WS /ws/market/{symbol}` | 实时行情推送 |
| `WS /ws/news` | 资讯更新推送 |
| `WS /ws/portfolio` | 组合更新推送 |

---

## 备注

- **ETF 目标权重**以小数存储（`0.3` = 30%），API 传入 / 返回均为小数。
- **akshare 编码**：返回列名可能为 latin1 乱码，采集层做 `_decode_df()` 处理。
- **数据持久化**：组合数据存 SQLite（`data/portfolio.db`），Docker 下通过 `./data` 卷挂载，容器重建不丢数据。
- **健康检查**：`GET /health` 返回 `{"status":"ok"}`。
