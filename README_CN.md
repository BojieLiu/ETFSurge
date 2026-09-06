# ETF Surge（ETF 破浪者）

> English: [README.md](./README.md)

一个多资产实时行情分析与 ETF 组合管理平台，覆盖 **A 股、港股、美股、黄金、原油、白银** 六大市场。
它想解决的问题是：让 AI 辅助投资变得**快、可靠、可审计**——AI 组合设计师、实时因子模型、LLM 市场分析三位一体，
而整个行情数据层全部构建在免费数据源之上。

后端 FastAPI（async），前端 Vue 3（Pinia + ECharts）。REST、WebSocket、SSE 三种通道并存。
行情按市场 5-15s 缓存，板块 60s 刷新，市态/情绪/资讯 120s 刷新。

---

## 这个系统为什么存在

出发点是一个人的困境：**没有人能盯住整个市场**。手动跟踪每个资产类别、每个板块、当天的每条新闻，
既慢又主观，还不可避免地狭窄——分析会偏向你已经相信的东西，错过你没在看的东西，而且总是晚到。
这个系统存在的意义就是填补这个缺口：以任何人都达不到的速度和广度，把全市场的数据采集和初筛分析跑起来。

最直觉的捷径——直接问 AI 聊天机器人——解决了覆盖问题，却制造了五个新问题：

1. **数据延迟。** 知识库和联网搜索给模型的「当下」通常是几小时甚至几天前的，而模型不会告诉你它旧了。
   它可能报错日期，或者自信满满地分析一段「还没发生」的行情。实时价格、盘中情绪、今天的新闻，
   恰恰是聊天工具最不擅长的。
2. **幻觉。** LLM 会自信地编造数字、代码和「趋势」。在投资决策里，一个编造的数字比没有数字更糟。
3. **风格漂移。** 同一个问题问两遍，答案的结构、重点都不一样。你没法在每次都变形的答案上建立可复用的流程。
4. **不可复现。** 相同的输入应该产生相同的组合。聊天模型做不到。
5. **不可审计。** 决策错了，你需要知道为什么：哪个因子、哪个数据源、哪个假设。聊天记录给不了你。

ETF Surge 就是为了正面回答这五个问题，而不是「又一个 AI 工具」。仓库里的每个工程选择都源自它们：

- **让 LLM 踩在实时数据上说话。** 每一次分析都跑在请求时拉取的实时数据层上——行情、K 线、指标、因子分。
  模型写的是它真正「看见」的数据的解读，而不是想象。
- **关键路径确定性。** 组合分配由纯函数引擎计算，零 I/O：相同输入，相同输出，每次如此。
  LLM 的文字是引擎输出的「装修」，永远不是真相来源。
- **因子模型带统计检验。** 38 个实盘因子 + 每日 IC 跟踪，让分析有事实骨架——一个因子有没有用是统计问题，
  不是模型说了算。
- **一切可审计。** 设计方案落库、因子分留痕、token 用量记账、数据源健康监控。组合长成这样，
  你能一路还原「为什么」。

还有一条硬约束压在底层：**全部数据源都是免费的，所以数据层必须扛得住不稳**。akshare、新浪、腾讯、
东财、levistock、mootdx——每一家大部分时间正常、坏起来各有姿势。所以每条数据链路后面都挂着降级链和熔断器；
空结果算「未命中」不算「失败」；所有源都挂时，API 明说「数据源不可用」，绝不端上过期或编造的数字。
一个帮你做投资决策的系统，最不能做的事就是悄悄喂你坏数据。

这些韧性工作占了本仓库的大头——不因为它光鲜，而是因为它是「演示」和「你敢托付决策的工具」之间的差距。

---

## 功能特性

### 行情数据

- **六大资产**——A 股、港股、美股、黄金、原油、白银：实时行情、K 线历史、技术指标
  （MA / MACD / RSI / KDJ / BOLL / ATR / VWAP）、复合买卖信号。
- **自选列表**实时富化：逐标的独立降级，盘后回退 T-1 收盘快照，输出统一的 7 字段实时契约
  （`price / change_pct / volume / as_of / is_estimated / estimate_source / data_source`）——
  前端永远不需要猜一个字段是什么意思。
- **行业/概念板块**：轮动、热度排行、热门板块（A/港）、人气股排行，全部按市场隔离。
- **统一搜索**：标的、板块、指数一个入口，多级降级（instruments 表 → levistock → 静态 A 股基座 → ETF 列表），
  板块/指数模式直连内存缓存与 indices_meta 表（round52 R177 后覆盖红利低波等中证 custom 指数）。
- **场外基金 NAV**；A 股与美股指数的**基本面**（PE / PB、资金流）。

### AI 组合设计

- `POST /portfolio/design-async` 从实时因子分生成**三档风险 ETF 组合**（防御 / 平衡 / 进攻）。
- **策略引擎**（`app/engine/`）是纯函数包：分配、层预算、入选理由、风控、复合信号、相关性、候选池平衡——
  零 I/O，纯度由 CI 里的 AST 门禁强制执行。**分配器的确定性**意味着：同样的行情快照，三套方案每次都一模一样——
  这是「可复现」三个字的工程兑现。
- 每档三层结构、按风险档位的预算表、硬风控（单只 ≤30%、行业集中度 <40%、相关性上限）。
  同指数/同主题标的会被去重（taxonomy 同族表归一），防止「两只中证A500 各配 20%/5%」这类重复敞口。
- 异步管线：数据 + 引擎先行 → `quick_ready`（方案先推给用户，不用等报告）→ LLM 报告 → 通知。
  数据降级时回退到**静态降级方案**而不是编一个。
- **一致性校验**：LLM 无法引入候选池之外的 ETF——越界会被追加修正脚注，而不是默默接受。

### 因子模型

- `factor_definitions.yaml` 定义 **193 个因子**；其中 **38 个有实盘计算函数**，
  覆盖 9 大类（技术 / 风格 / 情绪 / 另类 / 主题 / 微观结构 / ETF 专属 / 中国特色 / 宏观）。
- **每日 IC 跟踪**——IC（信息系数）衡量「因子昨天打的分」与「今天实际涨跌」的相关性：逐日记录，
  用 Spearman 秩相关 + Newey–West 标准误。一个因子要「转正」，需要 ≥250 个交易日的 IC 历史，
  且 t 统计量 ≥2、|IR| ≥0.5——**用统计说话，不用感觉**。
- IC 历史启动时回填、落 SQLite，经 `/factors/active` 按因子暴露（均值 IC、IR、t 值、零值率、状态）。

### LLM 分析套件

- **市场报告**（`/analysis/llm-report/stream`）、**投顾问答**（`/analysis/llm-advice/stream`）、
  **个股/板块深挖**（`/analysis/symbol-analysis/stream`、`/sector-analysis/stream`）、**新闻影响分析**。
- 四个分析端点全部 **SSE 流式**：首个字节立刻发出，重 I/O 后置——用户看到的是进度，而不是沉默。
- **供应商故障转移**：OpenCode Zen 主、DeepSeek 备，各供应商独立超时。

### 可观测性

- **Token 监控**——按函数的 LLM token 用量、时/日/月时间序列、失败日志（内存环落 SQLite）。
- **数据源监控**——每源健康、事件时间线、熔断器状态、连接池与线程池统计。
- **因子模型视图**——逐因子 IC 统计、类别覆盖、显著性状态。
- **运行时配置编辑**——UI 里改 API key 不用重启（DB 覆盖 `.env`）。
- **预热状态**端点 + 每 120s 全数据源健康探测。

### Agentic 层（v7 升级）

LLM 模块从「单次 prompt → 报告」升级为生产级 agent 栈：

- **MCP 工具层**——4 个 stdio MCP server（`quote` / `factor` / `portfolio` / `news`）包装真实生产链路
  （多源降级、38 因子纯函数引擎、异步策略检查管线、资讯桶）。每个工具输出带可追溯信封
  `{data, as_of, source, degraded}`；失败诚实降级，不编数据。任何 MCP 宿主可调
  （`python -m app.mcp_servers.quote_server`），agent 循环也可进程内直调。
- **Plan-and-Execute 循环 + 护栏**——步数预算（10 步，截断 → 部分结果）、分级时间预算
  （策略检查 90s / 设计报告 120s，出自单一模块）、循环检测（同工具同参数两次 → 终止）、
  工具白名单（未注册工具直接 PermissionError）、写确认门（下单/交易类动作必须显式确认）、
  输出 schema 校验（每步输出必须带 `source`——数字必须可溯源）。
- **带 CI 门禁的 Evals**——5 类金标集（报价 / 因子 / 格式合规 / 拒答抗幻觉 / 多步）。
  阻断门禁：总分 ≥95%、拒答零幻觉 100%、格式 100%。`python -m scripts.evals.ci_gate`。
- **Trace + 成本核算**——每次运行落结构化 trace（JSONL + SQLite `agentic_runs` 含单次成本）；
  模型价格表 + 单次 $0.5 预算熔断（`agentic_budget_exceeded` 告警）。

> STAR 一句话：「我把一个实盘组合系统的 LLM 模块加固成了生产级 agent 栈——真实降级链之上的 MCP 工具层、
> 每个数字可溯源的护栏化 Plan-and-Execute 循环、金标集 evals 以 95%+ 门禁卡 CI、单次运行成本追踪。」

---

## 系统架构

```
 浏览器 (Vue 3 · Pinia · ECharts · PWA)
 Dashboard / Market / Portfolio / News / Token / Source / Config
        │   REST (/api/v1) + WebSocket (/api/v1/ws) + SSE (/analysis/*/stream)
        ▼
 ┌───────────────────────────────────────────────┐
 │ FastAPI (async)                                │
 │ lifespan: warmup 序列(7 任务分段计时) · 后台循环 │
 │   sector 60s · regime+sentiment 120s · news    │
 │   120s · IC persistence 120s · health 120s     │
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
 │ agentic/ (v7 升级 · Plan-and-Execute)          │
 │ AgentLoop (步数/时间预算 · 写确认门 ·           │
 │   输出 schema 校验)                            │
 │ Executor (工具白名单 · 循环检测)                │
 │ trace_store (JSONL + SQLite 成本行)            │
 │ cost (模型价格表 · $0.5/run 预算熔断)           │
 └───────────────┬───────────────────────────────┘
                 │ 进程内 MCP handlers
 ┌───────────────▼───────────────────────────────┐
 │ mcp_servers/ (4 stdio servers · MCP SDK 1.x)   │
 │ quote (realtime/bars) · factor (snapshot)      │
 │ portfolio (strategy_check 2-phase)             │
 │ news (financial search)                        │
 │ 每个信封: {data, as_of, source, degraded}      │
 └───────────────┬───────────────────────────────┘
                 │
 ┌───────────────▼───────────────────────────────┐
 │ services (编排层)                              │
 │ market_data_hub (mixin 包) · strategy_design   │
 │ market_service · portfolio 包                  │
 │ llm_context · market_trends · etf_classifier   │
 └───────────────┬───────────────────────────────┘
                 │ 纯调用，无 I/O
 ┌───────────────▼───────────────────────────────┐
 │ engine/ (纯函数 · AST 纯度门禁)                 │
 │ allocation_engine · budgets · composite_signal │
 │ correlation · pool_balancing · rationale ·     │
 │ risk_controls                                  │
 └───────────────┬───────────────────────────────┘
                 │ factor scores
 ┌───────────────▼───────────────────────────────┐
 │ factors/ · fetchers/                           │
 │ factor_registry (38 实装 / 193 定义)           │
 │ ic_tracker (Spearman IC · Newey-West)          │
 │ SourceRegistry (熔断器 + 优先级)               │
 │ china_market · global_markets · etf_scanner    │
 │ sector · news · fundamentals · fund · macro    │
 └───────┬──────────────────┬──────────────┬──────┘
         │                  │              │
 ┌───────▼──────┐  ┌────────▼───────┐  ┌────▼────────────┐
 │ L1 进程内     │  │ L2 Redis       │  │ SQLite          │
 │ MemoryCache  │◄►│ (Docker 默认带, │  │ portfolio.db    │
 │ (TTL, 永可用) │  │  不可达自动降级)│  │ token_usage.db  │
 └──────────────┘  └────────────────┘  │ source.db       │
                                       └─────────────────┘
```

### 数据源降级链

每条链路都走 `SourceRegistry.route()`——冷却中的源被跳过，第一个返回有效数据的源胜出：

| 资产 / 操作 | 降级链 |
|---|---|
| A 股实时（单只） | mootdx → 腾讯 → 新浪 → TickFlow |
| A 股实时（批量） | mootdx → 腾讯 → 新浪 |
| 港股实时 | 新浪 → 腾讯 → 东财 → TickFlow |
| A 股日 K | 个股: mootdx → 新浪 → 网易 · ETF: 新浪 → 网易 → BaoStock → TickFlow |
| A 股分钟 K（15m/30m/1h/4h） | 新浪 → akshare 东财 |
| 中国指数 | 新浪 (s_sh) → mootdx → 腾讯 |
| ETF 全量扫描 | 新浪 + 腾讯 → 东财 (push2 → push2delay) → akshare spot |
| 美股实时 | TwelveData → Finnhub |
| 港/美股历史 | 腾讯 (港) → akshare → Finnhub → AlphaVantage |
| 板块/概念 | levistock → akshare |
| 基金 NAV / 场外 | akshare (东财) |

### 关键设计

1. **熔断器与「未命中 ≠ 失败」规则** —— `SourceRegistry` 给每个源记失败计数和冷却时间。
   连续失败（≥3 次、任意 HTTP 4xx/5xx、或 <500ms 快速失败）进入冷却，指数退避封顶 600s。
   空结果记为*未命中*而非失败——某只代码不存在不会把整个源打入冷宫。**打个比方：熔断器像家里的
   空气开关，跳闸保护电路；但「这盏灯没亮」不等于停电——所以我们区分「没数据」和「源坏了」。**
2. **纯函数策略引擎** —— `engine/` 零 I/O、零外部依赖，由 `scripts/check_engine_purity.py` 用 AST
   静态执法。确定性分配意味着引擎不需要 mock 任何东西就能单测。**就像计算器：按同样的键，
   永远得同样的数——组合分配这一步没有「灵感」，只有算术。**
3. **两级缓存 + 优雅降级** —— L1 进程内 `MemoryCache`（永远可用）+ L2 `RedisCache`（跨进程共享，
   不可达时自动降级为 no-op）。没有 Redis 系统照常全速跑；Docker prod 部署默认带一个 Redis。
4. **LLM 故障转移 + 一致性守卫** —— OpenCode Zen 主 / DeepSeek 备；`_validate_report_consistency()`
   会改写池外 ETF 选择并追加修正脚注，而不是默默接受。
5. **异步任务管线 + 部分结果** —— 设计任务在慢速 LLM 报告完成*之前*就把方案写库（`quick_ready`），
   用户秒级看到策略结果，而不是干等 60s+ 的报告。
6. **市场日历** —— `market_calendar.py` 掌握 A 股/港股/美股的交易时段。盘后返回估算 NAV 或最近收盘，
   而不是把旧价格冒充「实时」，字段 `estimate_source` 告诉前端它看到的是什么。
7. **诚实降级** —— 数据不可用时 API 明说（精度降级、`data_available=false`、`estimate_source=...`）。
   前端把这些状态显式渲染——加载/空/错误/慢各有各的样子。
8. **性能是约束不是装饰** —— 120s 后台循环保持热路径常温；指数与 K 线的 24h last-ok 磁盘缓存
   砍掉启动期的网络调用；SSE 首字节立即发出。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · httpx · asyncio 后台循环 |
| 数据源 | mootdx · 新浪 · 腾讯 · akshare · 网易 · 东财 · TickFlow · BaoStock · levistock (CLS) · TwelveData · Finnhub · AlphaVantage · multpl · Yahoo (美股指数 PE/PB) |
| 缓存 | 进程内 MemoryCache（默认）+ 可选 Redis（自动降级） |
| 数据库 | SQLite via aiosqlite（`portfolio.db` + `token_usage.db` + `source.db`），数据层已抽象。`portfolio.db` 固定 **DELETE journal 模式 + synchronous=FULL**（round38 R139：WAL 在双写者并发下反复 page corruption）——备份用 `sqlite3 portfolio.db "VACUUM INTO 'backup.db'"`，或停写后整文件拷贝 |
| LLM | OpenCode Zen（主）· DeepSeek（备）——OpenAI 兼容 |
| 前端 | Vue 3.5 · Vite 5 · Vue Router · Pinia · ECharts (vue-echarts) · axios · marked |
| 测试 | pytest (async) · vitest + jsdom · @vue/test-utils · Playwright (E2E) |
| 部署 | Docker / docker-compose（profiles: dev / prod）· nginx (prod) · PWA |

---

## 目录结构

```
ETF_Surge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan（warmup 序列 + 后台循环）
│   │   ├── config.py            # pydantic-settings (.env)
│   │   ├── database.py          # async SQLAlchemy / SQLite（DELETE journal + busy_timeout）
│   │   ├── models/              # ORM 模型 + Pydantic schemas
│   │   ├── fetchers/            # 数据源模块（各自带降级链）
│   │   │   ├── china_market.py      # A/港行情、K 线、指数
│   │   │   ├── global_markets_fetcher.py  # 美/港 (TwelveData/Finnhub/AlphaVantage)
│   │   │   ├── etf_scanner.py       # ETF 全量扫描管线
│   │   │   ├── sector_fetcher.py · levistock_fetcher.py · news_fetcher.py
│   │   │   ├── fundamentals_fetcher.py · fund_fetcher.py · macro_fetcher.py
│   │   │   ├── hk_hot_fetcher.py · sync_instruments.py · sync_indices*.py
│   │   ├── services/            # 编排层
│   │   │   ├── hub/             # MarketDataHub mixin 包（kline/realtime/sector/news/pool/...）
│   │   │   ├── portfolio/       # crud · allocation · pnl · pricing · strategy_check · transfer
│   │   │   ├── market_data_hub.py · strategy_design.py · market_service.py
│   │   │   ├── market_trends.py · llm_context.py · etf_classifier.py
│   │   │   ├── pool_audit.py · instruments_sync.py · indices_meta_sync.py
│   │   │   └── source_health.py     # 健康探测循环
│   │   ├── engine/              # 纯函数策略引擎（无 I/O —— AST 执法）
│   │   │   ├── allocation_engine.py · budgets.py · composite_signal.py
│   │   │   ├── correlation.py · pool_balancing.py · rationale.py · risk_controls.py
│   │   ├── factors/             # 因子模型
│   │   │   ├── factor_registry.py     # 38 实装 / 193 定义
│   │   │   ├── factor_definitions.yaml
│   │   │   └── ic_tracker.py          # Spearman IC · Newey-West
│   │   ├── analysis/            # 指标 · 信号 · llm · 供应商故障转移 · 文本管线
│   │   ├── tasks/               # task_manager · design_report · strategy_check_worker
│   │   │   ├── market_refresh.py · news_refresh.py · sector_refresh.py
│   │   ├── routers/             # market portfolio analysis news factors admin system ws
│   │   ├── monitor/             # token_usage · source_events · probes
│   │   ├── agentic/             # v7: agent_loop · executor · trace_store · cost · lg_agent
│   │   ├── mcp_servers/         # 4 个 stdio MCP server（quote/factor/portfolio/news）
│   │   └── core/                # source_registry · cache_service · ttl · async_utils
│   │                            # market_calendar · regime · factor_aggregate · fast_json
│   ├── scripts/evals/           # 金标集(64 条 jsonl) + ci_gate + harness + scorers（v7 evals 框架）
│   ├── tests/                   # 3,100+ pytest 用例（外部调用全 mock）
│   ├── scripts/                 # patrol.py · verify_e2e.py · data_health_check.py
│   │                            # smoke_startup.py · verify_perf.py · check_routes.py
│   │                            # check_engine_purity.py · audit_async_blocking.py · ...
│   ├── requirements.txt · Dockerfile · .env.example
├── frontend/
│   ├── src/
│   │   ├── views/               # Dashboard · MarketAnalysis · PortfolioAnalysis
│   │   │                        # NewsView · AiDesign · ConfigView · system
│   │   ├── components/          # 36 个组件（dashboard / design / market / analysis / ui）
│   │   │   ├── PortfolioAnalysis.vue · NewsView.vue · TokenMonitor.vue
│   │   │   ├── SourceMonitor.vue · FactorModelView.vue · GlobalIndicesStrip.vue
│   │   ├── stores/              # Pinia: market · portfolio · task · warmup · toast · loading
│   │   ├── composables/         # useNewsWS · useTaskWS · useLLMStream · useMarketSearch
│   │   ├── api/                 # axios 客户端（/api/v1 base）
│   │   ├── router/              # Vue Router 配置
│   │   └── styles/              # theme.css（design tokens · 暗色模式 · 红涨绿跌）
│   ├── src/ 下的 *.spec.js      # vitest 用例（组件/工具函数）
│   ├── e2e/                     # 16 个 Playwright E2E specs
│   ├── nginx.conf · Dockerfile  # 多阶段（dev / prod）
│   └── package.json
├── api-contracts/               # 59 份双语 API 契约（前后端对齐）
├── docker-compose.yml           # profiles: dev（热更新）/ prod（烘焙 + nginx）+ diag overlay
├── docs/                        # 设计文档 · 优化方案 · round 复验（archived/ 存已收官轮次）
├── data/                        # SQLite DB（Docker volume 挂载）
├── start.ps1 · stop.ps1 · start.bat · stop.bat · restart.bat
└── AGENTS.md                    # 工程约定（TDD · 反假完成 · commit 规范 · ...）
```

---

## 快速开始

### 方式一：本地开发（无需 Docker）

```bash
# 1. 后端
cd backend
pip install -r requirements.txt
cp .env.example .env        # 填入 API key（见下文）

uvicorn app.main:app --reload

# 2. 前端（另开终端 —— Windows 必须经 shell 执行）
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 。后端在 http://localhost:8000 。
> 没有 Redis？没关系——缓存自动降级到进程内内存。

### 方式二：Docker（同一份 compose，profile 切换）

```bash
# 开发态：源码挂载 + 热更新 → http://localhost:5173
docker-compose up --build --profile dev

# 生产态：镜像烘焙 + nginx → http://localhost
docker-compose up --build --profile prod
```

- `dev` 挂载 `./backend` 和 `./frontend`；后端跑 `uvicorn --reload`，前端跑 Vite dev server，改代码即时生效。
- `prod` 打包 后端 + Redis + nginx（烘焙前端）；`/api` 与 `/ws` 反代到后端。
- `dev` 依赖 `backend/.env` 存在。Vite 的 `/api`、`/ws` 代理容器内指向 `backend-dev`，本地回落 `localhost:8000`。
- 诊断场景另有 `docker-compose.diag.yml` overlay（注入 PROFILE_WARMUP=1 预热画像）。

---

## 环境变量

`backend/.env`（见 `.env.example`）：

| 变量 | 说明 | 默认 |
|---|---|---|
| `DATABASE_URL` | DB 连接（同时推导缓存 `DATA_DIR`） | `sqlite+aiosqlite:///{DATA_DIR}/portfolio.db` |
| `REDIS_URL` | Redis 连接（不可达 → 内存缓存） | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔 | `http://localhost:5173,http://127.0.0.1:5173` |
| `DEEPSEEK_API_KEY` | DeepSeek key（LLM 备用） | 空 |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen key（LLM 主用） | 空 |
| `FINNHUB_API_KEY` / `TWELVEDATA_API_KEY` / `ALPHAVANTAGE_API_KEY` / `TUSHARE_TOKEN` / `FRED_API_KEY` | 可选数据源 key | 空 |
| `LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` | LLM 供应商故障转移顺序 | `opencode_zen` / `deepseek` |
| `LLM_MODEL` | LLM 模型名 | `deepseek-v4-flash` |
| `WARMUP_BUDGET_S` | 启动预热预算 | `30` |
| `ETF_FAST_JSON` | demjson shim（akshare 热点修复），默认开 | `1` |

---

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/market/realtime` · `/realtime/{symbol}` | 全资产 / 单资产行情 |
| GET | `/api/v1/market/realtime/batch` | 批量行情（A/港/美并行） |
| GET | `/api/v1/market/realtime/portfolio` | 组合实时行情 |
| GET | `/api/v1/market/history/{symbol}` · `/chart/{symbol}` | K 线历史 · 图表序列 |
| GET | `/api/v1/market/indicators/{symbol}` · `/signal/{symbol}` | 技术指标 · 复合信号 |
| GET | `/api/v1/market/search` | 标的/板块/指数统一搜索（参数 `keyword` + `kind`） |
| GET | `/api/v1/market/indices/global` | 全球指数（按地区分组） |
| GET | `/api/v1/market/sectors/industry` · `/concept` · `/rotation` · `/heat` | 板块 |
| GET | `/api/v1/market/hot-plates` · `/stock-hot-rank` | 热门板块 / 人气股（A/港） |
| GET/POST/PUT/DELETE | `/api/v1/market/watchlist` | 自选 CRUD |
| GET/POST | `/api/v1/portfolio/etfs` | 持仓 CRUD |
| POST | `/api/v1/portfolio/calculate` · `/daily-pnl` | 仓位计算 · 日盈亏 |
| GET | `/api/v1/portfolio/pnl-history` · `/drift-check` · `/timeline` | 累计盈亏 · 漂移 · 活动 |
| GET/POST | `/api/v1/portfolio/export` · `/import` | CSV 导出/导入 |
| POST | `/api/v1/portfolio/design-async` · `/strategy-check-async` | 异步设计 / 策略检查 |
| GET | `/api/v1/portfolio/designs` · `/designs/{id}` · `/tasks` · `/strategy-checks` | 历史 + 任务状态 |
| POST | `/api/v1/portfolio/apply-design` | 应用 AI 生成的组合 |
| POST | `/api/v1/analysis/llm-report/stream` · `/llm-advice/stream` | SSE：市场报告 · 投顾问答 |
| POST | `/api/v1/analysis/symbol-analysis/stream` · `/sector-analysis/stream` | SSE：个股/板块深挖 |
| POST | `/api/v1/analysis/news-impact` | 新闻对持仓的影响 |
| GET | `/api/v1/news/headlines` · `/all` · `/macro` · `/global` · `/stock/{symbol}` · `/research/{symbol}` | 资讯（`/all` 为三桶聚合视图，round52 R178） |
| GET | `/api/v1/factors/model` · `/active` | 因子模型概览 · 活跃因子含 IC |
| GET | `/api/v1/admin/token-usage*` | LLM token 用量（汇总 / 时序 / 失败） |
| GET | `/api/v1/admin/sources/*` | 数据源健康 / 事件 / 熔断器 |
| GET/PUT/DELETE | `/api/v1/admin/config` | 运行时配置（API key 等） |
| GET | `/api/v1/admin/factor-health` · `/metrics` · `/llm/health` | 健康与指标 |
| GET | `/api/v1/system/warmup` | 启动预热状态 |
| GET | `/health` | 存活（`{"status":"ok"}`） |

### WebSocket 端点

| 路径 | 说明 |
|---|---|
| `WS /api/v1/ws/market/{symbol}` | 实时行情推送（后端在位；当前前端主要消费 portfolio 通道） |
| `WS /api/v1/ws/news` | 资讯推送（连接即推快照） |
| `WS /api/v1/ws/portfolio` | 组合变更广播（`portfolio_changed`） |
| `WS /api/v1/ws/task-notifications` | 后台任务进度 |

> 注意路径带 `/api/v1` 前缀；握手 403 先查前缀。

---

## 测试与质量保障

项目跑 **TDD 工作流**，分层测试策略——并且用门禁强制执行，而不是靠自觉：

```bash
# 全量巡检（L1 单测 → L5 前端）——日常开发循环入口
cd backend && python scripts/patrol.py --diff

# 后端单测（pytest，外部调用全 mock）
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

**规模**：约 3,100 后端 pytest 用例 · 前端 vitest 组件/工具用例 + 16 个 Playwright E2E specs · 59 份 API 契约。

**工程门禁**（由 `.githooks/pre-commit` 或 `patrol.py` 强制执行）：
- `check_engine_purity.py` —— AST 门禁：`engine/` 不得 import services/fetchers/tasks，不得出现 I/O。
- `audit_async_blocking.py` —— AST 门禁：`async def` 内不得出现同步 I/O（必须走 `run_sync` / `to_thread`）。
- `check_routes.py` —— 每个注册路由必须在 `api-contracts/` 有契约。
- `audit_unused_symbols.py` —— 死代码审计（冻结基线，只拦*新增*死符号）。
- `check_api_usage.py` —— 前端不得存在定义了却从不调用的 API 方法。
- `data_health_check.py` —— 数据管道健康（源可达性、因子方差、层深）。
  ⚠️ 检查器结论需与生产口径交叉验证（round53 教训：裸 compute 缺注入曾致 3 轮误报）。
- `verify_perf.py` —— 软性能门禁（watchlist ≤3s、search ≤1s、factor-health ≤2s）。

**测试原则**：外部网络 / LLM 调用在单测中必须 mock；`verify_e2e.py` 断言真实值（不是 HTTP 200 / 非空就算过）；
性能检查是软门禁，登记已知债务而不阻断交付。

---

## 开发约定

- **契约先行**：每个功能从 `api-contracts/` 的双语契约开始，前后端对着实现。
- **反假完成**：功能完成的判定 = 测试绿 *且* 现实核查通过——有真实调用点、真实数据路径、诚实的 UI 四态
  （加载/空/错误/慢各有渲染）。
- **红涨绿跌** —— UI 遵循国内习惯；token 在 `theme.css`。
- **权重是小数**（`0.3` = 30%），永不归一化——`target_amount = total_capital × target_weight`，现金是余数。
- **akshare 编码** —— 列名 latin1 乱码由 `_decode_df()` 归一。
- **`async def` ≠ 非阻塞** —— async 函数内的同步 I/O 必须走 `run_sync` / `to_thread`。
- **Commit message 全英文**（commit-msg 钩子硬拦截中文），格式见 AGENTS.md；提交须经 Git Bash。

---

## 已知局限

诚实评估（细节见 `docs/`）：

- **免费源天然不稳。** 东财 `push2` 限流、akshare 进入冷却、DeepSeek 高负载超时。降级链与熔断器吸收大部分；
  持续故障期间部分端点返回显式「数据源不可用」降级，而不是过期或编造的数据。
- **因子覆盖仍在积累。** 193 个定义因子中 38 个已实装；多数实盘因子需要 ≥250 交易日 IC 历史才能「转正」，
  早期统计显示 `no_data / accumulating` 属设计使然。
- **美股指数 PE/PB** 依赖免费层 multpl / Yahoo quoteSummary，源不可达时可能为 `None`。
- **港/美个股搜索**依赖 instruments 同步完成；受限容器环境 A 股个股段可能超时（静态 A 股基座兜住常见场景）。
- **SSE 单向** —— 仅服务端 → 客户端。流式分析够用；不是聊天通道。
- **单节点部署** —— SQLite 适合单实例；多用户/水平扩展需要 PostgreSQL 和消息队列。

---

## License

MIT License —— 见 [LICENSE](./LICENSE)
