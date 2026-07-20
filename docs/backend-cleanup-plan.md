# 后端清理方案

> **实现状态: ✅ 2026-07-20 已全部完成**
> - strategy_design.py: 1092 → 131 行 (‑88%)
> - 删除旧路由 5 条（/design, /design-enhanced, /portfolio-design, /portfolio-design/stream, /strategy-check）
> - 删除 dead code 约 300 行（_fetch_all_market, _collect_news, _build_portfolio_design_prompt, generate_portfolio_design, _fallback_portfolio_plans）
> - 删除 Schema 2 个（PortfolioDesignRequest, StrategyCheckRequest/Response）
> - import 路径 7 处 → 迁移到 task_manager.py

## 清理清单

### 1. 路由层删除

- [x] `POST /analysis/portfolio-design` — 旧 LLM 设计路径
- [x] `POST /analysis/portfolio-design/stream` — SSE 流式版
- [x] `POST /portfolio/design` — 路由已移除（旧同步版）
- [x] `POST /portfolio/design-enhanced` — 路由已移除（旧增强版）
- [x] `POST /portfolio/strategy-check` — 同步版本已移除（统一到 async）

### 2. 函数/类删除

- [x] `_fetch_all_market()` — 在 analysis.py 中，编排器提供缓存数据
- [x] `_collect_news()` — 在 analysis.py 中，编排器提供缓存数据
- [x] `get_cached_market_overview()` / `_set_cached_market_overview()` — 完整缓存类已移除
- [x] `_MARKET_OVERVIEW_CACHE` — 全局变量已移除
- [x] `_build_portfolio_design_prompt()` — llm.py 中组合设计专用 prompt 函数
- [x] `generate_portfolio_design()` — llm.py 中组合设计入口
- [x] `_fallback_portfolio_plans()` — llm.py 中 LLM 不可用的降级函数
- [x] `PortfolioDesignRequest` — analysis.py 中 Pydantic 模型
- [x] `StrategyCheckRequest/StrategyCheckResponse` — portfolio.py 中 schema

### 3. 任务管理器重构

- [x] DesignTaskManager → TaskManager（泛化，支持 design/check/report 三种类型）
- [x] WorkerRegistry 注册制（worker_registry.py）
- [x] report_worker.py 新增
- [x] 7 处 import 更新

### 4. 其他清理

- [x] `factor_registry.py` 删假数据 fallback
- [x] `factor_registry.py` 删除 6 个 scaffolding 函数（industry_diversification 已实现）
- [x] `strategy_check_worker.py` logger import 修复
- [x] `verify_e2e.py` 重写为 async 优先
