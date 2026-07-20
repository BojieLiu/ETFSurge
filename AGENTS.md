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
> 前端 Vite 的 `/api`、`/ws` 代理在 Docker 内自动指向容器 `backend-dev`，
> 本地非 Docker 开发回落到 `localhost:8000`，两种模式均无需改配置。

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

## 关键路径

- `backend/app/main.py` — FastAPI 入口 + lifespan：
  - 启动时预热 `refresh_market_cache()`（**25s** 超时）。
  - APScheduler：`refresh_market_cache` 每 **15s**、`refresh_news_cache` 每 **30s**。
  - 挂载路由：`market` / `portfolio` / `analysis` / `news` / `ws` / `admin`（前缀在各 router 内，统一为 `/api/v1/...`）。
- `backend/app/tasks/market_refresh.py` — 定时刷新行情 / 资讯缓存的调度包装。
- `backend/app/tasks/task_manager.py` — 通用 TaskManager（支持 design / check / report 三种任务类型）。
- `backend/app/tasks/worker_registry.py` — Worker 注册表，按 task_type 派发到对应 worker。
- `backend/app/tasks/design_tasks.py` — 向后兼容层，注册 design / report worker。
- `backend/app/tasks/report_worker.py` — 异步市场研判报告 worker（WS 推送进度 + 最终报告）。
- `backend/app/tasks/strategy_check_worker.py` — 异步策略检查 worker。
- `backend/app/tasks/design_report.py` — LLM 报告管道 `compose_and_push_report()`（WS 推送 + DB 持久化 + 90s 超时保护 + 一致性校验）。
- `backend/app/routers/ws.py` — WebSocket 路由 + `ConnectionManager`（含 `broadcast(channel, msg)`）。
  - 路径：`/ws/market/{symbol}`、`/ws/news`、`/ws/portfolio`、**`/ws/task-notifications`**、`/ws/design-report/{session_id}`。
- `backend/app/engine/` — **纯函数策略引擎包**，无 I/O 无外部依赖：
  - `budgets.py` — 层预算（`STRATEGY_META`、`dynamic_layer_budget()`）和预期收益调整。
  - `allocation_engine.py` — 核心分配器 `allocate()`，基于因子分排序选择标的分配权重。
  - `rationale.py` — 数据驱动的入选理由生成（因子分 + 市态感知 + 模板多样化）。
  - `risk_controls.py` — 风控约束（单只 ≤30%、行业集中度 <40%、层预算不超标）。
- `backend/app/services/strategy_design.py` — **轻量编排器（125 行，原 1092 行）**：
  - `generate_enhanced_design()` — 编排器入口：调用 pool_manager → engine/ 分配器 → 风控 → 返回三套方案。
- `backend/app/services/pool_manager.py` — **统一数据管道**（全市场扫描 + 因子计算 + 市场状态 + 新闻缓存）：
  - `get_factor_matrix()` / `get_pool()` / `get_market_regime()` / `get_market_sentiment()` / `get_news()`。
- `backend/app/factors/factor_registry.py` — FactorRegistry（24+ 维因子计算，含 KDJ / 综合信号 / industry_diversification，已删除假数据 fallback，带熔断保护）。
- `backend/app/services/market_trends.py` — `detect_market_regime()`（含 index_realtime fallback）、`compute_etf_trends()`。
- `backend/app/fetchers/akshare_fetcher.py` — A 股 / 港股 / 商品行情与资讯数据源（备用；主力为 `china_market.py` → mootdx/Sina 降级链）。
- `backend/app/fetchers/news_fetcher.py` — 资讯抓取（财新头条 / 宏观 / 国际），打 `level` / `stars`。
- `backend/app/services/portfolio_service.py` — 组合计算（`calculate_allocation` / `calculate_daily_pnl`）。
- `backend/app/services/market_service.py` — 实时行情 / 全球指数。
- `backend/app/analysis/llm.py` — DeepSeek LLM 集成；`_build_design_report_prompt()`、`generate_design_report()` 在此。
- `frontend/src/main.js` — `createApp` + `pinia` + `router`，挂 `#app`。
- `frontend/src/api/index.js` — axios 实例 `baseURL: '/api/v1'`，导出 `marketApi` / `portfolioApi` / `analysisApi` / `newsApi`。
- `frontend/src/stores/portfolio.js` — 组合状态（Pinia）。
- `frontend/src/stores/task.js` — 全局任务状态（运行中/完成/失败），持久化到 localStorage。
- `frontend/src/components/DashboardAiTools.vue` — 智能组合设计主面板（wizard/loading/result 三态，含历史记录、方案卡片、完整报告 Tab）。
- `frontend/src/components/PortfolioAnalysis.vue` — 组合管理 + 技术分析合并页。
- `frontend/src/components/NewsView.vue` — 资讯模块。
- `frontend/src/composables/useMarketWS.js` / `useNewsWS.js` — WebSocket 客户端。
- `backend/scripts/verify_e2e.py` — 端到端验证脚本（见「测试」章节）。

## LLM 配置

DeepSeek API key 放在 `backend/.env` 中:
```
DEEPSEEK_API_KEY=sk-xxx
```

key 也存在于 `E:\agent_workspace\deepseek_api_key.txt.txt`。

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
- **`/ws/news` 无广播**：光连上不会收到数据，需要后端任务周期性 `broadcast("news", payload)`。
- **LLM prompt 规则 1 必须硬约束**：`design_report.md` 的规则 1 禁止 LLM 篡改 ETF 标的。若 LLM 仍引入候选池外代码，一致性校验 `_validate_report_consistency` 会在后处理中追加修正脚注 + 写 ERROR 日志。

## API 契约流程（强制 / Mandatory）

**所有新功能必须先写 API 契约，再编码。** 契约文件位于 `api-contracts/` 目录。
**后端改动必须运行 `verify_e2e.py` 确认全 PASS 后才能 commit。**

**流程:**
1. 从 `api-contracts/contract_template.md` 复制模板到对应模块目录
2. 填写路由、请求/响应结构（双语）
3. 前后端各自对照契约实现
4. 跑后端单测 + `verify_e2e.py`
5. 联调时逐字段核对响应是否符合契约

**目录结构:**
```
api-contracts/
├── README.md              ← 流程说明
├── contract_template.md   ← 契约模板
├── portfolio/             ← 投资组合 (etfs, calculate, daily-pnl, strategy, design)
├── analysis/              ← AI 分析 (llm-report, news-impact, agents)
├── news/                  ← 资讯 (headlines, macro, global, stock, research)
├── factors/               ← 因子模型
└── market/               ← 行情 (realtime, history, search, indicators, signal, chart, indices)
```

**检查清单:** 每个契约文件末尾有 `Frontend-Backend Checklist`，实现后逐项打勾验证。

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

ETF 组合技能位于 `C:\Users\tiany\.agents\skills\etf-agent\`，可在 OpenCode 对话中直接使用。
