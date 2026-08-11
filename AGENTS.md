# AGENTS.md — ETF Surge

多资产实时行情分析与 ETF 组合管理系统。后端 FastAPI（async）+ 前端 Vue 3。

## 启动命令
> 推荐使用 `restart.bat`（一键重启前后端）或 `start.ps1` 启动、`stop.ps1` 停止。
> 如果手动启动：

### 本地开发（无需 Docker）

```bash
# 后端 (从项目根)
cd backend && uvicorn app.main:app --reload

# 前端 (另开终端) — Windows 必须用 shell 执行
cd frontend && cmd /c "npm run dev"
```

> **Windows 启动前端的坑**：必须用 shell 执行 `npm run dev`（或 `cmd /c npm run dev`）。
> **不要**直接 `node node_modules/.bin/vite` —— 该 bin 是 bash 脚本，Windows 下会报错。

### Docker 部署（同一份 docker-compose.yml，profiles 切换）

```bash
# 开发态：源码挂载 + 热更新，浏览器开 http://localhost:5173
docker-compose up --build --profile dev

# 生产态：镜像烘焙 + nginx，浏览器开 http://localhost
docker-compose up --build --profile prod
```

> 注意：dev 模式依赖 `backend/.env` 已存在（含 DEEPSEEK_API_KEY）。
> Docker 内 Vite 的 `/api`、`/ws` 代理自动指向容器 `backend-dev`；本地开发回落到 `localhost:8000`，无需改配置。

## 测试 / Testing（TDD 工作流）

新增功能遵循「先写失败单测 → 实现 → 补单测 → build + 功能链路验证」。

### E2E 链路验证（每次改完必做）
后端启动后运行，确保核心链路可用：

```bash
cd backend && python scripts/verify_e2e.py
# 输出示例：
#   [PASS] /health -> 200
#   [PASS] dataset 返回 N 条记录
#   [PASS] design_text  已持久化
#   [PASS] market_regime  已判定
```

检查项：服务存活 / 历史列表 / 设计详情 / 行情数据 / AI 设计（3套方案+正确regime）。每次改完代码、commit 前必须跑，确认全 PASS。

### 后端单测

```bash
cd backend && python -m pytest
```
  - 已配置 `pytest.ini` + `conftest.py`（`asyncio_mode = auto`，自动发现 async test）。
  - 专用测试文件：`tests/test_design_optimization_plan.py`（P0-P3、P0.5、UX3 共 7 个用例）。
  - 外部网络 / LLM（akshare、DeepSeek、yfinance 等）在单测中 **必须 mock**，不依赖真实 DB / 网络。
- **前端**：`cd frontend && npm test`（即 `npx vitest run`）
  - 已配置 `vitest.config.js` + `src/test/setup.js`（jsdom 环境）。
  - 组件测试用 `@vue/test-utils`。
- **链路验证**：后端用 `verify_e2e.py`；前端用 `npm run build` + 浏览器走查关键页面。
- **pre-commit 门禁**：`.githooks/pre-commit` 会执行密钥扫描 / check_routes / 前端 build / mypy / audit_async_blocking / pytest / smoke_startup 等检查（跳过方式见各段注释）。
  - **pytest 全量用 `-n auto` 并行**（pytest-xdist，xdist 缺失自动回退串行）；仅测试文件变更时只跑变更文件。
  - **smoke_startup 用 `SMOKE_FAST=1` 快速模式**：子进程设 `ETF_SURGE_SKIP_WARMUP=1` 跳过后台预热任务及其等待，并跳过 `/calculate` 懒加载（由 `verify_e2e.py` 覆盖）；完整模式 `python scripts/smoke_startup.py` 行为不变。
  - 前端 build 仅当 `frontend/src/*`、`index.html`、`vite.config.js`、`package.json` 变更时触发（`frontend/public/` 静态资源不触发）。
  - docker build 冒烟在 Docker daemon 不可用（Docker Desktop 未启动）时视为环境跳过，真实构建失败仍拦截。
  - **门禁治理约定（2026-08-09）**：新增门禁须说明与现有 13 段的差异化价值；死代码审计保留 3 个（check_api_usage / audit_unused_symbols / check_unused_styles，对象互不相同）不再新增同类；P3-6 测试文件基线为**提示不阻断**。
  - 跳过构建：`SKIP_FRONTEND_BUILD=1 git commit`。

## 会话记忆惯例（每轮结束必做，强制）

**目的**：避免每个新会话全量重读 docs/round*.md（几十万 token/轮），改用 `remember` 背景事实承接上下轮状态。

- **每轮（round/诊断/实施批次）结束时**，用 `remember` 写/更新一条 project 事实：
  - `name` 用轮次标识（如 `round10-容器复诊断完成-2026-08-08.md`），**更新用同 name 覆盖**（revision 递增），勿新建重复条目；
  - 正文含：**结果一句话 + 关键 commit + 验收口径 + How to apply 指针**（对照既有 round 事实格式）；
  - `description` 用可检索的一句话（将在下一会话自动召回注入）。
- **状态变化的轮次**更新既有事实而非新建；**已过时/矛盾的旧事实**用 `forget` 归档（避免召回冲突浪费额度）。
- 大段正文（方案细节）留在 docs/**（审计数据源），memory 只存结论/commit/指针。
- 会话开始时如需了解上轮进度：**先 memory search/read**（只读、有预算）而不是直接 read_file 全量。
- 重要长期规则（非「某轮状态」）放 AGENTS.md，勿放 memory（文档是常驻、memory 是有预算召回）。

## 反假完成机制（功能交付必做，强制）

**背景**：AI 快速实现易产生「测试绿但功能假」——只做脚手架、mock 跑通冒充完成、改了不被人调用的路径、测试验 `200/非空` 不验内容。下列检查在**每个功能交付**（DONE 之前）必做，测试绿**不足**以声明完成。

- **DoD = 测试绿 + 现实证真（reality check）双证**，缺一不可：
  1. **真实链路实证**：新端点/函数必须 `grep` 确认**有真实调用点**（前端调用 / 其它模块 import / 定时任务），非仅测试引用；0 引用 = 脚手架，**不得默认留存**——要接通或进「待删/待接通」清单；
  2. **非兜底数据**：功能输出**不得只有 fallback/默认值/硬编码**——验证真实数据源路径被走到（如 fetch_history 非空、真实行情值出现），mock 只在单测、不冒充实现；
  3. **内容正确性**：端点验证从「HTTP 200/非空」升级为**内容断言**（关键字段真实值、无「暂无数据」占位冒充成功）；
  4. **引用完整性**：改动后 `rg` 确认旧调用点同步（防改了一半留断裂）；
  5. **视觉/交互自检**（前端）：四态（loading/空/错误/慢数据）都有 UI；非空白/旧值冒充加载完成；用主题 token 非内联硬编码。
- **脚手架零容忍**：新增「未接入生产」的代码（死端点/死组件/未调用函数）**不允许静默留存**——要么接通、要么标 deleted/dead 进清理清单（round11 P0-3 教训倒转使用）。
- **测试要能「抓假」**：新功能测试应包含**能失败的负向断言**（如「全兜底时不得报 N/M 正常」「无 realtime 时前端有加载态」），不是恒绿的宽松断言。
- 每轮收尾：跑**reality check 清单**（下表）与全量测试并列，两者都过才算 round 完成。

| Check | 怎么验 | 假完成的信号 |
|---|---|---|
| 真实调用 | `rg` 调用点（前端/路由/任务/其它模块） | 0 调用 = 脚手架 |
| 非兜底 | 日志/响应抓真实值（非 fetch 空/mock/0） | 全默认/全"暂无" = 假实现 |
| 内容非空 | 断言关键字段**实际值**（非 len>0） | 只验 200/非空 = 空壳 |
| 引用同步 | 改动后 `rg` 旧名 | 旧名残留 = 改一半 |
| 交互四态 | 前端走查 loading/空/错/慢 | 空白/旧值冒充 = 假完成 |

## 性能验收（软门禁，不阻塞功能交付）

**目的**：性能差是 AI 代码高发问题（watchlist 曾 29.9s、factor-health 10.9s、首页 perf 52）。但性能优化**不应阻塞功能正确与需求迭代**——本项为**软门禁**：交付时必测、超阈值必记录并在后续轮次排期优化，**不硬性阻断 DONE**。

- **软 vs 硬**：性能检查**不产生 FAIL 阻断**（区别于反假完成的硬门槛）；满足「功能正确 + 需求完整」即 DONE，性能问题进入「已知性能债」清单。
- **必做（软）**：
  1. **关键路径耗时自测**：改动涉及到 watchlist / search / design / factor-health / symbol-analysis 等热点路径时，交付前量一次耗时（`time curl` 或 verify_e2e 已有 timer），对照基线记录到提交说明/issue；
  2. **复杂度审计**：新增网络/DB/文件调用必须`asyncio.wait_for`/超时参数或批量/缓存——**无超时的外部调用是"空转源"**（mootdx 8s 空转教训）；循环内 IO 需批量化或缓存；
  3. **不静默降级**：慢路径**不得用假数据/半真值兜底冒充正常**（属上节反假完成）；性能不足时**诚实地标注**（如「数据源慢，已降级」而非伪造值）。
- **记录机制**：每轮交付在 memory/文档里记「已知性能债」清单（路径 + 实测耗时 + 阈值），后续轮次按优先级排期优化——**不拖慢当前需求，但问题不消失**。
- **优先阈值参考**（仅登记基准，不阻塞）：watchlist ≤3s、搜索 ≤1s、factor-health ≤2s、首页 perf ≥60 / CLS <0.1（基线环境固定统一测量）。

## 关键路径

按目录定位代码，函数签名级细节用符号索引/LSP 查：

- `backend/app/main.py` — FastAPI 入口 + lifespan：启动预热 `refresh_market_cache()`（**25s** 超时）；后台异步循环刷新板块缓存（60s）、市态+情绪（120s）；挂载 `market` / `portfolio` / `analysis` / `news` / `ws` / `admin` 路由（统一前缀 `/api/v1/...`）。
- `backend/app/tasks/` — 后台任务：`market_refresh.py` 行情/资讯缓存调度；`task_manager.py` 通用 TaskManager（design/check/report 三型）+ `design_pipeline()`（design worker 主体）；`report_worker.py` / `strategy_check_worker.py` 异步 worker（WS 进度 + 最终报告）；`design_report.py` LLM 报告管道（WS 推送 + DB 持久化 + 90s 超时 + 一致性校验）。
- `backend/app/routers/ws.py` — WebSocket 路由 + `ConnectionManager.broadcast(channel, msg)`。路径见 §conventions。
- `backend/app/engine/` — **纯函数策略引擎包**，无 I/O 无外部依赖：`budgets.py` 层预算、`allocation_engine.py` 核心分配器、`rationale.py` 入选理由、`risk_controls.py` 风控（单只 ≤30%、行业集中度 <40%、层预算不超标）。
- `backend/app/services/` — 编排层：`strategy_design.py` 轻量编排器 `generate_enhanced_design()`（market_data_hub → engine/ 分配器 → 风控 → 三套方案）；`market_data_hub.py` 统一数据管道（`get_factor_matrix` / `get_pool` / `get_market_regime` / `get_market_sentiment` / `get_news`）；`market_service.py` 实时行情 / 全球指数；`portfolio_service.py` 组合与日盈亏计算；`llm_context.py` LLM 上下文管道 `build_full_context()`。
- `backend/app/factors/factor_registry.py` — FactorRegistry（33 维核心因子，含 KDJ / 综合信号 / premium_discount，无假数据 fallback，带熔断）。
- `backend/app/fetchers/` — 数据源：`china_market.py` A/港/商品行情资讯主力（mootdx/Sina 多源降级链）；`news_fetcher.py` 资讯抓取（财新头条 / 宏观 / 国际，打 `level` / `stars`）。
- `backend/app/analysis/llm.py` — DeepSeek LLM 集成（prompt 构建 + `generate_design_report()`）。
- `frontend/src/` — `main.js` 入口 + pinia + router；`api/index.js` axios `baseURL: '/api/v1'`（`marketApi`/`portfolioApi`/`analysisApi`/`newsApi`）；`stores/` 组合与任务状态；`components/` DashboardAiTools / PortfolioAnalysis / NewsView；`composables/useMarketWS.js`、`useNewsWS.js`。
- `backend/scripts/` — `verify_e2e.py` 端到端验证（见「测试」）；`encoding_diagnosis.py` 数据库编码诊断；`data_health_check.py` 数据管道健康检查。

## LLM 配置

DeepSeek API key 放在 `backend/.env` 中:
```
DEEPSEEK_API_KEY=sk-xxx
```

## conventions

- akshare 返回的列名可能是乱码（latin1 编码），用 `_decode_df()` 处理；若仍不匹配，`_normalize_columns()` 做二次映射。
- ETF 目标权重存为小数（0.3 = 30%），API 传入/返回都是小数。
- 组合数据持久化在 SQLite (`data/portfolio.db`)，Docker 部署时通过 volume 挂载。
- 前端 Vite 代理 `/api` → `localhost:8000`，开发时后端必须在 8000 端口；axios `baseURL` 为 `/api/v1`。
  - **Vite 代理规则顺序重要**：`/api/v1/ws` 必须排在 `/api` 之前，否则 WS 握手会被 HTTP 代理吞掉（见 `vite.config.js`）。
- WebSocket 路径: `/ws/market/{symbol}`, `/ws/news`, `/ws/portfolio`, `/ws/task-notifications`, `/ws/design-report/{session_id}`。
- 资讯分级：`level`（文字）+ `stars`（1-5 数字）；前端按 `level` 着色、按 `stars` 显示星数。
- 涨跌颜色：**红涨绿跌**（国内习惯）— 涨/盈用 `.text-up`（红），跌/亏用 `.text-down`（绿），定义在 `src/styles/theme.css`。勿套用西方绿涨红跌。
- **权重不归一化**：`calculate_allocation` 中 `target_amount = total_capital * target_weight`（不按权重和归一化）；现金 = `total_capital * (1 - Σtarget_weight)`。改时勿加归一化。

## 开发陷阱 / Gotchas

- **Vue `<script setup>` 是纯 JavaScript（无 `lang="ts"`）**：禁止写 `ref<string | null>(null)` 这类 TS 泛型。需要类型提示时用 `ref(null)` + JSDoc。
- **外部数据源会超时 / 限流**：akshare / yfinance / tushare / DeepSeek 任一都可能挂。用 `try/except` + `asyncio.wait_for`/`run_sync` 包裹，失败返回结构化错误而非崩溃。
- **前端 dev server 启动方式**：见「启动命令」中的 Windows 坑。
- **LLM prompt 规则 1 必须硬约束**：`design_report.md` 的规则 1 禁止 LLM 篡改 ETF 标的。若 LLM 仍引入候选池外代码，一致性校验 `_validate_report_consistency` 会在后处理中追加修正脚注 + 写 ERROR 日志。
- **`async def` ≠ 非阻塞**：`async def` 只改了函数签名，不改变调用链底层的行为。任何 `async def` 函数内部若直接调用同步 I/O（akshare/requests/urllib/pandas），会阻塞整个事件循环。正确做法：用 `await run_sync(call, *args)` 提交到线程池。判断标准——函数体内出现 `.get(`、`ak.`、`urllib.request` 等调用时，必须检查是否经过 `run_sync`/`asyncio.to_thread` 包裹。

## API 契约流程（强制 / Mandatory）

**所有新功能必须先写 API 契约，再编码。** 契约文件位于 `api-contracts/` 目录。

**流程:**
1. 从 `api-contracts/contract_template.md` 复制模板到对应模块目录
2. 填写路由、请求/响应结构（双语）
3. 前后端各自对照契约实现
4. 跑后端单测 + `verify_e2e.py`
5. 前端改动用 `npm run build` 验证无编译错误（pre-commit 门禁自动执行）
6. 联调时逐字段核对响应是否符合契约

**目录结构:**
```
api-contracts/
├── README.md              ← 流程说明
├── contract_template.md   ← 契约模板
├── portfolio/             ← 投资组合 (etfs, calculate, daily-pnl, strategy, design)
├── analysis/              ← AI 分析 (llm-report, news-impact, agents)
├── news/                  ← 资讯 (headlines, macro, global, stock, research)
├── factors/               ← 因子模型
├── admin/                 ← 运维监控 (token-usage, sources)
└── market/               ← 行情 (realtime, history, search, indicators, signal, chart, indices)
```

**检查清单:** 每个契约文件末尾有 `Frontend-Backend Checklist`，实现后逐项打勾验证。

> **🚨 2026-07-26 经验教训：契约必须先于实现，而非对实现的事后描述。**
> 即使是在为已存在接口补契约（如本次补 `apply-design` / `drift-check` 等 4 份契约），
> 正确的顺序仍然是：
> 1. **先写契约** — 定义接口形态、请求/响应结构，不参考后端代码
> 2. **再读后端代码确认契约正确** — 验证接口是否按契约实现，记录偏差
> 3. **再写单测** — 按契约描述的接口行为写测试
> 4. **再处理断裂点** — 以前端实际消费字段与契约/后端比对，修正不一致
>
> 反模式：先读后端/前端代码再补契约，会导致契约变成"对现状的追认"，
> 失去契约作为"对实现的约束"的核心价值——等人改接口时，看契约以为是对的，
> 实际代码可能早已跑偏。

## 部署
> 本地开发推荐 `restart.bat` — 自动停止旧进程、等端口释放、启动前后端、健康检查。
> 或手动运行：
> ```
> start.ps1 -Local         # 普通启动（带健康检查输出）
> start.ps1 -Local -Silent # 静默启动（无窗口）
> ```

```bash
docker-compose up -d    # 启动 backend + frontend(nginx)
```

## 关联 skill

ETF 组合管理与多资产行情分析使用已注册的 `etf-agent` skill（技能索引可查），直接 `/etf-agent` 调用。
