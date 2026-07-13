# AGENTS.md — ETF Surge

多资产实时行情分析与 ETF 组合管理系统。后端 FastAPI + 前端 Vue 3。

## 启动命令

### 本地开发（无需 Docker）

```bash
# 后端 (从项目根)
cd backend && uvicorn app.main:app --reload

# 前端 (另开终端)
cd frontend && npm run dev
```

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

## 关键路径

- `backend/app/main.py` — FastAPI 入口，注册路由和 lifespan
- `backend/app/fetchers/akshare_fetcher.py` — 所有行情/新闻数据源
- `backend/app/analysis/llm.py` — DeepSeek LLM 集成（使用 httpx）
- `frontend/src/stores/portfolio.js` — 组合状态管理
- `frontend/src/components/Dashboard.vue` — 总仓位/盈亏/分配页面

## LLM 配置

DeepSeek API key 放在 `backend/.env` 中:
```
DEEPSEEK_API_KEY=sk-xxx
```

key 也存在于 `E:\agent_workspace\deepseek_api_key.txt.txt`。

## conventions

- akshare 返回的列名可能是乱码（latin1 编码），用 `_decode_df()` 处理
- ETF 目标权重存为小数（0.3 = 30%），API 传入/返回都是小数
- 组合数据持久化在 SQLite (`data/portfolio.db`)，Docker 部署时通过 volume 挂载
- 前端 Vite 代理 `/api` → `localhost:8000`，开发时后端必须在 8000 端口
- WebSocket 路径: `/ws/market/{symbol}`, `/ws/news`, `/ws/portfolio`

## 部署

```bash
docker-compose up -d    # 启动 backend + redis + frontend(nginx)
```

## 关联 skill

ETF 组合技能位于 `C:\Users\tiany\.agents\skills\etf-agent\`，可在 OpenCode 对话中直接使用。
