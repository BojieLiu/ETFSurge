# ETF Surge（ETF 破浪者）

> 英文文档：[README.md](./README.md)

生产级多资产实时行情分析与 ETF 组合管理系统。覆盖 **A 股、港股、美股、黄金、原油、白银** 六大类资产，提供实时行情、技术分析、买卖信号、资讯监控，以及大模型驱动的投资研判。

基于 **FastAPI（async）** + **Vue 3（Pinia + ECharts）** 构建，通过 **REST + WebSocket 双通道**推送数据，行情刷新周期 **15 秒**。

---

## 功能特性

- **多资产实时行情**：股票 / ETF / 商品跨市场行情，支持实时与历史 K 线。
- **ETF 组合管理**：自定义组合、目标权重（小数，如 `0.3` = 30%）、持仓与仓位计算。
- **AI 智能组合设计**：基于实时行情、资讯与宏观指标，生成进攻型 / 平衡型 / 防御型三档 ETF 组合方案。内置**纯函数策略引擎**，包含因子评分、动态预算、入选理由生成与风控约束。
- **33 维核心因子模型**：K 线动量、成交量分析、波动率、KDJ、MACD、RSI、布林带、行业分散度、折溢价率、综合信号等——通过 FactorRegistry 计算（33 个核心因子，全部有真实 compute 函数），带 IC 跟踪。
- **异步任务系统**：后台任务管理，支持组合设计、策略检查、市场报告生成，通过 WebSocket 推送进度。
- **技术分析**：MA、MACD、RSI、KDJ、布林带，以及多指标聚合的买卖信号。
- **资讯监控**：财新头条、宏观政策、国际市场快讯——带 level/stars 分级。
- **LLM 集成**：DeepSeek / OpenCode Zen 双引擎，自动故障切换，支持市场解读、投资建议与报告生成。
- **WebSocket 推送**：行情、资讯、组合变更、任务进度、设计报告流式推送——无需轮询。
- **LLM Token 用量监控**：追踪 DeepSeek/OpenCode Zen API 消耗，专用 TokenMonitor 页面——时序图表、按功能聚合、失败日志。
- **PWA 支持**：可安装为桌面/移动端应用，带 Service Worker 缓存。
- **多数据源容灾**：熔断器模式，自动降级链（mootdx → Sina → Tencent → akshare → yfinance → levistock），任一源失败自动切换。

---

## 系统架构

```
                         ┌─────────────────────────────────────┐
    浏览器 (Vue 3) ◄────►│  前端  Vite / nginx / PWA           │
    Dashboard / Views     │  Pinia 状态 · ECharts · WS 客户端   │
                         └───────────┬─────────────────────────┘
                                     │  REST (/api) + WS (/ws)
                                     ▼
                         ┌─────────────────────────────────────┐
                         │  后端  FastAPI (async)               │
                         │  lifespan: 调度器 · 健康探针         │
                         │  路由: market / portfolio /          │
                         │    analysis / news / ws / admin      │
                         └───┬───────────┬──────────────┬───────┘
                             │           │              │
                    ┌────────▼──┐ ┌──────▼──────┐ ┌────▼──────────┐
                    │ services  │ │ analysis    │ │ tasks         │
                    │ market/   │ │ indicators/ │ │ TaskManager   │
                    │ portfolio │ │ signal/llm  │ │ (design/check │
                    │ pool_     │ │ text_       │ │  /report)     │
                    │ manager   │ │ pipeline*   │ │ · worker_reg  │
                    │ strategy_ │ │ (DeepSeek/  │ │ · 90s 超时保护│
                    │ design    │ │  OpenCode)  │ └──────┬────────┘
                    │ source_   │ └─────────────┘        │WS 推送
                    │ registry  │                        ▼
                    │ (熔断器)   │               ┌────────────────┐
                    │ cache_    │               │ design_report  │
                    │ service   │               │ compose_and_   │
                    │ (二级缓存) │               │ push_report()  │
                    └─────┬─────┘               │ 一致性校验     │
                          │                     └────────────────┘
             ┌────────────┼──────────────────────────────┐
              ▼            ▼              ▼
        china_market  yfinance       finnhub /        levistock
        (mootdx/sina/  (美股)        twelvedata       (备用源)
         tencent/                    (免费层)
         akshare)
             │
             ▼  news_fetcher → 财新 / 宏观 / 国际
             ▼  sector_fetcher / fund_fetcher / fundamental_fetcher / sentiment_fetcher
                         ┌──────────────┐      ┌──────────────┐
                         │ L1 内存缓存   │◄────►│ L2 Redis     │
                         │ (TTL, 始终   │      │ (可选,       │
                         │  可用)       │      │ 自动降级)    │
                         └──────────────┘      └──────────────┘
                         ┌───────────────────────────┐
                         │ SQLite (SQLAlchemy 异步)   │ → data/portfolio.db
                         └───────────────────────────┘
```

### 关键设计

1. **纯函数策略引擎 (`engine/`)**：`allocation_engine.py`、`budgets.py`、`rationale.py`、`risk_controls.py` —— 零 I/O、零外部依赖。完全基于因子分数与市场状态的确定性分配逻辑。
2. **统一数据管道 (`pool_manager.py`)**：单个入口获取因子矩阵、候选池、市场状态、情绪指数、板块动量与资讯缓存。
3. **因子注册表 (`factors/factor_registry.py`)**：33 维核心因子（动量、成交量、波动率、KDJ、MACD、RSI、布林带、行业分散度、折溢价率、综合信号），带 IC 跟踪与熔断保护。
4. **多数据源 + 熔断器 (`source_registry.py`)**：每个数据源维护失败计数与冷却时间。`route()` 按优先级依次尝试可用源；失败达到阈值即跳过，冷却后恢复。多个免费源互为补充。
5. **两级缓存 + 优雅降级**：L1 `MemoryCache`（进程内 TTL，始终可用）+ L2 `RedisCache`（跨进程，不可用时自动降级为无操作）。**没有 Redis 也能完整运行**。
6. **LLM 故障切换**：首选 `opencode_zen` 提供商，降级至 `deepseek`，自动重试，超时可配置。
7. **健康探针**：后台健康检查循环每 120s 检测 twelvedata 和 finnhub 数据源状态。
8. **异步任务系统 (`tasks/task_manager.py`)**：通用 TaskManager，支持 design / check / report 三种任务类型。通过 `worker_registry.py` 注册 worker，经 WebSocket (`/ws/task-notifications`) 推送进度，结果持久化至数据库。
9. **交易日历** (`core/market_calendar.py`)：判断 A 股 / 港股是否处于交易时段，非交易时段返回净值估算值而非过时价。
10. **一致性校验** (`tasks/design_report.py`)：`_validate_report_consistency()` 防止 LLM 引入候选池外的标的，违规时追加修正脚注。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · APScheduler · httpx |
| 数据源 | china_market (mootdx/Sina/Tencent/akshare) · yfinance · tushare · finnhub · twelvedata · levistock · alphavantage |
| 缓存 | 进程内 MemoryCache（默认）+ 可选 Redis（自动降级） |
| 数据库 | SQLite via aiosqlite（数据层已抽象，可切换其他 RDBMS） |
| LLM | DeepSeek API / OpenCode Zen（OpenAI 兼容协议，自动故障切换） |
| 前端 | Vue 3 · Vite · Vue Router · Pinia · ECharts (vue-echarts) · axios · marked |
| 测试 | pytest (async) · vitest + jsdom · @vue/test-utils · Playwright (E2E) |
| 部署 | Docker / docker-compose（profiles: dev / prod）· nginx（prod） |

---

## 目录结构

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan（DB/Redis/调度器/健康探针）
│   │   ├── config.py            # pydantic-settings（.env）
│   │   ├── database.py          # 异步 SQLAlchemy / SQLite
│   │   ├── models/              # ORM 模型 + Pydantic schemas
│   │   ├── fetchers/            # 18 个数据源模块
│   │   │   ├── china_market.py  # A/港/商品（mootdx→Sina→Tencent→akshare）
│   │   │   ├── yfinance_fetcher.py
│   │   │   ├── finnhub_fetcher.py / twelvedata_fetcher.py / alphavantage_fetcher.py
│   │   │   ├── tushare_fetcher.py / levistock_fetcher.py
│   │   │   ├── news_fetcher.py / sector_fetcher.py / sentiment_fetcher.py
│   │   │   ├── fund_fetcher.py / fundamental_fetcher.py / margin_fetcher.py
│   │   │   └── etf_scanner.py / benchmark_stocks.py
│   │   ├── services/            # 业务逻辑层
│   │   │   ├── source_registry.py   # 熔断器 + 优先级路由
│   │   │   ├── cache_service.py     # 二级缓存（内存 + Redis）
│   │   │   ├── pool_manager.py      # 统一数据管道
│   │   │   ├── strategy_design.py   # v5 轻量编排器（125 行）
│   │   │   ├── market_service.py    # 实时行情 / 全球指数
│   │   │   ├── portfolio_service.py # 仓位计算 / 盈亏 / 净值估算
│   │   │   ├── market_trends.py     # 市态判定 + ETF 趋势
│   │   │   └── source_health.py     # 健康探针循环
│   │   ├── engine/              # 纯函数策略引擎（无 I/O）
│   │   │   ├── allocation_engine.py # 核心分配器（因子排序）
│   │   │   ├── budgets.py           # 层预算 + 动态调整
│   │   │   ├── rationale.py         # 数据驱动的入选理由
│   │   │   └── risk_controls.py     # 风控约束（单只 ≤30%、行业 <40%）
│   │   ├── factors/             # 因子模型
│   │   │   ├── factor_registry.py   # 33 维核心因子计算
│   │   │   ├── factor_definitions.yaml
│   │   │   └── ic_tracker.py        # IC 跟踪
│   │   ├── analysis/            # 分析模块
│   │   │   ├── indicators.py       # MA/MACD/RSI/KDJ/布林带
│   │   │   ├── signal.py           # 聚合买卖信号
│   │   │   ├── llm.py              # DeepSeek/OpenCode 集成
│   │   │   ├── provider.py         # LLM 提供商故障切换
│   │   │   ├── text_pipeline.py / text_pipeline_b.py
│   │   │   └── registry.py / runtime.py
│   │   ├── monitor/             # LLM token 用量追踪
│   │   │   └── token_usage.py
│   │   ├── routers/             # REST + WebSocket 路由
│   │   │   ├── market.py / portfolio.py / analysis.py
│   │   │   ├── news.py / ws.py / admin.py
│   │   ├── tasks/               # 后台任务系统
│   │   │   ├── task_manager.py       # 通用 TaskManager
│   │   │   ├── worker_registry.py    # Worker 派发
│   │   │   ├── design_tasks.py       # 设计/报告 worker
│   │   │   ├── report_worker.py      # 异步市场报告
│   │   │   ├── strategy_check_worker.py
│   │   │   ├── design_report.py      # LLM 报告管道
│   │   │   ├── market_refresh.py     # 15s 刷新调度
│   │   │   └── news_refresh.py       # 30s 资讯刷新
│   │   ├── core/                # 横切工具
│   │   │   ├── ttl.py / async_utils.py / market_calendar.py
│   │   │   └── logging.py
│   │   └── utils/               # decode（latin1 解码）、proxy 工具
│   ├── tests/                   # pytest 测试（mock 外部调用）
│   ├── scripts/                 # verify_e2e.py, sync 脚本
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/          # 约 30 个 Vue 组件
│   │   │   ├── layout/         # AppLayout, PageHeader, PageContainer, Section
│   │   │   ├── dashboard/      # SummaryCards, AllocationPieChart, PnLBarChart 等
│   │   │   ├── design/         # DesignWizard, DesignResult, DesignHistory 等
│   │   │   ├── market/ / analysis/ / ui/  # 子组件目录
│   │   │   ├── PortfolioAnalysis.vue / PortfolioManager.vue
│   │   │   ├── NewsView.vue / GlobalIndicesStrip.vue
│   │   │   ├── TaskIndicator.vue / TaskProgress.vue / TokenMonitor.vue
│   │   ├── views/              # Dashboard.vue, DashboardAiTools.vue, MarketAnalysis.vue
│   │   ├── stores/             # Pinia: market, portfolio, task, toast, loading
│   │   ├── composables/        # useMarketWS, useNewsWS（WebSocket 客户端）
│   │   ├── api/                # axios 客户端（/api/v1 基地址）
│   │   └── router/             # Vue Router 配置
│   ├── e2e/                    # Playwright E2E 测试
│   ├── nginx.conf
│   ├── Dockerfile              # 多阶段构建（dev / prod）
│   └── package.json
├── api-contracts/              # API 契约文件（中英双语）
├── docker-compose.yml          # Profiles: dev（热更新）/ prod（烘焙镜像）
├── docs/                       # 设计文档与优化方案
├── prompt_eval/                # LLM Prompt 评估框架
├── data/                       # SQLite 数据文件（Docker volume 挂载）
├── start.ps1 / stop.ps1        # PowerShell 管理脚本
└── restart.bat                 # 一键重启
```

---

## 快速开始

### 方式一：本地开发（无需 Docker）

```bash
# 1. 后端
cd backend
pip install -r requirements.txt
cp .env.example .env        # 填入 API key（见下方环境变量说明）
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
| `DEEPSEEK_API_KEY` | DeepSeek API Key（LLM 降级用） | 空 |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen API Key（LLM 主用） | 空 |
| `TUSHARE_TOKEN` | Tushare token（可选） | 空 |
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage key（可选） | 空 |
| `FINNHUB_API_KEY` | Finnhub key（可选） | 空 |
| `TWELVEDATA_API_KEY` | Twelve Data key（可选） | 空 |
| `FRED_API_KEY` | FRED key（可选） | 空 |
| `LLM_PROVIDER` | 简单 LLM 提供商（设了 primary/fallback 后无效） | `deepseek` |
| `LLM_PRIMARY_PROVIDER` | 主 LLM 提供商 | `opencode_zen` |
| `LLM_FALLBACK_PROVIDER` | 降级 LLM 提供商（失败自动重试） | `deepseek` |
| `LLM_MODEL` | LLM 模型名 | `deepseek-v4-flash` |

---

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/market/realtime` | 全资产实时行情 |
| GET | `/api/v1/market/realtime/{symbol}` | 单资产行情 |
| GET | `/api/v1/market/history/{symbol}` | 历史 K 线 |
| GET | `/api/v1/market/indices/global` | 全球指数 |
| GET | `/api/v1/market/search?keyword=` | 搜索 ETF |
| GET | `/api/v1/market/indicators/{symbol}` | 技术指标 |
| GET | `/api/v1/market/signal/{symbol}` | 买卖信号 |
| GET/POST | `/api/v1/portfolio/etfs` | 组合管理 CRUD |
| POST | `/api/v1/portfolio/calculate` | 仓位计算 |
| POST | `/api/v1/portfolio/daily-pnl` | 当日盈亏 |
| GET | `/api/v1/portfolio/designs` | 历史 AI 设计方案列表 |
| GET | `/api/v1/portfolio/designs/{id}` | AI 设计方案详情 |
| POST | `/api/v1/portfolio/design-async` | 提交异步组合设计 |
| POST | `/api/v1/portfolio/apply-design` | 应用 AI 设计方案 |
| POST | `/api/v1/portfolio/strategy-check-async` | 提交异步策略检查 |
| GET | `/api/v1/news/headlines` | 财新头条 |
| GET | `/api/v1/news/macro` | 宏观政策 |
| GET | `/api/v1/news/global` | 国际市场 |
| POST | `/api/v1/analysis/portfolio-design` | AI 组合设计 |
| POST | `/api/v1/analysis/llm-report` | LLM 市场报告 |
| POST | `/api/v1/analysis/llm-advice` | LLM 投资建议 |
| GET | `/api/v1/admin/token-usage` | Token 用量汇总 |
| GET | `/api/v1/admin/token-usage/timeseries` | Token 时序数据 |
| GET | `/api/v1/admin/token-usage/failures` | 最近 LLM 失败记录 |
| GET | `/health` | 健康检查（`{"status":"ok"}`） |

### WebSocket 端点

| 路径 | 说明 |
|---|---|
| `WS /ws/market/{symbol}` | 实时行情流推送 |
| `WS /ws/news` | 资讯更新推送 |
| `WS /ws/portfolio` | 组合变更推送 |
| `WS /ws/task-notifications` | 后台任务进度推送 |
| `WS /ws/design-report/{session_id}` | 设计报告流式传输 |

---

## 测试

项目遵循 **TDD 工作流**，分层测试策略：

```bash
# 后端单测（pytest，mock 外部调用）
cd backend && python -m pytest

# 前端单测（vitest + jsdom）
cd frontend && npm test

# E2E 链路验证（需后端已启动）
cd backend && python scripts/verify_e2e.py

# 前端构建检查
cd frontend && npm run build

# E2E 测试（Playwright）
cd frontend && npm run test:e2e:smoke
```

**测试原则：**
- 外部网络 / LLM（akshare、DeepSeek、yfinance 等）在单测中**必须 mock**
- `verify_e2e.py` 检查链路：健康检查 → 行情数据 → 组合设计 → 资讯 → WebSocket → 管理端点
- `api-contracts/` 中的 API 契约确保前后端对齐

---

## 开发规范

- **契约先行**：新功能先在 `api-contracts/` 撰写 API 契约，再实现前后端。
- **每次 commit 前运行 `verify_e2e.py`**，确认核心链路完整。
- **红涨绿跌**：前端遵循国内习惯——涨/盈为红色，跌/亏为绿色。
- **ETF 权重**：以小数存储（`0.3` = 30%），API 传入/返回为小数，前端展示为百分比。
- **akshare 编码**：列名可能为 latin1 乱码，`_decode_df()` 自动处理。
- **权重不归一化**：`target_amount = total_capital * target_weight`，现金为剩余部分。

---

## 备注

- **数据持久化**：组合数据存 SQLite（`data/portfolio.db`），Docker 下通过 `./data` 卷挂载，容器重建不丢数据。
- **PWA**：前端支持渐进式 Web 应用安装，带 Service Worker 缓存。
- **免责声明**：本软件仅供教育与研究用途，不构成投资建议。

## 许可证

MIT License — 详见 [LICENSE](LICENSE)
