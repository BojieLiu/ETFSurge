# ETF Surge（ETF 破浪者）

> English version：[README.md](./README.md)

多资产实时行情分析与 ETF 组合管理系统，覆盖 **A 股、港股、美股、黄金、原油、白银** 六类资产。它诞生的目的是让 AI 辅助投资决策更快、更可靠、可审计——内置 AI 组合设计、实时因子模型与 LLM 投资分析，行情数据层全部基于免费数据源。

后端 FastAPI（async）+ 前端 Vue 3（Pinia + ECharts）。数据通过 REST、WebSocket、SSE 三条通道流动；行情缓存 5–15s、板块缓存每 60s、市态/情绪/资讯每 120s 刷新。

---

## 这个系统为什么存在

起点是一个人工问题：没有人能盯得住整个市场。靠人工跟踪每类资产、每个板块、每天的资讯，既慢又主观，视野天然狭窄——分析会偏向你本来就相信的东西，漏掉你没在看的，而且总是迟到。这个系统就是为了补上这个缺口：它收集数据、跑分析，覆盖全市场的广度和速度，是人做不到的。

最直接的捷径——直接问 AI 聊天工具——解决了覆盖面问题，却又带来五个新的硬伤：

1. **数据延迟**：模型可以接知识库和联网搜索补一些时效信息，但检索到的数据通常已经过了几个小时甚至几天——而它自己并不知道这份数据已过期。它可能把日期说错，甚至自信地分析「未来某个时刻」的行情，而那个时刻根本还没发生。实时报价、盘中情绪、当日资讯，恰恰是聊天工具最不擅长的。
2. **幻觉严重**：LLM 会自信地编造不存在的数字、标的和「趋势」。在投资决策里，一个编出来的数字比没有数字更糟。
3. **风格漂移**：同一个问题问两遍，回答的结构、侧重、语气都不一样。靠每次都在变形的答案，搭不起可重复的决策流程。
4. **不可重复**：同样的输入应当产出同样的组合。聊天模型做不到。
5. **不可审计**：决策出了问题，你要能说清为什么——哪个因子、哪条数据源、哪个假设。聊天记录给不了答案。

ETF Surge 是为了正面解决这五个问题而存在的，而不是「又一个 AI 工具」。这个仓库里的工程取舍，全部从这五个痛点倒推而来：

- **把 LLM 锚定在实时数据上**。每份分析都基于请求当下抓取的真实数据——行情、K 线、指标、因子分。模型写的是它真正「看到」的数据，而不是凭空发挥。
- **关键路径必须确定性**。组合分配由零 I/O 的纯函数引擎计算：同样的输入永远得到同样的输出。LLM 的叙述只是引擎结果的装饰，绝不是事实来源。
- **因子模型带统计检验**。38 个活跃因子配逐日 IC 跟踪，给分析一个事实骨架；因子是否显著是统计问题，不是模型的断言。
- **一切可审计**。设计方案持久化、因子分落盘、token 用量有日志、数据源健康被监控。你随时能还原「这个组合为什么长这样」。

而因为整个系统跑在免费数据源上，底下还有一个硬约束：**数据层必须扛得住不靠谱的提供商**。akshare、新浪、腾讯、东财、财联社、mootdx——每个源大部分时间可用，又各自以不同方式失灵。所以每类资产都有一条熔断路由背后的降级链；空结果记为「未命中」而非「失败」；所有源都不可用时，接口明说，而不是返回过期或伪造数据。一个帮你做投资决策的系统，绝不能悄悄给你坏数据。

这套容灾工程占了仓库的大半——不是因为它光鲜，而是因为它决定了这是「demo」还是「你真的敢拿来下决策的工具」。

---

## 功能特性

### 行情数据

- **六类资产**——A 股、港股、美股、黄金、原油、白银：实时行情、历史 K 线、技术指标（MA / MACD / RSI / KDJ / BOLL / ATR / VWAP）、多指标聚合的买卖信号。
- **自选列表**带实时增强：逐项降级、非交易时段回落 T-1 收盘快照，并统一为 **7 字段 realtime 契约**（`price / change_pct / volume / as_of / is_estimated / estimate_source / data_source`），前端永远不用猜字段含义。
- **板块与概念看板**：轮动、热度排名、热门板块（A/港股）、热门个股——全部按市场 tab 区分。
- **统一搜索**覆盖标的 / 板块 / 指数，多级降级（instruments 表 → levistock → 静态 A 股底座 → ETF 列表）。
- **场外基金净值**、**基本面数据**（PE/PB、主力资金流）覆盖 A 股与美股指数。

### AI 组合设计

- `POST /portfolio/design-async` 基于实时因子分生成**三档风险画像的 ETF 组合**（防守 / 平衡 / 进攻）。
- **策略引擎**（`app/engine/`）是纯函数包：分配、层预算、入选理由、风控、综合信号、相关性、池平衡——零 I/O，CI 用 AST 门禁强制校验纯度。
- 每档策略三层结构、每档有预算表，风控约束（单只 ≤ 30%、行业集中度 < 40%、相关性上限）。
- 异步流水线：数据 + 引擎先行 → `quick_ready`（LLM 报告完成前先把方案推给用户）→ LLM 报告 → 通知。数据退化时走**静态降级方案**，而不是凭空编造一个。
- **一致性校验**：LLM 不得引入候选池之外的 ETF——违规会追加修正脚注，而不是静默接受。

### 因子模型

- **193 个因子定义**（`factor_definitions.yaml`），**38 个已接入真实计算**，覆盖 9 大类（技术、风格、情绪、另类、主题、微观结构、ETF 特有、中国特有、宏观）。
- **逐日 IC 跟踪**——Spearman 秩相关 + Newey–West 标准误；因子需积累 ≥ 250 个交易日且 t 统计量 ≥ 2、|IR| ≥ 0.5 才判定「显著」。
- IC 历史启动时回填、落盘 SQLite，`/factors/active` 按因子暴露均值 IC、IR、t 统计量、零值占比与状态。

### LLM 分析套件

- **市场研判报告**（`/analysis/llm-report/stream`）、**AI 投资顾问问答**（`/analysis/llm-advice/stream`）、**标的 / 板块深度解读**（`/analysis/symbol-analysis/stream`、`/sector-analysis/stream`）、**资讯影响分析**。
- 四个分析端点均为 **SSE 流式**：首字节立即发出、重 I/O 后置，客户端先看到进度而不是沉默。
- **提供商故障切换**：OpenCode Zen 主用、DeepSeek 兜底，各自独立超时。

### 可观测性

- **Token 用量监控**——按功能聚合的 LLM token 消耗、时/日/月时间序列、失败日志（内存环形缓冲 + 落盘 SQLite）。
- **数据源监控**——每个数据源的健康状态、事件时间线、熔断器状态、连接池与线程池指标。
- **因子模型视图**——各因子 IC 统计、分类覆盖度、显著性状态。
- **运行时配置编辑器**——页面里改 API key 即时生效，无需重启（DB 覆盖层叠在 `.env` 之上）。
- **预热状态**端点 + 每 120s 对所有数据源做健康探针。

---

## 系统架构

```
 浏览器 (Vue 3 · Pinia · ECharts · PWA)
 首页 / 行情分析 / 组合分析 / 资讯 / Token 监控 / 数据源监控 / 配置
        │   REST (/api/v1) + WebSocket (/api/v1/ws) + SSE (/analysis/*/stream)
        ▼
 ┌───────────────────────────────────────────────┐
 │ FastAPI (async)                                │
 │ lifespan: 预热序列 · 后台循环                    │
 │   板块 60s · 市态+情绪 120s · 资讯 120s         │
 │   IC 落盘 120s · 健康探针 120s                  │
 │ 路由: market portfolio analysis news           │
 │      factors admin system ws                   │
 └───────────────┬───────────────────────────────┘
                 │
 ┌───────────────▼───────────────────────────────┐
 │ tasks (异步任务)                                │
 │ task_manager · design_pipeline (quick_ready)   │
 │ strategy_check_worker · design_report          │
 │ market_refresh · news_refresh · sector_refresh │
 └───────────────┬───────────────────────────────┘
                 │
 ┌───────────────▼───────────────────────────────┐
 │ services (编排层)                               │
 │ market_data_hub (mixin 包) · strategy_design · │
 │ market_service · portfolio 包 · llm_context ·  │
 │ market_trends · etf_classifier                 │
 └───────────────┬───────────────────────────────┘
                 │ 纯调用, 无 I/O
 ┌───────────────▼───────────────────────────────┐
 │ engine/ (纯函数 · AST 纯度门禁)                 │
 │ allocation_engine · budgets · composite_signal │
 │ correlation · pool_balancing · rationale ·     │
 │ risk_controls                                  │
 └───────────────┬───────────────────────────────┘
                 │ 因子分
 ┌───────────────▼───────────────────────────────┐
 │ factors/ · fetchers/                           │
 │ factor_registry (38 已接入 / 193 定义)          │
 │ ic_tracker (Spearman IC · Newey-West)          │
 │ SourceRegistry (熔断路由 + 优先级)              │
 │ china_market · global_markets · etf_scanner    │
 │ sector · news · fundamentals · fund · macro    │
 └───────┬──────────────────┬──────────────┬──────┘
         │                  │              │
 ┌───────▼──────┐  ┌────────▼───────┐  ┌────▼────────────┐
 │ L1 内存缓存   │  │ L2 Redis       │  │ SQLite          │
 │ (TTL, 常驻)  │◄►│ (可选, 自动降级)│  │ portfolio.db    │
 └──────────────┘  └────────────────┘  │ token_usage.db  │
                                       │ source.db       │
                                       └─────────────────┘
```

### 数据源降级链

每条链都经 `SourceRegistry.route()` 调度——冷却中的源跳过，第一个返回有效数据的源胜出：

| 资产 / 操作 | 降级链 |
|---|---|
| A 股实时（单只） | mootdx → 腾讯 → 新浪 → TickFlow |
| A 股实时（批量） | mootdx → 腾讯 → 新浪 |
| 港股实时 | 新浪 → 腾讯 → 东财 → TickFlow |
| A 股日 K 线 | 个股: mootdx → 新浪 → 网易 · ETF: 新浪 → 网易 → BaoStock → TickFlow |
| A 股分钟 K 线（15m/30m/1h/4h） | 新浪 → akshare 东财 |
| A 股指数 | 新浪(s_sh) → mootdx → 腾讯 |
| ETF 全量扫描 | 新浪 + 腾讯 → 东财（push2 → push2delay）→ akshare spot |
| 美股实时 | TwelveData → Finnhub |
| 港股 / 美股历史 | 腾讯（港股）→ akshare → Finnhub → AlphaVantage |
| 板块 / 概念 | 财联社 → akshare |
| 基金净值 / 场外 | akshare（东财） |

### 关键设计

1. **熔断器 + 「未命中 ≠ 失败」规则**——`SourceRegistry` 为每个数据源维护失败计数与冷却时长。连续失败（≥ 3 次、任意 HTTP 4xx/5xx、或 < 500ms 快速失败）即进入冷却，退避上限 600s。空结果记为未命中，单只标的查不到不会连累健康源。
2. **纯函数策略引擎**——`engine/` 零 I/O、零外部依赖，由 `scripts/check_engine_purity.py` 强制。确定性分配意味着引擎单测不需要 mock 任何东西。
3. **两级缓存 + 优雅降级**——L1 进程内 `MemoryCache`（始终可用）+ L2 `RedisCache`（跨进程，连不上自动降级为 no-op）。**没有 Redis 也能完整运行**。
4. **LLM 故障切换 + 一致性护栏**——OpenCode Zen 主用 / DeepSeek 兜底；`_validate_report_consistency()` 发现候选池外标的时追加修正脚注，而非接受。
5. **异步任务流水线 + 部分结果**——设计任务先写方案到 DB（`quick_ready`），再跑慢速 LLM 报告，用户几秒内看到策略结果，不必等 60s+ 的报告。
6. **交易日历**——`market_calendar.py` 识别 A 股 / 港股 / 美股交易时段。非交易时段返回净值估算或最近收盘价，`estimate_source` 字段告诉前端现在看到的是什么。
7. **诚实降级**——数据不可用时接口明说（精度降级、`data_available=false`、`estimate_source=...`）。前端对加载 / 空 / 错误 / 慢四种状态都有独立 UI。
8. **性能是约束不是事后**——120s 后台循环保持热点路径温热；指数与 K 线 24h 磁盘 last-ok 缓存削减启动期网络调用；SSE 首字节即时发出。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · httpx · asyncio 后台循环 |
| 数据源 | mootdx · 新浪 · 腾讯 · akshare · 网易 · 东财 · TickFlow · BaoStock · 财联社(CLS) · TwelveData · Finnhub · AlphaVantage · multpl · Yahoo（美股指数 PE/PB） |
| 缓存 | 进程内 MemoryCache（默认）+ 可选 Redis（自动降级） |
| 数据库 | SQLite via aiosqlite（`portfolio.db` + `token_usage.db` + `source.db`），数据层已抽象 |
| LLM | OpenCode Zen（主用）· DeepSeek（兜底）——OpenAI 兼容协议 |
| 前端 | Vue 3.5 · Vite 5 · Vue Router · Pinia · ECharts (vue-echarts) · axios · marked |
| 测试 | pytest (async) · vitest + jsdom · @vue/test-utils · Playwright (E2E) |
| 部署 | Docker / docker-compose（dev / prod 双 profile）· nginx（prod）· PWA |

---

## 目录结构

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan（预热 + 后台循环）
│   │   ├── config.py            # pydantic-settings（.env）
│   │   ├── database.py          # 异步 SQLAlchemy / SQLite
│   │   ├── models/              # ORM 模型 + Pydantic schemas
│   │   ├── fetchers/            # 数据源模块（各自带降级链）
│   │   │   ├── china_market.py      # A/港行情、K 线、指数
│   │   │   ├── global_markets_fetcher.py  # 美股/港股（TwelveData/Finnhub/AlphaVantage）
│   │   │   ├── etf_scanner.py       # ETF 全量扫描管道
│   │   │   ├── sector_fetcher.py · levistock_fetcher.py · news_fetcher.py
│   │   │   ├── fundamentals_fetcher.py · fund_fetcher.py · macro_fetcher.py
│   │   │   ├── hk_hot_fetcher.py · sync_instruments.py · sync_indices*.py
│   │   ├── services/            # 编排层
│   │   │   ├── hub/             # MarketDataHub mixin 包（kline/realtime/sector/news/pool…）
│   │   │   ├── portfolio/       # crud · allocation · pnl · pricing · strategy_check · transfer
│   │   │   ├── market_data_hub.py · strategy_design.py · market_service.py
│   │   │   ├── market_trends.py · llm_context.py · etf_classifier.py
│   │   │   ├── pool_audit.py · instruments_sync.py · indices_meta_sync.py
│   │   │   └── source_health.py     # 健康探针循环
│   │   ├── engine/              # 纯函数策略引擎（无 I/O — AST 门禁强制）
│   │   │   ├── allocation_engine.py · budgets.py · composite_signal.py
│   │   │   ├── correlation.py · pool_balancing.py · rationale.py · risk_controls.py
│   │   ├── factors/             # 因子模型
│   │   │   ├── factor_registry.py     # 38 已接入 / 193 定义
│   │   │   ├── factor_definitions.yaml
│   │   │   └── ic_tracker.py          # Spearman IC · Newey-West
│   │   ├── analysis/            # indicators · signal · llm · provider 故障切换 · 文本管道
│   │   ├── tasks/               # task_manager · design_pipeline · design_report
│   │   │   ├── strategy_check_worker.py · market_refresh.py · news_refresh.py · sector_refresh.py
│   │   ├── routers/             # market portfolio analysis news factors admin system ws
│   │   ├── monitor/             # token_usage · source_events · probes
│   │   └── core/                # source_registry · cache_service · ttl · async_utils
│   │                            # market_calendar · regime · factor_aggregate · fast_json
│   ├── tests/                   # 2400+ pytest 用例（外部调用全部 mock）
│   ├── scripts/                 # patrol.py · verify_e2e.py · data_health_check.py
│   │                            # smoke_startup.py · verify_perf.py · check_routes.py
│   │                            # check_engine_purity.py · audit_async_blocking.py · …
│   ├── requirements.txt · Dockerfile · .env.example
├── frontend/
│   ├── src/
│   │   ├── views/               # Dashboard · MarketAnalysis · ConfigView
│   │   ├── components/          # 40+ 组件（dashboard / design / market / analysis / ui）
│   │   │   ├── PortfolioAnalysis.vue · NewsView.vue · TokenMonitor.vue
│   │   │   ├── SourceMonitor.vue · FactorModelView.vue · GlobalIndicesStrip.vue
│   │   ├── stores/              # Pinia: market · portfolio · task · warmup · toast · loading
│   │   ├── composables/         # useNewsWS · useTaskWS · useLLMStream · useMarketSearch
│   │   ├── api/                 # axios 客户端（/api/v1 基地址）
│   │   ├── router/              # Vue Router 配置
│   │   └── styles/              # theme.css（设计 token · 深色模式 · 红涨绿跌）
│   ├── src/test/                # ~500 vitest 用例 · 16 个 Playwright E2E spec
│   ├── nginx.conf · Dockerfile  # 多阶段构建（dev / prod）
│   └── package.json
├── api-contracts/               # 57 份中英双语 API 契约（前后端对齐）
├── docker-compose.yml           # profiles: dev（热更新）/ prod（烘焙镜像 + nginx）
├── docs/                        # 设计文档 · 优化方案 · 逐轮复盘
├── prompt_eval/                 # LLM Prompt 评估框架
├── data/                        # SQLite 数据文件（Docker volume 挂载）
├── start.ps1 · stop.ps1 · restart.bat
└── AGENTS.md                    # 工程约定（TDD · 反假完成 · …）
```

---

## 快速开始

### 方式一：本地开发（无需 Docker）

```bash
# 1. 后端
cd backend
pip install -r requirements.txt
cp .env.example .env        # 填入 API key（见下方环境变量）
uvicorn app.main:app --reload

# 2. 前端（另开终端 —— Windows 必须用 shell 执行）
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。后端默认 http://localhost:8000 。
> 本地没装 Redis 也能跑：缓存自动降级为进程内内存缓存。

### 方式二：Docker（同一份 compose，profile 切换）

```bash
# 开发态：源码挂载 + 热更新 → http://localhost:5173
docker-compose up --build --profile dev

# 生产态：镜像烘焙 + nginx → http://localhost
docker-compose up --build --profile prod
```

- `dev` 挂载 `./backend` 与 `./frontend`：后端 `uvicorn --reload`，前端 Vite dev server，改代码即时生效。
- `prod` 打包后端 + Redis + nginx（前端构建产物），`/api`、`/ws` 由 nginx 反代到后端。
- `dev` 模式依赖 `backend/.env` 已存在；Vite 的 `/api`、`/ws` 代理在容器内指向 `backend-dev`，本地开发回落 `localhost:8000`。

---

## 环境变量

`backend/.env`（可参考 `.env.example`）：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | 数据库连接（同时推导 `DATA_DIR` 用于缓存落盘） | `sqlite+aiosqlite:///{DATA_DIR}/portfolio.db` |
| `REDIS_URL` | Redis 连接（连不上则降级内存缓存） | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | 允许的前端源，逗号分隔 | `http://localhost:5173,http://127.0.0.1:5173` |
| `DEEPSEEK_API_KEY` | DeepSeek key（LLM 兜底） | 空 |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen key（LLM 主用） | 空 |
| `FINNHUB_API_KEY` / `TWELVEDATA_API_KEY` / `ALPHAVANTAGE_API_KEY` / `TUSHARE_TOKEN` / `FRED_API_KEY` | 可选数据源 key | 空 |
| `LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` | LLM 提供商切换顺序 | `opencode_zen` / `deepseek` |
| `LLM_MODEL` | LLM 模型名 | `deepseek-v4-flash` |
| `WARMUP_BUDGET_S` | 启动预热预算 | `30` |
| `ETF_FAST_JSON` | demjson shim（akshare CPU 热点修复），默认开启 | `1` |

---

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/market/realtime` · `/realtime/{symbol}` | 全资产 / 单资产行情 |
| GET | `/api/v1/market/realtime/batch` | 批量行情（A/港/美并行） |
| GET | `/api/v1/market/realtime/portfolio` | 组合实时行情 |
| GET | `/api/v1/market/history/{symbol}` · `/chart/{symbol}` | 历史 K 线 · 图表序列 |
| GET | `/api/v1/market/indicators/{symbol}` · `/signal/{symbol}` | 技术指标 · 综合信号 |
| GET | `/api/v1/market/search` | 标的 / 板块 / 指数统一搜索 |
| GET | `/api/v1/market/indices/global` | 全球指数（按区域分组） |
| GET | `/api/v1/market/sectors/industry` · `/concept` · `/rotation` · `/heat` | 板块看板 |
| GET | `/api/v1/market/hot-plates` · `/stock-hot-rank` | 热门板块 / 热门个股（A/港股） |
| GET/POST/PUT/DELETE | `/api/v1/market/watchlist` | 自选列表 CRUD |
| GET/POST | `/api/v1/portfolio/etfs` | 持仓 CRUD |
| POST | `/api/v1/portfolio/calculate` · `/daily-pnl` | 仓位计算 · 当日盈亏 |
| GET | `/api/v1/portfolio/pnl-history` · `/drift-check` · `/timeline` | 累计盈亏 · 偏离检查 · 操作时间线 |
| GET/POST | `/api/v1/portfolio/export` · `/import` | CSV 导出 / 导入 |
| POST | `/api/v1/portfolio/design-async` · `/strategy-check-async` | 异步组合设计 / 策略检查 |
| GET | `/api/v1/portfolio/designs` · `/designs/{id}` · `/tasks` · `/strategy-checks` | 历史 + 任务状态 |
| POST | `/api/v1/portfolio/apply-design` | 应用 AI 设计方案 |
| POST | `/api/v1/analysis/llm-report/stream` · `/llm-advice/stream` | SSE：市场报告 · 顾问问答 |
| POST | `/api/v1/analysis/symbol-analysis/stream` · `/sector-analysis/stream` | SSE：标的 / 板块深度解读 |
| POST | `/api/v1/analysis/news-impact` | 资讯对组合的影响分析 |
| GET | `/api/v1/news/headlines` · `/macro` · `/global` · `/stock/{symbol}` · `/research/{symbol}` | 资讯源 |
| GET | `/api/v1/factors/model` · `/active` | 因子模型概览 · 活跃因子（含 IC） |
| GET | `/api/v1/admin/token-usage*` | LLM token 用量（汇总 / 时序 / 失败） |
| GET | `/api/v1/admin/sources/*` | 数据源健康 / 事件 / 熔断器 |
| GET/PUT/DELETE | `/api/v1/admin/config` | 运行时配置（API key 等） |
| GET | `/api/v1/admin/factor-health` · `/metrics` · `/llm/health` | 健康与指标 |
| GET | `/api/v1/system/warmup` | 启动预热状态 |
| GET | `/health` | 存活检查（`{"status":"ok"}`） |

### WebSocket 端点

| 路径 | 说明 |
|---|---|
| `WS /api/v1/ws/market/{symbol}` | 实时行情流 |
| `WS /api/v1/ws/news` | 资讯推送（连接即推快照） |
| `WS /api/v1/ws/portfolio` | 组合变更 / 实时广播 |
| `WS /api/v1/ws/task-notifications` | 后台任务进度 |
| `WS /api/v1/ws/design-report/{session_id}` | 设计报告流式推送 |

---

## 测试与质量保障

项目采用 **TDD 工作流** + 分层测试策略，且这套策略本身就有门禁：

```bash
# 全量巡检（L1 单测 → L5 前端）——日常开发循环入口
cd backend && python scripts/patrol.py --diff

# 后端单测（pytest，外部调用全部 mock）
cd backend && python -m pytest

# 前端单测（vitest + jsdom）
cd frontend && npm test

# E2E 链路验证（需后端已启动）
cd backend && python scripts/verify_e2e.py

# 前端构建检查
cd frontend && npm run build

# Playwright E2E
cd frontend && npm run test:e2e:smoke
```

**规模**：后端 ~2400 个 pytest 用例 · 前端 ~500 个 vitest 用例 · 16 个 Playwright E2E spec · 57 份 API 契约文件。

**工程门禁**（由 `.githooks/pre-commit` 或 `patrol.py` 强制执行）：
- `check_engine_purity.py`——AST 门禁：`engine/` 不得 import services/fetchers/tasks，不得使用 I/O。
- `audit_async_blocking.py`——AST 门禁：`async def` 内不得出现同步 I/O（必须走 `run_sync` / `to_thread`）。
- `check_routes.py`——每个注册路由必须存在于 `api-contracts/` 契约中。
- `audit_unused_symbols.py`——死代码审计，带冻结基线（只拦**新增**死符号）。
- `check_api_usage.py`——前端不得存在「定义了但从不调用」的 API 方法。
- `data_health_check.py`——数据管道健康（数据源可达性、因子方差、候选池深度）。
- `verify_perf.py`——性能软门禁（自选 ≤ 3s、搜索 ≤ 1s、factor-health ≤ 2s）。

**测试原则**：外部网络 / LLM 调用在单测中必须 mock；`verify_e2e.py` 断言真实值（不只是 HTTP 200 / 非空）；性能检查是软门禁——如实记录已知性能债，不阻塞功能交付。

---

## 开发规范

- **契约先行**：每个新功能先在 `api-contracts/` 写中英双语契约，再让前后端对照实现。
- **反假完成机制**：功能交付 = 测试绿 + 现实证真双证——真实调用点、真实数据路径、四态 UI（加载 / 空 / 错误 / 慢）都齐全才算完成。
- **红涨绿跌**——前端遵循国内习惯，token 定义在 `theme.css`。
- **权重是小数**（`0.3` = 30%），**不做归一化**——`target_amount = total_capital × target_weight`，现金为剩余部分。
- **akshare 编码**——列名可能为 latin1 乱码，`_decode_df()` 自动处理。
- **`async def` ≠ 非阻塞**——async 函数内的同步 I/O 必须经 `run_sync` / `run_in_thread` 提交线程池。

---

## 已知局限

如实说明当前边界（详见 `docs/`）：

- **免费数据源天然不稳定。** 东财 `push2` 限流、akshare 冷却窗口、DeepSeek 高峰超时——降级链与熔断器能吸收大部分影响，持续故障期间部分端点返回明确的 `数据源不可用` 降级，而非过期或假数据。
- **因子覆盖仍在积累。** 193 个定义中 38 个已接入计算；多数活跃因子需要 ≥ 250 个交易日的 IC 历史才能达到「显著」，早期统计显示 `no_data / 积累中` 是设计行为而非缺陷。
- **美股指数 PE/PB** 依赖 multpl / Yahoo 免费数据，数据源不可达时可能为 `None`。
- **港股 / 美股个股搜索**依赖 instruments 同步完成；受限容器环境中 A 股个股段可能超时（静态 A 股底座覆盖常见场景）。
- **SSE 是单向的**——仅服务端 → 客户端。适合流式分析，不是聊天传输通道。
- **单节点部署**——SQLite 适合单实例；多用户 / 水平扩展需要 PostgreSQL 与消息中间件。

---

## 许可证

MIT License —— 详见 [LICENSE](./LICENSE)
