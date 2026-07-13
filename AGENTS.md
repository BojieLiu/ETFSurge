# AGENTS.md — ETF Surge

多资产实时行情分析与 ETF 组合管理系统。后端 FastAPI（async）+ 前端 Vue 3。

## 启动命令

### 本地开发（无需 Docker）

```bash
# 后端 (从项目根)
cd backend && uvicorn app.main:app --reload

# 前端 (另开终端)
cd frontend && npm run dev
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

- **后端**：`cd backend && python -m pytest`
  - 已配置 `pytest.ini` + `conftest.py`（`asyncio_mode = auto`）。
  - 外部网络 / LLM（akshare、DeepSeek、yfinance 等）在单测中 **必须 mock**，不依赖真实 DB / 网络。
- **前端**：`cd frontend && npm test`（即 `npx vitest run`）
  - 已配置 `vitest.config.js` + `src/test/setup.js`（jsdom 环境）。
  - 组件测试用 `@vue/test-utils`。
- **链路验证**：后端用 `curl http://localhost:8000/...`；前端用 `npm run build` + 浏览器/Playwright 走查关键页面。

## 关键路径

- `backend/app/main.py` — FastAPI 入口 + lifespan：
  - 启动时预热 `refresh_market_cache()`（12s 超时）。
  - APScheduler：`refresh_market_cache` 每 **15s**、`refresh_news_cache` 每 **30s**（wrapper 在 `backend/app/tasks/market_refresh.py`）。
  - 挂载路由：`market` / `portfolio` / `analysis` / `news` / `ws`（前缀在各 router 内，统一为 `/api/v1/...`）。
- `backend/app/tasks/market_refresh.py` — 定时刷新行情 / 资讯缓存的调度包装。
- `backend/app/routers/ws.py` — WebSocket 路由 + `ConnectionManager`（含 `broadcast(channel, msg)`）。
  - 路径：`/ws/market/{symbol}`、`/ws/news`、`/ws/portfolio`。
  - 注意 `/ws/news` 默认是**被动端点**，目前没有广播任务往里推数据，需要时自行挂一个 poller 调 `broadcast("news", ...)`。
- `backend/app/fetchers/akshare_fetcher.py` — A 股 / 港股 / 商品行情与资讯数据源。
- `backend/app/fetchers/news_fetcher.py` — 资讯抓取（财新头条 / 宏观 / 国际），并给每条打 `level` / `stars`。
- `backend/app/services/portfolio_service.py` — 组合计算（`calculate_allocation` / `calculate_daily_pnl`）。
- `backend/app/services/market_service.py` — 实时行情 / 全球指数。
- `backend/app/analysis/llm.py` — DeepSeek LLM 集成（httpx）；`analyze_news` / `analyze_news_impact` 在此。
- `frontend/src/main.js` — `createApp` + `pinia` + `router`，挂 `#app`。
- `frontend/src/api/index.js` — axios 实例 `baseURL: '/api/v1'`，导出 `marketApi` / `portfolioApi` / `analysisApi` / `newsApi`。
- `frontend/src/stores/portfolio.js` — 组合状态（Pinia）。
- `frontend/src/components/Dashboard.vue` — 总仓位 / 盈亏 / 分配页面。
- `frontend/src/components/PortfolioAnalysis.vue` — 组合管理 + 技术分析的合并页（原两 tab 合一）。
- `frontend/src/components/NewsView.vue` — 资讯模块（分级着色 + 星标 + 单条 AI 分析）。
- `frontend/src/composables/useMarketWS.js` / `useNewsWS.js` — WebSocket 客户端（connect / disconnect / onMessage）。

## LLM 配置

DeepSeek API key 放在 `backend/.env` 中:
```
DEEPSEEK_API_KEY=sk-xxx
```

key 也存在于 `E:\agent_workspace\deepseek_api_key.txt.txt`。

## conventions

- akshare 返回的列名可能是乱码（latin1 编码），用 `_decode_df()` 处理。
- ETF 目标权重存为小数（0.3 = 30%），API 传入/返回都是小数。
- 组合数据持久化在 SQLite (`data/portfolio.db`)，Docker 部署时通过 volume 挂载。
- 前端 Vite 代理 `/api` → `localhost:8000`，开发时后端必须在 8000 端口；axios `baseURL` 为 `/api/v1`。
- WebSocket 路径: `/ws/market/{symbol}`, `/ws/news`, `/ws/portfolio`。
- 资讯分级：`level`（文字，如 重大/利好/利空/提醒）+ `stars`（1–5 数字）区分重要度；前端按 `level` 着色、按 `stars` 显示星数。
- 涨跌颜色：**红涨绿跌**（国内习惯）—— 涨/盈用 `.text-up`（红），跌/亏用 `.text-down`（绿），定义在 `src/styles/theme.css`。勿套用西方绿涨红跌。
- **权重不归一化**：`calculate_allocation` 中 `target_amount = total_capital * target_weight`（不按权重和归一化）；现金 = `total_capital * (1 - Σtarget_weight)`，即买完 ETF 后剩下的机动仓位。改这块逻辑时**不要**顺手加归一化。

## 开发陷阱 / Gotchas

- **Vue `<script setup>` 是纯 JavaScript（无 `lang="ts"`）**：禁止写 `ref<string | null>(null)` 这类 TS 泛型。它会当 JS 编译并抛 `ReferenceError: string is not defined`，导致整页空白。需要类型提示时用 `ref(null)` + JSDoc。
- **外部数据源会超时 / 限流**：akshare / yfinance / tushare / levistock / DeepSeek 任一都可能挂。用 `try/except` + 线程 / asyncio 超时包裹，失败返回结构化错误而非崩溃；缓存 TTL 见各 fetcher。
- **前端 dev server 启动方式**：见「启动命令」中的 Windows 坑。
- **`/ws/news` 无广播**：光连上不会收到数据，必须有一个后端任务周期性 `broadcast("news", payload)`（参考 `market_refresh` 的调度模式）。

## API 契约流程（强制 / Mandatory）

**所有新功能必须先写 API 契约，再编码。** 契约文件位于 `api-contracts/` 目录。

**流程:**
1. 从 `api-contracts/contract_template.md` 复制模板到对应模块目录
2. 填写路由、请求/响应结构（双语）
3. 前后端各自对照契约实现
4. 联调时逐字段核对响应是否符合契约

**目录结构:**
```
api-contracts/
├── README.md              ← 流程说明
├── contract_template.md   ← 契约模板
├── portfolio/             ← 投资组合 (etfs, calculate, daily-pnl, strategy, design)
├── analysis/              ← AI 分析 (llm-report, news-impact)
├── news/                  ← 资讯 (headlines, macro, global, stock, research)
└── market/               ← 行情 (realtime, history, search, indicators, signal, chart, indices)
```

**检查清单:** 每个契约文件末尾有 `Frontend-Backend Checklist`，实现后逐项打勾验证。

## 部署

```bash
docker-compose up -d    # 启动 backend + redis + frontend(nginx)
```

## 关联 skill

ETF 组合技能位于 `C:\Users\tiany\.agents\skills\etf-agent\`，可在 OpenCode 对话中直接使用。
