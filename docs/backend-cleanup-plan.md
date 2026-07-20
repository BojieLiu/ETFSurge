## 十二、后端冗余代码清理清单

实施完整方案后，以下后端代码变为冗余，在 Phase 3-4 执行过程中删除。

### 12.1 废弃路由

| 路由 | 文件 | 行号 | 删除原因 |
|------|------|------|----------|
| `POST /portfolio/design` | `routers/portfolio.py` | `@router.post("/design")` | 旧同步版，被 `/design-async` 取代 |
| `POST /portfolio/design-enhanced` | `routers/portfolio.py` | `@router.post("/design-enhanced")` | 功能合并到 `/design-async` |
| `POST /analysis/portfolio-design` | `routers/analysis.py` | `@router.post("/portfolio-design")` | 旧 LLM 路径，不走引擎 |
| `POST /analysis/portfolio-design/stream` | `routers/analysis.py` | `@router.post("/portfolio-design/stream")` | 同上，SSE 流式版 |

**确认方式**：确认上述路由的 `@router` 注册行无其他引用。

### 12.2 废弃函数和类

#### strategy_design.py（~840 行）

| 代码 | 行号 | 删除原因 |
|------|------|----------|
| `CANDIDATE_POOL` | 74-114 | 被 `pool_manager` 全量动态池取代 |
| `_NEWS_KEYWORD_MAP`（引用） | 240 | 未定义变量，引用处所在的 `map_news_to_etfs()` 整体废弃，随函数一并删除 |
| `power_law_weights()` | 119-132 | 权重分配改用因子分归一化 |
| `generate_full_design()` | 137-197 | v3 编排器，被 `generate_design_v5` 取代 |
| `map_news_to_etfs()` | 206-269 | 新闻影响以因子维度纳入 FactorRegistry |
| `dynamic_core_allocation()` | 274-327 | 核心层改因子分驱动 |
| `dynamic_defense_allocation()` | 330-380 | 防御层改因子分驱动 |
| `generate_enhanced_design()` 主体 | 676-1050 | 整体替换为新编排器 |
| 降级链路 `pool_ready → scanner → hardcoded` | 793-835 | 无降级策略 |
| 科技集中度 C2 规则 | 925-957 | 改为因子暴露矩阵检测 |
| 单行业 40% 规则 | 959-977 | 改为因子暴露矩阵检测 |

#### analysis.py（分析路由辅助函数）

| 代码 | 行号 | 删除原因 |
|------|------|----------|
| `_fetch_all_market()` | 108-142 | llm-report 改为编排器唯一输入，不再自采行情 |
| `_collect_news()` | 164-176 | 新闻改为从数据管道获取 |
| `_MARKET_OVERVIEW_CACHE` | 146 | 不再需要 30s TTL 缓存，编排器统一缓存 |
| `_get_cached_market_overview()` | 150 | 同上 |
| `get_cached_market_overview()` | 179 | 同上 |
| `PortfolioDesignRequest` | 265-267 | 仅被已删除的 `/portfolio-design` 路由使用 |
| `import generate_portfolio_design`, `_build_portfolio_design_prompt` | 14-17 | 仅被已删除的路由使用 |

#### analysis/llm.py（旧 LLM 设计路径）

| 代码 | 行号 | 删除原因 |
|------|------|----------|
| `generate_portfolio_design()` | 733 | 旧 LLM 设计路径，被引擎取代 |
| `_build_portfolio_design_prompt()` | 534 | 同上 |
| `prompts/v1/portfolio_design.md` | `prompts/v1/` | 旧 LLM 设计提示词文件 |

#### portfolio_service.py（策略检查自采逻辑）

| 代码 | 行号 | 删除原因 |
|------|------|----------|
| `strategy_check()` 内部的 `factor_registry.compute()` 调用 | 363 | 改为从编排器拿 `factor_matrix` |
| `strategy_check()` 内部的 `compute_etf_trends()` 调用 | 364 | 改为从编排器拿因子分 |
| `strategy_check()` 内部的 `_detect_regime()` 调用 | 364 | 改为从编排器拿 `market_regime` |
| 内部函数 `_compute_indicators()` | ~425 | 只有 `strategy_check` 调用，改为从 FactorRegistry 拿技术因子 |
| 内部函数 `_detect_regime()` | ~450 | 只有 `strategy_check` 调用，改为从编排器拿 regime |

**注**：`strategy_check()` 函数本身保留（对外接口不变），只删除内部自采逻辑。

#### market_trends.py

| 代码 | 行号 | 删除原因 |
|------|------|----------|
| `compute_etf_trends()` | 25 | 所有消费者（设计/策略检查）改用管道后不再使用，**删除前需确认 `tasks/market_refresh.py` 等文件无残留引用** |

### 12.3 保留但移入其他位置的代码

| 原代码 | 原文件 | 目标位置 | 说明 |
|--------|--------|----------|------|
| `DesignTaskManager` | `tasks/design_tasks.py` | `tasks/task_manager.py` | 抽取泛化为 `TaskManager` |
| `TaskNotifyManager` | `tasks/design_tasks.py` | `tasks/task_manager.py` | 保持原样迁入 |
| `_notify()`（design_tasks 版） | `tasks/design_tasks.py` | `tasks/task_manager.py` | 合并两版 `_notify`，采用带 `stage` 的签名 |
| `design_worker()` | `tasks/design_tasks.py` | `tasks/worker_registry.py` | 注册到 `WORKER_REGISTRY` |
| `strategy_check_worker()` | `tasks/strategy_check_worker.py` | `tasks/worker_registry.py` | 注册到 `WORKER_REGISTRY` |

### 12.4 保留不做删除的文件

| 文件 | 原因 |
|------|------|
| `tasks/market_refresh.py` | 数据管道调度器，保留并增强（新增 news/us_indices 等刷新） |
| `tasks/design_report.py` | 设计报告 WS 推送，保留 |
| `fetchers/news_fetcher.py` | 继续作为管道内部数据源 |
| `fetchers/sentiment_fetcher.py` | 继续作为管道内部数据源 |
| `services/market_service.py` | 继续作为管道内部数据源（get_global_indices / get_commodities 等） |
| `services/market_trends.py`（保留部分） | `detect_market_regime()` + `compute_sector_momentum()` 继续被管道使用 |

### 12.5 删除影响范围统计

| 文件 | 删除行数 | 影响 |
|------|----------|------|
| `services/strategy_design.py` | ~840 行 | 从 1050 行 → ~210 行（薄编排器） |
| `routers/analysis.py` | ~80 行 | 辅助函数 + 旧路由 + class |
| `analysis/llm.py` | ~60 行 | `generate_portfolio_design()` + `_build_portfolio_design_prompt()` |
| `services/portfolio_service.py` | ~70 行 | `strategy_check` 内部自采逻辑 |
| `services/market_trends.py` | ~60 行 | `compute_etf_trends()`（确认无其他引用后） |
| `routers/portfolio.py` | ~30 行 | 2 个旧路由 + 关联 import |
| `prompts/v1/portfolio_design.md` | 1 个文件 | 旧 LLM 提示词 |
| **合计** | **~1140 行** | 约占后端总代码的 15% |

### 12.6 与主文档 §4 删除清单的对应关系

| 主文档章节 | 本清单章节 | 说明 |
|-----------|-----------|------|
| §4.1 strategy_design.py 内部 | §12.2 | 完全覆盖，追加行号确认 |
| §4.2 冗余路由和辅助函数 | §12.1 + §12.2 | 合并到一个清单，追加提示词文件位置修正 |
| §4.3 FactorRegistry + indicators 清理 | 见主文档 | 独立管理，不在此重复 |
| §4.4 测试文件 | 见主文档 | 独立管理，不在此重复 |
| §五 保留和移入 engine 包 | §12.3 | 追加 `TaskManager` 迁移 |
